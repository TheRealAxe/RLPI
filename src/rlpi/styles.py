"""Styles de jeu : des familles de comportements qui vont ensemble chez les joueurs SSL et RLCS.

1. Traits par joueur-match (positionnement, jeu aérien, agressivité, tirs, défense, boost, vitesse, valeur des touches).
2. Moyenne par joueur (RLCS ≥ 10 matchs, SSL ≥ 3 matchs), centrée-réduite.
3. Analyse factorielle (ACP + rotation varimax) : chaque facteur = un groupe de traits qui varient ensemble = un style.
4. Score d'un joueur sur chaque style = combinaison de ses traits, exprimée en centile parmi les joueurs de référence.

Usage : python -m rlpi.styles explore   (affiche les facteurs)   ·   python -m rlpi.styles fit  → data/models/styles.json
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import polars as pl

from rlpi import config
from rlpi.config import FEATURES, FRAMES, MODELS

ME = config.PLAYER


def traits(source: str) -> pl.DataFrame:
    """Traits de style par joueur-match (indépendants du résultat autant que possible)."""
    from rlpi.dashboard import metrics
    from rlpi.perf import touch_xv

    st = metrics(pl.read_parquet(FEATURES / f"player_match_stats_{source}.parquet")).filter(~pl.col("is_bot"))
    st = st.with_columns(pl.col("replay_file").str.replace(r"\.replay$", "").str.replace(r"^.*[\\/]", "").alias("replay"))
    M = pl.col("movement.tracked_time") / 300
    st = st.with_columns(
        arrets=pl.col("core.saves") / M,
        mur=pl.col("touch.wall_touch_count") / M,
        aerien_haut_t=pl.col("touch.high_aerial_touch_count") / M,
        controle=pl.col("touch.control_touch_count") / pl.col("touch.touch_count").clip(1) * 100,
        ombre=100 * pl.col("positioning.time_shadow_defense") / pl.col("positioning.tracked_time"),
        tiers_def=100 * pl.col("positioning.time_defensive_third") / pl.col("positioning.tracked_time"),
        possession=100 * pl.col("positioning.time_has_possession") / pl.col("positioning.tracked_time"),
    )
    play_s = {}
    for mp in (FRAMES / source).glob("*.meta.json"):
        m = json.loads(mp.read_text(encoding="utf-8")); play_s[m["replay"]] = m["n_play_frames"] / 10
    tv = touch_xv(source).with_columns(pl.col("replay").replace_strict(play_s, default=None).alias("s"))
    t = tv.group_by("replay", "player_id").agg(
        (pl.len() / pl.col("s").first() * 300).alias("touches"),
        (pl.col("height") == "high_air").mean().mul(100).alias("t_haut"),
        (pl.col("height") == "low_air").mean().mul(100).alias("t_bas_air"),
        (pl.col("ball_y") * pl.when(pl.col("team") == 0).then(1).otherwise(-1) > 1700).mean().mul(100).alias("t_off"),
        (pl.col("ball_y") * pl.when(pl.col("team") == 0).then(1).otherwise(-1) < -1700).mean().mul(100).alias("t_def"),
        (pl.col("action") == "pass").mean().mul(100).alias("t_passe"),
        (pl.col("action") == "clear").mean().mul(100).alias("t_degage"),
        (pl.col("action").is_null()).mean().mul(100).alias("t_conduite"),
        (pl.col("dv_xv") < -0.02).mean().mul(100).alias("t_pertes"),
    )
    d = st.join(t, on=["replay", "player_id"], how="inner")
    # Style = ce qui te distingue des joueurs de TA partie : chaque trait est centré sur la moyenne des 6 joueurs
    # du match. Sinon le niveau (classé vs pros) se confond avec le style (ex. en GC tout le monde joue plus haut).
    return d.with_columns([(pl.col(k) - pl.col(k).mean().over("replay")).alias(k) for k in TRAITS])


# Traits utilisés pour les styles (le résultat — buts, victoires — est exclu)
TRAITS = ["premier_homme", "troisieme_homme", "derriere_balle", "moitie_adverse", "ombre", "tiers_def",
          "air_haut", "t_haut", "t_bas_air", "aerien_haut_t", "mur", "controle", "t_conduite", "possession",
          "demos", "bumps", "ff_par5", "tirs", "arrets", "t_degage", "t_passe", "passes",
          "boost_moyen", "boost_petits", "boost_vole", "vitesse", "supersonique", "touches", "t_pertes", "ratees"]


def player_table(min_rlcs: int = 10, min_ssl: int = 3) -> tuple[pl.DataFrame, pl.DataFrame]:
    rows = []
    for src, mn in (("rlcs", min_rlcs), ("ssl", min_ssl)):
        d = traits(src)
        g = d.group_by("player_id").agg(pl.col("player_name").last(), pl.len().alias("n"), *[pl.col(k).mean() for k in TRAITS])
        rows.append(g.filter(pl.col("n") >= mn).with_columns(pl.lit(src).alias("source")))
    ref = pl.concat(rows).drop_nulls(TRAITS)
    return ref, pl.concat([traits("rlcs").with_columns(pl.lit("rlcs").alias("source")),
                           traits("ssl").with_columns(pl.lit("ssl").alias("source"))], how="diagonal_relaxed")


def varimax(L: np.ndarray, it: int = 100, tol: float = 1e-6) -> np.ndarray:
    p, k = L.shape
    R = np.eye(k); d = 0
    for _ in range(it):
        Lr = L @ R
        u, s, vt = np.linalg.svd(L.T @ (Lr ** 3 - Lr @ np.diag((Lr ** 2).sum(0)) / p))
        R = u @ vt
        if s.sum() < d * (1 + tol):
            break
        d = s.sum()
    return L @ R


def factors(ref: pl.DataFrame, k: int):
    X = ref.select(TRAITS).to_numpy().astype(float)
    mu, sd = X.mean(0), X.std(0)
    Z = (X - mu) / sd
    C = np.corrcoef(Z, rowvar=False)
    ev, V = np.linalg.eigh(C)
    o = np.argsort(ev)[::-1]
    ev, V = ev[o], V[:, o]
    L = V[:, :k] * np.sqrt(ev[:k])
    Lr = varimax(L)
    # scores (régression de Thurstone)
    W = np.linalg.solve(C, Lr)
    S = Z @ W
    # orienter chaque facteur pour que sa plus forte saturation soit positive
    sign = np.sign(Lr[np.abs(Lr).argmax(0), range(k)])
    return mu, sd, Lr * sign, W * sign, S * sign, ev


def explore(kmin: int = 5, kmax: int = 9) -> None:
    ref, _ = player_table()
    print(ref.height, "joueurs de référence :", ref.group_by("source").len().to_dicts())
    _, _, _, _, _, ev = factors(ref, 3)
    print("valeurs propres :", [round(float(e), 2) for e in ev[:12]])
    for k in range(kmin, kmax + 1):
        _, _, Lr, _, S, _ = factors(ref, k)
        print(f"\n===== {k} facteurs")
        for j in range(k):
            o = np.argsort(-np.abs(Lr[:, j]))[:6]
            top = ", ".join(f"{TRAITS[i]} {Lr[i, j]:+.2f}" for i in o)
            best = ref.with_columns(pl.Series("f", S[:, j])).filter(pl.col("source") == "rlcs").sort("f", descending=True).head(4)["player_name"].to_list()
            print(f"  F{j + 1}: {top}   | pros les plus marqués : {best}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["explore", "fit"])
    a = ap.parse_args()
    if a.cmd == "explore":
        explore()
    else:
        m = fit()
        print(f"{m['n_ref']} joueurs de référence ({m['n_rlcs']} pros RLCS), {len(m['styles'])} styles :")
        for st in m["styles"]:
            print(f"  {st['name']:<13} facteur {st['factor'] + 1} pôle {st['pole']:+d} · accord {st['match']:.2f} · stabilité (pairs/impairs) {st['retest']:.2f} · "
                  + ", ".join(f"{x['t']} {x['l']:+.2f}" for x in st["traits"]))


K = 7
# Styles = pôles des facteurs. Chaque style a une signature (traits attendus et leur sens) ; un pôle de facteur reçoit
# le style dont la signature colle le mieux à ses saturations (robuste à l'ordre et au signe des facteurs).
POLES = {
    "Voltigeur": ({"aerien_haut_t": 1, "t_haut": 1, "air_haut": 1}, "Joue en l'air, va chercher les ballons hauts et les garde.",
                  "Chaque sortie aérienne coûte du boost et peut laisser un trou derrière : sors quand la balle est vraiment jouable."),
    "Forteresse": ({"tiers_def": 1, "arrets": 1, "moitie_adverse": -1}, "Reste près de son but, ferme les angles, arrête beaucoup.",
                   "À rester bas, tu laisses tes coéquipiers seuls devant : remonte en soutien quand la balle est chez eux."),
    "Harceleur": ({"moitie_adverse": 1, "boost_vole": 1, "tiers_def": -1}, "Vit dans le camp adverse, presse et vole le boost.",
                  "Ta pression laisse ton but exposé : quand tu perds la balle, le retour doit être immédiat."),
    "Ancre": ({"troisieme_homme": 1, "premier_homme": -1}, "Joue en dernier homme, couvre et ramasse les ballons.",
              "En restant trop loin, tu touches peu la balle : prends ta place dans la rotation quand c'est ton tour."),
    "Fer de lance": ({"premier_homme": 1, "troisieme_homme": -1, "touches": 1}, "Toujours premier sur la balle, enchaîne les duels.",
                     "Être toujours premier, c'est aussi partir trop tôt : vérifie qu'un coéquipier couvre avant de sauter."),
    "Fusée": ({"supersonique": 1, "vitesse": 1}, "Joue vite, toujours lancé à pleine vitesse.",
              "La vitesse sans contrôle donne des touches ratées : ralentis avant les touches qui comptent."),
    "Fiable": ({"tirs": 1, "ratees": -1, "derriere_balle": 1, "boost_moyen": 1}, "Propre et efficace : rate peu, reste du bon côté, garde du boost et tire.",
               "La sécurité peut devenir de la frilosité : ose davantage quand l'occasion est franche."),
    "Tête brûlée": ({"ratees": 1, "derriere_balle": -1, "boost_moyen": -1}, "Tente beaucoup, quitte à rater, à perdre la balle et à finir sans boost.",
                    "Tu tentes beaucoup : garde ces prises de risque pour les moments où un coéquipier couvre."),
    "Porteur": ({"controle": 1, "t_pertes": 1, "t_passe": 1}, "Garde et contrôle la balle, cherche la passe, quitte à la perdre.",
                "La conduite de balle se perd contre un bon challenge : décide plus tôt entre tirer, passer ou garder."),
    "Meneur": ({"passes": 1, "possession": 1}, "Fait jouer les autres, construit par la passe.",
               "Une passe sans coéquipier prêt est une balle perdue : annonce et attends l'appel."),
}
TRAIT_FR = {  # (plus que la plupart des joueurs, moins que la plupart des joueurs)
    "premier_homme": ("tu es souvent le premier sur la balle", "tu laisses souvent les autres aller au ballon"),
    "troisieme_homme": ("tu restes souvent en dernier homme", "tu restes rarement en dernier homme"),
    "derriere_balle": ("tu restes du bon côté de la balle", "tu te retrouves souvent devant la balle"),
    "moitie_adverse": ("tu vis dans le camp adverse", "tu restes plutôt dans ta moitié"),
    "ombre": ("tu défends en reculant face à l'attaquant", "tu défends rarement en reculant"),
    "tiers_def": ("tu passes beaucoup de temps près de ton but", "tu quittes vite ton tiers défensif"),
    "air_haut": ("tu passes beaucoup de temps haut en l'air", "tu restes près du sol"),
    "t_haut": ("tu joues beaucoup de ballons hauts", "tu joues peu de ballons hauts"),
    "t_bas_air": ("tu frappes souvent en sautant", "tu frappes rarement en sautant"),
    "aerien_haut_t": ("tu vas chercher les ballons très hauts", "tu vas rarement chercher les ballons hauts"),
    "mur": ("tu joues beaucoup les murs", "tu joues peu les murs"),
    "controle": ("tu contrôles la balle plus que tu ne la frappes", "tu frappes plus que tu ne contrôles"),
    "t_conduite": ("tu conduis beaucoup la balle", "tu conduis peu la balle"),
    "possession": ("tu as souvent la balle", "tu as rarement la balle"),
    "demos": ("tu démolis beaucoup", "tu démolis peu"),
    "bumps": ("tu vas souvent au contact", "tu évites le contact"),
    "ff_par5": ("tu disputes beaucoup de 50/50", "tu évites les 50/50"),
    "tirs": ("tu tires beaucoup", "tu tires peu"),
    "arrets": ("tu fais beaucoup d'arrêts", "tu fais peu d'arrêts"),
    "t_degage": ("tu dégages beaucoup", "tu dégages peu"),
    "t_passe": ("tu cherches souvent la passe", "tu cherches rarement la passe"),
    "passes": ("tes passes trouvent souvent preneur", "tes passes trouvent rarement preneur"),
    "boost_moyen": ("tu gardes une bonne réserve de boost", "tu joues souvent avec peu de boost"),
    "boost_petits": ("tu vis sur les petits pads", "tu vas chercher les grands pads"),
    "boost_vole": ("tu voles le boost adverse", "tu voles peu de boost adverse"),
    "vitesse": ("tu joues vite", "tu joues lentement"),
    "supersonique": ("tu passes beaucoup de temps à pleine vitesse", "tu atteins rarement la pleine vitesse"),
    "touches": ("tu touches beaucoup la balle", "tu touches peu la balle"),
    "t_pertes": ("tu perds souvent la balle", "tu perds rarement la balle"),
    "ratees": ("tu rates souvent ta touche", "tu rates rarement ta touche"),
}


def _retest(rl: pl.DataFrame, mu, sd, W) -> list[float]:
    """Matchs pairs vs impairs d'un même pro RLCS : le score de style se répète-t-il ?"""
    d = rl.drop_nulls(TRAITS).sort("date").with_columns(pl.int_range(pl.len()).over("player_id").alias("k"),
                                                        pl.len().over("player_id").alias("n")).filter(pl.col("n") >= 10)
    halves = [d.filter(pl.col("k") % 2 == r).group_by("player_id").agg(*[pl.col(t).mean() for t in TRAITS]).sort("player_id") for r in (0, 1)]
    A = ((halves[0].select(TRAITS).to_numpy() - mu) / sd) @ W
    B = ((halves[1].select(TRAITS).to_numpy() - mu) / sd) @ W
    out = []
    for j in range(W.shape[1]):
        r = float(np.corrcoef(A[:, j], B[:, j])[0, 1])
        out.append(2 * r / (1 + r))
    return out


