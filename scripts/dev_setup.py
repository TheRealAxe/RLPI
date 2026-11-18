"""Prépare l'environnement local (docker-compose.dev.yml) : Garage, puis remplissage depuis rlpi-data-lainox/.

    docker compose -f docker-compose.dev.yml up -d --build
    .venv/Scripts/python scripts/dev_setup.py [--data rlpi-data-lainox] [--source perso] [--limit N] [--force]

1. Garage (une seule fois) : rôle du nœud, bucket « rlpi », clé d'accès fixe de développement.
2. Remplissage, sans appeler ballchasing : les Parquet de rlpi-data-lainox/ sont déjà fusionnés (toutes les parties
   d'une source dans un fichier) ; on les découpe partie par partie pour écrire exactement ce que le worker aurait
   produit :
     - Garage : games/<partie>/frames/partie/…, games/<partie>/features/<table>_partie.parquet,
       value_curves_partie.json, result.json (sortie de rlpi.game run) ;
     - Postgres : matches (source « fichier », statut ok ou doublon, GUID, date) et match_players (les 6 joueurs).
   Une partie déjà en base est sautée (relancer le script ne crée pas de doublon), sauf avec --force.
3. Agrégats du tableau de bord des parties qui n'en ont pas (comme le worker après chaque partie).

DÉVELOPPEMENT SEULEMENT : les adresses et clés sont celles de docker-compose.dev.yml.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.dev.yml")]
ACCESS_KEY = "GKb56db53a9f4c57c9ac99c9b6"
SECRET_KEY = "753906dc8f3f63bc92b6592df7eb33b30892406c383742bb308691970f5382b7"
BUCKET = "rlpi"

# Mêmes services que dans le conteneur, mais vus depuis le poste (ports publiés sur 127.0.0.1)
os.environ.update(
    {
        "DATABASE_URL": "postgresql://rlpi:rlpi@localhost:5432/rlpi",
        "S3_ENDPOINT": "http://localhost:3900",
        "S3_ACCESS_KEY": ACCESS_KEY,
        "S3_SECRET_KEY": SECRET_KEY,
        "S3_BUCKET": BUCKET,
        "S3_REGION": "garage",
    }
)
sys.path.insert(0, str(ROOT / "src"))

GAME_SOURCE = "partie"  # comme rlpi.game
# Tables par partie produites par rlpi.game run (la synergie est calculée au niveau du joueur, pas ici)
TABLES = [
    "player_match_stats",
    "touch_values",
    "goal_xv",
    "touch_decisions",
    "placement",
    "passes",
    "perf",
    "defense",
    "kickoffs",
]


def garage(*args: str, check: bool = True) -> str:
    p = subprocess.run(
        [*COMPOSE, "exec", "-T", "garage", "/garage", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and p.returncode != 0:
        raise SystemExit(f"garage {' '.join(args)} : {p.stderr or p.stdout}")
    return p.stdout + p.stderr


def setup_garage() -> None:
    for _ in range(30):
        out = garage("node", "id", "-q", check=False)
        if "@" in out:
            break
        time.sleep(1)
    else:
        raise SystemExit("Garage ne répond pas : lancer d'abord docker compose -f docker-compose.dev.yml up -d")
    node = out.strip().splitlines()[-1].split("@")[0]
    if "NO ROLE ASSIGNED" in garage("status"):
        garage("layout", "assign", "-z", "dev", "-c", "10G", node)
        garage("layout", "apply", "--version", "1")
        print("Garage : rôle du nœud attribué")
    if BUCKET not in garage("bucket", "list"):
        garage("bucket", "create", BUCKET)
        print(f"Garage : bucket {BUCKET} créé")
    if ACCESS_KEY not in garage("key", "list"):
        garage("key", "import", "--yes", "-n", "rlpi-dev", ACCESS_KEY, SECRET_KEY)
        print("Garage : clé de développement importée")
    garage("bucket", "allow", "--read", "--write", "--owner", BUCKET, "--key", ACCESS_KEY)


def stem(s: str) -> str:
    return Path(str(s).replace("\\", "/")).name.removesuffix(".replay")


def seed(data: Path, source: str, limit: int | None, force: bool) -> None:
    import polars as pl
    from psycopg.types.json import Jsonb

    from rlpi import store

    frames = data / "frames" / source
    feats = data / "features"
    metas = sorted(frames.glob("*.meta.json"))[:limit] if limit else sorted(frames.glob("*.meta.json"))
    tables = {}
    for t in TABLES:
        f = feats / f"{t}_{source}.parquet"
        if f.exists():
            df = pl.read_parquet(f)
            key = "replay_file" if t == "player_match_stats" else "replay"
            tables[t] = df.with_columns(pl.col(key).map_elements(stem, return_dtype=pl.String).alias("_game"))
    curves_f = feats / f"value_curves_{source}.json"
    curves = json.loads(curves_f.read_text(encoding="utf-8")) if curves_f.exists() else []
    print(f"{len(metas)} partie(s) dans {frames} ; tables : {', '.join(tables)}")

    cli, b = store.s3(), store.bucket()
    seen_guid: dict[str, str] = {}
    n_ok = n_dup = n_skip = 0
    with store.connect() as conn:
        for mf in metas:
            meta = json.loads(mf.read_text(encoding="utf-8"))
            mid = store.safe(meta["replay"])
            if not force and conn.execute("SELECT 1 FROM matches WHERE id = %s", (mid,)).fetchone():
                n_skip += 1
                continue
            parts = {t: df.filter(pl.col("_game") == meta["replay"]).drop("_game") for t, df in tables.items()}
            st = parts.get("player_match_stats")
            guids = [g for g in st["match_guid"].unique().to_list() if g] if st is not None and st.height else []
            guid = guids[0] if guids else None
            dup_of = seen_guid.get(guid) if guid else None
            if guid and not dup_of:
                row = conn.execute(
                    "SELECT id FROM matches WHERE match_guid = %s AND id <> %s AND status IN ('ok', 'partiel')",
                    (guid, mid),
                ).fetchone()
                dup_of = row[0] if row else None
            status = "doublon" if dup_of else "ok"
            result = {
                "replay": meta["replay"],
                "file": f"{meta['replay']}.replay",
                "status": "ok",
                "date": meta["date"],
                "match_type": meta.get("match_type"),
                "n_frames": meta.get("n_frames"),
                "n_touches": meta.get("n_touches"),
                "players": meta["players"],
                "score": [meta.get("team0_score"), meta.get("team1_score")],
                "match_guid": guid,
                "online_3v3": bool(st is not None and st.height),
                "steps": {},
                "errors": {},
                "rempli_par": "scripts/dev_setup.py",
            }
            if dup_of:
                result["doublon_de"] = dup_of
            if status == "ok":
                prefix = f"games/{mid}"
                for f in frames.glob(f"{meta['replay']}.*"):
                    cli.upload_file(str(f), b, f"{prefix}/frames/{GAME_SOURCE}/{f.name}")
                for t, df in parts.items():
                    if df.height:
                        buf = io.BytesIO()
                        df.write_parquet(buf)
                        cli.put_object(
                            Bucket=b, Key=f"{prefix}/features/{t}_{GAME_SOURCE}.parquet", Body=buf.getvalue()
                        )
                cv = [c for c in curves if c.get("replay") == meta["replay"]]
                cli.put_object(
                    Bucket=b, Key=f"{prefix}/features/value_curves_{GAME_SOURCE}.json", Body=json.dumps(cv).encode()
                )
                cli.put_object(
                    Bucket=b,
                    Key=f"{prefix}/result.json",
                    Body=json.dumps(result, ensure_ascii=False, indent=1).encode(),
                )
                if guid:
                    seen_guid[guid] = mid
            conn.execute(
                """INSERT INTO matches (id, source, status, match_guid, played_at, result, worker)
                            VALUES (%s, 'fichier', %s, %s, %s, %s, 'dev_setup')
                            ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, match_guid = EXCLUDED.match_guid,
                            played_at = EXCLUDED.played_at, result = EXCLUDED.result, updated_at = now()""",
                (mid, status, guid, store.played_at(meta["date"]), Jsonb(result)),
            )
            conn.execute("DELETE FROM match_players WHERE match_id = %s", (mid,))
            if status == "ok":
                for p in meta["players"]:
                    conn.execute(
                        "INSERT INTO match_players (match_id, player_id, player_name, team) "
                        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (mid, p["id"], p.get("name"), p.get("team")),
                    )
                n_ok += 1
            else:
                n_dup += 1
    print(f"remplissage : {n_ok} partie(s) ok, {n_dup} doublon(s), {n_skip} déjà en base")
    # Agrégats du tableau de bord, comme le worker après chaque partie (rlpi.dashboard.storage)
    from rlpi.dashboard import storage

    with store.connect() as conn:
        todo = storage.missing(conn)
        for mid in todo:
            storage.compute_match(conn, cli, b, mid)
    print(f"agrégats du tableau de bord : {len(todo)} partie(s) calculée(s)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=str(ROOT / "rlpi-data-lainox"))
    ap.add_argument("--source", default="perso", help="nom de la source dans le dossier de données")
    ap.add_argument("--limit", type=int, help="seulement les N premières parties")
    ap.add_argument("--force", action="store_true", help="réécrire les parties déjà en base")
    ap.add_argument("--sans-garage", action="store_true", help="ne pas (re)configurer Garage")
    a = ap.parse_args()
    if not a.sans_garage:
        setup_garage()
    seed(Path(a.data), a.source, a.limit, a.force)


if __name__ == "__main__":
    main()
