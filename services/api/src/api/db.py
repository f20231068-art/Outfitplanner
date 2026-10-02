"""Database access: a connection pool and a tiny migration runner.

Migrations are numbered SQL files in services/api/migrations/. `migrate()` applies the ones that
have not been applied yet, in order, each in its own transaction, and records them in
schema_migrations. Run it with:  uv run python -m api.db
"""

import logging
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api.config import settings

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
MIGRATION_LOCK = 727_002  # so two copies of the app starting together do not both migrate


def make_pool(
    url: str | None = None, min_size: int = 1, max_size: int = 10, autocommit: bool = False
) -> ConnectionPool:
    """A pool of connections shared by all requests. Rows come back as dicts.
    `autocommit=True` is what LangGraph's checkpointer requires; normal request code uses
    transactions (commit on success, roll back on error)."""
    return ConnectionPool(
        url or settings.database_url, min_size=min_size, max_size=max_size,
        kwargs={"row_factory": dict_row, "autocommit": autocommit}, open=True,
    )


def migrate(url: str | None = None, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations. Returns the versions applied in this call."""
    applied_now: list[str] = []
    with psycopg.connect(url or settings.database_url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for path in sorted(directory.glob("*.sql")):
                if path.stem in done:
                    continue
                with conn.transaction():  # all of a file, or none of it
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
                applied_now.append(path.stem)
                log.info("applied migration %s", path.stem)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))
    return applied_now


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("applied:", migrate() or "nothing to do")
