"""Auth API routes — multi-step login flow with rate limiting."""

import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.auth.service import (
    AUTH_ACCOUNT,
    check_rate_limit,
    create_jwt,
    get_auth_steps,
    is_auth_configured,
    record_attempt,
    send_email_code,
    verify_email_code,
    verify_password,
    verify_totp,
)
from src.shared.logger import get_logger

logger = get_logger("auth.routes")

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_TTL = 600  # 10 minutes


class LoginRequest(BaseModel):
    account: str
    password: str


class TotpRequest(BaseModel):
    code: str
    session_token: str


class EmailCodeRequest(BaseModel):
    code: str
    session_token: str


class SendCodeRequest(BaseModel):
    session_token: str


# In-memory partial sessions: {session_token: {account, steps_completed, steps_remaining, created_at}}
_partial_sessions: dict[str, dict] = {}


def _get_client_ip(request: Request) -> str:
    """Extract client IP for rate limiting."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _cleanup_expired_sessions() -> None:
    """Remove expired partial sessions."""
    now = time.time()
    expired = [k for k, v in _partial_sessions.items() if now - v["created_at"] > SESSION_TTL]
    for k in expired:
        del _partial_sessions[k]


def _get_session(session_token: str) -> dict:
    """Get and validate a partial session."""
    _cleanup_expired_sessions()
    session = _partial_sessions.get(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return session


@router.get("/config")
async def auth_config():
    """Return what auth steps are required (no secrets exposed)."""
    if not is_auth_configured():
        return {"configured": False, "steps": []}
    return {"configured": True, "steps": get_auth_steps()}


@router.post("/login")
async def login(req: LoginRequest, request: Request):
    """Step 1: Verify account + password."""
    if not is_auth_configured():
        raise HTTPException(status_code=503, detail="Auth not configured")

    client_ip = _get_client_ip(request)
    if check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    if req.account != AUTH_ACCOUNT or not verify_password(req.password):
        record_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    steps = get_auth_steps()
    remaining = [s for s in steps if s != "password"]

    if not remaining:
        return {"status": "complete", "token": create_jwt(req.account)}

    session_token = secrets.token_urlsafe(32)
    _partial_sessions[session_token] = {
        "account": req.account,
        "steps_completed": ["password"],
        "steps_remaining": remaining,
        "created_at": time.time(),
    }

    return {"status": "pending", "next_step": remaining[0], "session_token": session_token}


@router.post("/verify-totp")
async def verify_totp_step(req: TotpRequest, request: Request):
    """Step 2 (if configured): Verify TOTP 2FA code."""
    client_ip = _get_client_ip(request)
    if check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    session = _get_session(req.session_token)

    if "totp" not in session["steps_remaining"]:
        raise HTTPException(status_code=400, detail="TOTP step not required")

    if not verify_totp(req.code):
        record_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Invalid TOTP code")

    session["steps_completed"].append("totp")
    session["steps_remaining"].remove("totp")

    if not session["steps_remaining"]:
        del _partial_sessions[req.session_token]
        return {"status": "complete", "token": create_jwt(session["account"])}

    return {"status": "pending", "next_step": session["steps_remaining"][0], "session_token": req.session_token}


@router.post("/send-email-code")
async def send_code(req: SendCodeRequest, request: Request):
    """Send verification code to configured email via Resend."""
    session = _get_session(req.session_token)

    if "email" not in session["steps_remaining"]:
        raise HTTPException(status_code=400, detail="Email step not required")

    # Rate limit email sending: 60s cooldown per session
    last_sent = session.get("last_email_sent", 0)
    if time.time() - last_sent < 60:
        raise HTTPException(status_code=429, detail="Please wait before requesting another code")

    success = await send_email_code(req.session_token, session["account"])
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send verification email")

    session["last_email_sent"] = time.time()
    return {"status": "sent", "message": "Verification code sent to your email"}


@router.post("/verify-email")
async def verify_email_step(req: EmailCodeRequest, request: Request):
    """Step 3 (if configured): Verify email code."""
    client_ip = _get_client_ip(request)
    if check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    session = _get_session(req.session_token)

    if "email" not in session["steps_remaining"]:
        raise HTTPException(status_code=400, detail="Email step not required")

    if not verify_email_code(req.session_token, req.code):
        record_attempt(client_ip)
        raise HTTPException(status_code=401, detail="Invalid or expired verification code")

    session["steps_completed"].append("email")
    session["steps_remaining"].remove("email")

    del _partial_sessions[req.session_token]
    return {"status": "complete", "token": create_jwt(session["account"])}
