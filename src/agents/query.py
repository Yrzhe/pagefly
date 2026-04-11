"""Query Agent — interactive knowledge assistant, used by Telegram bot."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import query

from src.agents.base import build_agent_options
from src.shared.logger import get_logger
from src.storage.db import init_db

logger = get_logger("agents.query")

# Callback type for tool call events
ToolCallback = Callable[[str], Coroutine[Any, Any, None]]


@dataclass
class QuerySession:
    """Holds a multi-turn conversation with the query agent."""
    messages: list[dict] = field(default_factory=list)


async def ask(
    user_message: str,
    session: QuerySession | None = None,
    on_tool_call: ToolCallback | None = None,
) -> str:
    """
    Send a message to the query agent and get a response.
    on_tool_call: async callback invoked with tool name when agent calls a tool.
    """
    init_db()
    options = build_agent_options(skill_name="query")

    # Build conversation context from session history
    if session and session.messages:
        history_parts = []
        for m in session.messages[-20:]:
            tag = "user" if m["role"] == "user" else "assistant"
            history_parts.append(f"<{tag}>{m['content']}</{tag}>")
        history = "\n".join(history_parts)
        prompt = f"<conversation_history>\n{history}\n</conversation_history>\n\n{user_message}"
    else:
        prompt = user_message

    if session is not None:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).astimezone().isoformat()
        session.messages.append({"role": "user", "content": user_message, "ts": ts})

    response_parts = []

    async for message in query(prompt=prompt, options=options):
        if not hasattr(message, "content"):
            continue

        for block in message.content:
            # Tool call event
            if hasattr(block, "name") and on_tool_call:
                tool_name = block.name.replace("mcp__pagefly__", "")
                try:
                    await on_tool_call(tool_name)
                except Exception:
                    pass

            # Text response
            if hasattr(block, "text"):
                response_parts.append(block.text)

    response = "\n".join(response_parts) if response_parts else "No response from agent."

    if session is not None:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).astimezone().isoformat()
        session.messages.append({"role": "assistant", "content": response, "ts": ts})

    return response


async def main():
    """Interactive CLI mode for testing."""
    session = QuerySession()
    print("PageFly Query Agent (type 'quit' to exit)")
    print("-" * 40)

    async def on_tool(name: str):
        print(f"  [tool] {name}")

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue

        print("Agent: ", end="", flush=True)
        response = await ask(user_input, session, on_tool_call=on_tool)
        print(response)


if __name__ == "__main__":
    asyncio.run(main())
