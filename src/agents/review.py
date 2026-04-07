"""Review Agent — generates daily/weekly/monthly knowledge reviews."""

import asyncio

from claude_agent_sdk import query

from src.agents.base import build_agent_options
from src.shared.config import load_skill_prompt
from src.shared.logger import get_logger
from src.storage.db import init_db

logger = get_logger("agents.review")


async def run_review(review_type: str = "daily") -> str:
    """
    Run a review agent for the given type (daily/weekly/monthly).
    Returns the review summary text.
    """
    init_db()

    # Load the review-type specific prompt
    try:
        type_prompt = load_skill_prompt("review", review_type)
    except FileNotFoundError:
        type_prompt = f"Generate a {review_type} review of the knowledge base."

    options = build_agent_options(
        skill_name="review",
        extra_system=f"Review type: {review_type}",
    )

    logger.info("Starting %s review agent...", review_type)

    response_parts = []

    async for message in query(prompt=type_prompt, options=options):
        if hasattr(message, "content"):
            for block in message.content:
                if hasattr(block, "text"):
                    response_parts.append(block.text)

    response = "\n".join(response_parts) if response_parts else f"No {review_type} review generated."

    logger.info("%s review complete (%d chars)", review_type, len(response))
    return response


def main():
    """CLI entry point."""
    import sys
    review_type = sys.argv[1] if len(sys.argv) > 1 else "daily"
    result = asyncio.run(run_review(review_type))
    print(result)


if __name__ == "__main__":
    main()
