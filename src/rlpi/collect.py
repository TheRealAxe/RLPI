"""Collecte des replays depuis ballchasing.

Usage :
    python -m rlpi.collect index-rlcs  [--season "RLCS 2026"]
    python -m rlpi.collect index-ssl   [--count 1500]
    python -m rlpi.collect download    [--source rlcs] [--limit 10]
    python -m rlpi.collect manifest

Principe (économe en appels API, compte « regular » : 500 listes/h, 200 téléchargements/h) :
1. `index-rlcs` parcourt l'arborescence des groupes officiels (compte RLCS Referee) d'une saison,
   en ignorant les épreuves 1v1 / 2v2, puis liste les replays mis en ligne par ce compte
   (200 par appel) et rattache chaque replay à son groupe → data/raw/index_rlcs.parquet.
2. `download` télécharge les replays indexés absents du disque (reprise automatique),
   un par un, et journalise chaque tentative dans data/raw/downloads.jsonl.
3. `manifest` produit data/raw/manifest.parquet (replays présents sur disque).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from rlpi import config

RLCS_REFEREE = "76561199225615730"
RLCS_SEASONS = {  # nom du groupe racine → id ballchasing
    "RLCS 2026": "rlcs-2026-d3chsz8nje",
    "RLCS 2025": "rlcs-2025-7ielfd7uhx",
}
SKIP_GROUPS = re.compile(r"^(1v1|2v2) Events$", re.I)

INDEX_RLCS = config.RAW / "index_rlcs.parquet"
INDEX_SSL = config.RAW / "index_ssl.parquet"
INDEXES = {"rlcs": INDEX_RLCS, "ssl": INDEX_SSL}
GROUPS_RLCS = config.RAW / "groups_rlcs.parquet"
DOWNLOAD_LOG = config.RAW / "downloads.jsonl"
MANIFEST = config.RAW / "manifest.parquet"


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# --------------------------------------------------------------------------- index RLCS
def walk_groups(api, root_id: str, root_name: str) -> list[dict]:
    """Parcourt l'arborescence ; n'interroge pas les groupes feuilles (économie d'appels)."""
    out: list[dict] = []
    stack = [(root_id, [root_name])]
    while stack:
        gid, path = stack.pop()
        for g in api.get_groups(group=gid, count=200, sort_by="name", sort_dir="asc"):
            if len(path) == 1 and SKIP_GROUPS.match(g["name"]):
                continue
            gpath = path + [g["name"]]
            out.append({
                "group_id": g["id"],
                "path": " / ".join(gpath),
                "depth": len(gpath) - 1,
                "direct_replays": g["direct_replays"],
                "indirect_replays": g["indirect_replays"],
            })
            is_leaf = g["direct_replays"] == g["indirect_replays"]
            if not is_leaf:
                stack.append((g["id"], gpath))
        log(f"  {len(out)} groupes vus ({' / '.join(path)})")
    return out


def players_of(team: dict) -> list[dict]:
    return [
        {"name": p.get("name"), "platform": (p.get("id") or {}).get("platform"),
         "player_id": (p.get("id") or {}).get("id"), "pro": bool(p.get("pro"))}
        for p in team.get("players", [])
    ]


def replay_row(r: dict, season: str, group_by_id: dict[str, dict]) -> dict | None:
    group = next((group_by_id[g["id"]] for g in r.get("groups", []) if g["id"] in group_by_id), None)
    if group is None:
        return None
    blue, orange = r.get("blue", {}), r.get("orange", {})
    pb, po = players_of(blue), players_of(orange)
    return {
        "replay_id": r["id"],
        "source": "rlcs",
        "season": season,
        "group_id": group["group_id"],
        "group_path": group["path"],
        "title": r.get("replay_title"),
        "date": r.get("date"),
        "duration": r.get("duration"),
        "overtime": r.get("overtime"),
        "map_code": r.get("map_code"),
        "blue_team": blue.get("name"),
        "orange_team": orange.get("name"),
        "blue_goals": blue.get("goals"),
        "orange_goals": orange.get("goals"),
        "n_blue": len(pb),
        "n_orange": len(po),
        "players": json.dumps({"blue": pb, "orange": po}, ensure_ascii=False),
    }


def index_rlcs(season: str, refresh: bool = False) -> None:
    api = config.ballchasing_api()
    root = RLCS_SEASONS[season]
    cached = (pl.read_parquet(GROUPS_RLCS).filter(pl.col("season") == season)
              if GROUPS_RLCS.exists() else pl.DataFrame())
    if cached.height and not refresh:
        log(f"Arborescence {season} reprise du cache ({cached.height} groupes).")
        groups = cached.drop("season").to_dicts()
    else:
        log(f"Arborescence des groupes {season}…")
        groups = walk_groups(api, root, season)
        gdf = pl.DataFrame(groups).with_columns(pl.lit(season).alias("season"))
        _upsert(GROUPS_RLCS, gdf, key="group_id")
    leaves = {g["group_id"]: g for g in groups if g["direct_replays"] > 0}
    expected = sum(g["direct_replays"] for g in leaves.values())
    log(f"{len(groups)} groupes, {len(leaves)} avec replays, {expected} replays attendus (3v3).")

    # Bornes de dates de la saison : on liste les uploads du Referee sur cette période.
    rows, seen, n_listed = [], set(), 0
    for r in api.get_replays(uploader=RLCS_REFEREE, playlist="private", count=100_000,
                             # l'API n'accepte que replay-date|created ; « upload-date »
                             # (proposé par la lib) renvoie une erreur 400
                             sort_by="created", sort_dir="asc",
                             created_after=_season_start(season)):
        n_listed += 1
        row = replay_row(r, season, leaves)
        if row and row["replay_id"] not in seen:
            seen.add(row["replay_id"])
            rows.append(row)
        if n_listed % 1000 == 0:
            log(f"  {n_listed} replays listés, {len(rows)} rattachés")
        if len(rows) >= expected:
            break
    log(f"{len(rows)} replays rattachés sur {n_listed} listés.")
    _upsert(INDEX_RLCS, pl.DataFrame(rows), key="replay_id")
    log(f"Index écrit : {INDEX_RLCS}")


def _season_start(season: str) -> str:
    year = int(season.split()[-1])
    return f"{year - 1}-09-01T00:00:00Z"


def _upsert(path: Path, df: pl.DataFrame, key: str) -> None:
    if path.exists():
        old = pl.read_parquet(path)
        df = pl.concat([old.filter(~pl.col(key).is_in(df[key].implode())), df], how="diagonal_relaxed")
    df.write_parquet(path)


# --------------------------------------------------------------------------- index SSL
def index_ssl(count: int) -> None:
    """Proxy du « top 100 » : replays Ranked Standard (3v3) récents, rang minimum SSL."""
    api = config.ballchasing_api()
    rows, seen = [], set()
    if INDEX_SSL.exists():
        seen = set(pl.read_parquet(INDEX_SSL)["replay_id"])
    for r in api.get_replays(playlist="ranked-standard", min_rank="supersonic-legend",
                             count=count, sort_by="replay-date", sort_dir="desc"):
        if r["id"] in seen or r.get("rocket_league_id") in seen:
            continue
        seen.add(r["id"])
        if r.get("rocket_league_id"):
            seen.add(r["rocket_league_id"])
        blue, orange = r.get("blue", {}), r.get("orange", {})
        pb, po = players_of(blue), players_of(orange)
        rows.append({
            "replay_id": r["id"], "source": "ssl",
            "season": f"RL {r.get('season')}",
            "group_id": None,
            "group_path": "SSL / " + (r.get("date") or "inconnu")[:7],
            "title": r.get("replay_title"), "date": r.get("date"),
            "duration": r.get("duration"), "overtime": r.get("overtime"),
            "map_code": r.get("map_code"),
            "blue_team": None, "orange_team": None,
            "blue_goals": blue.get("goals"), "orange_goals": orange.get("goals"),
            "n_blue": len(pb), "n_orange": len(po),
            "min_rank": (r.get("min_rank") or {}).get("name"),
            "max_rank": (r.get("max_rank") or {}).get("name"),
            "players": json.dumps({"blue": pb, "orange": po}, ensure_ascii=False),
        })
        if len(rows) % 500 == 0:
            log(f"  {len(rows)} replays SSL listés")
    log(f"{len(rows)} nouveaux replays SSL.")
    if rows:
        _upsert(INDEX_SSL, pl.DataFrame(rows), key="replay_id")
    log(f"Index écrit : {INDEX_SSL}")


# --------------------------------------------------------------------------- download
def replay_path(row: dict) -> Path:
    safe = lambda s: re.sub(r'[<>:"/\\|?*]+', "_", s).strip()[:80]
    parts = [safe(p) for p in row["group_path"].split(" / ")]
    return config.RAW.joinpath(row["source"], *parts, f"{row['replay_id']}.replay")


def download(source: str, limit: int | None, season: str | None) -> None:
    df = pl.read_parquet(INDEXES[source]).filter((pl.col("n_blue") == 3) & (pl.col("n_orange") == 3))
    if season:
        df = df.filter(pl.col("season") == season)
    df = df.sort("date", descending=True)  # le plus récent d'abord
    todo = [r for r in df.iter_rows(named=True) if not replay_path(r).exists()]
    if limit:
        todo = todo[:limit]
    log(f"{len(todo)} replays à télécharger ({df.height} indexés en 3v3).")
    api = config.ballchasing_api()
    ok = fail = 0
    for i, row in enumerate(todo, 1):
        dest = replay_path(row)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        entry = {"replay_id": row["replay_id"], "source": source,
                 "time": datetime.now(timezone.utc).isoformat()}
        try:
            api.download_replay(row["replay_id"], tmp)
            if tmp.stat().st_size < 10_000:
                raise RuntimeError(f"fichier trop petit ({tmp.stat().st_size} o)")
            tmp.replace(dest)
            entry |= {"status": "ok", "bytes": dest.stat().st_size, "path": str(dest.relative_to(config.ROOT))}
            ok += 1
        except Exception as exc:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            entry |= {"status": "error", "error": str(exc)[:300]}
            fail += 1
        with DOWNLOAD_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if i % 10 == 0 or i == len(todo):
            log(f"  {i}/{len(todo)} — ok {ok}, échecs {fail}")
    build_manifest()


# --------------------------------------------------------------------------- manifest
def build_manifest() -> None:
    frames = [pl.read_parquet(p) for p in INDEXES.values() if p.exists()]
    if not frames:
        log("Aucun index : rien à faire.")
        return
    df = pl.concat(frames, how="diagonal_relaxed")
    rows = df.to_dicts()
    df = df.with_columns(
        pl.Series("path", [str(replay_path(r).relative_to(config.ROOT)) for r in rows]),
        pl.Series("downloaded", [replay_path(r).exists() for r in rows]),
        pl.lit("3v3").alias("mode"),
    ).filter(pl.col("downloaded")).drop("downloaded")
    df.write_parquet(MANIFEST)
    log(f"Manifeste : {df.height} replays présents → {MANIFEST}")


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rlpi.collect")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("index-rlcs")
    s.add_argument("--season", default="RLCS 2026", choices=list(RLCS_SEASONS))
    s.add_argument("--refresh", action="store_true", help="reparcourir l'arborescence")
    s = sub.add_parser("index-ssl")
    s.add_argument("--count", type=int, default=1500)
    s = sub.add_parser("download")
    s.add_argument("--source", default="rlcs", choices=list(INDEXES))
    s.add_argument("--season")
    s.add_argument("--limit", type=int)
    sub.add_parser("manifest")
    a = p.parse_args(argv)
    config.RAW.mkdir(parents=True, exist_ok=True)
    if a.cmd == "index-rlcs":
        index_rlcs(a.season, a.refresh)
    elif a.cmd == "index-ssl":
        index_ssl(a.count)
    elif a.cmd == "download":
        download(a.source, a.limit, a.season)
    else:
        build_manifest()
    return 0


if __name__ == "__main__":
    sys.exit(main())
