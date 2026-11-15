"""Fantôme pro (prototype) : pour une touche de l'utilisateur, retrouve les situations RLCS les plus proches
et exporte les trajectoires (1,5 s avant → 3 s après la touche) pour une page de comparaison 2D.

Tout est ramené dans le repère du toucheur : il attaque vers +y. Les situations pro peuvent aussi être
retournées gauche/droite (x → −x) pour doubler les exemples.

Usage :
    python -m rlpi.ghost --player <pseudo ou identifiant> --since 2026-11-14 [--rank 0] [--source-ref rlcs]
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import polars as pl

import os

from rlpi.config import FEATURES, FRAMES, SOURCE
from rlpi.decisions import ACTION_FR, ACTIONS
from rlpi.value import load_replay

BEFORE, AFTER = 15, 30          # images à 10 Hz
PRE_RADIUS = 900.0              # présélection : balle à moins de 900 uu
TOP_K = 3


def _meta(source, replay):
    return load_replay(FRAMES / source / f"{replay}.meta.json")


def _slot_team(m, pid):
    p = next(p for p in m["players"] if p["id"] == pid)
    return p["slot"], p["team"]


def state_vec(f: pl.DataFrame, m: dict, i: int, slot: int, team: int, flip: float) -> np.ndarray:
    """Situation vue du toucheur (attaque vers +y) : balle, moi, 2 coéquipiers, 3 adversaires (triés par distance à la balle)."""
    s = 1.0 if team == 0 else -1.0
    def P(k):
        return np.array([flip * s * f[f"p{k}_x"][i], s * f[f"p{k}_y"][i], f[f"p{k}_z"][i]])
    def V(k):
        return np.array([flip * s * f[f"p{k}_vx"][i], s * f[f"p{k}_vy"][i], f[f"p{k}_vz"][i]])
    ball = np.array([flip * s * f["ball_x"][i], s * f["ball_y"][i], f["ball_z"][i]])
    bvel = np.array([flip * s * f["ball_vx"][i], s * f["ball_vy"][i], f["ball_vz"][i]])
    mates = [p["slot"] for p in m["players"] if p["team"] == team and p["slot"] != slot]
    opps = [p["slot"] for p in m["players"] if p["team"] != team]
    by_d = lambda ks: sorted(ks, key=lambda k: np.linalg.norm(P(k) - ball))
    mates, opps = by_d(mates)[:2], by_d(opps)[:3]
    if len(mates) < 2 or len(opps) < 3:
        return None
    # Poids : balle et moi comptent le plus ; vitesses ramenées à ~0,3 s de déplacement.
    parts = [ball * 1.0, bvel * 0.3, P(slot) * 1.0, V(slot) * 0.3,
             np.array([f[f"p{slot}_boost"][i] * 10.0])]
    parts += [P(k)[:2] * 0.6 for k in mates] + [P(k)[:2] * 0.5 for k in opps]
    return np.concatenate(parts)


def track(f: pl.DataFrame, m: dict, i: int, slot: int, team: int, flip: float) -> dict:
    """Trajectoires de la fenêtre, dans le repère du toucheur."""
    s = 1.0 if team == 0 else -1.0
    lo, hi = max(0, i - BEFORE), min(f.height - 1, i + AFTER)
    w = f.slice(lo, hi - lo + 1)
    r = lambda a: [round(float(v), 0) for v in a]
    out = {"ball": {"x": r(flip * s * w["ball_x"]), "y": r(s * w["ball_y"]), "z": r(w["ball_z"])},
           "t0": i - lo, "cars": []}
    for p in m["players"]:
        k = p["slot"]
        # yaw : rz en radians dans le repère monde ; on applique le miroir.
        yaw = w[f"p{k}_rz"].to_numpy().astype(float)
        if s < 0:
            yaw = yaw + np.pi
        if flip < 0:
            yaw = np.pi - yaw
        out["cars"].append({
            "name": p["name"], "me": k == slot, "mate": p["team"] == team,
            "x": r(flip * s * w[f"p{k}_x"]), "y": r(s * w[f"p{k}_y"]), "z": r(w[f"p{k}_z"]),
            "yaw": [round(float(v), 2) for v in yaw], "boost": r(w[f"p{k}_boost"]),
        })
    return out


def pick_target(player: str, since: str, rank: int) -> dict:
    d = pl.read_parquet(FEATURES / f"touch_decisions_{SOURCE}.parquet")
    d = (d.filter((pl.col("player_name") == player) & (pl.col("date") >= since)
                  & pl.col("adequacy").is_not_null() & (pl.col("act") != pl.col("best_action")))
          .sort("regret", descending=True))
    return d.row(rank, named=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", default=os.getenv("RLPI_PLAYER", ""))
    ap.add_argument("--since", default="2026-11-14")
    ap.add_argument("--rank", type=int, default=0)
    ap.add_argument("--ref", default="rlcs")
    ap.add_argument("--out", default="reports/fantome_data.js")
    a = ap.parse_args()

    tgt = pick_target(a.player, a.since, a.rank)
    m, f = _meta(SOURCE, tgt["replay"])
    slot, team = _slot_team(m, tgt["player_id"])
    q = state_vec(f, m, tgt["i"] - 2, slot, team, 1.0)
    s = 1.0 if team == 0 else -1.0
    tbx, tby = s * tgt["ball_x"], s * tgt["ball_y"]
    print(f"Cible : {tgt['date']} t={tgt['t_s']:.1f}s  joué={tgt['act']} meilleur={tgt['best_action']} regret={tgt['regret']:.3f}")

    ref = pl.read_parquet(FEATURES / f"touch_decisions_{a.ref}.parquet").filter(pl.col("action") != "save")
    sr = pl.when(pl.col("team") == 0).then(1.0).otherwise(-1.0)
    ref = ref.with_columns((sr * pl.col("ball_x")).alias("bx"), (sr * pl.col("ball_y")).alias("by"))
    cands = []
    for flip in (1.0, -1.0):
        c = ref.filter(((flip * pl.col("bx") - tbx) ** 2 + (pl.col("by") - tby) ** 2) < PRE_RADIUS ** 2)
        cands.append(c.with_columns(pl.lit(flip).alias("flip")))
    cands = pl.concat(cands)
    print(f"{cands.height} touches RLCS présélectionnées dans {cands['replay'].n_unique()} matchs")

    scored = []
    for (replay,), grp in cands.group_by("replay"):
        mr, fr = _meta(a.ref, replay)
        for r in grp.iter_rows(named=True):
            try:
                sl, tm = _slot_team(mr, r["player_id"])
            except StopIteration:
                continue
            if r["i"] - 2 < 0 or r["i"] + 3 >= fr.height:
                continue
            v = state_vec(fr, mr, r["i"] - 2, sl, tm, r["flip"])
            if v is None:
                continue
            scored.append((float(np.linalg.norm(v - q)), r, sl, tm))
    scored.sort(key=lambda x: x[0])
    # un seul exemple par match, pour varier les joueurs
    seen, best = set(), []
    for dist, r, sl, tm in scored:
        if r["replay"] in seen:
            continue
        seen.add(r["replay"]); best.append((dist, r, sl, tm))
        if len(best) == TOP_K:
            break
    d_ref = np.median([x[0] for x in scored]) if scored else 1.0

    pros = []
    for dist, r, sl, tm in best:
        mr, fr = _meta(a.ref, r["replay"])
        pros.append({
            "player": r["player_name"], "date": r["date"], "act": r["act"], "act_fr": ACTION_FR[r["act"]],
            "dv_3s": r["dv_3s"], "dist": round(dist), "similarity": round(100 * max(0.0, 1 - dist / d_ref)),
            "flip": r["flip"] < 0, "track": track(fr, mr, r["i"], sl, tm, r["flip"]),
        })
        print(f"  {r['player_name']:<14} distance {dist:6.0f}  action={r['act']}  dv_3s={r['dv_3s']:+.2f}")

    data = {
        "target": {
            "player": a.player, "date": tgt["date"], "t_s": tgt["t_s"], "clock": tgt["clock"],
            "act": tgt["act"], "act_fr": ACTION_FR[tgt["act"]], "best": tgt["best_action"],
            "best_fr": ACTION_FR[tgt["best_action"]], "regret": tgt["regret"], "dv_3s": tgt["dv_3s"],
            "role": tgt["role"], "height": tgt["height"],
            "policy": {k: tgt[f"p_{k}"] for k in ACTIONS}, "q": {k: tgt[f"q_{k}"] for k in ACTIONS},
            "track": track(f, m, tgt["i"], slot, team, 1.0),
        },
        "actions_fr": ACTION_FR, "ref": a.ref.upper(), "pros": pros,
    }
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("window.FANTOME = " + json.dumps(data, ensure_ascii=False) + ";\n")
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()
