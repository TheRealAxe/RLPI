"""Tableau de bord : critères automatiques d'un joueur comparés à ses lobbies, SSL et RLCS.

Usage :
    python -m rlpi.dashboard --player "Steam:<ton identifiant>"
Entrées : data/features/player_match_stats_{perso,rlcs}.parquet (voir rlpi.stats)
Sortie  : reports/tableau_de_bord.html (page autonome, à ouvrir dans un navigateur)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import polars as pl

from rlpi import config
from rlpi.config import DATA, MODELS, ROOT, SOURCE
from rlpi.fonts import PLACEHOLDER, font_css
import numpy as np

FEAT = DATA / "features"
UU_TO_KMH = 0.036  # 1 uu = 1 cm


def _c(df: pl.DataFrame, name: str) -> pl.Expr:
    return pl.col(name) if name in df.columns else pl.lit(0.0)


def metrics(df: pl.DataFrame) -> pl.DataFrame:
    """Une ligne par joueur et par match → indicateurs normalisés (par 5 min ou en %)."""
    t = pl.col("boost.tracked_time")
    tp = pl.col("positioning.tracked_time")
    tr = pl.col("rotation.active_game_time")
    per5 = lambda e: e / tp * 300  # noqa: E731
    pct = lambda e, base: e / base * 100  # noqa: E731
    c = lambda n: _c(df, n)  # noqa: E731
    ff_decided = c("fifty_fifty.wins") + c("fifty_fifty.losses")
    ko_decided = c("fifty_fifty.kickoff_wins") + c("fifty_fifty.kickoff_losses")
    return df.with_columns(
        # Boost mana
        boost_moyen=c("boost.boost_integral") / t / 255 * 100,
        boost_zero=pct(c("boost.time_zero_boost"), t),
        boost_plein=pct(c("boost.time_hundred_boost"), t),
        boost_utilise=per5(c("boost.amount_used") / 255),
        boost_petits=pct(c("boost.amount_collected_small"), c("boost.amount_collected")),
        boost_vole=per5(c("boost.amount_stolen") / 255),
        boost_gaspille=pct(c("boost.overfill_total"), c("boost.amount_collected")),
        # Vitesse / mouvement
        vitesse=c("movement.speed_integral") / c("movement.tracked_time") * UU_TO_KMH,
        supersonique=pct(c("movement.time_supersonic_speed"), c("movement.tracked_time")),
        lent=pct(c("movement.time_slow_speed"), c("movement.tracked_time")),
        au_sol=pct(c("movement.time_on_ground"), c("movement.tracked_time")),
        air_haut=pct(c("movement.time_high_air"), c("movement.tracked_time")),
        # 50/50
        ff_gagnes=pl.when(ff_decided > 0).then(pct(c("fifty_fifty.wins"), ff_decided)),
        ko_gagnes=pl.when(ko_decided > 0).then(pct(c("fifty_fifty.kickoff_wins"), ko_decided)),
        ff_par5=per5(c("fifty_fifty.count")),
        # Précision / attaque
        tirs=per5(c("core.shots")),
        buts=per5(c("core.goals")),
        passes=per5(c("pass.completed_pass_count")),
        frappes_fortes=per5(c("touch.hard_hit_count")),
        ratees=per5(c("whiff.whiff_count")),
        # Agressivité
        # bloc absent du replay quand personne n'a démoli / bumpé de tout le match : c'est 0, pas une donnée manquante
        demos=per5(c("demo.demos_inflicted").fill_null(0)),
        bumps=per5(c("bump.bumps_inflicted").fill_null(0)),
        moitie_adverse=pct(c("positioning.time_offensive_half"), tp),
        devant_balle=pct(c("positioning.time_in_front_of_ball"), tp),
        # Rotation / placement
        premier_homme=pct(c("rotation.time_first_man"), tr),
        troisieme_homme=pct(c("rotation.time_third_man"), tr),
        derriere_balle=pct(c("positioning.time_behind_ball"), tp),
    )


# (clé, libellé, unité, catégorie RLPI, sens : +1 plus haut = mieux, -1 plus bas = mieux, 0 = style)
METRICS = [
    ("boost_moyen", "Boost moyen", "%", "Boost mana", 0),
    ("boost_zero", "Temps à 0 boost", "% du temps", "Boost mana", -1),
    ("boost_utilise", "Boost consommé", "réservoirs pleins / 5 min", "Boost mana", 0),
    ("boost_petits", "Part des petits pads", "% du boost ramassé", "Boost mana", +1),
    ("boost_vole", "Boost volé chez l'adversaire", "réservoirs pleins / 5 min", "Boost mana", +1),
    ("boost_gaspille", "Boost gaspillé (déjà plein)", "% du boost ramassé", "Boost mana", -1),
    ("vitesse", "Vitesse moyenne", "km/h", "Speed", +1),
    ("supersonique", "Temps supersonique", "% du temps", "Speed", +1),
    ("lent", "Temps lent", "% du temps", "Speed", -1),
    ("au_sol", "Temps au sol", "% du temps", "Speed", 0),
    ("air_haut", "Temps en l'air (haut)", "% du temps", "Speed", 0),
    ("ff_gagnes", "50/50 gagnés", "% des 50/50 tranchés", "50's", +1),
    ("ko_gagnes", "Kickoffs gagnés", "% des kickoffs tranchés", "50's", +1),
    ("ff_par5", "50/50 disputés", "/ 5 min", "50's", 0),
    ("tirs", "Tirs", "/ 5 min", "Précision", +1),
    ("buts", "Buts", "/ 5 min", "Précision", +1),
    ("frappes_fortes", "Frappes fortes", "/ 5 min", "Précision", +1),
    ("ratees", "Balles ratées (whiffs)", "/ 5 min", "Précision", -1),
    ("passes", "Passes réussies", "/ 5 min", "Précision", +1),
    ("demos", "Démos infligées", "/ 5 min", "Agressivité", +1),
    ("bumps", "Bumps infligés", "/ 5 min", "Agressivité", +1),
    ("moitie_adverse", "Temps en moitié adverse", "% du temps", "Agressivité", +1),
    ("devant_balle", "Temps devant la balle", "% du temps", "Agressivité", 0),
    ("premier_homme", "Temps en 1er homme", "% du temps", "Placement", 0),
    ("troisieme_homme", "Temps en 3e homme", "% du temps", "Placement", 0),
    ("derriere_balle", "Temps derrière la balle", "% du temps", "Placement", 0),
]
KEYS = [m[0] for m in METRICS]


def percentile(value: float, ref: list[float]) -> float | None:
    if value is None:
        return None
    a = np.asarray([r for r in ref if r is not None], dtype=float)
    if not len(a):
        return None
    return float(100 * ((a < value).sum() + 0.5 * (a == value).sum()) / len(a))


# Références disponibles : (fichier, libellé, nb minimal de matchs par joueur)
REFS = {
    "rlcs": ("player_match_stats_rlcs.parquet", "RLCS", 2),
    "ssl": ("player_match_stats_ssl.parquet", "SSL", 1),
}


def compare(me: pl.DataFrame, ref_df: pl.DataFrame, min_matches: int, peers: dict | None = None) -> dict:
    """Centiles de `me` (et des joueurs comparés `peers` : {id: DataFrame}) face aux moyennes de `ref_df`."""
    peers = peers or {}
    agg = (
        ref_df.filter(~pl.col("is_bot"))
        .group_by("player_id")
        .agg(pl.col("player_name").last(), pl.len().alias("n"), *[pl.col(k).mean() for k in KEYS])
        .filter(pl.col("n") >= min_matches)
    )
    my_mean = me.select([pl.col(k).mean() for k in KEYS]).row(0, named=True)
    peer_mean = {pid: d.select([pl.col(k).mean() for k in KEYS]).row(0, named=True) for pid, d in peers.items()}
    rows = []
    for key, label, unit, cat, sens in METRICS:
        ref = [r for r in agg[key].to_list() if r is not None]
        names = [nm for r, nm in zip(agg[key].to_list(), agg["player_name"].to_list()) if r is not None]
        v = my_mean[key]
        p = percentile(v, ref)

        def note(q, sens=sens):
            return (q if sens > 0 else 100 - q) if (q is not None and sens != 0) else None

        pv = {pid: {"value": pm[key], "pct": percentile(pm[key], ref), "note": note(percentile(pm[key], ref))}
              for pid, pm in peer_mean.items()}
        rows.append({
            "peers": pv,
            "key": key, "label": label, "unit": unit, "cat": cat, "sens": sens,
            "value": v, "pct": p,
            "note": (p if sens > 0 else 100 - p) if (p is not None and sens != 0) else None,
            "ref": [{"v": r, "n": nm} for r, nm in zip(ref, names)],
            "ref_med": float(pl.Series(ref).median()) if ref else None,
            "matches": [
                {"d": d, "v": x, "w": w, "s": f"{g}-{o}"}
                for d, x, w, g, o in me.select("date", key, "won", "team_goals", "opp_goals").iter_rows()
            ],
        })
    cats: dict[str, list[float]] = {}
    for r in rows:
        if r["note"] is not None:
            cats.setdefault(r["cat"], []).append(r["note"])
    peer_radar = {}
    for pid in peers:
        pc: dict[str, list[float]] = {}
        for r in rows:
            if r["peers"][pid]["note"] is not None:
                pc.setdefault(r["cat"], []).append(r["peers"][pid]["note"])
        peer_radar[pid] = {c: sum(v) / len(v) for c, v in pc.items()}
    return {
        "metrics": rows,
        "radar": [{"cat": c, "note": sum(v) / len(v), "n": len(v),
                   "peers": {pid: peer_radar[pid].get(c) for pid in peers}} for c, v in cats.items()],
        "n_ref_players": agg.height,
        "n_ref_matches": ref_df["replay_file"].n_unique(),
        "ref_period": f"{ref_df['date'].min()[:7]} → {ref_df['date'].max()[:7]}",
    }


ACTION_FR = {"shot": "Tirs", "save": "Arrêts", "clear": "Dégagements", "pass": "Passes",
             "boom": "Frappes fortes", None: "Contrôles / autres"}


# Mesuré le 12/11/2026 : dans les parties classées de l'utilisateur, 1,5× plus de buts que prévu par le modèle
# appris sur RLCS (taux 4,9 % vs 3,3 % à 5 s) → les touches vers le but y « rapportent » plus.
RANKED_GOAL_RATIO = 1.5


@lru_cache(maxsize=None)
def _play_seconds(source: str) -> tuple:
    from rlpi.config import FRAMES
    out = []
    for p in (FRAMES / source).glob("*.meta.json"):
        m = json.loads(p.read_text(encoding="utf-8"))
        out.append((m["replay"], m["n_play_frames"] / 10))
    return tuple(out)


def play_seconds(source: str) -> dict[str, float]:
    return dict(_play_seconds(source))


def value_section(player: str, my_replays: list[str]) -> dict | None:
    """Valeur ajoutée par les touches (modèle de valeur v1, horizon 5 s)."""
    ft, fr_ = FEAT / f"touch_values_{SOURCE}.parquet", FEAT / "touch_values_rlcs.parquet"
    if not ft.exists() or not fr_.exists():
        return None
    rl = pl.read_parquet(fr_)
    me = pl.read_parquet(ft).filter((pl.col("player_id") == player) & pl.col("replay").is_in(my_replays))
    sec_r, sec_t = play_seconds("rlcs"), play_seconds(SOURCE)

    def per_match(df, secs):
        return (df.group_by("replay", "player_id", "player_name").agg(
                    pl.len().alias("n"), pl.col("dv").sum().alias("dv_sum"), pl.col("dv").mean().alias("dv_mean"),
                    (pl.col("dv") > 0).mean().alias("pos"), pl.col("date").first())
                .with_columns(pl.col("replay").replace_strict(secs, default=None).alias("play_s"))
                .with_columns((pl.col("dv_sum") / pl.col("play_s") * 300).alias("dv5")))

    ref = per_match(rl, sec_r)
    ref_dv5 = ref["dv5"].drop_nulls().to_list()
    mine = per_match(me, sec_t).sort("date")
    # Résultat des touches comparé au LOBBY (mêmes adversaires, même niveau de défense)
    lobby = per_match(pl.read_parquet(ft).filter(pl.col("replay").is_in(my_replays)), sec_t)
    others_dv5 = lobby.filter(pl.col("player_id") != player)["dv5"].drop_nulls().to_list()

    # Placement hors ballon : écart médian à la position « pro » prédite (plus petit = plus pro)
    from rlpi.config import FRAMES
    slot_of = {r: {p["id"]: p["slot"] for p in json.loads((FRAMES / SOURCE / f"{r}.meta.json")
                   .read_text(encoding="utf-8"))["players"]} for r in my_replays}
    plc = {}
    if (FEAT / "placement_rlcs.parquet").exists():
        pr = pl.read_parquet(FEAT / "placement_rlcs.parquet").group_by("replay", "slot").agg(
            pl.col("err").median(), pl.len())
        pt = pl.read_parquet(FEAT / f"placement_{SOURCE}.parquet").filter(pl.col("replay").is_in(my_replays)) \
            .group_by("replay", "slot").agg(pl.col("err").median(), pl.len())
        ref_err = pr["err"].to_list()
        for r, slot, err, n in pt.iter_rows():
            plc[(r, slot)] = (err, 100 - percentile(err, ref_err))
        me_slots = [(r, slot_of[r][player]) for r in my_replays]
        lob_err = [e for (r, s), (e, _) in plc.items() if (r, s) not in me_slots]
        plc_info = {"ref_med": float(np.median(ref_err)), "n_ref": len(ref_err),
                    "lobby_med": float(np.median(lob_err)) if lob_err else None,
                    "lobby_note": float(np.mean([100 - percentile(e, ref_err) for e in lob_err])) if lob_err else None}
    else:
        plc_info = None

    # Choix à la touche : regret moyen (écart à la meilleure option selon les pros, plus petit = mieux)
    dec, dec_info = {}, None
    if (FEAT / "touch_decisions_rlcs.parquet").exists():
        dr = pl.read_parquet(FEAT / "touch_decisions_rlcs.parquet").group_by("replay", "player_id") \
            .agg(pl.col("regret").mean(), (pl.col("p_pro")).mean().alias("ppro"))
        dt = pl.read_parquet(FEAT / f"touch_decisions_{SOURCE}.parquet").filter(pl.col("replay").is_in(my_replays)) \
            .group_by("replay", "player_id").agg(pl.col("regret").mean(), (pl.col("p_pro")).mean().alias("ppro"))
        ref_reg = dr["regret"].to_list()
        for r, pid, reg, ppro in dt.iter_rows():
            dec[(r, pid)] = (reg, 100 - percentile(reg, ref_reg), ppro)
        lob = [v for (r, pid), v in dec.items() if pid != player]
        dec_info = {"ref_med": float(np.median(ref_reg)), "n_ref": len(ref_reg),
                    "lobby_note": float(np.mean([v[1] for v in lob])) if lob else None,
                    "ref_ppro": float(dr["ppro"].mean())}

    matches = []
    for r in mine.iter_rows(named=True):
        lob_r = lobby.filter(pl.col("replay") == r["replay"]).sort("dv5", descending=True)["player_id"].to_list()
        p = plc.get((r["replay"], slot_of[r["replay"]][player]))
        d = dec.get((r["replay"], player))
        matches.append({"replay": r["replay"], "date": r["date"], "n": r["n"], "dv5": r["dv5"],
                        "dv_mean": r["dv_mean"], "pos": r["pos"],
                        "lobby_rank": lob_r.index(player) + 1 if player in lob_r else None,
                        "lobby_note": percentile(r["dv5"], others_dv5),
                        "rlcs_note": percentile(r["dv5"], ref_dv5),
                        "plc_err": p[0] if p else None, "plc_note": p[1] if p else None,
                        "dec_regret": d[0] if d else None, "dec_note": d[1] if d else None,
                        "dec_ppro": d[2] if d else None})

    by_action = []
    for act, label in ACTION_FR.items():
        flt = (pl.col("action").is_null()) if act is None else (pl.col("action") == act)
        a, b = me.filter(flt), rl.filter(flt)
        if a.height:
            by_action.append({"label": label, "n": a.height, "n5": a.height / sum(sec_t[r] for r in my_replays if r in sec_t) * 300,
                              "me": a["dv"].mean(), "ref": b["dv"].mean(), "me_pos": (a["dv"] > 0).mean(),
                              "ref_pos": (b["dv"] > 0).mean()})

    def touch_rows(df):
        return [{"replay": r["replay"], "date": r["date"], "clock": r["clock"], "action": ACTION_FR.get(r["action"], r["action"]),
                 "kind": r["kind"], "role": r["role"], "dv": r["dv"], "vb": r["v_before"], "va": r["v_after"],
                 "x": r["ball_x"], "y": r["ball_y"]} for r in df.iter_rows(named=True)]

    # Courbes de valeur de chaque match, du point de vue de l'équipe de l'utilisateur
    curves = {c["replay"]: c for c in json.loads((FEAT / f"value_curves_{SOURCE}.json").read_text(encoding="utf-8"))}
    from rlpi.config import FRAMES
    match_curves = {}
    for r in my_replays:
        if r not in curves:
            continue
        meta = json.loads((FRAMES / SOURCE / f"{r}.meta.json").read_text(encoding="utf-8"))
        team = next(p["team"] for p in meta["players"] if p["id"] == player)
        c = curves[r]
        v = [None if not pl_ else (x if team == 0 else -x) for x, pl_ in zip(c["v_team0"], c["play"])]
        tch = me.filter(pl.col("replay") == r)
        match_curves[r] = {
            "v": v, "goals": [{"k": g["i"] // 5, "pour": g["team"] == team} for g in c["goals"]],
            "touches": [{"k": i // 5, "dv": dv, "a": ACTION_FR.get(a, a), "clock": ck, "vb": vb, "va": va}
                        for i, dv, a, ck, vb, va in tch.select("i", "dv", "action", "clock", "v_before", "v_after").iter_rows()],
            "score": f"{meta['team0_score'] if team == 0 else meta['team1_score']}-{meta['team1_score'] if team == 0 else meta['team0_score']}",
        }

    rep = json.loads((MODELS / "value_h5_report.json").read_text(encoding="utf-8"))
    return {
        "matches": matches, "by_action": by_action,
        "worst": touch_rows(me.sort("dv").head(10)), "best": touch_rows(me.sort("dv", descending=True).head(5)),
        "curves": match_curves,
        "me_dv5": float(np.mean([m["dv5"] for m in matches])), "ref_dv5_med": float(np.median(ref_dv5)),
        "lobby_dv5_med": float(np.median(others_dv5)),
        "me_lobby_note": float(np.mean([m["lobby_note"] for m in matches])),
        "me_lobby_rank": float(np.mean([m["lobby_rank"] for m in matches if m["lobby_rank"]])),
        "plc": plc_info | {"me_note": float(np.nanmean([m["plc_note"] for m in matches if m["plc_note"] is not None])),
                           "me_med": float(np.nanmedian([m["plc_err"] for m in matches if m["plc_err"] is not None]))}
               if plc_info else None,
        "dec": dec_info | {"me_note": float(np.mean([m["dec_note"] for m in matches if m["dec_note"] is not None])),
                           "me_regret": float(np.mean([m["dec_regret"] for m in matches if m["dec_regret"] is not None])),
                           "me_ppro": float(np.mean([m["dec_ppro"] for m in matches if m["dec_ppro"] is not None]))}
               if dec_info else None,
        "ranked_goal_ratio": RANKED_GOAL_RATIO,
        "n_ref_pm": len(ref_dv5), "n_ref_matches": rl["replay"].n_unique(),
        "model": {k: rep[k] for k in ("auc", "n_matches", "n_test_matches", "horizon_s")} | {"calibration": rep["calibration"]},
    }


PEER_KEYS = ["boost_moyen", "boost_zero", "boost_vole", "vitesse", "supersonique", "ff_gagnes", "tirs", "buts",
             "passes", "ratees", "demos", "moitie_adverse", "premier_homme", "troisieme_homme", "derriere_balle"]
VALUE_KEYS = [("plc_note", "Placement hors ballon (vs pros)", +1), ("dec_note", "Choix à la touche (vs pros)", +1),
              ("lobby_note", "Résultat des touches (vs lobby)", +1), ("lobby_rank", "Rang dans la partie (1 = meilleur)", -1)]


def _stems(df: pl.DataFrame) -> list[str]:
    return [Path(f).stem for f in df["replay_file"].to_list()]


def peer_section(player: str, me: pl.DataFrame, peers: dict[str, pl.DataFrame]) -> list[dict]:
    """Pour chaque coéquipier comparé : notes de décision et face-à-face sur les parties communes."""
    out = []
    lab = {k: (label, unit, sens) for k, label, unit, _, sens in METRICS}
    my_value = value_section(player, _stems(me))
    my_by = {m["replay"]: m for m in my_value["matches"]} if my_value else {}
    me_s = me.with_columns(pl.Series("stem", _stems(me)))
    for pid, d in peers.items():
        reps = _stems(d)
        v = value_section(pid, reps)
        shared = sorted(set(reps) & set(my_by))
        pm = {m["replay"]: m for m in v["matches"]} if v else {}
        mine_sh = me_s.filter(pl.col("stem").is_in(shared))
        peer_sh = d.with_columns(pl.Series("stem", reps)).filter(pl.col("stem").is_in(shared))
        h2h = []
        for k in PEER_KEYS:
            label, unit, sens = lab[k]
            h2h.append({"key": k, "label": label, "unit": unit, "sens": sens,
                        "me": mine_sh[k].mean(), "peer": peer_sh[k].mean()})
        for k, label, sens in VALUE_KEYS:
            a = [my_by[r][k] for r in shared if my_by[r].get(k) is not None]
            b = [pm[r][k] for r in shared if r in pm and pm[r].get(k) is not None]
            h2h.append({"key": k, "label": label, "unit": "/6" if k == "lobby_rank" else "/100", "sens": sens,
                        "me": float(np.mean(a)) if a else None, "peer": float(np.mean(b)) if b else None,
                        "value": True})
        out.append({
            "id": pid, "name": d["player_name"][-1], "n": d.height, "n_shared": len(shared),
            "wins_shared": int(mine_sh["won"].sum()),
            "first": d["date"][0][:10], "last": d["date"][-1][:10],
            "value": {k: float(np.mean([m[k] for m in v["matches"] if m.get(k) is not None]))
                      for k, _, _ in VALUE_KEYS} if v else None,
            "h2h": h2h,
        })
    return out


def passes_section(player: str, my_replays: list[str], peers: dict[str, pl.DataFrame]) -> dict | None:
    """Balles données (vers l'avant / le côté / l'arrière) : récupérées par un coéquipier ou perdues."""
    ft, fr_ = FEAT / f"passes_{SOURCE}.parquet", FEAT / "passes_rlcs.parquet"
    if not ft.exists() or not fr_.exists():
        return None
    t = pl.read_parquet(ft).filter(pl.col("replay").is_in(my_replays))
    r = pl.read_parquet(fr_)
    sec_t, sec_r = play_seconds(SOURCE), play_seconds("rlcs")

    def summary(df: pl.DataFrame, secs: dict, key: str, label: str) -> dict:
        pm = df.select("replay", "player_id").unique()
        play = sum(secs.get(x, 0) for x in pm["replay"].to_list())
        ok = df.filter(pl.col("next").is_not_null())
        mate, nobody = ok.filter(pl.col("mate_closer")), ok.filter(~pl.col("mate_closer"))
        rec = lambda d: float((d["next"] == "coéquipier").mean()) if d.height else None  # noqa: E731
        return {"key": key, "label": label, "n": df.height, "n_games": pm.height,
                "per5": df.height / play * 300 if play else None,
                "recovered": rec(ok), "mate_pos": float(df["mate_closer"].mean()) if df.height else None,
                "rec_mate": rec(mate), "rec_nobody": rec(nobody),
                "dv_nobody": float(nobody["dv_2s"].mean()) if nobody.height else None,
                "void_lost": float(((~ok["mate_closer"]) & (ok["next"] == "adversaire")).mean()) if ok.height else None,
                # issues exactes (somme = 100 %) : récupérée en position / récupérée sans / perdue en position / dans le vide
                "split": [float(((ok["mate_closer"] == a) & ((ok["next"] == "coéquipier") == b)).mean())
                          for a, b in ((True, True), (False, True), (True, False), (False, False))] if ok.height else None}

    groups = [summary(t.filter(pl.col("player_id") == player), sec_t, "me", "Toi")]
    for pid, d in peers.items():
        groups.append(summary(t.filter(pl.col("player_id") == pid), sec_t, pid, d["player_name"][-1]))
    others = t.filter(~pl.col("player_id").is_in([player, *peers]))
    groups.append(summary(others, sec_t, "lobby", "Lobbies"))
    groups.append(summary(r, sec_r, "rlcs", "Pros RLCS"))

    me = t.filter(pl.col("player_id") == player)
    per_match = []
    for (rp,), g in me.group_by("replay"):
        ok = g.filter(pl.col("next").is_not_null())
        per_match.append({"replay": rp, "date": g["date"][0], "n": g.height,
                          "per5": g.height / sec_t[rp] * 300,
                          "recovered": float((ok["next"] == "coéquipier").mean()) if ok.height else None,
                          "void_lost": float(((~ok["mate_closer"]) & (ok["next"] == "adversaire")).mean()) if ok.height else None})
    per_match.sort(key=lambda m: m["date"])
    act_fr = {"forward": "Vers l'avant", "side": "Latérale", "back": "En retrait"}
    void = (me.filter((~pl.col("mate_closer")) & (pl.col("next") == "adversaire")).sort("dv_2s").head(10))
    return {
        "groups": groups, "matches": per_match,
        "void": [{"date": x["date"], "clock": x["clock"], "act": act_fr.get(x["act"], x["act"]), "dv": x["dv_2s"],
                  "x": x["ball_x"], "y": x["ball_y"], "d_mate": x["d_mate"] / 100, "d_opp": x["d_opp"] / 100,
                  "delay": x["delay_s"]} for x in void.iter_rows(named=True)],
    }


# Mesures techniques (clé, libellé, unité, sens, définition) — calculées par joueur et par match
TECH = [
    ("t_speed", "Vitesse moyenne", "km/h", +1, "Vitesse moyenne de la voiture sur le temps suivi."),
    ("t_sup", "Temps supersonique", "% du temps", +1, "Temps au-dessus de 2 200 uu/s (≈ 79 km/h, seuil du jeu) ÷ temps suivi."),
    ("t_slow", "Temps lent", "% du temps", -1, "Temps sous le seuil « lent » du détecteur subtr-actor ÷ temps suivi."),
    ("t_highair", "Temps en l'air (haut)", "% du temps", +1, "Temps au-dessus du seuil « haut » de subtr-actor ÷ temps suivi : jeu aérien engagé."),
    ("t_haer", "Touches aériennes hautes", "/ 5 min", +1, "Touches de balle classées « aérien haut » par subtr-actor, par 5 minutes de jeu."),
    ("t_aer", "Touches aériennes (toutes)", "/ 5 min", +1, "Toutes les touches de balle en l'air (bas et haut), par 5 minutes de jeu."),
    ("t_wall", "Touches au mur", "/ 5 min", +1, "Touches de balle faites depuis un mur, par 5 minutes de jeu."),
    ("t_awhiff", "Aériens ratés", "/ 5 min", -1, "Whiffs aériens de subtr-actor, par 5 minutes : approche rapide et orientée vers la balle, passage tout près (en général à moins de 2 m) sans contact, sans qu'un adversaire l'ait touchée avant. Non vérifié à l'œil."),
    ("t_beaten", "Battu sur la balle", "/ 5 min", -1, "Fois où un adversaire touche la balle juste avant toi alors que tu y allais (détecteur subtr-actor), par 5 minutes."),
]


def tech_metrics(df: pl.DataFrame) -> pl.DataFrame:
    t = pl.col("positioning.tracked_time")
    mv = pl.col("movement.tracked_time")
    c = lambda n: _c(df, n)  # noqa: E731
    return df.with_columns(
        t_speed=c("movement.speed_integral") / mv * UU_TO_KMH,
        t_sup=c("movement.time_supersonic_speed") / mv * 100,
        t_slow=c("movement.time_slow_speed") / mv * 100,
        t_highair=c("movement.time_high_air") / mv * 100,
        t_haer=c("touch.high_aerial_touch_count") / t * 300,
        t_aer=c("touch.aerial_touch_count") / t * 300,
        t_wall=c("touch.wall_touch_count") / t * 300,
        t_awhiff=c("whiff.aerial_whiff_count") / t * 300,
        t_beaten=c("whiff.beaten_to_ball_count") / t * 300,
    )


def tech_section(player: str, me: pl.DataFrame, peers: dict[str, pl.DataFrame], perso_all: pl.DataFrame) -> dict:
    """Mesures techniques : toi, coéquipiers, tes lobbies (GC), SSL et RLCS (médianes par joueur-match)."""
    ssl = tech_metrics(pl.read_parquet(FEAT / "player_match_stats_ssl.parquet").filter(~pl.col("is_bot")))
    rl = tech_metrics(pl.read_parquet(FEAT / "player_match_stats_rlcs.parquet").filter(~pl.col("is_bot")))
    lob = tech_metrics(perso_all.filter(pl.col("replay_file").is_in(me["replay_file"].to_list())
                                       & ~pl.col("player_id").is_in([player, *peers]) & ~pl.col("is_bot")))
    mine = tech_metrics(me)
    rows = []
    for k, label, unit, sens, d in TECH:
        s = ssl[k].drop_nulls().to_numpy()
        v = float(mine[k].mean())
        rows.append({"key": k, "label": label, "unit": unit, "sens": sens, "def": d, "me": v,
                     "pct_ssl": float(100 * ((s < v).mean() + 0.5 * (s == v).mean())),
                     "peers": {pid: float(tech_metrics(dd)[k].mean()) for pid, dd in peers.items()},
                     "lobby": float(lob[k].median()), "ssl": float(np.median(s)), "rlcs": float(rl[k].median()),
                     "ssl_q": [float(np.percentile(s, q)) for q in (10, 25, 75, 90)],
                     "matches": [float(x) if x is not None else None for x in mine[k].to_list()]})
    return {"rows": rows, "n_lobby": lob.height, "n_ssl": ssl.height, "n_rlcs": rl.height}


def perf_section(player: str, my_replays: list[str], peers: dict[str, pl.DataFrame]) -> dict | None:
    """Indice de performance RLPI (voir rlpi.perf) : par match et global, pour l'utilisateur, ses coéquipiers et ses lobbies."""
    fp, rp = FEAT / f"perf_{SOURCE}.parquet", MODELS / "perf_report.json"
    if not fp.exists() or not rp.exists():
        return None
    from rlpi.perf import COMPONENTS, KEYS

    rep = json.loads(rp.read_text(encoding="utf-8"))
    t = pl.read_parquet(fp).filter(pl.col("replay").is_in(my_replays))
    me = t.filter(pl.col("player_id") == player).sort("date")
    rng = np.random.default_rng(0)

    def summary(df: pl.DataFrame) -> dict | None:
        if df.is_empty():
            return None
        x = df["index"].to_numpy()
        boots = [rng.choice(x, len(x)).mean() for _ in range(2000)]
        return {"mean": float(x.mean()), "lo": float(np.percentile(boots, 10)), "hi": float(np.percentile(boots, 90)),
                "n": len(x), "comps": {k: float(df[f"c_{k}"].mean()) for k in KEYS},
                "prod": float(df["prod"].mean()) if "prod" in df.columns else None,
                "fond": float(df["fond"].mean()) if "fond" in df.columns else None,
                "win_good": float(df.filter(pl.col("index") >= 50)["won"].mean()) if (df["index"] >= 50).any() else None,
                "win_bad": float(df.filter(pl.col("index") < 50)["won"].mean()) if (df["index"] < 50).any() else None}

    matches = []
    for r in me.iter_rows(named=True):
        game = t.filter(pl.col("replay") == r["replay"]).sort("index", descending=True)
        ids = game["player_id"].to_list()
        mates = game.filter((pl.col("team") == r["team"]) & (pl.col("player_id") != player))
        matches.append({
            "replay": r["replay"], "date": r["date"], "won": bool(r["won"]), "index": r["index"],
            "prod": r.get("prod"), "fond": r.get("fond"),
            "rank": ids.index(player) + 1, "n_players": len(ids),
            "comps": {k: r[f"c_{k}"] for k in KEYS},
            "peers": {pid: float(game.filter(pl.col("player_id") == pid)["index"][0]) for pid in peers if pid in ids},
            "mates": [{"name": m["player_name"], "index": m["index"]} for m in mates.iter_rows(named=True)],
            "opp_mean": float(game.filter(pl.col("team") != r["team"])["index"].mean()),
            "opps": [{"name": o["player_name"], "index": o["index"]}
                     for o in game.filter(pl.col("team") != r["team"]).iter_rows(named=True)],
        })
    last = me.tail(5)["index"].to_numpy()
    return {
        "components": [{"key": k, "label": lab, "weight": rep["weights"][k]} for k, lab, _ in COMPONENTS],
        "me": summary(me) | {"last5": float(last.mean()) if len(last) else None},
        "peers": {pid: summary(t.filter(pl.col("player_id") == pid)) for pid in peers},
        "lobby": summary(t.filter(~pl.col("player_id").is_in([player, *peers]))),
        "matches": matches,
        "validation": {k: rep.get(k, rep.get(k.replace("perso_", "theo_"))) for k in ("n_ref_player_matches", "n_ref_matches", "auc_player_oof",
                                                "team_acc_oof", "perso_team_acc", "perso_n_matches", "rlcs_team_acc",
                                                "rlcs_team_acc_prod", "rlcs_team_acc_fond", "rlcs_n_matches",
                                                "retest", "split_half", "version")},
    }


