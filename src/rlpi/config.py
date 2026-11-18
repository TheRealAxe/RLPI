"""Chemins du projet et chargement des secrets (.env)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

# Dossier des données (par défaut data/ à la racine). RLPI_DATA permet de travailler dans un autre dossier,
# par exemple un dossier temporaire par partie (rlpi.game) ; RLPI_MODELS garde alors les modèles partagés.
DATA = Path(os.getenv("RLPI_DATA") or ROOT / "data")
RAW = DATA / "raw"
FRAMES = DATA / "frames"
FEATURES = DATA / "features"
MODELS = Path(os.getenv("RLPI_MODELS") or DATA / "models")
CONFIG = ROOT / "config"

# Décisions validées (voir docs/JOURNAL.md)
GAME_MODE = "ranked-standard"  # 3v3

# Nom de la source des parties suivies : fichiers data/frames/<source>/ et data/features/*_<source>.* (« perso »
# par défaut). Aucun joueur n'est fixé dans le code : le joueur est celui de la session (site) ou celui passé en
# paramètre (--player des commandes).
SOURCE = os.getenv("RLPI_SOURCE", "perso").strip() or "perso"


def ballchasing_token() -> str:
    token = os.getenv("BALLCHASING_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BALLCHASING_TOKEN absent : copie .env.example en .env et renseigne ta clé API."
        )
    return token


def ballchasing_api(**kwargs):
    """Client ballchasing avec limitation de débit proactive."""
    import ballchasing

    kwargs.setdefault("proactive_rate_limit", True)
    return ballchasing.Api(ballchasing_token(), **kwargs)
