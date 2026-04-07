"""Compiler Agent — reads knowledge/, generates compiled articles in wiki/."""

import asyncio

from claude_agent_sdk import query

from src.agents.base import build_agent_options
from src.shared.logger import get_logger
from src.storage.db import init_db

logger = get_logger("agents.compiler")


async def run_compiler() -> None:
    """
    Run the compiler agent.
    It will autonomously:
    1. List documents in knowledge/
    2. Read their content
    3. Identify themes and connections
    4. Write compiled articles to wiki/
    """
    init_db()
    options = build_agent_options(skill_name="compiler")

    prompt = (
        "Please compile the knowledge base. "
        "Start by reading the wiki index (read_wiki_index) to see what's already compiled. "
        "Then list all documents in knowledge/ to find new uncompiled content. "
        "Read the new documents and for each one: "
        "1) Create a summary article (one per source doc). "
        "2) Extract key concepts — if a concept page already exists in the index, "
        "READ it and UPDATE it (pass update_id) with merged new information. "
        "Only create a new concept page if nothing related exists. "
        "3) Discover connections — same rule: update existing connection pages, don't duplicate. "
        "When new info contradicts old data, mark it with ⚠️ 矛盾 inline. "
        "For each article, provide a clear one-line summary (max 150 chars)."
    )

    from src.shared.activity_log import append_log
    logger.info("Starting compiler agent...")

    async for message in query(prompt=prompt, options=options):
        if hasattr(message, "content"):
            logger.info("Agent: %s", str(message.content)[:200])
        elif hasattr(message, "result"):
            logger.info("Agent result: %s", str(message.result)[:200])

    append_log("compile", "Compiler run finished")
    logger.info("Compiler agent finished.")


def main() -> None:
    """Entry point for running the compiler."""
    asyncio.run(run_compiler())


if __name__ == "__main__":
    main()
