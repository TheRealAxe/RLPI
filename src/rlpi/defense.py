"""Défense en infériorité : reculer (« de dos », shadow) ou sauter au ballon (rush) ?

Situation retenue (vue de l'équipe qui défend, terrain retourné pour qu'elle défende vers y = −5120) :
  - jeu en cours, balle dans sa moitié (y < 0), balle basse (z < 500) ;
  - un attaquant au ballon (adversaire le plus proche, à moins de 600 uu), du mauvais côté pour nous
    (y attaquant > y balle : il pousse vers notre but) ;
  - 1 adversaire (1v1) ou 2 adversaires (1v2) à moins de 2 500 uu de la balle ;
  - un seul défenseur à moins de 2 500 uu de la balle, placé entre la balle et son but, à 800–3 000 uu
    de la balle : ses coéquipiers sont plus loin (en train de revenir).
  Un épisode = la première image qui remplit ces conditions ; on attend 3 s avant d'en ouvrir un autre.

Choix du défenseur sur la seconde suivante (10 images) :
  - rush   : vitesse de rapprochement moyenne vers la balle > +500 uu/s ;
  - recul  : vitesse moyenne vers son but > 300 uu/s ET rapprochement ≤ +200 uu/s (garde la distance) ;
  - autre  : le reste (attente, déplacement latéral…).

Issues : but encaissé dans les 5 s / 10 s ; variation de valeur (modèle h5) à 3 s et 5 s ; but marqué à 10 s.
Danger de départ = V au moment de la décision (modèle h5), pour comparer à danger égal.

Usage : python -m rlpi.defense --source rlcs [--limit 10]  → data/features/defense_{source}.parquet
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import polars as pl

from rlpi.config import FEATURES, FRAMES, MODELS
from rlpi.value import FPS, features, labels_and_score

NEAR, POSS = 2500.0, 600.0


def episodes(m: dict, f: pl.DataFrame, booster) -> list[dict]:
    n = f.height
    phase = f["phase"].to_numpy()
    goals = sorted(m["goals"], key=lambda g: g["i"])
    out = []
    for team in (0, 1):
        s = 1.0 if team == 0 else -1.0
        bx, by, bz = s * f["ball_x"].to_numpy(), s * f["ball_y"].to_numpy(), f["ball_z"].to_numpy()
        own = [p["slot"] for p in m["players"] if p["team"] == team]
        opp = [p["slot"] for p in m["players"] if p["team"] != team]
        if len(own) != 3 or len(opp) != 3:
            return []
        P = lambda k, c: (s if c in ("x", "y", "vx", "vy") else 1.0) * f[f"p{k}_{c}"].to_numpy()  # noqa: E731
        dist = {k: np.hypot(P(k, "x") - bx, P(k, "y") - by) + np.where(f[f"p{k}_demo"].to_numpy() > 0, 1e5, 0)
                for k in own + opp}
        do = np.stack([dist[k] for k in opp]); dm = np.stack([dist[k] for k in own])
        att_y = np.choose(np.argmin(do, 0), [P(k, "y") for k in opp])
        n_opp = (do < NEAR).sum(0); n_own = (dm < NEAR).sum(0)
        dfd_i = np.argmin(dm, 0); dfd = np.array(own)[dfd_i]
        dfd_y = np.choose(dfd_i, [P(k, "y") for k in own])
        dfd_d = dm.min(0)
        ok = ((phase == 1) & (by < 0) & (bz < 500) & (do.min(0) < POSS) & (att_y > by)
              & np.isin(n_opp, [1, 2]) & (n_own == 1) & (dfd_y < by) & (dfd_d > 800) & (dfd_d < 3000))
        sd = labels_and_score(m, n, team, 5)[1]
        X = features(f, team, sd)
        oppX = features(f, 1 - team, labels_and_score(m, n, 1 - team, 5)[1])
        last = -10**9
        for i in np.where(ok)[0]:
            if i - last < 3 * FPS or i + 10 * FPS >= n or not (phase[i:i + 10] == 1).all():
                continue
            last = i
            k = dfd[i]
            w = slice(i, i + 10)
            vx, vy = P(k, "vx")[w], P(k, "vy")[w]
            px, py = P(k, "x")[w], P(k, "y")[w]
            if np.hypot(np.diff(P(k, "x")[i:i + 30]), np.diff(P(k, "y")[i:i + 30])).max() > 400 \
                    or f[f"p{k}_demo"][i:i + 30].max() > 0:
                continue  # démoli / réapparition dans les 3 s : épisode écarté
            dx, dy = bx[w] - px, by[w] - py
            closing = float(np.mean((vx * dx + vy * dy) / np.maximum(np.hypot(dx, dy), 1)))
            # vers son but (0, −5120)
            gx, gy = -px, -5120 - py
            to_goal = float(np.mean((vx * gx + vy * gy) / np.maximum(np.hypot(gx, gy), 1)))
            choice = "rush" if closing > 500 else "recul" if (to_goal > 300 and closing <= 200) else "autre"
            nxt = next((g for g in goals if g["i"] >= i), None)
            conc = lambda h: bool(nxt and nxt["team"] != team and nxt["i"] - i <= h * FPS)  # noqa: E731
            scor = bool(nxt and nxt["team"] == team and nxt["i"] - i <= 10 * FPS)
            idx = [i, min(i + 3 * FPS, n - 1), min(i + 5 * FPS, n - 1)]
            p_us = booster.predict(X[idx]); p_them = booster.predict(oppX[idx])
            v = p_us - p_them
            # pendant/après un but encaissé, la valeur est acquise
            for j, t in enumerate(idx):
                if nxt and nxt["i"] <= t:
                    v[j] = 1.0 if nxt["team"] == team else -1.0
            name = next(p["name"] for p in m["players"] if p["slot"] == k)
            pid = next(p["id"] for p in m["players"] if p["slot"] == k)
            out.append({
                "replay": m["replay"], "i": int(i), "team": team, "player_name": name, "player_id": pid,
                "situation": f"1v{int(n_opp[i])}", "choice": choice, "closing": closing, "to_goal": to_goal,
                "dist_ball": float(dfd_d[i]), "ball_y": float(by[i]), "boost": float(P(k, "boost")[i]),
                "v0": float(v[0]), "p_concede0": float(p_them[0]),
                "dv3": float(v[1] - v[0]), "dv5": float(v[2] - v[0]),
                "concede5": conc(5), "concede10": conc(10), "score10": scor,
            })
    return out


def run(source: str, limit: int | None) -> pl.DataFrame:
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(MODELS / "value_h5.txt"))
    metas = sorted((FRAMES / source).glob("*.meta.json"))[:limit]
    rows = []
    for mp in metas:
        m = json.loads(mp.read_text(encoding="utf-8"))
        if len(m["goals"]) != m["n_header_goals"]:
            continue
        f = pl.read_parquet(mp.with_name(m["replay"] + ".parquet"))
        rows += episodes(m, f, booster)
    df = pl.DataFrame(rows)
    df = df.with_columns(pl.lit(source).alias("source"))
    if limit is None:
        df.write_parquet(FEATURES / f"defense_{source}.parquet")
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="rlcs")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    df = run(a.source, a.limit)
    print(df.height, "épisodes")
    print(df.group_by("situation", "choice").agg(pl.len(), pl.col("concede5").mean(), pl.col("v0").mean(),
                                                 pl.col("dv3").mean()).sort("situation", "choice"))


if __name__ == "__main__":
    main()
