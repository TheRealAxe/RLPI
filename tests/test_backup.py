"""Sauvegardes de la base (rlpi.backup) : rétention, planification par le worker, restauration refusée sur une base
non vide. La sauvegarde réelle (pg_dump → Garage → pg_restore) est vérifiée dans docker-compose.dev.yml (journal)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import fakeredis
import pytest

from rlpi import backup


def at(y: int, m: int, d: int, h: int = 3) -> datetime:
    return datetime(y, m, d, h, tzinfo=UTC)


def test_cle():
    k = backup.key_for(at(2026, 11, 18))
    assert k == "backups/rlpi-20261118T030000Z.dump" and backup.key_time(k) == at(2026, 11, 18)
    assert backup.key_time("backups/autre.txt") is None


def test_retention():
    now = at(2026, 11, 18)
    keys = [backup.key_for(now - timedelta(days=i)) for i in range(0, 400)] + ["backups/note.txt"]
    gone = set(backup.to_delete(keys, now, days=14, months=6))
    kept = {k for k in keys if k not in gone and backup.key_time(k)}
    assert all(backup.key_for(now - timedelta(days=i)) in kept for i in range(14))  # 14 derniers jours
    firsts = {backup.key_for(at(2026, m, 1)) for m in range(6, 12)}
    assert firsts <= kept  # première de chacun des 6 derniers mois, mois en cours compris
    assert backup.key_for(at(2026, 5, 1)) in gone  # au-delà de 6 mois
    assert len(kept) == 14 + 6
    assert "backups/note.txt" not in gone


def test_retention_premier_du_mois_en_cours():
    now = at(2026, 11, 30)
    keys = [backup.key_for(now - timedelta(days=i)) for i in range(0, 61)]
    kept = set(keys) - set(backup.to_delete(keys, now, days=14, months=6))
    assert backup.key_for(at(2026, 11, 1)) in kept and backup.key_for(at(2026, 10, 1)) in kept
    assert backup.key_for(at(2026, 11, 2)) not in kept


def test_heure(monkeypatch):
    monkeypatch.setenv("RLPI_BACKUP_HOUR", "3")
    assert not backup.due(at(2026, 11, 18, 2)) and backup.due(at(2026, 11, 18, 3))
    monkeypatch.setenv("RLPI_BACKUP_HOUR", "off")
    assert not backup.due(at(2026, 11, 18, 23))


def test_une_sauvegarde_par_jour(monkeypatch):
    monkeypatch.setenv("RLPI_BACKUP_HOUR", "3")
    calls = []
    monkeypatch.setattr(backup, "run", lambda: calls.append(1) or "backups/x")
    r = fakeredis.FakeRedis()
    assert backup.maybe_run(r, "w1", at(2026, 11, 18, 4)) == "backups/x"
    assert backup.maybe_run(r, "w2", at(2026, 11, 18, 5)) is None  # déjà faite aujourd'hui (autre worker)
    assert backup.maybe_run(r, "w1", at(2026, 11, 19, 1)) is None  # pas encore l'heure
    assert backup.maybe_run(r, "w1", at(2026, 11, 19, 3)) == "backups/x"
    assert len(calls) == 2


def test_echec_retente_dans_une_heure(monkeypatch):
    monkeypatch.setenv("RLPI_BACKUP_HOUR", "3")

    def boom() -> str:
        raise RuntimeError("pg_dump a échoué")

    monkeypatch.setattr(backup, "run", boom)
    r = fakeredis.FakeRedis()
    assert backup.maybe_run(r, "w1", at(2026, 11, 18, 4)) is None  # écrit au journal, ne lève pas
    ttl = r.ttl("rlpi:backup:2026-11-18")
    assert 0 < ttl <= 3600


def test_restauration_refusee_sur_base_non_vide(database):
    with pytest.raises(SystemExit, match="déjà"):
        backup.restore("backups/rlpi-20261118T030000Z.dump", database, s3=object(), bucket="rlpi")
