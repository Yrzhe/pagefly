"""Classifier — single Claude API call with structured output."""

import json

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
    },
    "required": ["category", "title", "description", "tags", "confidence", "reasoning"],
    "additionalProperties": False,
}


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
                "content": f"Categories:\n{categories_json}\n\nDocument content:\n{content_excerpt}",
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
            if subcategory:
                cat_def = next(
                    (c for c in categories_data["categories"] if c["id"] == result["category"]),
                    None,
                )
                if cat_def and subcategory not in cat_def.get("subcategories", []):
                    subcategory = ""

            logger.info(
                "Classified (attempt %d): %s/%s (confidence=%.2f)",
                attempt, result["category"], subcategory, result["confidence"],
            )
            return ClassificationResult(
                category=result["category"],
                subcategory=subcategory,
                title=result["title"],
                description=result["description"],
                tags=result.get("tags", []),
                confidence=result["confidence"],
                reasoning=result.get("reasoning", ""),
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
    )
