"""Outils communs des tests.

- Jeu d'essai : tests/fixtures/ (fabriqué par scripts/make_fixtures.py, données anonymisées).
- Base Postgres : les tests qui en ont besoin créent une base temporaire sur le serveur donné par
  RLPI_TEST_DATABASE_URL (ex. postgresql://rlpi:rlpi@localhost:5432/rlpi avec docker-compose.dev.yml) et y passent
  les migrations de migrations/. Sans cette variable, ces tests sont sautés ; en CI, RLPI_TEST_REQUIRE_DB=1 les
  rend obligatoires (échec au lieu de saut).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
MIGRATIONS = ROOT / "migrations"


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshot",
        action="store_true",
        help="réécrire l'instantané du tableau de bord (tests/snapshots/) au lieu de le comparer",
    )


@pytest.fixture(scope="session")
def joueurs() -> dict:
    return json.loads((FIXTURES / "joueurs.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------ Postgres


def migration_files() -> list[tuple[int, str, Path]]:
    out = []
    for f in MIGRATIONS.glob("V*__*.sql"):
        m = re.fullmatch(r"V(\d+)__(.+)\.sql", f.name)
        assert m, f"nom de migration invalide : {f.name}"
        out.append((int(m.group(1)), m.group(2).replace("_", " "), f))
    return sorted(out)


# Table d'historique de Flyway pour PostgreSQL (mêmes colonnes) : les tests passent les migrations eux-mêmes, sans
# Java ; la CI vérifie à part, avec le vrai Flyway, que le schéma obtenu est le même (test_migrations.py).
FLYWAY_HISTORY = """
CREATE TABLE flyway_schema_history (
    installed_rank integer NOT NULL PRIMARY KEY, version varchar(50), description varchar(200) NOT NULL,
    type varchar(20) NOT NULL, script varchar(1000) NOT NULL, checksum integer, installed_by varchar(100) NOT NULL,
    installed_on timestamp NOT NULL DEFAULT now(), execution_time integer NOT NULL, success boolean NOT NULL)
"""


def apply_migrations(conn, upto: int | None = None) -> None:
    conn.execute(FLYWAY_HISTORY)
    for rank, (v, desc, f) in enumerate(migration_files(), start=1):
        if upto is not None and v > upto:
            break
        conn.execute(f.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO flyway_schema_history (installed_rank, version, description, type, script, "
            "installed_by, execution_time, success) VALUES (%s, %s, %s, 'SQL', %s, 'tests', 0, true)",
            (rank, str(v), desc, f.name),
        )


@pytest.fixture(scope="session")
def pg_server() -> str:
    url = os.getenv("RLPI_TEST_DATABASE_URL", "").strip()
    if not url:
        if os.getenv("RLPI_TEST_REQUIRE_DB") == "1":
            pytest.fail("RLPI_TEST_DATABASE_URL absente alors que RLPI_TEST_REQUIRE_DB=1")
        pytest.skip("RLPI_TEST_DATABASE_URL absente : tests Postgres sautés")
    return url


@pytest.fixture(scope="session")
def make_database(pg_server):
    """Crée des bases temporaires sur le serveur de test ; toutes supprimées à la fin de la session."""
    import psycopg

    created = []

    def make(migrate: bool | int = True) -> str:
        name = f"rlpi_test_{uuid.uuid4().hex[:10]}"
        with psycopg.connect(pg_server, autocommit=True) as c:
            c.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        url = urlsplit(pg_server)._replace(path=f"/{name}").geturl()
        if migrate is not False:
            with psycopg.connect(url, autocommit=True) as c:
                apply_migrations(c, None if migrate is True else migrate)
        return url

    yield make
    with psycopg.connect(pg_server, autocommit=True) as c:
        for name in created:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def database(make_database) -> str:
    """Une base migrée partagée par la session (vidée avant chaque test par `db`)."""
    return make_database()


@pytest.fixture
def db(database, monkeypatch):
    """DATABASE_URL pointe sur la base de test, tables vidées, pool de rlpi.store remis à zéro."""
    import psycopg

    from rlpi import store

    with psycopg.connect(database, autocommit=True) as c:
        c.execute(
            "TRUNCATE accounts, matches, match_players, reference_aggregates, player_versions, sessions, swipe_decks, "
            "dead_tasks "
            "CASCADE"
        )
    monkeypatch.setenv("DATABASE_URL", database)
    reset_store(monkeypatch)
    yield database
    if store._pool is not None:
        store._pool.close()
    reset_store(monkeypatch)


def reset_store(monkeypatch) -> None:
    from rlpi import store

    monkeypatch.setattr(store, "_pool", None)
    monkeypatch.setattr(store, "_schema_ok", False)