def fit() -> dict:
    ref, pm = player_table()
    mu, sd, Lr, W, S, ev = factors(ref, K)
    rel = _retest(pm.filter(pl.col("source") == "rlcs"), mu, sd, W)
    styles = []
    # Appariement pôle ↔ style : meilleur score de signature, chaque style et chaque pôle utilisés une fois
    cand = []
    for j in range(K):
        for pole in (+1, -1):
            load = Lr[:, j] * pole
            for name, (sig, _, _) in POLES.items():
                m = sum(sg * load[TRAITS.index(t)] for t, sg in sig.items()) / len(sig)
                cand.append((m, j, pole, name))
    used_pole, used_name = set(), set()
    for m, j, pole, name in sorted(cand, reverse=True):
        if m < 0.35 or (j, pole) in used_pole or name in used_name:
            continue
        used_pole.add((j, pole)); used_name.add(name)
        _, tag, trap = POLES[name]
        load = Lr[:, j] * pole
        o = [i for i in np.argsort(-np.abs(load)) if abs(load[i]) > 0.3][:6]
        styles.append({"name": name, "tagline": tag, "trap": trap, "factor": j, "pole": pole, "match": float(m),
                       "traits": [{"t": TRAITS[i], "l": float(load[i])} for i in o],
                       "ref_sorted": np.sort(S[:, j] * pole).round(4).tolist(), "retest": rel[j]})
    styles.sort(key=lambda st: (st["factor"], -st["pole"]))
    is_pro = (ref["source"] == "rlcs").to_numpy()
    pros = ref.filter(pl.col("source") == "rlcs")
    model = {"traits": TRAITS, "mu": mu.tolist(), "sd": sd.tolist(), "W": W.tolist(), "loadings": Lr.tolist(),
             "styles": styles, "n_ref": ref.height, "n_rlcs": pros.height,
             "pros": [{"name": n, "id": i, "n": int(c), "s": s.round(3).tolist()}
                      for n, i, c, s in zip(pros["player_name"], pros["player_id"], pros["n"], S[is_pro])],
             "trait_sorted": {t: np.sort(ref[t].to_numpy()).round(4).tolist() for t in TRAITS},
             "trait_fr": TRAIT_FR}
    (MODELS / "styles.json").write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    return model


if __name__ == "__main__":
    main()
