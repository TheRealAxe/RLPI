"""Synergie entre coéquipiers : mesures par paire (A, B) de la même équipe, dans chaque partie.

Enchaînements (touches valorisées, voir rlpi.value) :
  - « A sert B » : B fait la touche suivante (≤ 3 s après la touche de A), A et B coéquipiers ;
  - part des touches de A suivies par B, et réciproquement ;
  - valeur de l'enchaînement A → B = ΔV(A) + ΔV(B) ; « bonus » = valeur − ce que valent en moyenne
    ces deux touches dans la même source (ΔV moyen de A et de B toutes touches confondues).
Placement (images à 10 i/s, jeu en cours, vue de l'équipe) :
  - double commit : A et B tous deux à < 1 000 uu de la balle, un adversaire à < 1 500 uu ;
  - montés ensemble : ni A ni B entre la balle et le but, le 3e coéquipier à > 3 000 uu de la balle ;
  - écart moyen entre A et B.

Usage : python -m rlpi.synergy --source perso|ssl [--limit N]  → data/features/synergy_{source}.parquet
"""
from __future__ import annotations

import argparse
import json
from itertools import combinations

import numpy as np
import polars as pl

from rlpi.config import SOURCE
from rlpi.context import DataContext, resolve

FPS = 10
CHAIN_S = 3.0


def pair_rows(m: dict, f: pl.DataFrame, tv: pl.DataFrame, mean_dv: dict[str, float]) -> list[dict]:
    play = f["phase"].to_numpy() == 1
    play_s = play.sum() / FPS
    bx, by = f["ball_x"].to_numpy(), f["ball_y"].to_numpy()
    slot = {p["id"]: p["slot"] for p in m["players"]}
    tv = tv.sort("i")
    ti, tp, _tt, tdv = tv["i"].to_numpy(), tv["player_id"].to_list(), tv["team"].to_numpy(), tv["dv"].to_numpy()
    out = []
    for team in (0, 1):
        s = 1 if team == 0 else -1
        mates = [p["id"] for p in m["players"] if p["team"] == team]
        opp = [p["slot"] for p in m["players"] if p["team"] != team]
        if len(mates) != 3:
            continue
        X = {pid: s * f[f"p{slot[pid]}_x"].to_numpy() for pid in mates}
        Y = {pid: s * f[f"p{slot[pid]}_y"].to_numpy() for pid in mates}
        sby, sbx = s * by, s * bx
        d = {pid: np.hypot(X[pid] - sbx, Y[pid] - sby) for pid in mates}
        d_opp = np.min([np.hypot(s * f[f"p{k}_x"].to_numpy() - sbx, s * f[f"p{k}_y"].to_numpy() - sby) for k in opp], 0)
        n_touch = {pid: int(sum(1 for p in tp if p == pid)) for pid in mates}
        for a, b in combinations(mates, 2):
            c = [x for x in mates if x not in (a, b)][0]
            dc = play & (d[a] < 1000) & (d[b] < 1000) & (d_opp < 1500)
            up = play & (Y[a] > sby) & (Y[b] > sby) & (d[c] > 3000)
            row = {"replay": m["replay"], "date": m["date"], "team": team, "a": a, "b": b,
                   "a_name": next(p["name"] for p in m["players"] if p["id"] == a),
                   "b_name": next(p["name"] for p in m["players"] if p["id"] == b),
                   "won": sum(g["team"] == team for g in m["goals"]) > sum(g["team"] != team for g in m["goals"]),
                   "play_s": play_s, "n_a": n_touch[a], "n_b": n_touch[b],
                   "double_commit_s": dc.sum() / FPS, "montes_ensemble_s": up.sum() / FPS,
                   "ecart": float(np.hypot(X[a] - X[b], Y[a] - Y[b])[play].mean())}
            for src, dst, tag in ((a, b, "ab"), (b, a, "ba")):
                n = 0; val = 0.0; bonus = 0.0
                for k in range(len(ti) - 1):
                    if tp[k] == src and tp[k + 1] == dst and ti[k + 1] - ti[k] <= CHAIN_S * FPS:
                        n += 1
                        v = tdv[k] + tdv[k + 1]
                        val += v
                        bonus += v - mean_dv[src] - mean_dv[dst]
                row[f"chain_{tag}"] = n; row[f"chain_val_{tag}"] = val; row[f"chain_bonus_{tag}"] = bonus
            out.append(row)
    return out


def run(source: str, limit: int | None, ctx: DataContext | None = None) -> pl.DataFrame:
    ctx = resolve(ctx)
    tv_all = pl.read_parquet(ctx.feature("touch_values", source))
    mean_dv = dict(tv_all.group_by("player_id").agg(pl.col("dv").mean()).iter_rows())
    rows = []
    for mp in sorted(ctx.frames(source).glob("*.meta.json"))[:limit]:
        m = json.loads(mp.read_text(encoding="utf-8"))
        tv = tv_all.filter(pl.col("replay") == m["replay"])
        if tv.is_empty():
            continue
        f = pl.read_parquet(mp.with_name(m["replay"] + ".parquet"))
        rows += pair_rows(m, f, tv, mean_dv)
    df = pl.DataFrame(rows).with_columns(pl.lit(source).alias("source"))
    if limit is None:
        df.write_parquet(ctx.feature("synergy", source))
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=SOURCE)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    df = run(a.source, a.limit)
    print(df.height, "paires-parties")
    print(df.select("a_name", "b_name", "play_s", "n_a", "n_b", "chain_ab", "chain_ba", "chain_bonus_ab",
                    "double_commit_s", "montes_ensemble_s", "ecart").head(6))


if __name__ == "__main__":
    main()
