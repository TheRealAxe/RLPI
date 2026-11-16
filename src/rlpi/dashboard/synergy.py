"""Synergie par paire de coéquipiers (voir rlpi.synergy), sur les parties retenues, face à « toi + un inconnu »
et aux SSL.

Par partie : les lignes de chaque paire (rlpi.synergy.pair_rows), avec la valeur brute des enchaînements. Le
« bonus » d'un enchaînement retire le ΔV moyen des deux joueurs sur toutes les parties du joueur connecté : il est
donc calculé au moment du contenu (rlpi.dashboard.content), pas dans la partie.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from rlpi.dashboard import bootstrap

if TYPE_CHECKING:
    from rlpi.context import DataContext
    from rlpi.dashboard.aggregate import GameInput
    from rlpi.dashboard.content import Games

SYN_KEYS = [  # clé, libellé, unité, sens (+1 plus haut = mieux, −1 plus bas = mieux, 0 style)
    ("connexion", "Connexion", "% des touches reprises par l'autre", +1),
    ("bonus", "Bonus par enchaînement", "pts de valeur en plus", +1),
    ("double_commit", "Double commit", "s / 5 min", -1),
    ("montes", "Montés ensemble sans couverture", "s / 5 min", -1),
    ("ecart", "Écart moyen entre vous", "m", 0),
]
SUMS = (
    "play_s",
    "n_a",
    "n_b",
    "chain_ab",
    "chain_ba",
    "chain_bonus_ab",
    "chain_bonus_ba",
    "double_commit_s",
    "montes_ensemble_s",
    "ecart",
)


def per_game(g: GameInput) -> list[dict]:
    """Lignes de synergie de la partie, sans le bonus (dépend des autres parties du joueur)."""
    from rlpi.synergy import pair_rows

    tv = g.tables.get("touch_values")
    f = g.frames()
    if tv is None or tv.is_empty() or f is None:
        return []
    rows = pair_rows(g.meta, f, tv, defaultdict(float))
    return [{k: v for k, v in r.items() if not k.startswith("chain_bonus_")} for r in rows]


def with_bonus(rows: list[dict], mean_dv: dict[str, float]) -> list[dict]:
    """Bonus d'un enchaînement A → B = valeur − ΔV moyen de A − ΔV moyen de B (somme sur les enchaînements)."""
    out = []
    for r in rows:
        ma, mb = mean_dv.get(r["a"], 0.0), mean_dv.get(r["b"], 0.0)
        out.append(
            r
            | {
                "chain_bonus_ab": r["chain_val_ab"] - r["chain_ab"] * ma - r["chain_ab"] * mb,
                "chain_bonus_ba": r["chain_val_ba"] - r["chain_ba"] * mb - r["chain_ba"] * ma,
            }
        )
    return out


def _agg(s: dict) -> dict:
    """Mesures d'un ensemble de lignes, à partir de leurs sommes (et du nombre de lignes pour l'écart moyen)."""
    T = s["play_s"] / 300
    ch = s["chain_ab"] + s["chain_ba"]
    return {
        "connexion": 100 * ch / max(s["n_a"] + s["n_b"], 1),
        "bonus": 100 * (s["chain_bonus_ab"] + s["chain_bonus_ba"]) / max(ch, 1),
        "double_commit": s["double_commit_s"] / T,
        "montes": s["montes_ensemble_s"] / T,
        "ecart": s["ecart"] / s["rows"] / 100,
        "n_chains": int(ch),
    }


def _sums(g: pl.DataFrame) -> dict:
    return {k: g[k].sum() for k in SUMS} | {"rows": g.height}


def _syn_dir(g: pl.DataFrame, src: str) -> dict:
    """Sens src → l'autre : part des touches de src reprises, bonus moyen par enchaînement."""
    ab = g.filter(pl.col("a") == src)
    ba = g.filter(pl.col("b") == src)
    n = ab["n_a"].sum() + ba["n_b"].sum()  # type: ignore
    ch = ab["chain_ab"].sum() + ba["chain_ba"].sum()  # type: ignore
    bonus = ab["chain_bonus_ab"].sum() + ba["chain_bonus_ba"].sum()  # type: ignore
    return {"sert": 100 * ch / max(n, 1), "bonus": 100 * bonus / max(ch, 1), "n": int(ch)}  # type: ignore


def reference(ctx: DataContext) -> dict | None:
    fs = ctx.feature("synergy", "ssl")
    return _agg(_sums(pl.read_parquet(fs))) if fs.exists() else None


def section(
    ref: dict | None, games: Games, player: str, my_replays: list[str], peers: dict[str, pl.DataFrame]
) -> dict | None:
    if ref is None or not games.has_synergy:
        return None
    rows = [r for gm in games.ordered(my_replays) for r in gm.pairs]
    if not rows:
        return {"pairs": {}, "n_random": 0}
    t = pl.DataFrame(with_bonus(rows, games.mean_dv), infer_schema_length=None)
    mine = t.filter((pl.col("a") == player) | (pl.col("b") == player))
    other = pl.when(pl.col("a") == player).then(pl.col("b")).otherwise(pl.col("a"))
    mine = mine.with_columns(other.alias("mate"))
    rnd = mine.filter(~pl.col("mate").is_in(list(peers)))
    random = _agg(_sums(rnd)) if rnd.height else None
    rng = np.random.default_rng(0)
    pairs = {}
    for pid in peers:
        g = mine.filter(pl.col("mate") == pid)
        if g.is_empty():
            continue
        reps = sorted(g["replay"].unique().to_list())
        # Sommes de chaque partie : un tirage (avec remise) des parties additionne leurs sommes
        part = {r: _sums(g.filter(pl.col("replay") == r)) for r in reps}
        keys = [*SUMS, "rows"]
        M = np.array([[part[r][k] for k in keys] for r in reps], dtype=float)
        bs = [_agg(dict(zip(keys, M[i].sum(0)))) for i in bootstrap.draws(rng, len(reps), 200)]
        est = _agg(_sums(g))
        pairs[pid] = {
            "n": len(reps),
            "won": float(g["won"].mean()),  # type: ignore[arg-type]
            "rows": [
                {
                    "key": k,
                    "label": lab,
                    "unit": u,
                    "sens": s,
                    "v": est[k],
                    "lo": float(np.percentile([b[k] for b in bs], 10)),
                    "hi": float(np.percentile([b[k] for b in bs], 90)),
                    "ssl": ref[k],
                    "random": random[k] if random else None,
                }
                for k, lab, u, s in SYN_KEYS
            ],
            "me_to": _syn_dir(g, player),
            "to_me": _syn_dir(g, pid),
            "n_chains": est["n_chains"],
        }
    n_random = rnd["replay"].n_unique()
    return {"pairs": pairs, "n_random": n_random}
