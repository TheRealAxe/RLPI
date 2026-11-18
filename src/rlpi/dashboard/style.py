"""Style de jeu (voir rlpi.styles) : style principal et secondaire, ce qui le signe, pro le plus proche,
régularité du style d'un match à l'autre ; mêmes calculs pour les coéquipiers suivis.

Par partie : les traits de chaque joueur (centrés sur les joueurs de la partie, donc calculables partie par
partie). Le modèle des styles (styles.json) fait partie de la référence.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

if TYPE_CHECKING:
    from rlpi.context import DataContext
    from rlpi.dashboard.aggregate import GameInput
    from rlpi.dashboard.content import Games


def per_game(g: GameInput) -> dict[str, dict]:
    from rlpi.perf import xv
    from rlpi.styles import TRAITS, traits_from

    st, tv = g.tables.get("player_match_stats"), g.tables.get("touch_values")
    if st is None or tv is None or st.is_empty() or tv.is_empty():
        return {}
    tr = traits_from(st, xv(tv, g.tables.get("goal_xv")), {g.replay: g.play_s})
    return {
        r["player_id"]: {"data": {"traits": {k: r[k] for k in TRAITS}}, "details": {}} for r in tr.iter_rows(named=True)
    }


def reference(ctx: DataContext) -> dict | None:
    mp = ctx.models / "styles.json"
    return json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else None


def traits_table(games: Games, my_replays: list[str]) -> pl.DataFrame:
    from rlpi.styles import TRAITS

    rows = [
        {"replay": gm.replay, "player_id": pid, **pg.data["traits"]}
        for gm in games.ordered(my_replays)
        for pid, pg in gm.players.items()
        if "traits" in pg.data
    ]
    schema = {"replay": pl.String, "player_id": pl.String} | dict.fromkeys(TRAITS, pl.Float64)
    return pl.DataFrame(rows, schema=schema)


def _style_scores(S: dict, X: np.ndarray) -> np.ndarray:
    """Traits moyens (n, T) → centile sur chaque style (n, n_styles)."""
    Z = (X - np.array(S["mu"])) / np.array(S["sd"])
    F = Z @ np.array(S["W"])
    out = np.zeros((len(X), len(S["styles"])))
    for j, st in enumerate(S["styles"]):
        ref = np.asarray(st["ref_sorted"])
        out[:, j] = 100 * np.searchsorted(ref, F[:, st["factor"]] * st["pole"], side="right") / len(ref)
    return out


def section(
    S: dict | None, games: Games, player: str, my_replays: list[str], peers: dict[str, pl.DataFrame]
) -> dict | None:
    if S is None:
        return None
    T = S["traits"]
    tr = traits_table(games, my_replays)
    W = np.array(S["W"])

    stable = [j for j, st in enumerate(S["styles"]) if st["retest"] >= 0.5]

    def scores(pid: str):
        d = tr.filter(pl.col("player_id") == pid).drop_nulls(T)
        if d.height < 5:  # moins de 5 parties : pas de style attribué
            return None
        X = d.select(T).to_numpy().astype(float)
        return d.height, X, _style_scores(S, X.mean(0, keepdims=True))[0]

    raw = {pid: scores(pid) for pid in [player, *peers]}
    have = {pid: r for pid, r in raw.items() if r is not None}
    # Style du trio : un style que tous les joueurs suivis partagent nettement (≥ 80) décrit l'équipe, pas l'individu
    team = [j for j in stable if len(have) >= 2 and all(r[2][j] >= 80 for r in have.values())]
    team_factors = {S["styles"][j]["factor"] for j in team}

    def profile(pid: str) -> dict | None:
        if pid not in have:
            return None
        n, X, pct = have[pid]
        mean = X.mean(0, keepdims=True)
        ok = [j for j in stable if S["styles"][j]["factor"] not in team_factors] or stable
        order = sorted(ok, key=lambda j: -pct[j])
        main = order[0]
        second = next((j for j in order[1:] if S["styles"][j]["factor"] != S["styles"][main]["factor"]), None)
        per_match = _style_scores(S, X)
        top2 = np.argsort(-np.where(np.isin(np.arange(len(pct)), ok), per_match, -1), axis=1)[:, :2]
        regular = int((top2 == main).any(axis=1).sum())
        # signature : les traits les plus marqués face aux joueurs de référence
        sig = []
        for i, t in enumerate(T):
            ref = np.asarray(S["trait_sorted"][t])
            p = float(100 * np.searchsorted(ref, mean[0, i], side="right") / len(ref))
            sig.append({"t": t, "pct": p, "txt": S["trait_fr"][t][0 if p >= 50 else 1]})
        # d'abord les traits qui portent ton style principal et secondaire (dans leur sens), hors traits du trio
        L = np.array(S["loadings"])
        team_tr = {T[i] for f_ in team_factors for i in range(len(T)) if abs(L[i, f_]) >= 0.4}
        mine = {}
        for j in [main, second]:
            if j is None:
                continue
            stj = S["styles"][j]
            for i, t in enumerate(T):
                load = L[i, stj["factor"]] * stj["pole"]
                if abs(load) >= 0.4 and t not in team_tr:
                    mine[t] = load
        cand = [x for x in sig if x["t"] in mine and (x["pct"] - 50) * mine[x["t"]] > 0]
        rest = [x for x in sig if x["t"] not in team_tr and x not in cand]
        sig = (sorted(cand, key=lambda x: -abs(x["pct"] - 50)) + sorted(rest, key=lambda x: -abs(x["pct"] - 50)))[:4]
        f = (mean - np.array(S["mu"])) / np.array(S["sd"]) @ W
        pros = sorted(S["pros"], key=lambda p: float(np.linalg.norm(np.asarray(p["s"]) - f[0])))[:3]
        return {
            "n": n,
            "main": main,
            "second": second,
            "pct": pct.tolist(),
            "regular": regular,
            "signature": sig,
            "like": [{"name": p["name"], "n": p["n"]} for p in pros],
            "polyvalent": bool(pct[main] < 65),
        }

    styles = [{k: st[k] for k in ("name", "tagline", "trap", "factor", "pole", "retest")} for st in S["styles"]]
    return {
        "styles": styles,
        "me": profile(player),
        "peers": {pid: profile(pid) for pid in peers},
        "team": team,
        "n_ref": S["n_ref"],
        "n_rlcs": S["n_rlcs"],
    }
