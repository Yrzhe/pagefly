"""Classifier — single Claude API call with structured output."""

import json
import re

import anthropic

from src.shared.config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, CLASSIFIER_MODEL, load_categories, load_prompt
from src.shared.logger import get_logger
from src.shared.types import ClassificationResult

logger = get_logger("governance.classifier")

MAX_RETRIES = 3

CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string"},
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
        "category", "title", "description", "tags", "confidence", "reasoning",
        "relevance_score", "temporal_type", "key_claims",
    ],
    "additionalProperties": False,
}


def _build_existing_structure() -> str:
    """Scan knowledge/ to build a snapshot of existing categories, subcategories, and article titles."""
    from src.shared.config import KNOWLEDGE_DIR

    if not KNOWLEDGE_DIR.exists():
        return "No existing documents yet."

    structure: dict[str, dict[str, list[str]]] = {}
    for meta_path in KNOWLEDGE_DIR.rglob("metadata.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            cat = meta.get("category", "")
            sub = meta.get("subcategory", "")
            title = meta.get("title", "")
            if not cat:
                continue
            if cat not in structure:
                structure[cat] = {}
            if sub not in structure[cat]:
                structure[cat][sub] = []
            if title and len(structure[cat][sub]) < 5:
                structure[cat][sub].append(title)
        except Exception:
            continue

    if not structure:
        return "No existing documents yet."

    lines = ["Existing knowledge base structure (use these categories/subcategories when possible):"]
    for cat in sorted(structure):
        for sub in sorted(structure[cat]):
            titles = structure[cat][sub]
            label = f"{cat}/{sub}" if sub else cat
            titles_str = ", ".join(f'"{t}"' for t in titles[:3])
            lines.append(f"  - {label} ({len(titles)} docs, e.g. {titles_str})")

    return "\n".join(lines)


def classify(content: str, max_chars: int = 2000) -> ClassificationResult:
    """
    Classify document content.
    - Load categories from categories.json
    - Load prompt from prompts/classifier.md
    - Call Claude API with structured output
    - Validate returned category is in the list
    - Retry up to 3 times if category is invalid
    """
    categories_data = load_categories()
    system_prompt = load_prompt("classifier")
    categories_json = json.dumps(categories_data, ensure_ascii=False, indent=2)
    content_excerpt = content[:max_chars]
    existing_structure = _build_existing_structure()

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, base_url=ANTHROPIC_BASE_URL)
    valid_ids = {c["id"] for c in categories_data["categories"]}

    last_result: dict = {}
    for attempt in range(1, MAX_RETRIES + 1):
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": (
                    f"Categories:\n{categories_json}\n\n"
                    f"{existing_structure}\n\n"
                    f"Document content:\n{content_excerpt}"
                ),
            }],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": CLASSIFICATION_SCHEMA,
                }
            },
        )

        text = next((b.text for b in response.content if b.type == "text"), "")
        result = json.loads(text)
        last_result = result

        if result["category"] in valid_ids:
            subcategory = result.get("subcategory", "")
            # Allow classifier to propose new subcategories — don't force empty
            # Sanitize: ASCII-only, lowercase, hyphens, no consecutive hyphens
            if subcategory:
                subcategory = subcategory.strip().lower().replace(" ", "-")
                subcategory = "".join(c for c in subcategory if c.isascii() and (c.isalnum() or c == "-"))
                subcategory = re.sub(r'-{2,}', '-', subcategory).strip("-")
                if not subcategory:
                    subcategory = ""

            relevance = max(1, min(10, int(result.get("relevance_score", 5))))
            temporal = result.get("temporal_type", "evergreen")
            if temporal not in ("evergreen", "time_sensitive"):
                temporal = "evergreen"
            key_claims = result.get("key_claims", [])[:5]

            logger.info(
                "Classified (attempt %d): %s/%s (confidence=%.2f, relevance=%d, %s)",
                attempt, result["category"], subcategory, result["confidence"],
                relevance, temporal,
            )
            return ClassificationResult(
                category=result["category"],
                subcategory=subcategory,
                title=result["title"],
                description=result["description"],
                tags=result.get("tags", []),
                confidence=result["confidence"],
                reasoning=result.get("reasoning", ""),
                relevance_score=relevance,
                temporal_type=temporal,
                key_claims=key_claims,
            )

        logger.warning(
            "Attempt %d: category '%s' not in valid list, retrying...",
            attempt, result["category"],
        )

    logger.warning("All %d attempts failed, falling back to misc", MAX_RETRIES)
    return ClassificationResult(
        category="misc",
        subcategory="",
        title=last_result.get("title", ""),
        description=last_result.get("description", ""),
        tags=last_result.get("tags", []),
        confidence=0.0,
        reasoning="Classification failed after max retries",
        relevance_score=5,
        temporal_type="evergreen",
        key_claims=[],
    )
