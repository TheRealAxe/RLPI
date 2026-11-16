"""Indicateurs par joueur et par partie (stats subtr-actor) : critères RLPI comparés aux références, mesures
techniques, répartitions du temps (compositions).

Par partie (worker) : `metrics()` et `tech_metrics()` donnent une valeur par joueur ; les colonnes brutes des
compositions sont gardées telles quelles (sommes). Références (SSL, RLCS) : calculées une fois (rlpi.dashboard.reference).
"""

from __future__ import annotations

import numpy as np
import polars as pl

from rlpi.dashboard.common import UU_TO_KMH, as_array, col, percentile


def metrics(df: pl.DataFrame) -> pl.DataFrame:
    """Une ligne par joueur et par match → indicateurs normalisés (par 5 min ou en %)."""
    t = pl.col("boost.tracked_time")
    tp = pl.col("positioning.tracked_time")
    tr = pl.col("rotation.active_game_time")
    per5 = lambda e: e / tp * 300  # noqa: E731
    pct = lambda e, base: e / base * 100  # noqa: E731
    c = lambda n: col(df, n)  # noqa: E731
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

# Références disponibles : (fichier, libellé, nb minimal de matchs par joueur)
REFS = {
    "rlcs": ("player_match_stats_rlcs.parquet", "RLCS", 2),
    "ssl": ("player_match_stats_ssl.parquet", "SSL", 1),
}


def compare_reference(ref_df: pl.DataFrame, min_matches: int) -> dict:
    """Partie fixe de la comparaison à une référence : moyenne de chaque joueur de référence (≥ min_matches
    parties), dans l'ordre de la table. `ref_df` : sortie de metrics()."""
    agg = (
        ref_df.filter(~pl.col("is_bot"))
        .group_by("player_id", maintain_order=True)
        .agg(pl.col("player_name").last(), pl.len().alias("n"), *[pl.col(k).mean() for k in KEYS])
        .filter(pl.col("n") >= min_matches)
    )
    return {
        "players": {c: agg[c].to_list() for c in ["player_id", "player_name", *KEYS]},
        "n_ref_matches": ref_df["replay_file"].n_unique(),
        "ref_period": f"{ref_df['date'].min()[:7]} → {ref_df['date'].max()[:7]}",  # type: ignore
    }


def compare(me: pl.DataFrame, ref: dict, player: str, peers: dict | None = None) -> dict:
    """Centiles de `me` (et des joueurs comparés `peers` : {id: DataFrame}) face aux moyennes des joueurs de la
    référence `ref` (compare_reference), le joueur lui-même exclu."""
    peers = peers or {}
    pl_ = ref["players"]
    keep = [i for i, pid in enumerate(pl_["player_id"]) if pid != player]
    names_all = [pl_["player_name"][i] for i in keep]
    my_mean = me.select([pl.col(k).mean() for k in KEYS]).row(0, named=True)
    peer_mean = {pid: d.select([pl.col(k).mean() for k in KEYS]).row(0, named=True) for pid, d in peers.items()}
    rows = []
    for key, label, unit, cat, sens in METRICS:
        col_ = [pl_[key][i] for i in keep]
        ref_v = [r for r in col_ if r is not None]
        names = [nm for r, nm in zip(col_, names_all) if r is not None]
        arr = as_array(ref_v)
        v = my_mean[key]
        p = percentile(v, arr)

        def note(q, sens=sens):
            return (q if sens > 0 else 100 - q) if (q is not None and sens != 0) else None

        pv = {
            pid: {"value": pm[key], "pct": percentile(pm[key], arr), "note": note(percentile(pm[key], arr))}
            for pid, pm in peer_mean.items()
        }
        rows.append(
            {
                "peers": pv,
                "key": key,
                "label": label,
                "unit": unit,
                "cat": cat,
                "sens": sens,
                "value": v,
                "pct": p,
                "note": (p if sens > 0 else 100 - p) if (p is not None and sens != 0) else None,
                "ref": [{"v": r, "n": nm} for r, nm in zip(ref_v, names)],
                "ref_med": float(pl.Series(ref_v).median()) if ref_v else None,  # type: ignore[arg-type]
                "matches": [
                    {"d": d, "v": x, "w": w, "s": f"{g}-{o}"}
                    for d, x, w, g, o in me.select("date", key, "won", "team_goals", "opp_goals").iter_rows()
                ],
            }
        )
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
        "radar": [
            {"cat": c, "note": sum(v) / len(v), "n": len(v), "peers": {pid: peer_radar[pid].get(c) for pid in peers}}
            for c, v in cats.items()
        ],
        "n_ref_players": len(keep),
        "n_ref_matches": ref["n_ref_matches"],
        "ref_period": ref["ref_period"],
    }


