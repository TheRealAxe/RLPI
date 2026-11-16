"""Tableau de bord : critères automatiques d'un joueur comparés à ses lobbies, SSL et RLCS.

Le calcul est découpé en trois temps (phase D de docs/PLAN_REFONTE_WEB.md) :
    aggregate  agrégats d'une partie, calculés une fois par le worker et enregistrés dans Postgres (storage)
    reference  partie fixe (références RLCS / SSL, rapports des modèles), calculée une fois
    content    contenu de la page, à partir des agrégats des parties retenues par les filtres
Une section du tableau de bord = un module : metrics (critères, technique, compositions), value, peers, passes,
heat, perf, synergy, style, advice (conseils et progression).

En ligne de commande, sur un dossier de données classique (RLPI_DATA, source RLPI_SOURCE), le même contenu que
GET /api/joueurs/{id}/tableau, en JSON (pour vérifier un calcul sans serveur) :
    python -m rlpi.dashboard --player "Steam:<ton identifiant>"   → reports/tableau_de_bord.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rlpi.context import DataContext, resolve
from rlpi.dashboard.common import percentile
from rlpi.dashboard.metrics import KEYS, METRICS, metrics, tech_metrics

__all__ = ["KEYS", "METRICS", "games_from_context", "make_payload", "metrics", "percentile", "tech_metrics"]


def games_from_context(ctx: DataContext):
    """Agrégats de toutes les parties d'un dossier de données (calculés à la volée)."""
    from rlpi.dashboard.aggregate import compute, from_context
    from rlpi.dashboard.content import Games

    return Games(compute(g) for g in from_context(ctx))


def make_payload(
    player: str,
    compare_with: list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    with_ids: list[str] | None = None,
    without_ids: list[str] | None = None,
    ctx: DataContext | None = None,
) -> dict:
    """Profil d'un joueur calculé sur un dossier de données (ligne de commande)."""
    from rlpi.dashboard import content, reference

    ctx = resolve(ctx)
    return content.make_payload(
        games_from_context(ctx), reference.build(ctx), player, compare_with, since, until, with_ids, without_ids
    )


def main() -> None:
    from rlpi.config import ROOT

    ap = argparse.ArgumentParser()
    ap.add_argument("--player", required=True, help="identifiant, ex. Steam:7656119800000000x")
    ap.add_argument("--compare", nargs="*", default=[], help="coéquipiers proposés, identifiants")
    ap.add_argument("--since", help="ne garder que les parties à partir de cette date (AAAA-MM-JJ)")
    ap.add_argument("--until", help="ne garder que les parties jusqu'à cette date (AAAA-MM-JJ)")
    ap.add_argument("--out", default=str(ROOT / "reports" / "tableau_de_bord.json"))
    a = ap.parse_args()
    data = make_payload(a.player, a.compare, a.since, a.until)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"→ {out}")
