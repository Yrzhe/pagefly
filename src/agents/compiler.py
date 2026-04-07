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
        "Start by reading the wiki index (read_wiki_index) to see what's already compiled, "
        "then list all documents in knowledge/ to find new uncompiled content. "
        "Read the new documents, then generate summary articles, concept articles, "
        "or connection analyses as appropriate. "
        "For each article, provide a clear one-line summary (max 150 chars). "
        "Write each compiled article to wiki/ using the write_wiki_article tool. "
        "Focus on extracting key insights and identifying connections between documents."
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
