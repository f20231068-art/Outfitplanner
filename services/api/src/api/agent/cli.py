"""Terminal chat for the stylist agent: `uv run python -m api.agent.cli [thread-id]`.

The conversation never ends: keep typing (a style, "cheaper", "more like outfit 2", a question). Type "quit" to
leave. Re-run with the same thread-id to continue from Postgres.
"""

import sys
import uuid

from langgraph.checkpoint.postgres import PostgresSaver

from api.agent.graph import build_graph
from api.agent.llm import get_llm
from api.agent.products import mock_search
from api.config import settings


def show(values: dict) -> None:
    print(f"\nStylist: {values['messages'][-1].content}")
    if values.get("phase") == "choosing_style":
        for s in values["styles"]:
            print(f"  [{s['id']}] {s['name']} - {s['description']}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252 and choke on the rupee sign
    thread_id = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
    print(f"(thread: {thread_id})  type quit to leave")
    config = {"configurable": {"thread_id": thread_id}}

    with PostgresSaver.from_conn_string(settings.database_url) as saver:
        saver.setup()
        graph = build_graph(get_llm(), mock_search, saver)
        while True:
            text = input("You: ").strip()
            if text.lower() in ("quit", "exit"):
                break
            if text:
                show(graph.invoke({"messages": [("user", text)]}, config))


if __name__ == "__main__":
    main()
