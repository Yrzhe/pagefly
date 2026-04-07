"""分类器 — 单次 Claude API 调用 + 结构化输出。"""

import json

import anthropic

from src.shared.config import ANTHROPIC_API_KEY, CLASSIFIER_MODEL, load_categories, load_prompt
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
    对文档内容进行分类。
    - 从 categories.json 加载分类列表
    - 从 prompts/classifier.md 加载提示词
    - 调用 Claude API 获取结构化分类结果
    - 校验返回的 category 是否在列表中
    - 不在则重试（最多 3 次）
    """
    categories_data = load_categories()
    system_prompt = load_prompt("classifier")
    categories_json = json.dumps(categories_data, ensure_ascii=False, indent=2)
    content_excerpt = content[:max_chars]

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    valid_ids = {c["id"] for c in categories_data["categories"]}

    for attempt in range(1, MAX_RETRIES + 1):
        response = client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"分类列表：\n{categories_json}\n\n文档内容：\n{content_excerpt}",
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
        title=result.get("title", ""),
        description=result.get("description", ""),
        tags=result.get("tags", []),
        confidence=0.0,
        reasoning="Classification failed after max retries",
    )