# ------------------------------------------------------------------------------------------------ technique
# Mesures techniques (clé, libellé, unité, sens, définition) — calculées par joueur et par match
TECH = [
    ("t_speed", "Vitesse moyenne", "km/h", +1, "Vitesse moyenne de la voiture sur le temps suivi."),
    (
        "t_sup",
        "Temps supersonique",
        "% du temps",
        +1,
        "Temps au-dessus de 2 200 uu/s (≈ 79 km/h, seuil du jeu) ÷ temps suivi.",
    ),
    ("t_slow", "Temps lent", "% du temps", -1, "Temps sous le seuil « lent » du détecteur subtr-actor ÷ temps suivi."),
    (
        "t_highair",
        "Temps en l'air (haut)",
        "% du temps",
        +1,
        "Temps au-dessus du seuil « haut » de subtr-actor ÷ temps suivi : jeu aérien engagé.",
    ),
    (
        "t_haer",
        "Touches aériennes hautes",
        "/ 5 min",
        +1,
        "Touches de balle classées « aérien haut » par subtr-actor, par 5 minutes de jeu.",
    ),
    (
        "t_aer",
        "Touches aériennes (toutes)",
        "/ 5 min",
        +1,
        "Toutes les touches de balle en l'air (bas et haut), par 5 minutes de jeu.",
    ),
    ("t_wall", "Touches au mur", "/ 5 min", +1, "Touches de balle faites depuis un mur, par 5 minutes de jeu."),
    (
        "t_awhiff",
        "Aériens ratés",
        "/ 5 min",
        -1,
        "Whiffs aériens de subtr-actor, par 5 minutes : approche rapide et orientée vers la balle, passage tout près (en général à moins de 2 m) sans contact, sans qu'un adversaire l'ait touchée avant. Non vérifié à l'œil.",
    ),
    (
        "t_beaten",
        "Battu sur la balle",
        "/ 5 min",
        -1,
        "Fois où un adversaire touche la balle juste avant toi alors que tu y allais (détecteur subtr-actor), par 5 minutes.",
    ),
]
TECH_KEYS = [t[0] for t in TECH]


def tech_metrics(df: pl.DataFrame) -> pl.DataFrame:
    t = pl.col("positioning.tracked_time")
    mv = pl.col("movement.tracked_time")
    c = lambda n: col(df, n)  # noqa: E731
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


def tech_reference(ssl: pl.DataFrame, rl: pl.DataFrame) -> dict:
    """Partie fixe : valeurs SSL par joueur-match (pour le centile), médianes et quantiles SSL et RLCS.
    `ssl`, `rl` : sorties de tech_metrics(), sans les bots."""
    rows = {}
    for k in TECH_KEYS:
        s = ssl[k].drop_nulls().to_numpy()
        rows[k] = {
            "ssl_values": s.tolist(),
            "ssl": float(np.median(s)),
            "rlcs": float(rl[k].median()),  # type: ignore[arg-type]
            "ssl_q": [float(np.percentile(s, q)) for q in (10, 25, 75, 90)],
        }
    return {"rows": rows, "n_ssl": ssl.height, "n_rlcs": rl.height}


def tech_section(ref: dict, me: pl.DataFrame, peers: dict[str, pl.DataFrame], lobby: pl.DataFrame) -> dict:
    """Mesures techniques : toi, coéquipiers, tes lobbies (GC), SSL et RLCS (médianes par joueur-match).
    `me`, `peers`, `lobby` contiennent déjà les colonnes de tech_metrics()."""
    rows = []
    for k, label, unit, sens, d in TECH:
        r = ref["rows"][k]
        s = np.asarray(r["ssl_values"], dtype=float)
        v = float(me[k].mean())  # type: ignore[arg-type]
        rows.append(
            {
                "key": k,
                "label": label,
                "unit": unit,
                "sens": sens,
                "def": d,
                "me": v,
                "pct_ssl": float(100 * ((s < v).mean() + 0.5 * (s == v).mean())),
                "peers": {pid: float(dd[k].mean()) for pid, dd in peers.items()},  # type: ignore[arg-type]
                "lobby": float(lobby[k].median()),  # type: ignore
                "ssl": r["ssl"],
                "rlcs": r["rlcs"],  # type: ignore[arg-type]
                "ssl_q": r["ssl_q"],
                "matches": [float(x) if x is not None else None for x in me[k].to_list()],
            }
        )
    return {"rows": rows, "n_lobby": lobby.height, "n_ssl": ref["n_ssl"], "n_rlcs": ref["n_rlcs"]}


