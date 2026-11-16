"""Page « Les modèles » : ce que fait chaque modèle et ses scores de pertinence, de vérité, d'efficacité et de fiabilité.

Lit les rapports des modèles (data/models/*.json) et quelques tables dérivées, pour rester à jour.

    content(ctx, sources)   contenu de la page, en données (servi par l'API : GET /api/modeles, affiché par la
                            page Vue /modeles)

Les textes peuvent contenir un peu de HTML fixe, écrit ici (<b>) : jamais de donnée venant d'un joueur.
Une fiche dont les données manquent (rapport ou table absents) est omise et citée dans « absents ».
"""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import polars as pl

from rlpi.context import DataContext, resolve

# Mesures du modèle de placement (journal du 12/11/2026, validation hors échantillon sur RLCS)
PLACEMENT = {"err_model_m": 17.3, "err_naive_m": 34.1, "n_positions": "2,7 millions"}


def fr(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",").replace("-", "−")


def pc(x: float, d: int = 0) -> str:
    return f"{100 * x:.{d}f}".replace(".", ",") + " %"


def goal_detection(ctx: DataContext, sources: tuple[str, ...]) -> dict:
    ok = tot = 0
    for src in sources:
        for mp in ctx.frames(src).glob("*.meta.json"):
            m = json.loads(mp.read_text(encoding="utf-8"))
            tot += 1
            ok += len(m["goals"]) == m["n_header_goals"]
    return {"ok": ok, "tot": tot}


def perf_vs_ingame(ctx: DataContext) -> dict:
    p = pl.read_parquet(ctx.feature("perf", "ssl"))
    s = pl.read_parquet(ctx.feature("player_match_stats", "ssl")).with_columns(
        pl.col("replay_file").str.replace(r"\.replay$", "").str.replace(r"^.*[\\/]", "").alias("replay"))
    d = p.join(s.select("replay", "player_id", "core.score"), on=["replay", "player_id"])
    rho = d.select(pl.corr("index", "core.score", method="spearman")).item()  # corrélation des rangs (Spearman)
    return {"rho": float(rho), "n": d.height}


def card(title: str, role: str, where: str, how: list[str], scores: list[tuple], verdict: tuple, limits: list[str],
         anchor: str) -> dict:
    """scores : (axe, valeur, référence, lecture, niveau 'ok'|'mid'|'bad')"""
    return {"title": title, "anchor": anchor, "role": role, "where": where, "how": how,
            "scores": [dict(zip(("axe", "valeur", "reference", "lecture", "niveau"), s)) for s in scores],
            "verdict": {"label": verdict[0], "niveau": verdict[1]}, "limits": limits}


