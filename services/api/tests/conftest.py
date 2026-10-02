"""Shared test setup: a real, throwaway Postgres database (the local docker one), so the SQL,
triggers and locks are tested for real. Tests that need it are skipped if Postgres is not running."""

import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from api.config import settings
from api.db import make_pool, migrate


def _url_for(dbname: str) -> str:
    return make_conninfo(**{**conninfo_to_dict(settings.database_url), "dbname": dbname})


def _admin() -> psycopg.Connection:
    return psycopg.connect(_url_for("postgres"), autocommit=True, connect_timeout=3)


@pytest.fixture
def make_database():
    """Factory: returns the URL of a brand-new migrated database; all are dropped afterwards."""
    created: list[str] = []

    def factory() -> str:
        try:
            admin = _admin()
        except psycopg.OperationalError:
            pytest.skip("Postgres is not running (docker compose up -d postgres)")
        name = f"stylist_test_{uuid.uuid4().hex[:10]}"
        with admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        created.append(name)
        url = _url_for(name)
        migrate(url)
        return url

    yield factory
    if created:
        with _admin() as admin:
            for name in created:
                admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def db_url(make_database) -> str:
    return make_database()


@pytest.fixture
def pool(db_url):
    p = make_pool(db_url, min_size=1, max_size=8)
    yield p
    p.close()
