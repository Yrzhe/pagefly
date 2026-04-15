"""Desktop activity capture — storage + transcription helpers.

Two kinds of rows land here:
  - `audio_recordings`   : meeting recordings uploaded from Mac client,
                           transcribed async via OpenAI Whisper.
  - `activity_events`    : screen/app context blocks (app, window, URL,
                           text excerpt), optionally linked to an audio row.

The canonical append-only log on disk is
    data/activity/YYYY-MM-DD.jsonl
with raw m4a files under
    data/activity/audio/<id>.<ext>
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from src.shared.config import DATA_DIR
from src.shared.logger import get_logger
from src.storage import db

logger = get_logger("activity")

ACTIVITY_DIR = DATA_DIR / "activity"
AUDIO_DIR = ACTIVITY_DIR / "audio"

_ALLOWED_AUDIO_EXT = {"m4a", "mp3", "wav", "webm", "ogg", "flac", "mp4"}
# Accepts plain uuid / base32 / hex. Rejects slashes, dots, spaces — path-traversal safe.
_SAFE_UUID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _ensure_dirs() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def is_safe_uuid(local_uuid: str) -> bool:
    return bool(_SAFE_UUID_RE.match(local_uuid or ""))


def save_audio_upload(local_uuid: str, content: bytes, fmt: str) -> tuple[Path, bool]:
    """Persist an uploaded audio blob atomically.

    Returns (path, created) where `created=True` means this call wrote the file,
    `created=False` means another concurrent request already wrote it. The caller
    uses `created` to decide whether to enqueue transcription.
    """
    _ensure_dirs()
    if not is_safe_uuid(local_uuid):
        raise ValueError("Invalid local_uuid — must match [A-Za-z0-9_-]{8,64}")
    fmt = fmt.lower().lstrip(".")
    if fmt not in _ALLOWED_AUDIO_EXT:
        raise ValueError(f"Unsupported audio format: {fmt}")

    dest = AUDIO_DIR / f"{local_uuid}.{fmt}"
    # Make sure the resolved path is still inside AUDIO_DIR (defense in depth).
    if AUDIO_DIR.resolve() not in dest.resolve().parents:
        raise ValueError("Resolved audio path escapes AUDIO_DIR")

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(dest, flags, 0o600)
    except FileExistsError:
        return dest, False
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
    except Exception:
        # Clean up partial write so a retry can succeed.
        try:
            dest.unlink(missing_ok=True)
        except Exception:  # pragma: no cover
            pass
        raise
    return dest, True


def jsonl_path_for(date_str: str) -> Path:
    """data/activity/YYYY-MM-DD.jsonl for the given date string."""
    _ensure_dirs()
    return ACTIVITY_DIR / f"{date_str}.jsonl"


def append_events_to_jsonl(events: list[dict]) -> None:
    """Append each event to its day's jsonl. Expected key: `started_at` (ISO)."""
    if not events:
        return
    _ensure_dirs()
    # Group by date (UTC part of the ISO timestamp).
    by_date: dict[str, list[dict]] = {}
    for e in events:
        ts = (e.get("started_at") or "")[:10]  # YYYY-MM-DD
        if not ts:
            continue
        by_date.setdefault(ts, []).append(e)
    for date_str, bucket in by_date.items():
        path = jsonl_path_for(date_str)
        with path.open("a", encoding="utf-8") as f:
            for e in bucket:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")


def transcribe_audio(audio_row: dict) -> tuple[str, str]:
    """Run Whisper on the stored audio file. Returns (transcript, json_path).

    Caller is responsible for updating audio_recordings with the result.
    """
    from openai import OpenAI
    from src.shared.config import OPENAI_API_KEY, OPENAI_BASE_URL, TRANSCRIPTION_MODEL

    audio_path = Path(audio_row["file_path"])
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file missing: {audio_path}")

    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with audio_path.open("rb") as fh:
                resp = client.audio.transcriptions.create(
                    model=TRANSCRIPTION_MODEL,
                    file=fh,
                )
            transcript = resp.text or ""
            # Persist raw response alongside the audio for later word-timing work.
            json_path = audio_path.with_suffix(".transcript.json")
            json_path.write_text(
                json.dumps({"text": transcript, "model": TRANSCRIPTION_MODEL}, ensure_ascii=False),
                encoding="utf-8",
            )
            return transcript, str(json_path)
        except Exception as exc:
            last_error = exc
            wait = 2 ** attempt
            logger.warning(
                "Transcription attempt %d/3 failed for audio_id=%s: %s. Retrying in %ds",
                attempt + 1, audio_row.get("id"), exc, wait,
            )
            time.sleep(wait)

    raise RuntimeError(f"Transcription failed after 3 attempts: {last_error}") from last_error


def process_audio_transcription(audio_id: int) -> None:
    """Worker task: transcribe a single audio_recordings row end-to-end.

    Safe to call from asyncio.create_task via run_in_executor. Never raises —
    failures are recorded on the row so the client can poll for them.
    """
    row = db.get_audio_recording(audio_id)
    if not row:
        logger.error("process_audio_transcription: audio_id=%s not found", audio_id)
        return
    if row["status"] == "transcribed":
        return  # already done, idempotent

    db.set_audio_status(audio_id, "transcribing")
    try:
        transcript, json_path = transcribe_audio(row)
        db.update_audio_transcript(
            audio_id=audio_id,
            transcript=transcript,
            transcript_path=json_path,
            status="transcribed",
        )
        logger.info("Transcribed audio_id=%s (%d chars)", audio_id, len(transcript))
    except Exception as exc:
        logger.error("Transcription failed for audio_id=%s: %s", audio_id, exc)
        db.update_audio_transcript(
            audio_id=audio_id,
            transcript="",
            transcript_path="",
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
