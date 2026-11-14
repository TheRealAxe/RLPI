"""Passes tentées vs passes récupérées.

Une « balle donnée » = touche qui envoie la balle vers l'avant, sur le côté ou en retrait (intention
déduite de la direction, voir rlpi.decisions), hors tirs et hors conduite, jouée hors de son tiers
défensif (pour ne pas compter les dégagements).
Pour chacune :
  - qui touche ensuite (premier joueur différent) : coéquipier = passe récupérée, adversaire = perdue ;
  - coéquipier disponible ? 1 s après la touche, le coéquipier le plus proche de la balle est-il plus
    près que l'adversaire le plus proche ?
  - gain de valeur à 2 s (ΔV), pour voir ce que coûte une passe dans le vide.

Usage : python -m rlpi.passes  → data/features/passes_{rlcs,theo}.parquet
"""
from __future__ import annotations

import numpy as np
import polars as pl

from rlpi.config import FEATURES, FRAMES
from rlpi.value import load_replay

GIVE = ("forward", "side", "back")
OWN_THIRD_Y = -1700  # en coordonnées « équipe qui attaque vers y > 0 »


def build(source: str) -> pl.DataFrame:
    dec = pl.read_parquet(FEATURES / f"touch_decisions_{source}.parquet")
    allt = pl.read_parquet(FEATURES / f"touch_values_{source}.parquet")
    out = []
    for (replay,), grp in dec.group_by("replay"):
        m, f = load_replay(FRAMES / source / f"{replay}.meta.json")
        slot_of = {p["id"]: p["slot"] for p in m["players"]}
        seq = allt.filter(pl.col("replay") == replay).sort("i").select("i", "player_id", "team").rows()
        n = f.height
        pos = {k: np.column_stack([f[f"p{k}_x"].to_numpy(), f[f"p{k}_y"].to_numpy(), f[f"p{k}_z"].to_numpy()])
               for k in range(6)}
        ball = np.column_stack([f["ball_x"].to_numpy(), f["ball_y"].to_numpy(), f["ball_z"].to_numpy()])
        for r in grp.iter_rows(named=True):
            if r["act"] not in GIVE or r["ball_y"] < OWN_THIRD_Y:
                continue
            i, team, pid = r["i"], r["team"], r["player_id"]
            nxt = next(((ti, tp, tt) for ti, tp, tt in seq if ti > i and tp != pid), None)
            j = min(i + 10, n - 1)
            mates = [slot_of[p["id"]] for p in m["players"] if p["team"] == team and p["id"] != pid]
            opps = [slot_of[p["id"]] for p in m["players"] if p["team"] != team]
            dm = min(np.linalg.norm(pos[k][j] - ball[j]) for k in mates)
            do = min(np.linalg.norm(pos[k][j] - ball[j]) for k in opps)
            out.append({
                "replay": replay, "date": r["date"], "player_id": pid, "player_name": r["player_name"],
                "team": team, "i": i, "act": r["act"], "ball_x": r["ball_x"], "ball_y": r["ball_y"],
                "clock": r["clock"], "dv_2s": r["dv_2s"],
                "next": None if nxt is None else ("coéquipier" if nxt[2] == team else "adversaire"),
                "delay_s": None if nxt is None else (nxt[0] - i) / 10,
                "mate_closer": bool(dm < do), "d_mate": float(dm), "d_opp": float(do),
            })
    return pl.DataFrame(out)


def main() -> None:
    for src in ("rlcs", "theo"):
        df = build(src)
        df.write_parquet(FEATURES / f"passes_{src}.parquet")
        print(f"→ passes_{src}.parquet : {df.height:,} balles données")


if __name__ == "__main__":
    main()
