"""Contenu du tableau de bord calculé sur le jeu d'essai, par le même chemin que le site (/moi).

Comme le worker puis le serveur : agrégats de chaque partie (format du worker dans Garage, rlpi.dashboard.aggregate),
partie fixe calculée depuis les références (RLCS, SSL) et les rapports des modèles de tests/fixtures/reference/
(rlpi.dashboard.reference), puis contenu de la page (rlpi.dashboard.content.page).
"""

from __future__ import annotations

from pathlib import Path

from rlpi.context import DataContext

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
REFERENCE = FIXTURES / "reference"


def reference_context() -> DataContext:
    return DataContext(data=REFERENCE, source="perso", ref=REFERENCE, models=REFERENCE / "models")


def game_dirs() -> list[Path]:
    return sorted((FIXTURES / "games").iterdir())


def aggregates(dirs: list[Path] | None = None) -> list[dict]:
    from rlpi.dashboard import aggregate

    return [aggregate.compute(aggregate.from_game_dir(d)) for d in (dirs if dirs is not None else game_dirs())]


def games(aggs: list[dict]):
    from rlpi.dashboard.content import Games

    return Games(aggs)


def reference() -> dict:
    from rlpi.dashboard import reference

    return reference.build(reference_context())


def payload(g, ref: dict, player: str, **filters: str) -> dict:
    from rlpi.dashboard import content

    split = lambda k: [x for x in (filters.get(k) or "").split(",") if x]  # noqa: E731
    return content.page(
        g, ref, player, filters.get("j"), filters.get("since"), filters.get("until"), split("avec"), split("sans")
    )
