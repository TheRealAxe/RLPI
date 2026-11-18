"""Sauvegardes de la base : pg_dump quotidien vers Garage, rétention, restauration.

    python -m rlpi.backup run                              sauvegarder maintenant
    python -m rlpi.backup list                             sauvegardes présentes dans Garage
    python -m rlpi.backup prune                            appliquer la rétention
    python -m rlpi.backup restore latest --into <URL>      restaurer la dernière (ou une clé) dans une base VIDE

Planification : chaque jour, à partir de RLPI_BACKUP_HOUR (heure UTC, défaut 3), le premier worker libre fait la
sauvegarde du jour (verrou Redis : une seule par jour, tous workers confondus ; nouvel essai une heure plus tard en
cas d'échec). RLPI_BACKUP_HOUR=off désactive la planification (docker-compose.dev.yml).

Fichiers : backups/rlpi-AAAAMMJJTHHMMSSZ.dump dans le bucket (format « custom » de pg_dump, compressé, restaurable
table par table). Rétention : toutes les sauvegardes des RLPI_BACKUP_DAYS derniers jours (défaut 14), plus la
première de chaque mois pendant RLPI_BACKUP_MONTHS mois (défaut 6). Pas de copie hors du serveur pour le moment
(décidé le 2026-11-16) : Garage est sur la même machine que Postgres.

Restauration : `--into` est obligatoire et la base cible doit être vide (aucune table) : on ne restaure jamais
par-dessus une base en service. La sauvegarde contient l'historique Flyway : la base restaurée est à la bonne version.
Marche à suivre complète : docs/DEPLOIEMENT_COOLIFY.md (« Sauvegardes »).

Il faut pg_dump / pg_restore de la même version majeure que le serveur (ou plus récente) : postgresql-client-18
dans l'image du worker.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rlpi import logs, store

PREFIX = "backups/"
KEY_RE = re.compile(r"backups/rlpi-(\d{8}T\d{6}Z)\.dump")
LOCK = "rlpi:backup:"  # + date UTC du jour


def key_for(now: datetime) -> str:
    return f"{PREFIX}rlpi-{now.strftime('%Y%m%dT%H%M%SZ')}.dump"


def key_time(key: str) -> datetime | None:
    m = KEY_RE.fullmatch(key)
    return datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) if m else None


def to_delete(keys: list[str], now: datetime, days: int = 14, months: int = 6) -> list[str]:
    """Sauvegardes à supprimer : on garde tout ce qui a moins de `days` jours, et la première sauvegarde de chacun
    des `months` derniers mois (mois en cours compris). Les clés qui ne sont pas des sauvegardes sont ignorées."""
    dated = sorted((t, k) for k in keys if (t := key_time(k)) is not None)
    recent = now - timedelta(days=days)
    month_keys: list[tuple[int, int]] = []
    y, m = now.year, now.month
    for _ in range(months):
        month_keys.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    first_of_month: dict[tuple[int, int], str] = {}
    for t, k in dated:
        first_of_month.setdefault((t.year, t.month), k)
    keep = {k for t, k in dated if t > recent} | {first_of_month[mk] for mk in month_keys if mk in first_of_month}
    return [k for _, k in dated if k not in keep]


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name, "").strip()
    return int(v) if v.isdigit() else default


def list_backups(s3: Any = None, bucket: str | None = None) -> list[tuple[str, int]]:
    """(clé, taille en octets) des sauvegardes, de la plus ancienne à la plus récente."""
    s3, bucket = s3 or store.s3(), bucket or store.bucket()
    out: list[tuple[str, int]] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=PREFIX):
        out += [(o["Key"], int(o["Size"])) for o in page.get("Contents", []) if key_time(o["Key"])]
    return sorted(out)


def prune(s3: Any = None, bucket: str | None = None, now: datetime | None = None) -> list[str]:
    s3, bucket = s3 or store.s3(), bucket or store.bucket()
    old = to_delete(
        [k for k, _ in list_backups(s3, bucket)],
        now or datetime.now(UTC),
        _env_int("RLPI_BACKUP_DAYS", 14),
        _env_int("RLPI_BACKUP_MONTHS", 6),
    )
    for k in old:
        s3.delete_object(Bucket=bucket, Key=k)
    if old:
        logs.log(f"sauvegardes : {len(old)} ancienne(s) supprimée(s)", supprimees=len(old))
    return old


def run(s3: Any = None, bucket: str | None = None) -> str:
    """pg_dump de DATABASE_URL vers Garage, puis rétention. Retourne la clé écrite."""
    s3, bucket = s3 or store.s3(), bucket or store.bucket()
    url = store.url("DATABASE_URL", ("postgres://", "postgresql://"))
    now = datetime.now(UTC)
    key = key_for(now)
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="rlpi_backup_") as tmp:
        f = Path(tmp) / "rlpi.dump"
        r = subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-acl", f"--file={f}", f"--dbname={url}"],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if r.returncode != 0:  # le message de pg_dump ne contient pas le mot de passe
            raise RuntimeError(f"pg_dump a échoué (code {r.returncode}) : {r.stderr.strip()[-500:]}")
        size = f.stat().st_size
        s3.upload_file(str(f), bucket, key)
    logs.log("sauvegarde écrite", cle=key, octets=size, duree_s=round(time.time() - t0, 1))
    prune(s3, bucket, now)
    return key


def due(now: datetime | None = None) -> bool:
    """L'heure de la sauvegarde du jour est-elle passée ? (RLPI_BACKUP_HOUR, « off » : jamais)"""
    h = os.getenv("RLPI_BACKUP_HOUR", "3").strip().lower()
    if h in ("off", "non", "") or not h.isdigit():
        return False
    return (now or datetime.now(UTC)).hour >= int(h)


