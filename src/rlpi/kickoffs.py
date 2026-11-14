"""Kickoffs : où part la balle, et qu'est-ce que ça donne vraiment ?

Pour chaque kickoff (reprise du jeu balle au centre) et pour chaque équipe T (vue de T, qui attaque vers y > 0) :
  - zone de la balle 1,5 s après la première touche (grille 3 × 3 : arrière / milieu / avant × gauche / centre / droite,
    limites x = ±1 300, y = ±2 000) ;
  - première équipe à toucher la balle après le duel (première touche à plus de 0,5 s de la première touche du kickoff) ;
  - valeur V_T (modèle h5) 3 s et 5 s après la première touche ; but marqué / encaissé dans les 10 s.

Usage : python -m rlpi.kickoffs --source rlcs  → data/features/kickoffs_{source}.parquet
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import polars as pl

from rlpi.config import FEATURES, FRAMES, MODELS
from rlpi.value import FPS, features, labels_and_score

ZX, ZY = 1300.0, 2000.0


def zone(x: float, y: float) -> str:
    row = "arrière" if y < -ZY else "avant" if y > ZY else "milieu"
    col = "gauche" if x < -ZX else "droite" if x > ZX else "centre"
    return f"{row} {col}"


def kickoffs(m: dict, f: pl.DataFrame, t: pl.DataFrame, booster) -> list[dict]:
    ph = f["phase"].to_numpy()
    n = f.height
    bx0, by0 = f["ball_x"].to_numpy(), f["ball_y"].to_numpy()
    ti = t.filter(pl.col("slot") >= 0).sort("i")
    tI, tT = ti["i"].to_numpy(), ti["team"].to_numpy()
    goals = sorted(m["goals"], key=lambda g: g["i"])
    starts = [i for i in range(1, n) if ph[i] == 1 and ph[i - 1] != 1 and abs(bx0[i]) < 50 and abs(by0[i]) < 50]
    feats = {team: features(f, team, labels_and_score(m, n, team, 5)[1]) for team in (0, 1)}
    out = []
    for s0 in starts:
        k = np.searchsorted(tI, s0)
        if k >= len(tI) or tI[k] - s0 > 6 * FPS:
            continue
        i1 = int(tI[k])  # première touche
        iz, i3, i5 = i1 + 15, i1 + 3 * FPS, i1 + 5 * FPS
        if i5 >= n or (ph[i1:iz] != 1).any():
            continue
        after = np.where(tI > i1 + 5)[0]
        nxt_team = int(tT[after[0]]) if len(after) and tI[after[0]] < i1 + 6 * FPS else None
        g = next((g for g in goals if g["i"] >= i1), None)
        p = {team: booster.predict(feats[team][[i1, i3, i5]]) for team in (0, 1)}
        for team in (0, 1):
            sgn = 1 if team == 0 else -1
            v = p[team] - p[1 - team]
            for j, idx in enumerate((i1, i3, i5)):
                if g and g["i"] <= idx:
                    v[j] = 1.0 if g["team"] == team else -1.0
            out.append({
                "replay": m["replay"], "i": i1, "team": team,
                "zone": zone(sgn * bx0[iz], sgn * by0[iz]),
                "x": float(sgn * bx0[iz]), "y": float(sgn * by0[iz]),
                "first_touch_us": int(tT[k]) == team,
                "next_touch_us": None if nxt_team is None else nxt_team == team,
                "v3": float(v[1]), "v5": float(v[2]),
                "goal_for10": bool(g and g["team"] == team and g["i"] - i1 <= 10 * FPS),
                "goal_against10": bool(g and g["team"] != team and g["i"] - i1 <= 10 * FPS),
            })
    return out


def run(source: str, limit: int | None) -> pl.DataFrame:
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(MODELS / "value_h5.txt"))
    rows = []
    for mp in sorted((FRAMES / source).glob("*.meta.json"))[:limit]:
        m = json.loads(mp.read_text(encoding="utf-8"))
        if len(m["goals"]) != m["n_header_goals"]:
            continue
        f = pl.read_parquet(mp.with_name(m["replay"] + ".parquet"))
        t = pl.read_parquet(mp.with_name(m["replay"] + ".touches.parquet"))
        rows += [{**r, "date": m["date"]} for r in kickoffs(m, f, t, booster)]
    df = pl.DataFrame(rows).with_columns(pl.lit(source).alias("source"))
    if limit is None:
        df.write_parquet(FEATURES / f"kickoffs_{source}.parquet")
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="rlcs")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    df = run(a.source, a.limit)
    print(df.height // 2, "kickoffs")
    print(df.group_by("zone").agg(pl.len(), pl.col("next_touch_us").mean().round(2), pl.col("v5").mean().round(3),
                                  pl.col("goal_for10").mean().round(3), pl.col("goal_against10").mean().round(3)).sort("zone"))


if __name__ == "__main__":
    main()
