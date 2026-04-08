"""Voice converter — transcribes audio files to markdown via OpenAI API."""

import time
from pathlib import Path

from openai import OpenAI

from src.shared.config import OPENAI_API_KEY, OPENAI_BASE_URL, TRANSCRIPTION_MODEL
from src.shared.logger import get_logger
from src.shared.types import ConvertResult, IngestInput

logger = get_logger("ingest.converters.voice")

VOICE_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".webm", ".flac", ".mp4", ".mpeg", ".mpga"}
MAX_RETRIES = 3
RETRY_BACKOFF = 2


def _get_client() -> OpenAI:
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def can_handle(input_data: IngestInput) -> bool:
    if input_data.type == "file" and input_data.file_path:
        p = Path(input_data.file_path)
        return p.exists() and p.suffix.lower() in VOICE_EXTENSIONS
    return False


def convert(input_data: IngestInput) -> ConvertResult:
    """Audio file -> Markdown transcription."""
    audio_path = Path(input_data.file_path)
    audio_name = audio_path.stem
    client = _get_client()

    transcript = _transcribe(client, audio_path)

    if not transcript.strip():
        transcript = "*No speech detected in audio.*"

    title = _extract_title(transcript, input_data.original_filename or audio_name)

    # Build markdown
    duration_note = f"Source: {input_data.original_filename or audio_path.name}"
    markdown = (
        f"# {title}\n\n"
        f"> {duration_note}\n\n"
        f"{transcript}"
    )

    logger.info(
        "Voice converted: %s (%d chars, model=%s)",
        audio_name, len(transcript), TRANSCRIPTION_MODEL,
    )
    return ConvertResult(markdown=markdown, title=title, images=[])


def _transcribe(client: OpenAI, audio_path: Path) -> str:
    """Transcribe audio file with retry."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            with open(audio_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model=TRANSCRIPTION_MODEL,
                    file=audio_file,
                )
            return response.text
        except Exception as e:
            last_error = e
            wait = RETRY_BACKOFF ** attempt
            logger.warning(
                "Transcription failed (attempt %d/%d): %s. Retrying in %ds...",
                attempt + 1, MAX_RETRIES, e, wait,
            )
            time.sleep(wait)

    raise RuntimeError(f"Transcription failed after {MAX_RETRIES} attempts: {last_error}") from last_error


def _extract_title(transcript: str, fallback: str) -> str:
    """Extract title from first sentence, or use filename."""
    # Use first ~60 chars of transcript as title
    first_line = transcript.strip().split("\n")[0]
    if len(first_line) > 80:
        # Cut at word boundary
        title = first_line[:77].rsplit(" ", 1)[0] + "..."
    elif first_line:
        title = first_line
    else:
        title = Path(fallback).stem if "." in fallback else fallback
    return title
