"""Conseils (trois leviers) et progression sur la période : calculés sur le contenu déjà assemblé."""

from __future__ import annotations

import numpy as np

from rlpi.dashboard import bootstrap

COMP_ADVICE = {
    "impact": (
        "Tes touches rapportent peu",
        "Avant chaque touche, choisis où la balle doit aller : un coin, un coéquipier, le cadre. Une touche « pour toucher » ne rapporte rien.",
    ),
    "boost": (
        "Tu tombes trop souvent à sec",
        "Prends un grand pad pendant chaque rotation retour, et garde 30 de boost avant de sauter sur un ballon.",
    ),
    "vitesse": (
        "Tu joues trop lentement",
        "Enchaîne les flips et garde la pleine vitesse entre deux actions : arriver vite, c'est choisir avant l'adversaire.",
    ),
    "collectif": (
        "Tes passes trouvent peu preneur",
        "Avant de centrer, vérifie qu'un coéquipier suit ; le receveur annonce « je suis là ».",
    ),
    "duels": (
        "Tu perds tes 50/50",
        "Arrive avec du boost et saute un peu plus tôt : un 50/50 se gagne sur l'élan et le contact franc.",
    ),
    "placement": (
        "Ton placement s'écarte de celui d'un pro",
        "En 2e homme, reste à hauteur du ballon côté opposé ; en 3e, centré, devant ton but.",
    ),
    "fiabilite": (
        "Tu rates des ballons",
        "Ralentis avant les touches qui comptent : mieux vaut une touche propre qu'une frappe forte ratée.",
    ),
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


ART = {
    "Voltigeur": "du",
    "Forteresse": "de la",
    "Harceleur": "du",
    "Ancre": "de l'",
    "Fer de lance": "du",
    "Fusée": "de la",
    "Fiable": "du",
    "Tête brûlée": "de la",
    "Porteur": "du",
    "Meneur": "du",
}


def advice_section(payload: dict) -> list[dict]:
    """Trois conseils : le levier qui coûte le plus de points d'indice, le retard technique le plus net face
    aux lobbies, et le piège de ton style."""
    out = []
    pf = payload.get("perf")
    if pf and pf.get("me"):
        w = {c["key"]: c["weight"] for c in pf["components"]}
        comps = pf["me"]["comps"]
        cost = sorted(
            ((w[k] * (50 - v), k) for k, v in comps.items() if k in COMP_ADVICE and w.get(k, 0) > 0.02), reverse=True
        )
        if cost and cost[0][0] > 0:
            k = cost[0][1]
            t, txt = COMP_ADVICE[k]
            out.append(
                {
                    "kind": "Indice",
                    "title": t,
                    "text": txt,
                    "why": f"C'est la composante qui te coûte le plus de points d'indice ({round(comps[k])}/100, poids {round(100 * w[k])} %).",
                }
            )
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
            out.append(
                {
                    "kind": "Technique",
                    "title": f"{r['label']} : sous tes lobbies",
                    "text": TECH_ADVICE[r["key"]],
                    "why": f"{round(abs(rel) * 100)} % {'de moins' if r['sens'] > 0 else 'de plus'} que les autres joueurs de tes parties.",
                }
            )
    st = payload.get("style")
    if st and st.get("me"):
        main = st["styles"][st["me"]["main"]]
        out.append(
            {
                "kind": "Style",
                "title": f"Le piège {ART.get(main['name'], 'du')} {main['name']}".replace("de l' ", "de l'"),
                "text": main["trap"],
                "why": f"Ton style principal ressort dans {st['me']['regular']} de tes {st['me']['n']} parties.",
            }
        )
    return out


def progress_section(payload: dict, last: int | None = None) -> dict | None:
    """Évolution sur les parties de la période (ou les `last` dernières) : indice, sous-notes, composantes et technique ;
    comparaison seconde moitié vs première moitié, intervalle 80 % par tirage des parties."""
    pf = payload.get("perf")
    if not pf or len(pf["matches"]) < 6:
        return None
    ms = pf["matches"][-last:] if last else pf["matches"]
    n = len(ms)
    h = n // 2
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
        boots = bootstrap.mean_diffs(rng, b, a, 1000) * sens
        lo, hi = np.percentile(boots, [10, 90])
        changes.append(
            {
                "key": key,
                "label": label,
                "before": float(a.mean()),
                "after": float(b.mean()),
                "delta": float(d),
                "effect": float(d / sd),
                "lo": float(lo),
                "hi": float(hi),
                "clear": bool(lo > 0 or hi < 0),
                "unit": "/100"
                if not key.startswith("t_")
                else next(r["unit"] for r in payload["tech"]["rows"] if "t_" + r["key"] == key),
                "headline": key in ("index", "prod", "fond"),
            }
        )
    idx = np.array([m["index"] for m in ms], dtype=float)
    roll = [float(np.mean(idx[max(0, i - 4) : i + 1])) for i in range(n)]
    return {
        "n": n,
        "half": h,
        "dates": dates,
        "index": idx.tolist(),
        "roll5": roll,
        "won": [m["won"] for m in ms],
        "changes": changes,
    }