# Répartitions du temps (chaque groupe somme à 100 %) : (clé, titre, base, [(colonne, libellé)])
COMPOSITIONS = [
    ("role", "Rôle dans la rotation", "rotation.active_game_time",
     [("rotation.time_first_man", "1er homme"), ("rotation.time_second_man", "2e homme"),
      ("rotation.time_third_man", "3e homme"), ("rotation.time_ambiguous_role", "indéterminé")]),
    ("third", "Zone du terrain", "positioning.tracked_time",
     [("positioning.time_defensive_third", "tiers défensif"), ("positioning.time_neutral_third", "tiers central"),
      ("positioning.time_offensive_third", "tiers offensif")]),
    ("ballpos", "Par rapport à la balle", "positioning.tracked_time",
     [("positioning.time_behind_ball", "derrière la balle"), ("positioning.time_level_with_ball", "à hauteur"),
      ("positioning.time_in_front_of_ball", "devant la balle")]),
    ("boost", "Réserve de boost", "boost.tracked_time",
     [("boost.time_boost_0_25", "0–25"), ("boost.time_boost_25_50", "25–50"),
      ("boost.time_boost_50_75", "50–75"), ("boost.time_boost_75_100", "75–100")]),
    ("height", "Au sol ou en l'air", "movement.tracked_time",
     [("movement.time_on_ground", "au sol"), ("movement.time_low_air", "en l'air (bas)"),
      ("movement.time_high_air", "en l'air (haut)")]),
    ("speed", "Vitesse", "movement.tracked_time",
     [("movement.time_slow_speed", "lent"), ("movement.time_boost_speed", "rapide"),
      ("movement.time_supersonic_speed", "supersonique")]),
    ("touch", "Type de touche", "touch.touch_count",
     [("touch.control_touch_count", "contrôle"), ("touch.medium_hit_count", "frappe moyenne"),
      ("touch.hard_hit_count", "frappe forte")]),
]


