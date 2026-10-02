"""Terminal chat for the stylist agent: `uv run python -m api.agent.cli [thread-id]`.

Re-run with the same thread-id to resume a paused session from Postgres.
"""

import sys
import uuid

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from api.agent.graph import build_graph
from api.agent.llm import get_llm
from api.agent.products import mock_search
from api.config import settings


def show_interrupt(payload: dict) -> str:
    if payload["type"] == "choose_style":
        print("\nStylist: Pick a style:")
        for s in payload["styles"]:
            print(f"  [{s['id']}] {s['name']} - {s['description']}")
    else:
        print(f"\nStylist: {payload['question']}")
    return input("You: ").strip()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252 and choke on the rupee sign
    thread_id = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
    print(f"(thread: {thread_id})")
    config = {"configurable": {"thread_id": thread_id}}

    with PostgresSaver.from_conn_string(settings.database_url) as saver:
        saver.setup()
        graph = build_graph(get_llm(), mock_search, saver)

        if graph.get_state(config).next:  # paused session: just resume
            result = graph.invoke(None, config)
        else:
            result = graph.invoke({"messages": [("user", input("You: ").strip())]}, config)

        while result.get("__interrupt__"):
            answer = show_interrupt(result["__interrupt__"][0].value)
            result = graph.invoke(Command(resume=answer), config)

        print(f"\nStylist: {result['messages'][-1].content}")


if __name__ == "__main__":
    main()
