"""Coéquipiers comparés : notes de décision et face-à-face sur les parties jouées ensemble."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from rlpi.dashboard import value
from rlpi.dashboard.metrics import METRICS

if TYPE_CHECKING:
    from rlpi.dashboard.content import Games

PEER_KEYS = [
    "boost_moyen",
    "boost_zero",
    "boost_vole",
    "vitesse",
    "supersonique",
    "ff_gagnes",
    "tirs",
    "buts",
    "passes",
    "ratees",
    "demos",
    "moitie_adverse",
    "premier_homme",
    "troisieme_homme",
    "derriere_balle",
]
VALUE_KEYS = [
    ("plc_note", "Placement hors ballon (vs pros)", +1),
    ("dec_note", "Choix à la touche (vs pros)", +1),
    ("lobby_note", "Résultat des touches (vs lobby)", +1),
    ("lobby_rank", "Rang dans la partie (1 = meilleur)", -1),
]


def section(
    ref: dict | None, games: Games, my_value: dict | None, me: pl.DataFrame, peers: dict[str, pl.DataFrame]
) -> list[dict]:
    """Pour chaque coéquipier comparé : notes de décision et face-à-face sur les parties communes.
    `my_value` : section « value » du joueur (déjà calculée) ; `me`, `peers` : lignes joueur-partie (stats)."""
    out = []
    lab = {k: (label, unit, sens) for k, label, unit, _, sens in METRICS}
    my_by = {m["replay"]: m for m in my_value["matches"]} if my_value else {}
    for pid, d in peers.items():
        reps = d["replay"].to_list()
        v = value.section(ref, games, pid, reps, details=False)
        shared = sorted(set(reps) & set(my_by))
        pm = {m["replay"]: m for m in v["matches"]} if v else {}
        mine_sh = me.filter(pl.col("replay").is_in(shared))
        peer_sh = d.filter(pl.col("replay").is_in(shared))
        h2h = []
        for k in PEER_KEYS:
            label, unit, sens = lab[k]
            h2h.append(
                {
                    "key": k,
                    "label": label,
                    "unit": unit,
                    "sens": sens,
                    "me": mine_sh[k].mean(),
                    "peer": peer_sh[k].mean(),
                }
            )
        for k, label, sens in VALUE_KEYS:
            a = [my_by[r][k] for r in shared if my_by[r].get(k) is not None]
            b = [pm[r][k] for r in shared if r in pm and pm[r].get(k) is not None]
            h2h.append(
                {
                    "key": k,
                    "label": label,
                    "unit": "/6" if k == "lobby_rank" else "/100",
                    "sens": sens,
                    "me": float(np.mean(a)) if a else None,
                    "peer": float(np.mean(b)) if b else None,
                    "value": True,
                }
            )
        out.append(
            {
                "id": pid,
                "name": d["player_name"][-1],
                "n": d.height,
                "n_shared": len(shared),
                "wins_shared": int(mine_sh["won"].sum()),
                "first": d["date"][0][:10],
                "last": d["date"][-1][:10],
                "value": {
                    k: float(np.mean([m[k] for m in v["matches"] if m.get(k) is not None])) for k, _, _ in VALUE_KEYS
                }
                if v
                else None,
                "h2h": h2h,
            }
        )
    return out
