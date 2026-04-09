"""Classifier — two-step classification with structured output."""

import json
import re

import anthropic

from src.shared.config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, CLASSIFIER_MODEL, KNOWLEDGE_DIR, load_categories, load_prompt
from src.shared.logger import get_logger
from src.shared.types import ClassificationResult

logger = get_logger("governance.classifier")

MAX_RETRIES = 3

# ── Step 1 schema: category only ──

STEP1_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["category", "reasoning"],
    "additionalProperties": False,
}

# ── Step 2 schema: subcategory + all metadata ──

STEP2_SCHEMA = {
    "type": "object",
    "properties": {
        "subcategory": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "relevance_score": {"type": "integer", "description": "Personal value to user, 1-10"},
        "temporal_type": {"type": "string", "enum": ["evergreen", "time_sensitive"]},
        "key_claims": {"type": "array", "items": {"type": "string"}, "description": "Core assertions, max 5"},
    },
    "required": [
        "subcategory", "title", "description", "tags", "confidence", "reasoning",
        "relevance_score", "temporal_type", "key_claims",
    ],
    "additionalProperties": False,
}


def _normalize(s: str) -> str:
    """Normalize a string for matching: lowercase, strip, hyphens for spaces."""
    s = s.strip().lower().replace(" ", "-").replace("_", "-")
    s = "".join(c for c in s if c.isascii() and (c.isalnum() or c == "-"))
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def _fuzzy_match(value: str, candidates: set[str]) -> str | None:
    """Try to match a value to candidates using normalized comparison."""
    norm = _normalize(value)
    for c in candidates:
        if _normalize(c) == norm:
            return c
    return None


def _get_existing_subcategories(category: str) -> dict[str, list[str]]:
    """Get existing subcategories and their article titles for a category from the filesystem."""
    result: dict[str, list[str]] = {}
    cat_dir = KNOWLEDGE_DIR / category
    if not cat_dir.exists():
        return result

    for meta_path in cat_dir.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            sub = meta.get("subcategory", "")
            title = meta.get("title", "")
            if sub not in result:
                result[sub] = []
            if title and len(result[sub]) < 5:
                result[sub].append(title)
        except Exception:
            continue
    return result


def _get_existing_categories() -> dict[str, list[str]]:
    """Get existing categories and sample titles from the filesystem."""
    result: dict[str, list[str]] = {}
    if not KNOWLEDGE_DIR.exists():
        return result

    for meta_path in KNOWLEDGE_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            cat = meta.get("category", "")
            title = meta.get("title", "")
            if not cat:
                continue
            if cat not in result:
                result[cat] = []
            if title and len(result[cat]) < 3:
                result[cat].append(title)
        except Exception:
            continue
    return result