SYN_KEYS = [  # clé, libellé, unité, sens (+1 plus haut = mieux, −1 plus bas = mieux, 0 style)
    ("connexion", "Connexion", "% des touches reprises par l'autre", +1),
    ("bonus", "Bonus par enchaînement", "pts de valeur en plus", +1),
    ("double_commit", "Double commit", "s / 5 min", -1),
    ("montes", "Montés ensemble sans couverture", "s / 5 min", -1),
    ("ecart", "Écart moyen entre vous", "m", 0),
]


def _syn_agg(g: pl.DataFrame) -> dict:
    T = g["play_s"].sum() / 300
    ch = (g["chain_ab"] + g["chain_ba"]).sum()
    return {"connexion": 100 * ch / max((g["n_a"] + g["n_b"]).sum(), 1),
            "bonus": 100 * (g["chain_bonus_ab"] + g["chain_bonus_ba"]).sum() / max(ch, 1),
            "double_commit": g["double_commit_s"].sum() / T, "montes": g["montes_ensemble_s"].sum() / T,
            "ecart": g["ecart"].mean() / 100, "n_chains": int(ch)}


def _syn_dir(g: pl.DataFrame, src: str) -> dict:
    """Sens src → l'autre : part des touches de src reprises, bonus moyen par enchaînement."""
    ab = g.filter(pl.col("a") == src); ba = g.filter(pl.col("b") == src)
    n = ab["n_a"].sum() + ba["n_b"].sum(); ch = ab["chain_ab"].sum() + ba["chain_ba"].sum()
    bonus = ab["chain_bonus_ab"].sum() + ba["chain_bonus_ba"].sum()
    return {"sert": 100 * ch / max(n, 1), "bonus": 100 * bonus / max(ch, 1), "n": int(ch)}