def _report(ctx: DataContext, name: str, absent: list[str]) -> dict | None:
    f = ctx.models / name
    if not f.exists():
        absent.append(f"models/{name}")
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def content(ctx: DataContext | None = None, sources: tuple[str, ...] = ("rlcs", "ssl")) -> dict:
    """Contenu de la page. `sources` : parties dont on vérifie la détection des buts (images par image)."""
    ctx = resolve(ctx)
    absent: list[str] = []
    v = _report(ctx, "value_h5_report.json", absent)
    q = _report(ctx, "q_touch_report.json", absent)
    p = _report(ctx, "perf_report.json", absent)
    gd = goal_detection(ctx, sources)
    try:
        pv = perf_vs_ingame(ctx)
    except (FileNotFoundError, OSError):
        absent.append("features/perf_ssl.parquet")
        pv = None

    def count(stem: str, f) -> int:
        return sum(f(pl.read_parquet(x)) for s in ("rlcs", "ssl") if (x := ctx.feature(stem, s)).exists())

    n_def = count("defense", lambda d: d.height)
    n_ko = count("kickoffs", lambda d: d.height // 2)
    syn = ctx.feature("synergy", "ssl")
    n_syn = pl.read_parquet(syn)["replay"].n_unique() if syn.exists() else 0
    cards = []
    summary = []
    if gd["tot"]:
        cards.append(card(
        "Lecture des replays", "Transforme chaque replay en positions, vitesses, boost et événements (touches, 50/50, ratés, passes, démos), dix fois par seconde. Tout le reste en dépend.",
        "partout.", [
            "Parseur <b>subtr-actor 1.5.1</b> : positions et orientation des 6 voitures et de la balle, boost, démolitions.",
            "Détection des buts refaite par nos soins : la balle franchit la ligne <b>et</b> le jeu s'arrête dans les 1,5 s (les codes d'état du jeu changent selon les versions).",
            "Événements (50/50, ratés, passes) : détecteurs de subtr-actor, non modifiés."],
        [("Vérité", f"{gd['ok']} / {gd['tot']}", "buts détectés = score officiel du replay", f"{pc(gd['ok'] / gd['tot'], 1)} des replays exacts ; les autres sont écartés des calculs.", "ok"),
         ("Vérité", "≈ 2 m", "distance médiane voiture-balle au moment d'une touche", "Cohérent avec la taille d'une voiture : les touches sont bien attribuées.", "ok")],
        ("Solide", "ok"),
        ["Les voitures ne sont mises à jour qu'environ 15 fois par seconde dans un replay : les positions entre deux mises à jour sont reconstruites.",
         "Les détecteurs d'événements de subtr-actor (ratés, 50/50, passes, kickoffs) n'ont pas été vérifiés à l'œil un par un : leur définition est documentée dans « Comment c'est calculé »."],
        "lecture"))
    if v is not None:
        cal = v["calibration"]
        cal_err = float(np.average([abs(c["predit"] - c["observe"]) for c in cal], weights=[c["n"] for c in cal]))
        cards.append(card(
        "Valeur de la situation", "À chaque instant, la chance que ton équipe marque dans les 5 s moins celle que l'adversaire marque. C'est la brique de base : elle sert à juger les touches, l'impact, les kickoffs, la défense et la synergie.",
        "Ce match › Le déroulé ; indirectement dans l'indice, les touches, la synergie.", [
            f"<b>{v['n_matches']} matchs RLCS</b>, une image tous les 0,2 s, soit {v['n_rows']:,} situations".replace(",", " ") + " vues par chacune des deux équipes.",
            "99 informations par situation : balle (position, vitesse, trajectoire vers chaque but), les 6 voitures (position, vitesse, boost, démolie, face à la balle), temps restant, écart au score.",
            "Algorithme <b>LightGBM</b> (arbres de décision boostés). Test sur des matchs entiers mis de côté, jamais vus à l'apprentissage."],
        [("Vérité", f"AUC {fr(v['auc'])}", "0,5 = hasard · 1 = parfait", f"Sur {v['n_test_matches']} matchs jamais vus, il classe correctement une situation dangereuse avant une situation calme {pc(v['auc'])} du temps.", "ok"),
         ("Vérité", f"± {fr(100 * cal_err, 1)} pt", "écart moyen entre chance annoncée et fréquence observée", "Bien calibré : quand il annonce 30 %, il y a bien ≈ 30 % de buts.", "ok"),
         ("Efficacité", f"−{round(100 * (1 - v['logloss'] / v['logloss_base']))} %", "erreur (log-loss) vs « toujours le taux moyen »", f"Log-loss {fr(v['logloss'], 3)} contre {fr(v['logloss_base'], 3)} sans modèle.", "ok"),
         ("Pertinence", "× 1,5", "buts en classé vs prévu par le modèle pro", "En classé, les défenses encaissent plus : le modèle sous-estime le danger réel dans tes parties. Les notes « face aux lobbies » corrigent en comparant aux joueurs de la même partie.", "mid")],
        ("Solide", "ok"),
        ["Appris sur des pros : les chances qu'il annonce sont celles d'une défense de pro.", "Ne voit pas au-delà de 5 s : une construction lente n'est créditée qu'au moment où elle devient dangereuse.", "Ne connaît pas les joueurs : même situation = même valeur, quel que soit le niveau."],
        "valeur"))
    if p is not None:
        sh = p.get("split_half", {})
        cards.append(card(
        "Placement hors ballon", "Où un pro se placerait, en 2e ou 3e homme, dans la même situation. Ton écart à cette position donne la note de placement.",
        "Ma forme (tuile placement), Mon jeu, composante de l'indice.", [
            f"<b>{PLACEMENT['n_positions']} positions</b> de 2e et 3e hommes en RLCS.",
            "Deux modèles LightGBM (x et y) prédisent la position à partir de la balle, des 5 autres voitures et du temps.",
            "Note = centile de ton écart parmi les écarts des pros (100 = plus proche que tous les pros)."],
        [("Vérité", f"{fr(PLACEMENT['err_model_m'], 1)} m", "écart médian d'un pro à la position prédite (hors échantillon)", "Les pros eux-mêmes sont à ≈ 17 m de la prédiction : le placement « idéal » n'est pas un point unique.", "mid"),
         ("Efficacité", f"−{round(100 * (1 - PLACEMENT['err_model_m'] / PLACEMENT['err_naive_m']))} %", f"vs position moyenne sans modèle ({fr(PLACEMENT['err_naive_m'], 1)} m)", "Le modèle divise l'erreur par deux.", "ok"),
         ("Fiabilité", fr(sh.get("placement", float("nan"))), "moitiés d'un même match (SSL)", "Assez stable dans un match : c'est une habitude de jeu.", "mid"),
         ("Pertinence", "faible", "lien avec la victoire en SSL / RLCS", "À ce niveau, un placement plus « pro » ne sépare pas les gagnants des perdants : poids presque nul dans l'indice.", "bad")],
        ("Correct", "mid"),
        ["Mesure la ressemblance à un pro, pas la qualité d'une décision : une bonne rotation non conventionnelle est pénalisée.", "Ne note que le 2e et le 3e homme."],
        "placement"))
    if q is not None:
        cards.append(card(
        "Choix à la touche", "Pour chaque touche, quelle action un pro aurait tendance à jouer (tir, passe, dégagement…) et combien chaque option aurait rapporté. Ton « regret » = meilleure option réaliste − option jouée.",
        "Mon jeu › Tous les indicateurs (choix à la touche, expérimental).", [
            f"<b>{q['n']:,} touches</b> RLCS ({q['n_matches']} matchs), action définie par la direction donnée à la balle.".replace(",", " "),
            "Un modèle prédit l'action jouée par un pro (policy), un autre la valeur obtenue selon l'action (Q). Validation croisée par matchs.",
            "Options « réalistes » : celles qu'un pro joue au moins 10 % du temps dans cette situation."],
        [("Vérité", pc(q["policy_acc"]), "action du pro devinée · 36 % en devinant toujours la plus fréquente", "Devine assez bien ce qu'un pro ferait.", "mid"),
         ("Efficacité", f"R² {fr(q['r2_oof'])}", f"vs {fr(q['r2_action_mean'])} avec la seule moyenne par action", "Explique un quart de ce que rapporte une touche : mieux que rien, loin d'être précis.", "mid"),
         ("Pertinence", "biaisée", "tir toujours « meilleur », jeu arrière toujours « pire »", "La valeur à 5 s récompense le danger immédiat, pas la conservation du ballon.", "bad")],
        ("Expérimental", "bad"),
        ["À ne pas utiliser pour juger une décision précise.", "Ne voit pas les feintes ni les intentions de passe non abouties."],
        "choix"))
    if p is not None and pv is not None:
        rt, sh = p["retest"], p.get("split_half", {})
        w = p["weights"]
        wtxt = ", ".join(f"{k} {round(100 * x)} %" for k, x in sorted(w.items(), key=lambda kv: -kv[1]) if x >= .005)
        imp_need = rt["prod"]["matches_for_08"]
        cards.append(card(
        "Indice de performance (v2)", "Une note sur 100 par match : « as-tu bien joué ? », face aux performances de joueurs SSL. Avec deux sous-notes : Production (ce que tes touches ont produit) et Fondamentaux (boost, passes, vitesse, 50/50, placement, ratés).",
        "Ma forme, Ce match, Mon trio.", [
            f"7 mesures par match, comparées à {p['n_ref_player_matches']} performances SSL ({p['n_ref_matches']} parties où les 6 joueurs sont SSL).",
            f"Poids appris sur ce qui fait gagner en SSL (régression logistique, poids négatifs mis à 0) : {wtxt}.",
            "<b>Version 2 (14/11/2026)</b> : une touche qui marque est créditée de la valeur que le modèle donnait au tir juste avant la ligne (≈ 0,75), plus d'un +1 automatique. En v1, un tiers de l'impact venait des seuls buts.",
            "Note = centile parmi les performances SSL (50 = SSL médian dans une partie SSL)."],
        [("Pertinence", pc(p["rlcs_team_acc"]), f"équipe au meilleur indice moyen = gagnante, {p['rlcs_n_matches']} matchs RLCS jamais vus", f"Validation croisée SSL : {pc(p['team_acc_oof'])} · tes parties : {pc(p['perso_team_acc'])} ({p['perso_n_matches']}). Production seule : {pc(p['rlcs_team_acc_prod'])} · fondamentaux seuls : {pc(p['rlcs_team_acc_fond'])}.", "ok"),
         ("Pertinence", f"ρ {fr(pv['rho'])}", "corrélation avec le score affiché en jeu (SSL)", "Lié au score du jeu mais différent : l'indice compte aussi le boost, la vitesse et les passes, et retire des points quand une touche dégrade la situation.", "mid"),
         ("Fiabilité", fr(sh.get("index", float("nan"))), "accord entre les deux moitiés d'un même match (SSL) · 0,7 = bon", "Une note de match est surtout le reflet de quelques grosses touches : elle raconte ce qui s'est passé, elle ne mesure pas un niveau.", "bad"),
         ("Fiabilité", f"{rt['index']['matches_for_08']} parties", "pour une moyenne fiable (0,8), test-retest sur les pros RLCS", f"Fondamentaux : {rt['fond']['matches_for_08']} parties · production : {imp_need}. Juge ta progression sur des moyennes, pas sur un match.", "mid")],
        ("Correct en moyenne, volatile par match", "mid"),
        ["Mesure la performance relative aux joueurs SSL, pas ton niveau : en classé, l'impact est plus facile à obtenir.",
         "Les poids reflètent ce qui fait gagner en SSL, pas forcément ce qui fait progresser.",
         "Fiabilité mesurée chez les pros RLCS, très homogènes : entre joueurs de niveaux différents, elle est plus haute."],
        "indice"))
    analyses = [
        {"analyse": "Défense seul : reculer ou rush", "donnees": f"{n_def:,} situations RLCS et SSL".replace(",", " "),
         "credible": "Comparaison à danger égal (pondération par score de propension), intervalles par tirage des matchs.",
         "limite": "Observationnel : on ne voit pas tout ce qui fait choisir un joueur."},
        {"analyse": "Kickoffs : où part la balle", "donnees": f"{n_ko:,} kickoffs RLCS et SSL".replace(",", " "),
         "credible": "Mesure ce qui suit (possession, valeur, buts), pas seulement le duel.",
         "limite": "Zones à seuils fixes ; type de kickoff pas encore distingué."},
        {"analyse": "Synergie entre coéquipiers", "donnees": f"tes parties vs {n_syn} parties SSL",
         "credible": "Interactions fréquentes (touches, positions), intervalles à 80 %.",
         "limite": "Peu de parties par paire ; niveau des adversaires non neutralisé."},
    ]
    pending = [
        "<b>Validation humaine</b> : aucun modèle n'a encore été comparé à ton jugement. La page « Juger des actions » (swipe) servira à ça : quand tu jugeras une action « bien » et le modèle « mal », on saura où il se trompe.",
        "<b>Gestes techniques</b> (resets, double taps, air dribbles) : détecteurs disponibles mais pas vérifiés, donc non affichés.",
        "<b>Niveau</b> : aucune note ne dit « tu as le niveau de tel rang ». Il faudrait des replays de chaque rang.",
    ]
    if gd["tot"]:
        summary.append(("Lecture des replays", "lecture", "Solide", "ok", f"{pc(gd['ok'] / gd['tot'], 1)} des buts exacts"))
    if v is not None:
        summary.append(("Valeur de la situation", "valeur", "Solide", "ok", f"AUC {fr(v['auc'])} sur matchs jamais vus"))
    if p is not None:
        summary.append(("Placement hors ballon", "placement", "Correct", "mid", "erreur divisée par 2 · lien faible avec la victoire"))
    if q is not None:
        summary.append(("Choix à la touche", "choix", "Expérimental", "bad", f"R² {fr(q['r2_oof'])}"))
    if p is not None and pv is not None:
        summary.append(("Indice de performance", "indice", "Correct en moyenne", "mid", f"{pc(p['rlcs_team_acc'])} des matchs RLCS · fiable à partir de {p['retest']['index']['matches_for_08']} parties"))
    return {
        "resume": [dict(zip(("titre", "ancre", "verdict", "niveau", "chiffre"), r)) for r in summary],
        "fiches": cards,
        "analyses": analyses,
        "a_faire": pending,
        "absents": absent,
        "genere": datetime.now().strftime("%d/%m/%Y %H:%M"),
    }