def maybe_run(r: Any, worker_id: str, now: datetime | None = None) -> str | None:
    """Appelé par la boucle du worker : fait la sauvegarde du jour si elle est due et qu'aucun autre worker ne l'a
    prise. Un échec est écrit au journal et retenté une heure plus tard ; il n'arrête jamais le worker."""
    now = now or datetime.now(UTC)
    if not due(now):
        return None
    lock = LOCK + now.strftime("%Y-%m-%d")
    if not r.set(lock, worker_id, nx=True, ex=36 * 3600):
        return None
    try:
        return run()
    except Exception as e:  # noqa: BLE001
        r.set(lock, worker_id, ex=3600)  # nouvel essai dans une heure
        logs.error("sauvegarde : échec (nouvel essai dans une heure)", erreur=f"{type(e).__name__}: {e}"[:600])
        return None


def restore(key: str, into: str, s3: Any = None, bucket: str | None = None) -> None:
    """Restaure une sauvegarde dans la base `into`, qui doit être vide."""
    import psycopg

    s3, bucket = s3 or store.s3(), bucket or store.bucket()
    if key == "latest":
        found = list_backups(s3, bucket)
        if not found:
            raise SystemExit("Aucune sauvegarde dans le bucket")
        key = found[-1][0]
    with psycopg.connect(into, connect_timeout=10) as c:
        n = c.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN "
            "('pg_catalog', 'information_schema')"
        ).fetchone()
        if n and n[0]:
            raise SystemExit(f"La base cible contient déjà {n[0]} table(s) : restauration refusée (base vide exigée)")
    with tempfile.TemporaryDirectory(prefix="rlpi_restore_") as tmp:
        f = Path(tmp) / "rlpi.dump"
        s3.download_file(bucket, key, str(f))
        r = subprocess.run(
            ["pg_restore", "--no-owner", "--no-acl", "--exit-on-error", f"--dbname={into}", str(f)],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if r.returncode != 0:
            raise SystemExit(f"pg_restore a échoué (code {r.returncode}) : {r.stderr.strip()[-800:]}")
    logs.log("sauvegarde restaurée", cle=key)


def main() -> None:
    os.environ["RLPI_LOG_FORMAT"] = "texte"  # commande lancée à la main : sortie lisible
    ap = argparse.ArgumentParser(description="Sauvegardes de la base RLPI (Garage)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="sauvegarder maintenant")
    sub.add_parser("list", help="lister les sauvegardes")
    sub.add_parser("prune", help="appliquer la rétention")
    s = sub.add_parser("restore", help="restaurer dans une base vide")
    s.add_argument("key", help="clé (backups/rlpi-….dump) ou « latest »")
    s.add_argument("--into", required=True, help="URL postgresql://… d'une base vide")
    a = ap.parse_args()
    if a.cmd == "run":
        run()
    elif a.cmd == "list":
        found = list_backups()
        for k, size in found:
            print(f"{k}  {size / 1e6:.1f} Mo")
        print(f"{len(found)} sauvegarde(s)")
    elif a.cmd == "prune":
        prune()
    else:
        restore(a.key, a.into)


if __name__ == "__main__":
    main()