def synergy_section(player: str, my_replays: list[str], peers: dict[str, pl.DataFrame]) -> dict | None:
    """Synergie par paire (voir rlpi.synergy), sur les parties retenues, face à « toi + un inconnu » et aux SSL."""
    ft, fs = FEAT / f"synergy_{SOURCE}.parquet", FEAT / "synergy_ssl.parquet"
    if not ft.exists() or not fs.exists():
        return None
    t = pl.read_parquet(ft).filter(pl.col("replay").is_in(my_replays))
    mine = t.filter((pl.col("a") == player) | (pl.col("b") == player))
    other = pl.when(pl.col("a") == player).then(pl.col("b")).otherwise(pl.col("a"))
    mine = mine.with_columns(other.alias("mate"))
    ref = {"ssl": _syn_agg(pl.read_parquet(fs))}
    rnd = mine.filter(~pl.col("mate").is_in(list(peers)))
    ref["random"] = _syn_agg(rnd) if rnd.height else None
    ref["n_random"] = rnd["replay"].n_unique()
    rng = np.random.default_rng(0)
    pairs = {}
    for pid in peers:
        g = mine.filter(pl.col("mate") == pid)
        if g.is_empty():
            continue
        reps = g["replay"].unique().to_list()
        parts = {r: g.filter(pl.col("replay") == r) for r in reps}
        bs = [_syn_agg(pl.concat([parts[r] for r in rng.choice(reps, len(reps))])) for _ in range(200)]
        est = _syn_agg(g)
        pairs[pid] = {"n": len(reps), "won": float(g["won"].mean()),
                      "rows": [{"key": k, "label": lab, "unit": u, "sens": s, "v": est[k],
                                "lo": float(np.percentile([b[k] for b in bs], 10)),
                                "hi": float(np.percentile([b[k] for b in bs], 90)),
                                "ssl": ref["ssl"][k], "random": ref["random"][k] if ref["random"] else None}
                               for k, lab, u, s in SYN_KEYS],
                      "me_to": _syn_dir(g, player), "to_me": _syn_dir(g, pid), "n_chains": est["n_chains"]}
    return {"pairs": pairs, "n_random": ref["n_random"]}


