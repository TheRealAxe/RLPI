"""Valeur ajoutée par les touches (modèle de valeur v1, horizon 5 s), placement hors ballon, choix à la touche,
courbes de valeur des parties.

- par partie (`per_game`) : pour chaque joueur, somme et nombre de ΔV, actions, erreur de placement, regret ;
  pour le joueur affiché seulement (détails) : ses pires et meilleures touches, ses touches sur la courbe ;
- référence (`reference`) : RLCS, calculée une fois ;
- contenu (`section`) : combine les parties retenues par les filtres.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from rlpi.dashboard.common import Sorted, percentile

if TYPE_CHECKING:
    from rlpi.context import DataContext
    from rlpi.dashboard.aggregate import GameInput
    from rlpi.dashboard.content import Games

ACTION_FR = {
    "shot": "Tirs",
    "save": "Arrêts",
    "clear": "Dégagements",
    "pass": "Passes",
    "boom": "Frappes fortes",
    None: "Contrôles / autres",
}

# Mesuré le 12/11/2026 : dans les parties classées de l'utilisateur, 1,5× plus de buts que prévu par le modèle
# appris sur RLCS (taux 4,9 % vs 3,3 % à 5 s) → les touches vers le but y « rapportent » plus.
RANKED_GOAL_RATIO = 1.5
N_WORST, N_BEST = 10, 5


def _act_filter(act: str | None) -> pl.Expr:
    return pl.col("action").is_null() if act is None else (pl.col("action") == act)


def _act_key(act: str | None) -> str:
    return "" if act is None else act


def per_match(df: pl.DataFrame, secs: dict) -> pl.DataFrame:
    """Touches → une ligne par partie et par joueur : nombre, somme et moyenne des ΔV, ΔV par 5 min."""
    return (
        df.group_by("replay", "player_id", "player_name")
        .agg(
            pl.len().alias("n"),
            pl.col("dv").sum().alias("dv_sum"),
            pl.col("dv").mean().alias("dv_mean"),
            (pl.col("dv") > 0).mean().alias("pos"),
            pl.col("date").first(),
        )
        .with_columns(pl.col("replay").replace_strict(secs, default=None).alias("play_s"))
        .with_columns((pl.col("dv_sum") / pl.col("play_s") * 300).alias("dv5"))
    )


def touch_rows(df: pl.DataFrame) -> list[dict]:
    return [
        {
            "replay": r["replay"],
            "date": r["date"],
            "clock": r["clock"],
            "action": ACTION_FR.get(r["action"], r["action"]),
            "kind": r["kind"],
            "role": r["role"],
            "dv": r["dv"],
            "vb": r["v_before"],
            "va": r["v_after"],
            "x": r["ball_x"],
            "y": r["ball_y"],
        }
        for r in df.iter_rows(named=True)
    ]


# ------------------------------------------------------------------------------------------------ par partie


def per_game(g: GameInput) -> dict[str, dict]:
    """{joueur: {"data": …, "details": …}} pour une partie."""
    out: dict[str, dict] = {}

    def slot(pid: str) -> dict:
        return out.setdefault(pid, {"data": {}, "details": {}})

    tv = g.tables.get("touch_values")
    if tv is not None and tv.height:
        pm = per_match(tv, {g.replay: g.play_s})
        for r in pm.iter_rows(named=True):
            slot(r["player_id"])["data"]["touch"] = {k: r[k] for k in ("n", "dv_sum", "dv_mean", "pos", "date")}
        for (pid,), me in tv.group_by("player_id", maintain_order=True):
            d = slot(str(pid))
            acts = {}
            for act in ACTION_FR:
                a = me.filter(_act_filter(act))
                if a.height:
                    acts[_act_key(act)] = [a.height, a["dv"].sum(), int((a["dv"] > 0).sum())]
            d["data"]["actions"] = acts
            d["details"]["worst"] = touch_rows(me.sort("dv").head(N_WORST))
            d["details"]["best"] = touch_rows(me.sort("dv", descending=True).head(N_BEST))
            d["details"]["curve"] = [
                {"k": i // 5, "dv": dv, "a": ACTION_FR.get(a, a), "clock": ck, "vb": vb, "va": va}
                for i, dv, a, ck, vb, va in me.select("i", "dv", "action", "clock", "v_before", "v_after").iter_rows()
            ]

    slot_of = {p["slot"]: p["id"] for p in g.meta["players"]}
    plc = g.tables.get("placement")
    if plc is not None and plc.height:
        for _r, s, err, _n in plc.group_by("replay", "slot").agg(pl.col("err").median(), pl.len()).iter_rows():
            if s in slot_of:
                slot(slot_of[s])["data"]["plc_err"] = err
    dec = g.tables.get("touch_decisions")
    if dec is not None and dec.height:
        for _r, pid, reg, ppro in (
            dec.group_by("replay", "player_id")
            .agg(pl.col("regret").mean(), pl.col("p_pro").mean().alias("ppro"))
            .iter_rows()
        ):
            slot(pid)["data"]["dec"] = [reg, ppro]
    return out


def curve(g: GameInput) -> dict | None:
    """Courbe de valeur de la partie (vue de l'équipe 0, None hors jeu) et buts."""
    c = next((c for c in g.curves if c.get("replay") == g.replay), None)
    if c is None:
        return None
    return {
        "v": [None if not p else x for x, p in zip(c["v_team0"], c["play"])],
        "goals": [[gl["i"] // 5, gl["team"]] for gl in c["goals"]],
    }


# ------------------------------------------------------------------------------------------------ référence


def reference(ctx: DataContext, play_seconds) -> dict | None:
    fr_ = ctx.feature("touch_values", "rlcs")
    if not fr_.exists():
        return None
    rl = pl.read_parquet(fr_)
    ref = per_match(rl, play_seconds(ctx, "rlcs"))
    ref_dv5 = ref["dv5"].drop_nulls().to_list()
    by_action = {}
    for act in ACTION_FR:
        b = rl.filter(_act_filter(act))
        by_action[_act_key(act)] = {"mean": b["dv"].mean(), "pos": (b["dv"] > 0).mean()}
    plc = None
    if ctx.feature("placement", "rlcs").exists():
        pr = (
            pl.read_parquet(ctx.feature("placement", "rlcs"))
            .group_by("replay", "slot")
            .agg(pl.col("err").median(), pl.len())
        )
        ref_err = pr["err"].to_list()
        plc = {"err": ref_err, "ref_med": float(np.median(ref_err)), "n_ref": len(ref_err)}
    dec = None
    if ctx.feature("touch_decisions", "rlcs").exists():
        dr = (
            pl.read_parquet(ctx.feature("touch_decisions", "rlcs"))
            .group_by("replay", "player_id")
            .agg(pl.col("regret").mean(), (pl.col("p_pro")).mean().alias("ppro"))
        )
        ref_reg = dr["regret"].to_list()
        dec = {
            "regret": ref_reg,
            "ref_med": float(np.median(ref_reg)),
            "n_ref": len(ref_reg),
            "ref_ppro": float(dr["ppro"].mean()),  # type: ignore
        }  # type: ignore[arg-type]
    rep = json.loads((ctx.models / "value_h5_report.json").read_text(encoding="utf-8"))
    return {
        "dv5": ref_dv5,
        "dv5_med": float(np.median(ref_dv5)),
        "n_ref_matches": rl["replay"].n_unique(),
        "by_action": by_action,
        "plc": plc,
        "dec": dec,
        "model": {k: rep[k] for k in ("auc", "n_matches", "n_test_matches", "horizon_s")}
        | {"calibration": rep["calibration"]},
    }


# ------------------------------------------------------------------------------------------------ contenu


def refs(ref: dict) -> dict[str, Sorted]:
    """Distributions de référence triées, gardées avec la référence (calculées une fois par processus)."""
    if "_sorted" not in ref:
        ref["_sorted"] = {
            "dv5": Sorted(ref["dv5"]),
            "err": Sorted(ref["plc"]["err"]) if ref["plc"] else Sorted([]),
            "regret": Sorted(ref["dec"]["regret"]) if ref["dec"] else Sorted([]),
        }
    return ref["_sorted"]


def section(ref: dict | None, games: Games, player: str, my_replays: list[str], details: bool = True) -> dict | None:
    """Valeur ajoutée par les touches du joueur sur les parties `my_replays` (details=False : seulement ce qui
    sert à la comparaison avec les coéquipiers)."""
    if ref is None or not games.has_touches:
        return None
    rows = []
    for r in my_replays:
        gm = games.by_replay[r]
        for pid, pg in gm.players.items():
            t = pg.data.get("touch")
            if t is not None:
                rows.append({"replay": r, "player_id": pid, **t, "play_s": gm.play_s})
    if not rows:
        return None
    for x in rows:  # même calcul que (dv_sum / play_s) * 300 en Polars
        x["dv5"] = x["dv_sum"] / x["play_s"] * 300 if x["dv_sum"] is not None and x["play_s"] else None
    mine = sorted((x for x in rows if x["player_id"] == player), key=lambda x: x["date"])
    ref_dv5 = refs(ref)["dv5"]
    others_dv5 = Sorted([x["dv5"] for x in rows if x["player_id"] != player and x["dv5"] is not None])

    # Placement hors ballon : écart médian à la position « pro » prédite (plus petit = plus pro)
    plc: dict = {}
    plc_info = None
    if ref["plc"] is not None:
        ref_err = refs(ref)["err"]
        for r in my_replays:
            for pid, pg in games.by_replay[r].players.items():
                err = pg.data.get("plc_err")
                if err is not None:
                    plc[(r, pid)] = (err, 100 - percentile(err, ref_err))  # type: ignore[operator]
        lob_err = [e for (_r, pid), (e, _) in plc.items() if pid != player]
        plc_info = {
            "ref_med": ref["plc"]["ref_med"],
            "n_ref": ref["plc"]["n_ref"],
            "lobby_med": float(np.median(lob_err)) if lob_err else None,
            "lobby_note": float(np.mean([100 - percentile(e, ref_err) for e in lob_err])) if lob_err else None,  # type: ignore
        }  # type: ignore[operator]

    # Choix à la touche : regret moyen (écart à la meilleure option selon les pros, plus petit = mieux)
    dec: dict = {}
    dec_info = None
    if ref["dec"] is not None:
        ref_reg = refs(ref)["regret"]
        for r in my_replays:
            for pid, pg in games.by_replay[r].players.items():
                d = pg.data.get("dec")
                if d is not None:
                    dec[(r, pid)] = (d[0], 100 - percentile(d[0], ref_reg), d[1])  # type: ignore[operator]
        lob = [v for (_r, pid), v in dec.items() if pid != player]
        dec_info = {
            "ref_med": ref["dec"]["ref_med"],
            "n_ref": ref["dec"]["n_ref"],
            "lobby_note": float(np.mean([v[1] for v in lob])) if lob else None,
            "ref_ppro": ref["dec"]["ref_ppro"],
        }

    by_game: dict[str, list[dict]] = {}
    for x in rows:
        by_game.setdefault(x["replay"], []).append(x)
    # rang dans la partie : ΔV par 5 min décroissant (valeurs manquantes en premier, comme le tri de Polars)
    by_rank = {
        r: [x["player_id"] for x in sorted(g, key=lambda x: (x["dv5"] is not None, -(x["dv5"] or 0.0)))]
        for r, g in by_game.items()
    }
    matches = []
    for r in mine:
        lob_r = by_rank[r["replay"]]
        p = plc.get((r["replay"], player))
        d = dec.get((r["replay"], player))
        matches.append(
            {
                "replay": r["replay"],
                "date": r["date"],
                "n": r["n"],
                "dv5": r["dv5"],
                "dv_mean": r["dv_mean"],
                "pos": r["pos"],
                "lobby_rank": lob_r.index(player) + 1 if player in lob_r else None,
                "lobby_note": percentile(r["dv5"], others_dv5),
                "rlcs_note": percentile(r["dv5"], ref_dv5),
                "plc_err": p[0] if p else None,
                "plc_note": p[1] if p else None,
                "dec_regret": d[0] if d else None,
                "dec_note": d[1] if d else None,
                "dec_ppro": d[2] if d else None,
            }
        )
    out: dict = {"matches": matches}
    if not details:
        return out

    my_games = [games.by_replay[r] for r in my_replays]
    mine_pg = [(gm, gm.players[player]) for gm in my_games if player in gm.players]
    play_total = sum(gm.play_s for gm in my_games)
    by_action = []
    for act, label in ACTION_FR.items():
        k = _act_key(act)
        n = dv = pos = 0
        for _gm, pg in mine_pg:
            a = pg.data.get("actions", {}).get(k)
            if a:
                n += a[0]
                dv += a[1]
                pos += a[2]
        if n:
            b = ref["by_action"][k]
            by_action.append(
                {
                    "label": label,
                    "n": n,
                    "n5": n / play_total * 300,
                    "me": dv / n,
                    "ref": b["mean"],
                    "me_pos": pos / n,
                    "ref_pos": b["pos"],
                }
            )

    def best_rows(key: str, n: int, descending: bool) -> list[dict]:
        cand = [t for _gm, pg in mine_pg for t in pg.details.get(key, [])]
        if not cand:
            return []
        return pl.DataFrame(cand, infer_schema_length=None).sort("dv", descending=descending).head(n).to_dicts()

    # Courbes de valeur de chaque match, du point de vue de l'équipe de l'utilisateur
    match_curves = {}
    for gm in my_games:
        if gm.curve is None or player not in gm.players:
            continue
        team = gm.team_of[player]
        s0, s1 = gm.score
        match_curves[gm.replay] = {
            "v": [None if x is None else (x if team == 0 else -x) for x in gm.curve["v"]],
            "goals": [{"k": k, "pour": t == team} for k, t in gm.curve["goals"]],
            "touches": gm.players[player].details.get("curve", []),
            "score": f"{s0 if team == 0 else s1}-{s1 if team == 0 else s0}",
        }

    return out | {
        "by_action": by_action,
        "worst": best_rows("worst", N_WORST, False),
        "best": best_rows("best", N_BEST, True),
        "curves": match_curves,
        "me_dv5": float(np.mean([m["dv5"] for m in matches])),
        "ref_dv5_med": ref["dv5_med"],
        "lobby_dv5_med": float(np.median(others_dv5.a)),
        "me_lobby_note": float(np.mean([m["lobby_note"] for m in matches])),
        "me_lobby_rank": float(np.mean([m["lobby_rank"] for m in matches if m["lobby_rank"]])),
        "plc": plc_info
        | {
            "me_note": float(np.nanmean([m["plc_note"] for m in matches if m["plc_note"] is not None])),
            "me_med": float(np.nanmedian([m["plc_err"] for m in matches if m["plc_err"] is not None])),
        }
        if plc_info
        else None,
        "dec": dec_info
        | {
            "me_note": float(np.mean([m["dec_note"] for m in matches if m["dec_note"] is not None])),
            "me_regret": float(np.mean([m["dec_regret"] for m in matches if m["dec_regret"] is not None])),
            "me_ppro": float(np.mean([m["dec_ppro"] for m in matches if m["dec_ppro"] is not None])),
        }
        if dec_info
        else None,
        "ranked_goal_ratio": RANKED_GOAL_RATIO,
        "n_ref_pm": len(ref["dv5"]),
        "n_ref_matches": ref["n_ref_matches"],
        "model": ref["model"],
    }