def classify(content: str, max_chars: int = 2000) -> ClassificationResult:
    """
    Two-step classification:
    Step 1: Choose category (with existing categories as context)
    Step 2: Choose subcategory + metadata (with existing subcategories for that category)
    """
    categories_data = load_categories()
    system_prompt = load_prompt("classifier")
    content_excerpt = content[:max_chars]

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, base_url=ANTHROPIC_BASE_URL)
    valid_ids = {c["id"] for c in categories_data["categories"]}

    # ── Step 1: Pick category ──
    existing_cats = _get_existing_categories()
    existing_lines = []
    for cat_id, titles in sorted(existing_cats.items()):
        sample = ", ".join(f'"{t}"' for t in titles)
        existing_lines.append(f"  - {cat_id} ({len(titles)} docs, e.g. {sample})")
    existing_str = "\n".join(existing_lines) if existing_lines else "  (no documents yet)"

    categories_list = json.dumps([c["id"] for c in categories_data["categories"]])

    category = None
    for attempt in range(1, MAX_RETRIES + 1):
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=256,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": (
                    f"STEP 1: Choose the best category for this document.\n\n"
                    f"Available categories: {categories_list}\n\n"
                    f"Existing documents by category:\n{existing_str}\n\n"
                    f"Document content:\n{content_excerpt}"
                ),
            }],
            output_config={"format": {"type": "json_schema", "schema": STEP1_SCHEMA}},
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        result = json.loads(text)

        raw_cat = result.get("category", "")
        matched = _fuzzy_match(raw_cat, valid_ids)
        if matched:
            category = matched
            logger.info("Step 1 (attempt %d): category=%s", attempt, category)
            break
        logger.warning("Step 1 attempt %d: '%s' not valid, retrying...", attempt, raw_cat)

    if not category:
        category = "misc"
        logger.warning("Step 1 failed, falling back to misc")

    # ── Step 2: Pick subcategory + metadata ──
    # Get predefined subcategories from config
    cat_def = next((c for c in categories_data["categories"] if c["id"] == category), None)
    predefined_subs = set(cat_def.get("subcategories", [])) if cat_def else set()

    # Get existing subcategories from filesystem
    existing_subs = _get_existing_subcategories(category)
    all_subs = predefined_subs | set(existing_subs.keys())
    all_subs.discard("")  # remove empty

    sub_lines = []
    for sub in sorted(all_subs):
        titles = existing_subs.get(sub, [])
        if titles:
            sample = ", ".join(f'"{t}"' for t in titles[:3])
            sub_lines.append(f"  - {sub} ({len(titles)} docs, e.g. {sample})")
        else:
            sub_lines.append(f"  - {sub} (no docs yet)")
    subs_str = "\n".join(sub_lines) if sub_lines else "  (no subcategories yet — you may propose one or leave empty)"

    last_result: dict = {}
    for attempt in range(1, MAX_RETRIES + 1):
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": (
                    f"STEP 2: The document has been assigned to category '{category}'.\n"
                    f"Now choose a subcategory and extract metadata.\n\n"
                    f"Existing subcategories under '{category}':\n{subs_str}\n\n"
                    f"IMPORTANT: Prefer existing subcategories. Only propose a new one if none fit.\n"
                    f"If no subcategory is needed, use empty string.\n"
                    f"New subcategories must be lowercase English with hyphens (e.g., 'reinforcement-learning').\n\n"
                    f"Document content:\n{content_excerpt}"
                ),
            }],
            output_config={"format": {"type": "json_schema", "schema": STEP2_SCHEMA}},
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        result = json.loads(text)
        last_result = result

        # Normalize and match subcategory
        raw_sub = result.get("subcategory", "")
        if raw_sub:
            matched_sub = _fuzzy_match(raw_sub, all_subs)
            subcategory = matched_sub if matched_sub else _normalize(raw_sub)
        else:
            subcategory = ""

        relevance = max(1, min(10, int(result.get("relevance_score", 5))))
        temporal = result.get("temporal_type", "evergreen")
        if temporal not in ("evergreen", "time_sensitive"):
            temporal = "evergreen"
        key_claims = result.get("key_claims", [])[:5]

        logger.info(
            "Step 2 (attempt %d): %s/%s (confidence=%.2f, relevance=%d, %s)",
            attempt, category, subcategory, result.get("confidence", 0),
            relevance, temporal,
        )
        return ClassificationResult(
            category=category,
            subcategory=subcategory,
            title=result.get("title", ""),
            description=result.get("description", ""),
            tags=result.get("tags", []),
            confidence=result.get("confidence", 0.0),
            reasoning=result.get("reasoning", ""),
            relevance_score=relevance,
            temporal_type=temporal,
            key_claims=key_claims,
        )

    # Fallback
    logger.warning("Step 2 failed, returning with partial data")
    return ClassificationResult(
        category=category,
        subcategory="",
        title=last_result.get("title", ""),
        description=last_result.get("description", ""),
        tags=last_result.get("tags", []),
        confidence=0.0,
        reasoning="Step 2 classification failed",
        relevance_score=5,
        temporal_type="evergreen",
        key_claims=[],
    )
