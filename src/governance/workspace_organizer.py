"""Workspace organizer — daily LLM-powered triage of workspace files."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from src.shared.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_BASE_URL,
    CLASSIFIER_MODEL,
    WORKSPACE_DIR,
    RAW_DIR,
)
from src.shared.logger import get_logger

logger = get_logger("governance.workspace_organizer")

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "action": {"type": "string", "enum": ["delete", "ingest", "keep"]},
                    "reason": {"type": "string"},
                },
                "required": ["path", "action", "reason"],
            },
        },
    },
    "required": ["decisions"],
}

SYSTEM_PROMPT = """You are the PageFly workspace organizer. Your job is to triage files in the agent workspace.

For each file, decide one of:
- **keep**: File is still useful (recent drafts, work in progress, actively referenced)
- **ingest**: File has lasting value and should be saved to the knowledge base (move to raw/ for processing)
- **delete**: File is temporary, outdated, or no longer needed (scratch notes, old exports, test outputs)

Rules:
- Files older than 7 days that aren't actively useful should be deleted
- Drafts or analysis results with lasting value should be ingested
- Recently created files (< 1 day) should usually be kept unless obviously disposable
- When in doubt, keep rather than delete
- Use the same language as the file content for the reason field"""


def organize_workspace() -> dict:
    """
    Scan workspace, ask LLM to triage each file, execute decisions.
    Returns summary: {kept: int, ingested: int, deleted: int, errors: int, details: list}
    """
    if not WORKSPACE_DIR.exists() or not any(WORKSPACE_DIR.rglob("*")):
        logger.info("Workspace is empty, nothing to organize")
        return {"kept": 0, "ingested": 0, "deleted": 0, "errors": 0, "details": []}

    # 1. Collect file inventory
    inventory = _scan_workspace()
    if not inventory:
        return {"kept": 0, "ingested": 0, "deleted": 0, "errors": 0, "details": []}

    # 2. Ask LLM for decisions
    decisions = _get_decisions(inventory)

    # 3. Execute decisions
    result = _execute_decisions(decisions)

    # 4. Clean up empty directories
    _cleanup_empty_dirs()

    logger.info(
        "Workspace organized: kept=%d, ingested=%d, deleted=%d, errors=%d",
        result["kept"], result["ingested"], result["deleted"], result["errors"],
    )
    return result


def _scan_workspace() -> list[dict]:
    """Collect file info + preview for each workspace file."""
    now = datetime.now(timezone.utc)
    files = []

    for file_path in sorted(WORKSPACE_DIR.rglob("*")):
        if not file_path.is_file():
            continue

        rel_path = str(file_path.relative_to(WORKSPACE_DIR))
        stat = file_path.stat()
        age_days = (now - datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)).days

        # Read preview (first 500 chars for text files)
        preview = ""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            preview = content[:500]
        except Exception:
            preview = f"(binary file, {stat.st_size} bytes)"

        files.append({
            "path": rel_path,
            "size_bytes": stat.st_size,
            "age_days": age_days,
            "preview": preview,
        })

    return files


def _get_decisions(inventory: list[dict]) -> list[dict]:
    """Call LLM to decide what to do with each file."""
    file_descriptions = []
    for f in inventory:
        file_descriptions.append(
            f"**{f['path']}** (size={f['size_bytes']}B, age={f['age_days']}d)\n"
            f"Preview: {f['preview'][:300]}"
        )

    user_msg = (
        f"Today is {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.\n"
        f"There are {len(inventory)} files in the workspace:\n\n"
        + "\n\n---\n\n".join(file_descriptions)
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, base_url=ANTHROPIC_BASE_URL)

    try:
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": DECISION_SCHEMA,
                }
            },
        )

        text = next((b.text for b in response.content if b.type == "text"), "")
        result = json.loads(text)
        return result.get("decisions", [])
    except Exception as e:
        logger.error("LLM decision failed: %s", e)
        return []


def _execute_decisions(decisions: list[dict]) -> dict:
    """Execute triage decisions."""
    from src.shared.activity_log import append_log

    summary = {"kept": 0, "ingested": 0, "deleted": 0, "errors": 0, "details": []}

    for d in decisions:
        rel_path = d["path"]
        action = d["action"]
        reason = d.get("reason", "")
        file_path = (WORKSPACE_DIR / rel_path).resolve()

        # Safety check
        if not file_path.is_relative_to(WORKSPACE_DIR.resolve()):
            logger.warning("Skipping path outside workspace: %s", rel_path)
            summary["errors"] += 1
            continue

        if not file_path.exists():
            logger.warning("File not found: %s", rel_path)
            summary["errors"] += 1
            continue

        try:
            if action == "keep":
                summary["kept"] += 1

            elif action == "delete":
                file_path.unlink()
                summary["deleted"] += 1
                logger.info("Workspace delete: %s (%s)", rel_path, reason)

            elif action == "ingest":
                _move_to_raw(file_path, rel_path)
                summary["ingested"] += 1
                logger.info("Workspace ingest: %s (%s)", rel_path, reason)

            summary["details"].append({"path": rel_path, "action": action, "reason": reason})

        except Exception as e:
            logger.error("Failed to %s %s: %s", action, rel_path, e)
            summary["errors"] += 1

    # Log activity
    if summary["deleted"] + summary["ingested"] > 0:
        append_log(
            "workspace_organize",
            f"Daily triage: {summary['deleted']} deleted, {summary['ingested']} ingested, {summary['kept']} kept",
        )

    return summary


def _move_to_raw(file_path: Path, rel_path: str) -> None:
    """Move a workspace file to raw/ for ingest processing."""
    from src.ingest.pipeline import ingest
    from src.shared.types import IngestInput

    input_data = IngestInput(
        type="file",
        file_path=str(file_path),
        original_filename=file_path.name,
    )
    doc_id = ingest(input_data)

    if doc_id:
        file_path.unlink(missing_ok=True)
        logger.info("Workspace file ingested: %s → raw/ (id=%s)", rel_path, doc_id[:8])
    else:
        logger.warning("Ingest failed for workspace file: %s", rel_path)


def _cleanup_empty_dirs() -> None:
    """Remove empty directories in workspace."""
    if not WORKSPACE_DIR.exists():
        return
    for dir_path in sorted(WORKSPACE_DIR.rglob("*"), reverse=True):
        if dir_path.is_dir() and not any(dir_path.iterdir()):
            dir_path.rmdir()