# ------------------------------------------------------------------------------------------- compositions
# Répartitions du temps (chaque groupe somme à 100 %) : (clé, titre, base, [(colonne, libellé)])
COMPOSITIONS = [
    (
        "role",
        "Rôle dans la rotation",
        "rotation.active_game_time",
        [
            ("rotation.time_first_man", "1er homme"),
            ("rotation.time_second_man", "2e homme"),
            ("rotation.time_third_man", "3e homme"),
            ("rotation.time_ambiguous_role", "indéterminé"),
        ],
    ),
    (
        "third",
        "Zone du terrain",
        "positioning.tracked_time",
        [
            ("positioning.time_defensive_third", "tiers défensif"),
            ("positioning.time_neutral_third", "tiers central"),
            ("positioning.time_offensive_third", "tiers offensif"),
        ],
    ),
    (
        "ballpos",
        "Par rapport à la balle",
        "positioning.tracked_time",
        [
            ("positioning.time_behind_ball", "derrière la balle"),
            ("positioning.time_level_with_ball", "à hauteur"),
            ("positioning.time_in_front_of_ball", "devant la balle"),
        ],
    ),
    (
        "boost",
        "Réserve de boost",
        "boost.tracked_time",
        [
            ("boost.time_boost_0_25", "0–25"),
            ("boost.time_boost_25_50", "25–50"),
            ("boost.time_boost_50_75", "50–75"),
            ("boost.time_boost_75_100", "75–100"),
        ],
    ),
    (
        "height",
        "Au sol ou en l'air",
        "movement.tracked_time",
        [
            ("movement.time_on_ground", "au sol"),
            ("movement.time_low_air", "en l'air (bas)"),
            ("movement.time_high_air", "en l'air (haut)"),
        ],
    ),
    (
        "speed",
        "Vitesse",
        "movement.tracked_time",
        [
            ("movement.time_slow_speed", "lent"),
            ("movement.time_boost_speed", "rapide"),
            ("movement.time_supersonic_speed", "supersonique"),
        ],
    ),
    (
        "touch",
        "Type de touche",
        "touch.touch_count",
        [
            ("touch.control_touch_count", "contrôle"),
            ("touch.medium_hit_count", "frappe moyenne"),
            ("touch.hard_hit_count", "frappe forte"),
        ],
    ),
]
COMPO_COLUMNS = sorted({c for _, _, base, parts in COMPOSITIONS for c in [base, *(p for p, _ in parts)]})


def composition_parts(df: pl.DataFrame) -> dict:
    """Parts de temps cumulées (somme des temps / somme des bases) d'un groupe de lignes joueur-partie :
    {"n": lignes, "parts": {clé de composition: [parts] ou None si la base manque}}."""
    out: dict = {}
    for key, _, base, parts in COMPOSITIONS:
        if df.is_empty() or base not in df.columns:
            out[key] = None
            continue
        tot = df[base].sum()
        out[key] = [float(df[c].sum() / tot) if tot and c in df.columns else None for c, _ in parts]  # type: ignore
    return {"n": df.height, "parts": out}


def compositions(groups: list[tuple[str, str, dict]]) -> list[dict]:
    """groups : (clé, libellé, composition_parts(...)) — les groupes de référence sont calculés une fois."""
    out = []
    for key, title, _, parts in COMPOSITIONS:
        rows = [
            {"key": gkey, "label": label, "n": g["n"], "parts": g["parts"][key]}
            for gkey, label, g in groups
            if g["parts"][key] is not None
        ]
        out.append({"key": key, "title": title, "labels": [lab for _, lab in parts], "rows": rows})
    return out
