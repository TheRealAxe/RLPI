"""Où lire les données d'un calcul : celles du joueur et celles de référence (RLCS, SSL, rapports des modèles).

Le tableau de bord (rlpi.dashboard) et les calculs qu'il appelle (rlpi.synergy, rlpi.styles, rlpi.perf) reçoivent
un DataContext au lieu de lire des chemins globaux fixés à l'import : on peut ainsi calculer le tableau de bord de
n'importe quel joueur dans le même processus.

    data    dossier des données du joueur : features/*_<source>.*, frames/<source>/
    source  nom de la source du joueur (« perso » pour le site)
    ref     dossier des données de référence : features/*_rlcs.*, *_ssl.*, frames/rlcs/…
    models  dossier des rapports et modèles (styles.json, perf_report.json…)

Les fichiers d'une source sont lus dans `data` si c'est la source du joueur, dans `ref` sinon. En ligne de
commande (DataContext.default()), `data` et `ref` sont le même dossier : config.DATA.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataContext:
    data: Path
    source: str
    ref: Path
    models: Path

    @classmethod
    def default(cls) -> DataContext:
        """Valeurs de rlpi.config (variables RLPI_DATA, RLPI_SOURCE, RLPI_MODELS) : usage en ligne de commande."""
        from rlpi import config

        return cls(data=config.DATA, source=config.SOURCE, ref=config.DATA, models=config.MODELS)

    def root(self, source: str) -> Path:
        return self.data if source == self.source else self.ref

    def features(self, source: str) -> Path:
        """Dossier features/ où se trouvent les tables de cette source."""
        return self.root(source) / "features"

    def feature(self, stem: str, source: str, ext: str = "parquet") -> Path:
        """Table <stem>_<source>.<ext> (ex. touch_values_rlcs.parquet)."""
        return self.features(source) / f"{stem}_{source}.{ext}"

    def frames(self, source: str) -> Path:
        """Dossier frames/<source>/ (images par image et métadonnées des parties)."""
        return self.root(source) / "frames" / source


def resolve(ctx: DataContext | None) -> DataContext:
    return ctx if ctx is not None else DataContext.default()
