"""Page « Les modèles » : ce que fait chaque modèle et ses scores de pertinence, de vérité, d'efficacité et de fiabilité.

Lit les rapports des modèles (data/models/*.json) et quelques tables dérivées, pour rester à jour.
Styles repris du gabarit du tableau de bord (charte Plateau).

Usage : python -m rlpi.models_page  → reports/modeles.html
"""
from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path

import numpy as np
import polars as pl

from rlpi.config import FEATURES, FRAMES, MODELS, ROOT, SOURCE

TEMPLATE = Path(__file__).parent / "dashboard_template.html"
OUT = ROOT / "reports" / "modeles.html"

# Mesures du modèle de placement (journal du 12/11/2026, validation hors échantillon sur RLCS)
PLACEMENT = {"err_model_m": 17.3, "err_naive_m": 34.1, "n_positions": "2,7 millions"}


def fr(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace(".", ",").replace("-", "−")


def pc(x: float, d: int = 0) -> str:
    return f"{100 * x:.{d}f}".replace(".", ",") + " %"


def plateau_css() -> str:
    t = TEMPLATE.read_text(encoding="utf-8")
    a = t.index("/* ======================================================================\n   RLPI · Plateau")
    b = t.index("/* ======================================================================\n   Application")
    return t[a:b]


def goal_detection() -> dict:
    ok = tot = 0
    for src in ("rlcs", "ssl", SOURCE):
        for mp in (FRAMES / src).glob("*.meta.json"):
            m = json.loads(mp.read_text(encoding="utf-8"))
            tot += 1
            ok += len(m["goals"]) == m["n_header_goals"]
    return {"ok": ok, "tot": tot}


def perf_vs_ingame() -> dict:
    from scipy.stats import spearmanr
    p = pl.read_parquet(FEATURES / "perf_ssl.parquet")
    s = pl.read_parquet(FEATURES / "player_match_stats_ssl.parquet").with_columns(
        pl.col("replay_file").str.replace(r"\.replay$", "").str.replace(r"^.*[\\/]", "").alias("replay"))
    d = p.join(s.select("replay", "player_id", "core.score"), on=["replay", "player_id"])
    return {"rho": float(spearmanr(d["index"], d["core.score"])[0]), "n": d.height}


def card(title: str, role: str, where: str, how: list[str], scores: list[tuple], verdict: tuple, limits: list[str],
         anchor: str) -> str:
    """scores : (axe, valeur, référence, lecture, niveau 'ok'|'mid'|'bad')"""
    rows = "".join(
        f"<tr><th scope='row' class='pl-tag'>{escape(a)}</th><td class='pl-dx v {lvl}'>{v}</td>"
        f"<td class='pl-small'>{r}</td><td class='pl-small'>{lec}</td></tr>" for a, v, r, lec, lvl in scores)
    return f"""
<section class="model" id="{anchor}">
  <div class="mh"><h2 class="pl-dx pl-title">{escape(title)}</h2><span class="pl-cut pl-tag badge {verdict[1]}">{escape(verdict[0])}</span></div>
  <p class="pl-body read">{role}</p>
  <p class="pl-small pl-muted">Dans la page : {where}</p>
  <h3 class="pl-tag grph">Comment il est construit</h3>
  <ol class="pl-body">{''.join(f'<li>{x}</li>' for x in how)}</ol>
  <h3 class="pl-tag grph">Scores</h3>
  <div class="tw"><table class="sc"><thead><tr><th class="pl-tag">Axe</th><th class="pl-tag">Valeur</th><th class="pl-tag">Référence</th><th class="pl-tag">Ce que ça veut dire</th></tr></thead>
  <tbody>{rows}</tbody></table></div>
  <h3 class="pl-tag grph">Limites</h3>
  <ul class="pl-body">{''.join(f'<li>{x}</li>' for x in limits)}</ul>
</section>"""


def build() -> Path:
    v = json.loads((MODELS / "value_h5_report.json").read_text(encoding="utf-8"))
    q = json.loads((MODELS / "q_touch_report.json").read_text(encoding="utf-8"))
    p = json.loads((MODELS / "perf_report.json").read_text(encoding="utf-8"))
    gd = goal_detection()
    pv = perf_vs_ingame()
    sh = p.get("split_half", {})
    rt = p["retest"]
    cal = v["calibration"]
    cal_err = float(np.average([abs(c["predit"] - c["observe"]) for c in cal], weights=[c["n"] for c in cal]))
    n_def = sum(pl.read_parquet(FEATURES / f"defense_{s}.parquet").height for s in ("rlcs", "ssl") if (FEATURES / f"defense_{s}.parquet").exists())
    n_ko = sum(pl.read_parquet(FEATURES / f"kickoffs_{s}.parquet").height // 2 for s in ("rlcs", "ssl") if (FEATURES / f"kickoffs_{s}.parquet").exists())
    n_syn = pl.read_parquet(FEATURES / "synergy_ssl.parquet")["replay"].n_unique() if (FEATURES / "synergy_ssl.parquet").exists() else 0
    w = p["weights"]
    wtxt = ", ".join(f"{k} {round(100 * x)} %" for k, x in sorted(w.items(), key=lambda kv: -kv[1]) if x >= .005)

    cards = []
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
    imp_need = rt["prod"]["matches_for_08"]
    cards.append(card(
        "Indice de performance (v2)", "Une note sur 100 par match : « as-tu bien joué ? », face aux performances de joueurs SSL. Avec deux sous-notes : Production (ce que tes touches ont produit) et Fondamentaux (boost, passes, vitesse, 50/50, placement, ratés).",
        "Ma forme, Ce match, Mon trio.", [
            f"7 mesures par match, comparées à {p['n_ref_player_matches']} performances SSL ({p['n_ref_matches']} parties où les 6 joueurs sont SSL).",
            f"Poids appris sur ce qui fait gagner en SSL (régression logistique, poids négatifs mis à 0) : {wtxt}.",
            "<b>Version 2 (14/11/2026)</b> : une touche qui marque est créditée de la valeur que le modèle donnait au tir juste avant la ligne (≈ 0,75), plus d'un +1 automatique. En v1, un tiers de l'impact venait des seuls buts.",
            "Note = centile parmi les performances SSL (50 = SSL médian dans une partie SSL)."],
        [("Pertinence", pc(p["rlcs_team_acc"]), f"équipe au meilleur indice moyen = gagnante, {p['rlcs_n_matches']} matchs RLCS jamais vus", f"Validation croisée SSL : {pc(p['team_acc_oof'])} · tes parties : {pc(p.get('perso_team_acc', p.get('theo_team_acc')))} ({p.get('perso_n_matches', p.get('theo_n_matches'))}). Production seule : {pc(p['rlcs_team_acc_prod'])} · fondamentaux seuls : {pc(p['rlcs_team_acc_fond'])}.", "ok"),
         ("Pertinence", f"ρ {fr(pv['rho'])}", "corrélation avec le score affiché en jeu (SSL)", "Lié au score du jeu mais différent : l'indice compte aussi le boost, la vitesse et les passes, et retire des points quand une touche dégrade la situation.", "mid"),
         ("Fiabilité", fr(sh.get("index", float("nan"))), "accord entre les deux moitiés d'un même match (SSL) · 0,7 = bon", "Une note de match est surtout le reflet de quelques grosses touches : elle raconte ce qui s'est passé, elle ne mesure pas un niveau.", "bad"),
         ("Fiabilité", f"{rt['index']['matches_for_08']} parties", "pour une moyenne fiable (0,8), test-retest sur les pros RLCS", f"Fondamentaux : {rt['fond']['matches_for_08']} parties · production : {imp_need}. Juge ta progression sur des moyennes, pas sur un match.", "mid")],
        ("Correct en moyenne, volatile par match", "mid"),
        ["Mesure la performance relative aux joueurs SSL, pas ton niveau : en classé, l'impact est plus facile à obtenir.",
         "Les poids reflètent ce qui fait gagner en SSL, pas forcément ce qui fait progresser.",
         "Fiabilité mesurée chez les pros RLCS, très homogènes : entre joueurs de niveaux différents, elle est plus haute."],
        "indice"))
    analyses = f"""
<section class="model" id="analyses">
  <div class="mh"><h2 class="pl-dx pl-title">Analyses</h2><span class="pl-cut pl-tag badge mid">Descriptif</span></div>
  <p class="pl-body read">Ce ne sont pas des modèles entraînés mais des mesures construites sur la valeur de la situation, comparées aux pros. Elles décrivent ce qui se passe ; elles ne prouvent pas une cause.</p>
  <div class="tw"><table class="sc"><thead><tr><th class="pl-tag">Analyse</th><th class="pl-tag">Données</th><th class="pl-tag">Ce qui la rend crédible</th><th class="pl-tag">Ce qui la limite</th></tr></thead><tbody>
  <tr><th scope="row" class="pl-tag">Défense seul : reculer ou rush</th><td class="pl-small">{str(f'{n_def:,}').replace(',', ' ')} situations RLCS et SSL</td><td class="pl-small">Comparaison à danger égal (pondération par score de propension), intervalles par tirage des matchs.</td><td class="pl-small">Observationnel : on ne voit pas tout ce qui fait choisir un joueur.</td></tr>
  <tr><th scope="row" class="pl-tag">Kickoffs : où part la balle</th><td class="pl-small">{str(f'{n_ko:,}').replace(',', ' ')} kickoffs RLCS et SSL</td><td class="pl-small">Mesure ce qui suit (possession, valeur, buts), pas seulement le duel.</td><td class="pl-small">Zones à seuils fixes ; type de kickoff pas encore distingué.</td></tr>
  <tr><th scope="row" class="pl-tag">Synergie entre coéquipiers</th><td class="pl-small">tes parties vs {n_syn} parties SSL</td><td class="pl-small">Interactions fréquentes (touches, positions), intervalles à 80 %.</td><td class="pl-small">Peu de parties par paire ; niveau des adversaires non neutralisé.</td></tr>
  </tbody></table></div>
</section>"""
    pending = """
<section class="model" id="avenir">
  <div class="mh"><h2 class="pl-dx pl-title">Pas encore validé</h2><span class="pl-cut pl-tag badge bad">À faire</span></div>
  <ul class="pl-body">
    <li><b>Validation humaine</b> : aucun modèle n'a encore été comparé à ton jugement. La page « Juger des actions » (swipe) servira à ça : quand tu jugeras une action « bien » et le modèle « mal », on saura où il se trompe.</li>
    <li><b>Gestes techniques</b> (resets, double taps, air dribbles) : détecteurs disponibles mais pas vérifiés, donc non affichés.</li>
    <li><b>Niveau</b> : aucune note ne dit « tu as le niveau de tel rang ». Il faudrait des replays de chaque rang.</li>
  </ul>
</section>"""
    summary_rows = [
        ("Lecture des replays", "#lecture", "Solide", "ok", f"{pc(gd['ok'] / gd['tot'], 1)} des buts exacts"),
        ("Valeur de la situation", "#valeur", "Solide", "ok", f"AUC {fr(v['auc'])} sur matchs jamais vus"),
        ("Placement hors ballon", "#placement", "Correct", "mid", f"erreur divisée par 2 · lien faible avec la victoire"),
        ("Choix à la touche", "#choix", "Expérimental", "bad", f"R² {fr(q['r2_oof'])}"),
        ("Indice de performance", "#indice", "Correct en moyenne", "mid", f"{pc(p['rlcs_team_acc'])} des matchs RLCS · fiable à partir de {rt['index']['matches_for_08']} parties"),
    ]
    summary = "".join(f"<a class='pl-row sr' href='{a}'><span class='pl-dx nm'>{escape(n)}</span><span class='pl-small'>{escape(s)}</span><span class='pl-cut pl-tag badge {c}'>{escape(b)}</span></a>"
                      for n, a, b, c, s in summary_rows)
    css = plateau_css() + """
.page { max-width: 1000px; margin: 0 auto; padding: 26px 30px 48px; }
@media (max-width: 720px) { .page { padding: 20px 16px 40px; } }
a { color: inherit; }
h1, h2, h3, p { margin: 0; font-weight: inherit; font-size: inherit; }
.top { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 22px; }
.top a { text-decoration: none; }
.read { margin: 8px 0 4px; max-width: 760px; }
.model { margin-top: 44px; padding-top: 18px; border-top: 3px solid var(--ink); }
.mh { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.badge { padding: 4px 16px 4px 14px; display: inline-block; }
.badge.ok { background: var(--good); color: var(--on-good); }
.badge.mid { background: var(--surface-alt); color: var(--ink); box-shadow: inset 0 0 0 1px var(--rule); }
.badge.bad { background: var(--bad); color: var(--panel-ink); }
.grph { margin: 20px 0 6px; color: var(--ink-muted); }
ol, ul { margin: 0; padding-left: 20px; } li { margin: 4px 0; max-width: 820px; }
.tw { overflow-x: auto; }
.sc { width: 100%; border-collapse: collapse; min-width: 640px; }
.sc th, .sc td { text-align: left; vertical-align: top; padding: 10px 12px 10px 0; border-bottom: 1px solid var(--rule); }
.sc thead th { color: var(--ink-muted); }
.sc td.v { font-size: 30px; white-space: nowrap; }
.sc td.v.ok { color: var(--good-on-dark); } .sc td.v.mid { color: var(--ink); } .sc td.v.bad { color: var(--bad); }
.sr { display: grid; grid-template-columns: minmax(180px, 260px) 1fr auto; gap: 12px; align-items: center; text-decoration: none; }
.sr .nm { font-size: 26px; }
.sr:hover { background: var(--surface-alt); }
.axes { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 18px; }
.axes > div { padding: 14px 16px; background: var(--surface-alt); }
@media (max-width: 720px) { .sr { grid-template-columns: 1fr; } }
"""
    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Les modèles RLPI</title><style>{css}</style></head>
<body class="pl-page"><div class="page">
<div class="top"><header class="pl-header"><div class="pl-volt pl-cut pl-dx pl-title">RLPI</div><div class="pl-panel pl-cut pl-tag">Les modèles</div></header>
<a class="pl-tag pl-muted" href="index.html">◂ Accueil</a></div>
<h1 class="pl-dx" style="font-size:var(--dx-56)">Ce que valent nos modèles</h1>
<p class="pl-body read">Chaque note du tableau de bord vient d'un modèle ou d'une mesure. Voici comment chacun est construit et à quel point on peut s'y fier, mesuré sur des matchs qu'il n'a jamais vus.</p>
<div class="axes">
  <div><div class="pl-tag">Pertinence</div><p class="pl-small pl-muted">Mesure-t-il la bonne chose ? (lien avec la victoire, avec le jeu)</p></div>
  <div><div class="pl-tag">Vérité</div><p class="pl-small pl-muted">Ce qu'il annonce est-il exact sur des données jamais vues ?</p></div>
  <div><div class="pl-tag">Efficacité</div><p class="pl-small pl-muted">Fait-il mieux qu'une règle simple sans modèle ?</p></div>
  <div><div class="pl-tag">Fiabilité</div><p class="pl-small pl-muted">Donne-t-il la même réponse quand on le mesure deux fois ?</p></div>
</div>
<h2 class="pl-tag grph" style="margin-top:28px">En un coup d'œil</h2>
<div>{summary}</div>
{''.join(cards)}
{analyses}
{pending}
<p class="pl-small pl-muted" style="margin-top:40px">Généré le {datetime.now().strftime("%d/%m/%Y %H:%M")} à partir des rapports des modèles (data/models). Régénérer : <code>python -m rlpi.models_page</code>.</p>
</div></body></html>"""
    OUT.write_text(html, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print("→", build())
