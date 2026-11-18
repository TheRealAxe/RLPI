"""Migrations Flyway et vérification de la version du schéma par le serveur et le worker."""

from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg
import pytest

from rlpi import migrate, store
from tests.conftest import ROOT, migration_files, reset_store


def test_version_attendue_egale_derniere_migration():
    assert store.SCHEMA_VERSION == migration_files()[-1][0]
    versions = [v for v, _, _ in migration_files()]
    assert versions == list(range(1, len(versions) + 1)), "migrations numérotées 1, 2, 3… sans trou"


def test_plus_aucun_create_ni_alter_dans_le_code():
    """Le schéma n'est défini que par migrations/ (DB first)."""
    for f in (ROOT / "src").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"\b(CREATE|ALTER|DROP)\s+(TABLE|INDEX)\b", text, re.IGNORECASE), f.name


def test_flyway_env():
    e = migrate.flyway_env("postgresql://rlpi:p%40ss%3Aw@db.internal:6543/rlpi?sslmode=require", Path("/m"))
    assert e["FLYWAY_URL"] == "jdbc:postgresql://db.internal:6543/rlpi?sslmode=require"
    assert (e["FLYWAY_USER"], e["FLYWAY_PASSWORD"]) == ("rlpi", "p@ss:w")
    assert e["FLYWAY_LOCATIONS"] == f"filesystem:{Path('/m')}"
    assert e["FLYWAY_BASELINE_ON_MIGRATE"] == "true" and e["FLYWAY_BASELINE_VERSION"] == "1"
    assert "'" not in e["FLYWAY_BASELINE_DESCRIPTION"]  # sinon le SQL du baseline de Flyway est cassé
    assert e["FLYWAY_CLEAN_DISABLED"] == "true"
    assert migrate.flyway_env("postgres://u@h/b", Path("/m"))["FLYWAY_URL"] == "jdbc:postgresql://h:5432/b"
    with pytest.raises(SystemExit):
        migrate.flyway_env("mysql://u@h/b", Path("/m"))


def test_schema_a_jour(db):
    with psycopg.connect(db, autocommit=True) as c:
        assert store.check_schema(c) == store.SCHEMA_VERSION
        assert c.execute("SELECT to_regclass('games')").fetchone()[0] is None  # supprimée par V2


def test_base_sans_flyway(make_database):
    with psycopg.connect(make_database(migrate=False), autocommit=True) as c:
        with pytest.raises(store.SchemaError, match="aucune migration Flyway"):
            store.check_schema(c)


def test_migration_en_echec(make_database):
    with psycopg.connect(make_database(), autocommit=True) as c:
        c.execute(
            "INSERT INTO flyway_schema_history (installed_rank, version, description, type, script, "
            "installed_by, execution_time, success) VALUES (99, '3', 'essai', 'SQL', 'V3__essai.sql', 't', 0, "
            "false)"
        )
        with pytest.raises(store.SchemaError, match="V3 essai"):
            store.check_schema(c)


def test_base_plus_recente_acceptee(make_database):
    with psycopg.connect(make_database(), autocommit=True) as c:
        c.execute(
            "INSERT INTO flyway_schema_history (installed_rank, version, description, type, script, "
            "installed_by, execution_time, success) VALUES (99, '99', 'futur', 'SQL', 'V99__futur.sql', 't', 0, "
            "true)"
        )
        assert store.check_schema(c) == 99


def test_pool_refuse_une_base_pas_a_jour(make_database, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", make_database(migrate=1))
    reset_store(monkeypatch)
    with pytest.raises(store.SchemaError):
        store.pool()
    assert store._pool is None


def schema_of(url: str) -> dict:
    with psycopg.connect(url) as c:
        q = lambda sql: sorted(c.execute(sql).fetchall())  # noqa: E731
        return {
            "colonnes": q(
                "SELECT table_name, ordinal_position, column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name <> 'flyway_schema_history'"
            ),
            "index": q(
                "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename <> 'flyway_schema_history'"
            ),
            "contraintes": q(
                "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE connamespace = 'public'::regnamespace "
                "AND conrelid::regclass::text <> 'flyway_schema_history'"
            ),
        }


@pytest.mark.skipif(not os.getenv("RLPI_FLYWAY_DATABASE_URL"), reason="base migrée par le vrai Flyway (CI seulement)")
def test_vrai_flyway_meme_schema(database):
    """La CI passe les migrations avec le vrai Flyway sur une base vide : même schéma que celui des tests."""
    flyway_db = os.environ["RLPI_FLYWAY_DATABASE_URL"]
    with psycopg.connect(flyway_db) as c:
        assert store.check_schema(c) == store.SCHEMA_VERSION
    assert schema_of(flyway_db) == schema_of(database)


# ------------------------------------------------------------------------------------------------ V3, V4, V5


def migration(v: int) -> str:
    return next(f for n, _, f in migration_files() if n == v).read_text(encoding="utf-8")


def test_v3_played_at_converti(make_database):
    """Texte du replay et ISO de ballchasing convertis ; valeur illisible signalée puis mise à NULL."""
    from datetime import UTC, datetime, timedelta, timezone

    with psycopg.connect(make_database(migrate=2), autocommit=True) as c:
        rows = [
            ("replay", "2026-04-19 21-25-40"),
            ("iso", "2026-11-14T00:43:59Z"),
            ("iso+1", "2026-11-14T01:43:59+01:00"),
            ("illisible", "hier soir"),
            ("mois13", "2026-13-01 10-00-00"),
            ("vide", None),
        ]
        for mid, v in rows:
            c.execute("INSERT INTO matches (id, source, status, played_at) VALUES (%s, 'fichier', 'ok', %s)", (mid, v))
        notices = []
        c.add_notice_handler(lambda d: notices.append(d.message_primary))
        c.execute("SET TIME ZONE 'Europe/Paris'")  # le résultat ne dépend pas du fuseau de la session
        with c.transaction():
            c.execute(migration(3))
        got = dict(c.execute("SELECT id, played_at FROM matches").fetchall())
    assert got["replay"] == datetime(2026, 4, 19, 21, 25, 40, tzinfo=UTC)
    assert got["iso"] == got["iso+1"] == datetime(2026, 11, 14, 1, 43, 59, tzinfo=timezone(timedelta(hours=1)))
    assert got["illisible"] is None and got["mois13"] is None and got["vide"] is None
    assert sum("illisible" in n for n in notices) == 2 and any("hier soir" in n for n in notices)


def test_v4_statut_inconnu_bloque_la_migration(make_database):
    url = make_database(migrate=3)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("INSERT INTO matches (id, source, status) VALUES ('a', 'fichier', 'ok'), ('b', 'fichier', 'bizarre')")
        with pytest.raises(psycopg.errors.RaiseException, match=r"statut inconnu.*b \(bizarre\)"):
            with c.transaction():
                c.execute(migration(4))
        assert c.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'matches_status_check'").fetchone() == (0,)
        c.execute("UPDATE matches SET status = 'erreur' WHERE id = 'b'")
        with c.transaction():
            c.execute(migration(4))
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute("INSERT INTO matches (id, source, status) VALUES ('c', 'fichier', 'inconnu')")


def test_v5_colonnes_des_indicateurs(database):
    """Les colonnes typées de player_game_aggregates sont exactement celles écrites par rlpi.dashboard.storage."""
    from rlpi.dashboard import storage

    with psycopg.connect(database) as c:
        cols = {
            r[0]
            for r in c.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'player_game_aggregates'"
            ).fetchall()
        }
    assert cols == {"match_id", "player_id", "data", "details", *storage.COLUMNS}
