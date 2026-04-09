"""Authentication service — multi-step login with configurable security levels.

Flow: password → optional TOTP 2FA → optional email verification (Resend).
"""

import hashlib
import hmac
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone

import jwt
import bcrypt

from src.shared.config import _cfg
from src.shared.logger import get_logger

logger = get_logger("auth.service")

# ── Config ──

_auth = _cfg.get("auth", {})
AUTH_ACCOUNT: str = _auth.get("account", "")
AUTH_PASSWORD_HASH: str = _auth.get("password_hash", "")
TOTP_SECRET: str = _auth.get("totp_secret", "")
RESEND_API_KEY: str = _auth.get("resend_api_key", "")
RESEND_FROM_DOMAIN: str = _auth.get("resend_from_domain", "pagefly.ink")
JWT_SECRET: str = _auth.get("jwt_secret", "")
JWT_EXPIRY_HOURS: int = _auth.get("jwt_expiry_hours", 24)

if not JWT_SECRET:
    JWT_SECRET = secrets.token_hex(32)
    logger.warning("No jwt_secret configured — using random secret (sessions won't survive restart)")

# Pending email codes: {session_token: {code, email, expires_at}}
_pending_codes: dict[str, dict] = {}

# Rate limiting: {ip_or_account: [timestamps]}
_login_attempts: dict[str, list[float]] = {}
MAX_ATTEMPTS = 5
ATTEMPT_WINDOW = 300  # 5 minutes

# Used TOTP counters for replay prevention
_used_totp_counters: set[int] = set()


def is_auth_configured() -> bool:
    """Check if login credentials are set."""
    return bool(AUTH_ACCOUNT and AUTH_PASSWORD_HASH)


def get_auth_steps() -> list[str]:
    """Return the login steps required based on config."""
    steps = ["password"]
    if TOTP_SECRET:
        steps.append("totp")
    if RESEND_API_KEY:
        steps.append("email")
    return steps


def check_rate_limit(identifier: str) -> bool:
    """Return True if rate limit exceeded."""
    now = time.time()
    attempts = _login_attempts.get(identifier, [])
    # Clean old attempts
    recent = [t for t in attempts if now - t < ATTEMPT_WINDOW]
    _login_attempts[identifier] = recent
    if len(recent) >= MAX_ATTEMPTS:
        return True
    return False


def record_attempt(identifier: str) -> None:
    """Record a login attempt."""
    attempts = _login_attempts.setdefault(identifier, [])
    attempts.append(time.time())


def hash_password(password: str) -> str:
    """Hash a password with bcrypt for storage."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str) -> bool:
    """Verify password against stored bcrypt hash."""
    if not AUTH_PASSWORD_HASH:
        return False
    try:
        return bcrypt.checkpw(password.encode(), AUTH_PASSWORD_HASH.encode())
    except (ValueError, TypeError):
        # Fallback for legacy SHA-256 hashes (salt:hash format)
        if ":" in AUTH_PASSWORD_HASH:
            salt, stored_hash = AUTH_PASSWORD_HASH.split(":", 1)
            computed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
            return hmac.compare_digest(computed, stored_hash)
        return False


def verify_totp(code: str) -> bool:
    """Verify a TOTP 6-digit code against the configured secret."""
    if not TOTP_SECRET:
        return True

    if not code or len(code) != 6 or not code.isdigit():
        return False

    current_counter = int(time.time()) // 30
    for offset in (-1, 0, 1):
        counter = current_counter + offset
        if counter in _used_totp_counters:
            continue
        expected = _generate_totp(TOTP_SECRET, offset)
        if hmac.compare_digest(code, expected):
            _used_totp_counters.add(counter)
            # Clean old counters (keep last 10 minutes)
            cutoff = current_counter - 20
            _used_totp_counters.difference_update(
                {c for c in _used_totp_counters if c < cutoff}
            )
            return True
    return False


def _generate_totp(secret: str, offset: int = 0) -> str:
    """Generate a TOTP code (RFC 6238)."""
    import base64
    key = base64.b32decode(secret.upper().replace(" ", ""), casefold=True)
    counter = struct.pack(">Q", int(time.time()) // 30 + offset)
    mac = hmac.new(key, counter, hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)


async def send_email_code(session_token: str, email: str) -> bool:
    """Send a 6-digit verification code via Resend. Returns True on success."""
    if not RESEND_API_KEY:
        return False

    code = "".join(str(secrets.randbelow(10)) for _ in range(6))
    expires = time.time() + 300

    # Clean expired codes
    now = time.time()
    for k in list(_pending_codes.keys()):
        if _pending_codes[k]["expires_at"] < now:
            del _pending_codes[k]

    _pending_codes[session_token] = {"code": code, "email": email, "expires_at": expires}

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": f"PageFly <noreply@{RESEND_FROM_DOMAIN}>",
                    "to": [email],
                    "subject": "PageFly Login Verification",
                    "html": (
                        f"<h2>Your verification code</h2>"
                        f"<p style='font-size:32px;font-family:monospace;letter-spacing:8px'><b>{code}</b></p>"
                        f"<p>This code expires in 5 minutes.</p>"
                        f"<p style='color:#999'>If you didn't request this, ignore this email.</p>"
                    ),
                },
            )
            if resp.status_code in (200, 201):
                logger.info("Verification email sent to %s", email)
                return True
            logger.error("Resend API error: %s %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        logger.error("Failed to send verification email: %s", e)
        return False


def verify_email_code(session_token: str, code: str) -> bool:
    """Verify an email verification code bound to a session."""
    if not RESEND_API_KEY:
        return True

    pending = _pending_codes.get(session_token)
    if not pending:
        return False

    if time.time() > pending["expires_at"]:
        del _pending_codes[session_token]
        return False

    if not hmac.compare_digest(code, pending["code"]):
        return False

    del _pending_codes[session_token]
    return True


def create_jwt(account: str) -> str:
    """Create a JWT token for a verified user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": account,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
        "type": "session",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_jwt(token: str) -> dict | None:
    """Verify and decode a JWT token. Returns payload or None."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
