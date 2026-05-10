"""Linker Agent — discovers cross-domain connections between knowledge documents."""

import asyncio

from claude_agent_sdk import query

from src.agents.base import build_agent_options
from src.shared.logger import get_logger
from src.storage.db import init_db

logger = get_logger("agents.linker")


async def run_linker() -> str:
    """
    Run the linker agent.
    It will autonomously:
    1. Survey existing connections in the wiki
    2. Analyze documents for missing cross-domain links
    3. Create/update connection articles in wiki/
    Returns a summary of work done.
    """
    init_db()
    options = build_agent_options(skill_name="linker", max_turns=40)

    prompt = (
        "Discover missing connections in the knowledge base. "
        "Start by reading the wiki index to see existing connections. "
        "Then query the database for document categories and tags to find "
        "cross-domain opportunities. Read promising document pairs and create "
        "connection articles where genuine relationships exist. "
        "Focus on quality over quantity — max 10 new connections per run."
    )

    logger.info("Starting linker agent...")
    response_parts = []

    async for message in query(prompt=prompt, options=options):
        if hasattr(message, "content"):
            for block in message.content:
                if hasattr(block, "text"):
                    response_parts.append(block.text)

    result = "\n".join(response_parts) if response_parts else "No connections discovered."

    from src.shared.activity_log import append_log
    append_log("linker", "Linker run finished", f"{len(result)} chars")

    logger.info("Linker agent finished (%d chars output).", len(result))
    return result


def main() -> None:
    """Entry point for running the linker."""
    asyncio.run(run_linker())


if __name__ == "__main__":
    main()