def compositions(groups: list[tuple[str, str, pl.DataFrame]]) -> list[dict]:
    """Parts de temps cumulées (somme des temps / somme des bases) pour chaque groupe."""
    out = []
    for key, title, base, parts in COMPOSITIONS:
        rows = []
        for gkey, label, df in groups:
            if df.is_empty() or base not in df.columns:
                continue
            tot = df[base].sum()
            rows.append({"key": gkey, "label": label, "n": df.height,
                         "parts": [float(df[c].sum() / tot) if tot and c in df.columns else None for c, _ in parts]})
        out.append({"key": key, "title": title, "labels": [lab for _, lab in parts], "rows": rows})
    return out


GRID_X, GRID_Y = 8, 10  # cases du terrain (largeur × longueur) : ~1 000 × 1 000 uu, assez pour 24 parties


def _bins(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    gx = np.clip(((x + 4096) / 8192 * GRID_X).astype(int), 0, GRID_X - 1)
    gy = np.clip(((y + 5120) / 10240 * GRID_Y).astype(int), 0, GRID_Y - 1)
    return gy * GRID_X + gx


def heatmaps(player: str, my_replays: list[str], n_pro: int = 200, step: int = 5) -> dict:
    """Où le joueur passe son temps (jeu en cours) et où il touche la balle, terrain orienté vers l'attaque."""
    from rlpi.config import FRAMES

    def occupancy(source: str, replays: list[str], who) -> np.ndarray:
        h = np.zeros(GRID_X * GRID_Y)
        for r in replays:
            mp = FRAMES / source / f"{r}.meta.json"
            if not mp.exists():
                continue
            m = json.loads(mp.read_text(encoding="utf-8"))
            cols = ["phase"] + [f"p{p['slot']}_{a}" for p in m["players"] for a in ("x", "y")]
            f = pl.read_parquet(mp.with_name(r + ".parquet"), columns=cols)
            play = f["phase"].to_numpy() == 1
            for p in m["players"]:
                if not who(p):
                    continue
                s = 1 if p["team"] == 0 else -1
                x = s * f[f"p{p['slot']}_x"].to_numpy()[play][::step]
                y = s * f[f"p{p['slot']}_y"].to_numpy()[play][::step]
                h += np.bincount(_bins(x, y), minlength=GRID_X * GRID_Y)
        return h / h.sum() if h.sum() else h

    pros = sorted(p.name.removesuffix(".meta.json") for p in (FRAMES / "rlcs").glob("*.meta.json"))
    pros = pros[:: max(1, len(pros) // n_pro)][:n_pro]
    occ_me = occupancy(SOURCE, my_replays, lambda p: p["id"] == player)
    occ_lobby = occupancy(SOURCE, my_replays, lambda p: p["id"] != player)
    occ_pro = occupancy("rlcs", pros, lambda p: True)

    t = pl.read_parquet(FEAT / f"touch_values_{SOURCE}.parquet").filter(
        (pl.col("player_id") == player) & pl.col("replay").is_in(my_replays))
    rl = pl.read_parquet(FEAT / "touch_values_rlcs.parquet")

    def touch_grid(df: pl.DataFrame):
        b = _bins(df["ball_x"].to_numpy(), df["ball_y"].to_numpy())
        n = np.bincount(b, minlength=GRID_X * GRID_Y)
        sdv = np.bincount(b, weights=df["dv"].to_numpy(), minlength=GRID_X * GRID_Y)
        return n, np.where(n > 0, sdv / np.maximum(n, 1), np.nan)

    n_me, dv_me = touch_grid(t)
    n_pro_t, dv_pro = touch_grid(rl)

    def r(a):
        return [None if not np.isfinite(v) else round(float(v), 5) for v in a]

    return {"gx": GRID_X, "gy": GRID_Y, "n_pro_replays": len(pros),
            "occ_me": r(occ_me), "occ_lobby": r(occ_lobby), "occ_pro": r(occ_pro),
            "touch_n": [int(v) for v in n_me], "touch_dv": r(dv_me),
            "touch_share_pro": r(n_pro_t / n_pro_t.sum()), "touch_dv_pro": r(dv_pro),
            "n_touches": int(t.height)}


@lru_cache(maxsize=1)
def _perso_metrics(mtime: float) -> pl.DataFrame:
    return metrics(pl.read_parquet(FEAT / f"player_match_stats_{SOURCE}.parquet"))


def filter_games(df: pl.DataFrame, since: str | None = None, until: str | None = None,
                 with_ids: list[str] | None = None, without_ids: list[str] | None = None) -> pl.DataFrame:
    """Garde les parties dans la plage de dates (jours inclus) et selon la présence de joueurs."""
    if since:  # date du replay « AAAA-MM-JJ HH-MM-SS »
        df = df.filter(pl.col("date") >= since)
    if until:
        df = df.filter(pl.col("date") <= until + " 99")
    keep = None
    present = df.group_by("replay_file").agg(pl.col("player_id"))
    for pid in with_ids or []:
        ok = set(present.filter(pl.col("player_id").list.contains(pid))["replay_file"].to_list())
        keep = ok if keep is None else keep & ok
    for pid in without_ids or []:
        ok = set(present.filter(~pl.col("player_id").list.contains(pid))["replay_file"].to_list())
        keep = ok if keep is None else keep & ok
    return df if keep is None else df.filter(pl.col("replay_file").is_in(list(keep)))


def make_payload(player: str, compare_with: list[str] | None = None, since: str | None = None,
                 until: str | None = None, with_ids: list[str] | None = None,
                 without_ids: list[str] | None = None) -> dict:
    perso = _perso_metrics((FEAT / f"player_match_stats_{SOURCE}.parquet").stat().st_mtime)
    perso = filter_games(perso, since, until, with_ids, without_ids)
    me = perso.filter(pl.col("player_id") == player).sort("date")
    # Joueurs comparés : identifiants ou pseudos présents dans les parties de l'utilisateur
    peers = {}
    for q in compare_with or []:
        d = perso.filter((pl.col("player_id") == q) | (pl.col("player_name").str.to_lowercase() == q.lower()))
        if d.is_empty():
            print(f"  joueur comparé introuvable : {q}")
            continue
        pid = d["player_id"].mode()[0]
        peers[pid] = d.filter(pl.col("player_id") == pid).sort("date")
    if me.is_empty():
        raise SystemExit(f"Joueur {player} absent des replays")
    # Les autres joueurs des parties de l'utilisateur ne servent pas de référence (niveau inconnu).

    refs = {}
    for key, (fname, label, min_n) in REFS.items():
        path = FEAT / fname
        if not path.exists():
            continue
        ref_df = metrics(pl.read_parquet(path)).filter(pl.col("player_id") != player)
        if ref_df.is_empty():
            continue
        refs[key] = {"label": label, **compare(me, ref_df, min_n, peers)}
        print(f"  référence {label} : {refs[key]['n_ref_players']} joueurs, {refs[key]['n_ref_matches']} matchs")

    payload = {
        "player": me["player_name"][-1],
        "n_matches": me.height,
        "wins": int(me["won"].sum()),
        "first": me["date"][0][:10], "last": me["date"][-1][:10],
        "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "refs": refs,
        "default_ref": "ssl" if "ssl" in refs and refs["ssl"]["n_ref_players"] >= 30 else "rlcs",
        "value": value_section(player, [Path(f).stem for f in me["replay_file"].to_list()]),
        "peers": peer_section(player, me, peers),
        "passes": passes_section(player, [Path(f).stem for f in me["replay_file"].to_list()], peers),
        "heat": heatmaps(player, [Path(f).stem for f in me["replay_file"].to_list()]),
        "perf": perf_section(player, [Path(f).stem for f in me["replay_file"].to_list()], peers),
        "synergy": synergy_section(player, [Path(f).stem for f in me["replay_file"].to_list()], peers),
    }
    groups = [("me", payload["player"], me)]
    groups += [(pid, d["player_name"][-1], d) for pid, d in peers.items()]
    lobby_df = perso.filter(pl.col("replay_file").is_in(me["replay_file"].to_list())
                           & ~pl.col("player_id").is_in([player, *peers]) & ~pl.col("is_bot"))
    groups.append(("lobby", "Lobbies", lobby_df))
    for key, (fname, label, _) in REFS.items():
        if (FEAT / fname).exists():
            groups.append((key, f"Joueurs {label}", pl.read_parquet(FEAT / fname).filter(~pl.col("is_bot"))))
    payload["compo"] = compositions(groups)
    payload["tech"] = tech_section(player, me, peers, perso)
    payload["record"] = [{"d": d, "w": bool(w), "s": f"{g}-{o}"}
                         for d, w, g, o in me.select("date", "won", "team_goals", "opp_goals").iter_rows()]
    payload["filters"] = {"since": since, "until": until, "with": with_ids or [], "without": without_ids or []}
    my_replays = [Path(f).stem for f in me["replay_file"].to_list()]
    payload["style"] = style_section(player, my_replays, peers)
    payload["advice"] = advice_section(payload)
    payload["progress"] = progress_section(payload)
    return payload


# ------------------------------------------------------------------ style de jeu, conseils, progression
@lru_cache(maxsize=1)
def _styles_model(mtime: float) -> dict:
    return json.loads((MODELS / "styles.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _perso_traits(mtime: float) -> pl.DataFrame:
    from rlpi.styles import traits
    return traits(SOURCE)


def _style_scores(S: dict, X: np.ndarray) -> np.ndarray:
    """Traits moyens (n, T) → centile sur chaque style (n, n_styles)."""
    Z = (X - np.array(S["mu"])) / np.array(S["sd"])
    F = Z @ np.array(S["W"])
    out = np.zeros((len(X), len(S["styles"])))
    for j, st in enumerate(S["styles"]):
        ref = np.asarray(st["ref_sorted"])
        out[:, j] = 100 * np.searchsorted(ref, F[:, st["factor"]] * st["pole"], side="right") / len(ref)
    return out


def style_section(player: str, my_replays: list[str], peers: dict[str, pl.DataFrame]) -> dict | None:
    """Style de jeu (voir rlpi.styles) : style principal et secondaire, ce qui le signe, pro le plus proche,
    régularité du style d'un match à l'autre ; mêmes calculs pour les coéquipiers suivis."""
    mp = MODELS / "styles.json"
    if not mp.exists():
        return None
    S = _styles_model(mp.stat().st_mtime)
    T = S["traits"]
    tr = _perso_traits((FEAT / f"player_match_stats_{SOURCE}.parquet").stat().st_mtime).filter(pl.col("replay").is_in(my_replays))
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
        d = X
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
                l = L[i, stj["factor"]] * stj["pole"]
                if abs(l) >= 0.4 and t not in team_tr:
                    mine[t] = l
        cand = [x for x in sig if x["t"] in mine and (x["pct"] - 50) * mine[x["t"]] > 0]
        rest = [x for x in sig if x["t"] not in team_tr and x not in cand]
        sig = (sorted(cand, key=lambda x: -abs(x["pct"] - 50)) + sorted(rest, key=lambda x: -abs(x["pct"] - 50)))[:4]
        f = (mean - np.array(S["mu"])) / np.array(S["sd"]) @ W
        pros = sorted(S["pros"], key=lambda p: float(np.linalg.norm(np.asarray(p["s"]) - f[0])))[:3]
        return {"n": n, "main": main, "second": second, "pct": pct.tolist(), "regular": regular,
                "signature": sig, "like": [{"name": p["name"], "n": p["n"]} for p in pros],
                "polyvalent": bool(pct[main] < 65)}

    styles = [{k: st[k] for k in ("name", "tagline", "trap", "factor", "pole", "retest")} for st in S["styles"]]
    return {"styles": styles, "me": profile(player), "peers": {pid: profile(pid) for pid in peers},
            "team": team, "n_ref": S["n_ref"], "n_rlcs": S["n_rlcs"]}


COMP_ADVICE = {
    "impact": ("Tes touches rapportent peu", "Avant chaque touche, choisis où la balle doit aller : un coin, un coéquipier, le cadre. Une touche « pour toucher » ne rapporte rien."),
    "boost": ("Tu tombes trop souvent à sec", "Prends un grand pad pendant chaque rotation retour, et garde 30 de boost avant de sauter sur un ballon."),
    "vitesse": ("Tu joues trop lentement", "Enchaîne les flips et garde la pleine vitesse entre deux actions : arriver vite, c'est choisir avant l'adversaire."),
    "collectif": ("Tes passes trouvent peu preneur", "Avant de centrer, vérifie qu'un coéquipier suit ; le receveur annonce « je suis là »."),
    "duels": ("Tu perds tes 50/50", "Arrive avec du boost et saute un peu plus tôt : un 50/50 se gagne sur l'élan et le contact franc."),
    "placement": ("Ton placement s'écarte de celui d'un pro", "En 2e homme, reste à hauteur du ballon côté opposé ; en 3e, centré, devant ton but."),
    "fiabilite": ("Tu rates des ballons", "Ralentis avant les touches qui comptent : mieux vaut une touche propre qu'une frappe forte ratée."),
}
TECH_ADVICE = {
    "t_speed": "Ta vitesse moyenne est sous celle de tes lobbies : enchaîne les flips au sol et ne lâche pas l'accélérateur entre deux actions.",
    "t_sup": "Tu atteins rarement la pleine vitesse : boost en ligne droite jusqu'au supersonique, puis entretiens-la sans boost (le supersonique se garde).",
    "t_slow": "Tu passes beaucoup de temps lent : après chaque action, relance-toi immédiatement vers ta prochaine position.",
    "t_highair": "Tu montes peu en l'air : 10 minutes par jour de pack d'entraînement aérien suffisent à progresser vite.",
    "t_haer": "Tu joues peu de ballons hauts : travaille les aériens rapides (saut, flip-reset du saut, boost) en partie libre.",
    "t_aer": "Tu joues peu de ballons en l'air : vise les ballons à hauteur de voiture en sautant plutôt qu'en attendant qu'ils tombent.",
    "t_wall": "Tu joues peu les murs : les balles au mur sont des passes gratuites, va les chercher.",
    "t_awhiff": "Tu rates des aériens : sors plus tôt mais moins vite, et vise le centre de la balle plutôt que d'aller fort.",
    "t_beaten": "Tu arrives souvent second sur la balle : anticipe où elle va être plutôt que de la suivre.",
}


ART = {"Voltigeur": "du", "Forteresse": "de la", "Harceleur": "du", "Ancre": "de l'", "Fer de lance": "du",
       "Fusée": "de la", "Fiable": "du", "Tête brûlée": "de la", "Porteur": "du", "Meneur": "du"}


def advice_section(payload: dict) -> list[dict]:
    """Trois conseils : le levier qui coûte le plus de points d'indice, le retard technique le plus net face
    aux lobbies, et le piège de ton style."""
    out = []
    pf = payload.get("perf")
    if pf and pf.get("me"):
        w = {c["key"]: c["weight"] for c in pf["components"]}
        comps = pf["me"]["comps"]
        cost = sorted(((w[k] * (50 - v), k) for k, v in comps.items() if k in COMP_ADVICE and w.get(k, 0) > 0.02), reverse=True)
        if cost and cost[0][0] > 0:
            k = cost[0][1]; t, txt = COMP_ADVICE[k]
            out.append({"kind": "Indice", "title": t, "text": txt,
                        "why": f"C'est la composante qui te coûte le plus de points d'indice ({round(comps[k])}/100, poids {round(100 * w[k])} %)."})
    tech = payload.get("tech")
    if tech:
        gaps = []
        for r in tech["rows"]:
            if r["sens"] == 0 or r["lobby"] in (None, 0) or r["key"] not in TECH_ADVICE:
                continue
            rel = (r["me"] - r["lobby"]) / abs(r["lobby"]) * r["sens"]
            gaps.append((rel, r))
        gaps.sort(key=lambda x: x[0])
        if gaps and gaps[0][0] < -0.08:
            rel, r = gaps[0]
            out.append({"kind": "Technique", "title": f"{r['label']} : sous tes lobbies", "text": TECH_ADVICE[r["key"]],
                        "why": f"{round(abs(rel) * 100)} % {'de moins' if r['sens'] > 0 else 'de plus'} que les autres joueurs de tes parties."})
    st = payload.get("style")
    if st and st.get("me"):
        main = st["styles"][st["me"]["main"]]
        out.append({"kind": "Style", "title": f"Le piège {ART.get(main['name'], 'du')} {main['name']}".replace("de l' ", "de l'"), "text": main["trap"],
                    "why": f"Ton style principal ressort dans {st['me']['regular']} de tes {st['me']['n']} parties."})
    return out


def progress_section(payload: dict, last: int | None = None) -> dict | None:
    """Évolution sur les parties de la période (ou les `last` dernières) : indice, sous-notes, composantes et technique ;
    comparaison seconde moitié vs première moitié, intervalle 80 % par tirage des parties."""
    pf = payload.get("perf")
    if not pf or len(pf["matches"]) < 6:
        return None
    ms = pf["matches"][-last:] if last else pf["matches"]
    n = len(ms); h = n // 2
    rng = np.random.default_rng(0)
    series = {"index": ("Indice", [m["index"] for m in ms], 1)}
    if ms[0].get("prod") is not None:
        series["prod"] = ("Production", [m["prod"] for m in ms], 1)
        series["fond"] = ("Fondamentaux", [m["fond"] for m in ms], 1)
    labels = {c["key"]: c["label"] for c in pf["components"]}
    for k in labels:
        series["c_" + k] = (labels[k], [m["comps"][k] for m in ms], 1)
    dates = [m["date"] for m in ms]
    for r in (payload.get("tech") or {}).get("rows", []):
        if r["sens"] != 0 and len(r["matches"]) >= n and r["key"] != "t_speed":  # vitesse déjà comptée (composante)
            series["t_" + r["key"]] = (r["label"], r["matches"][-n:], r["sens"])
    changes = []
    for key, (label, vals, sens) in series.items():
        v = np.array([np.nan if x is None else x for x in vals], dtype=float)
        a, b = v[:h], v[h:]
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
        if len(a) < 3 or len(b) < 3:
            continue
        sd = np.nanstd(v) or 1.0
        d = (b.mean() - a.mean()) * sens
        boots = [(rng.choice(b, len(b)).mean() - rng.choice(a, len(a)).mean()) * sens for _ in range(1000)]
        lo, hi = np.percentile(boots, [10, 90])
        changes.append({"key": key, "label": label, "before": float(a.mean()), "after": float(b.mean()), "delta": float(d),
                        "effect": float(d / sd), "lo": float(lo), "hi": float(hi), "clear": bool(lo > 0 or hi < 0),
                        "unit": "/100" if not key.startswith("t_") else next(r["unit"] for r in payload["tech"]["rows"] if "t_" + r["key"] == key),
                        "headline": key in ("index", "prod", "fond")})
    idx = np.array([m["index"] for m in ms], dtype=float)
    roll = [float(np.mean(idx[max(0, i - 4):i + 1])) for i in range(n)]
    return {"n": n, "half": h, "dates": dates, "index": idx.tolist(), "roll5": roll,
            "won": [m["won"] for m in ms], "changes": changes}


def build(players: list[str], out: Path, since: str | None = None) -> Path:
    """Une page, un profil par joueur (le premier est affiché par défaut) ; chacun est comparé aux autres."""
    perso = pl.read_parquet(FEAT / f"player_match_stats_{SOURCE}.parquet")
    ids = []
    for q in players:
        d = perso.filter((pl.col("player_id") == q) | (pl.col("player_name").str.to_lowercase() == q.lower()))
        if d.is_empty():
            print(f"  joueur introuvable : {q}")
            continue
        ids.append(d["player_id"].mode()[0])
    profiles = {}
    for pid in ids:
        print(f"  profil {pid}")
        profiles[pid] = make_payload(pid, [o for o in ids if o != pid], since)
    data = {"default": ids[0], "order": ids, "profiles": profiles}
    html = (Path(__file__).parent / "dashboard_template.html").read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    html = html.replace(PLACEHOLDER, font_css(embed=True))      # polices intégrées : page autonome, sans réseau
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--player", default=config.PLAYER, required=not config.PLAYER, help="identifiant, ex. Steam:7656... (profil affiché par défaut)")
    ap.add_argument("--compare", nargs="*", default=config.COMPARE, help="autres profils, pseudos ou identifiants (ex. Pseudo1 Pseudo2)")
    ap.add_argument("--since", help="ne garder que les parties à partir de cette date (AAAA-MM-JJ)")
    ap.add_argument("--out", default=str(ROOT / "reports" / "tableau_de_bord.html"))
    a = ap.parse_args()
    print(f"→ {build([a.player, *a.compare], Path(a.out), a.since)}")


if __name__ == "__main__":
    main()
