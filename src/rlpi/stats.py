"""Extraction des stats par joueur et par match avec subtr-actor (prototype de dashboard).

Usage :
    python -m rlpi.stats --source theo --dir "C:/.../TAGame/Demos" --online-3v3
    python -m rlpi.stats --source rlcs --limit 30
Sortie : data/features/player_match_stats_<source>.parquet (une ligne par joueur et par match).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import polars as pl

from rlpi.config import DATA as DATA_DIR

MODULES = [
    "core", "boost", "movement", "positioning", "rotation", "fifty_fifty", "demo", "bump",
    "touch", "whiff", "pass", "kickoff", "powerslide",
]


def _pid(remote_id) -> str:
    if isinstance(remote_id, dict):
        k, v = next(iter(remote_id.items()))
        return f"{k}:{v}"
    return str(remote_id)


def _flatten(prefix: str, d: dict, out: dict) -> None:
    for k, v in d.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[f"{prefix}.{k}"] = float(v)


def extract(path: str) -> list[dict]:
    import subtr_actor as sa

    r = sa.get_summed_stats(path, MODULES)
    meta = r["replay_meta"]
    headers = {h[0]: h[1] for h in meta["all_headers"]}
    players: dict[str, dict] = {}
    for team_key, team in (("team_zero", 0), ("team_one", 1)):
        for p in meta.get(team_key) or []:
            players[_pid(p["remote_id"])] = {
                "replay_file": Path(path).name,
                "replay_path": str(path),
                "replay_id": headers.get("Id"),
                "match_guid": headers.get("MatchGUID"),
                "date": headers.get("Date"),
                "map": headers.get("MapName"),
                "match_type": headers.get("MatchType"),
                "game_type": (meta.get("game_type") or {}).get("game_type"),
                "team_size": headers.get("TeamSize"),
                "duration_s": headers.get("TotalSecondsPlayed"),
                "recorder": headers.get("PlayerName"),
                "player_id": _pid(p["remote_id"]),
                "player_name": p["name"],
                "team": team,
                "won": int(headers.get(f"Team{team}Score", 0) > headers.get(f"Team{1 - team}Score", 0)),
                "team_goals": headers.get(f"Team{team}Score", 0),
                "opp_goals": headers.get(f"Team{1 - team}Score", 0),
                "car": p.get("car_hitbox_family"),
                "is_bot": bool((p.get("stats") or {}).get("bBot", False)),
                "shots": (p.get("stats") or {}).get("Shots"),
            }
    for mod, v in r["modules"].items():
        for ps in v.get("player_stats", []) or []:
            pid = _pid(ps["player_id"])
            if pid in players:
                _flatten(mod, ps["stats"], players[pid])
    return list(players.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--dir", nargs="+", help="un ou plusieurs dossiers de replays (sinon data/raw/<source>)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--online-3v3", action="store_true", help="garder seulement les parties en ligne 3v3")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    roots = [Path(d) for d in a.dir] if a.dir else [DATA_DIR / "raw" / a.source]
    files = sorted((f for r in roots for f in r.rglob("*.replay")), key=lambda p: p.stat().st_mtime, reverse=True)
    root = ", ".join(str(r) for r in roots)
    if a.limit:
        files = files[: a.limit]
    print(f"{len(files)} replays à traiter ({root})", flush=True)

    rows, failures = [], []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(extract, str(f)): f for f in files}
        for i, fut in enumerate(as_completed(futs), 1):
            f = futs[fut]
            try:
                rows.extend(fut.result())
            except Exception as e:  # noqa: BLE001
                failures.append({"file": str(f), "error": repr(e)})
            print(f"  {i}/{len(files)} — {time.time() - t0:.0f}s, échecs {len(failures)}", flush=True)

    df = pl.DataFrame(rows, infer_schema_length=None)
    # Un même match peut exister en double (dossier du jeu + téléchargement ballchasing)
    n0 = df["replay_file"].n_unique()
    keep = df.group_by("match_guid").agg(pl.col("replay_file").min())["replay_file"]
    df = df.filter(pl.col("replay_file").is_in(keep.implode()) | pl.col("match_guid").is_null())
    if df["replay_file"].n_unique() < n0:
        print(f"  {n0 - df['replay_file'].n_unique()} doublon(s) écarté(s) (même MatchGUID)")
    if a.online_3v3:
        df = df.filter((pl.col("match_type") == "Online") & (pl.col("team_size") == 3))
    out = DATA_DIR / "features" / f"player_match_stats_{a.source}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out)
    print(f"→ {out} : {df.height} lignes, {df['replay_file'].n_unique()} matchs, échecs {len(failures)}")
    if failures:
        (out.with_suffix(".failures.json")).write_text(json.dumps(failures, indent=1), encoding="utf-8")
        sys.exit(0)


if __name__ == "__main__":
    main()
