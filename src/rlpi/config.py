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

# Nom de la source des parties du joueur suivi : fichiers data/frames/<source>/ et data/features/*_<source>.*
# « theo » pour les données de Théo (tableau de bord en ligne) ; le kit partagé utilise « perso ».
SOURCE = os.getenv("RLPI_SOURCE", "theo").strip() or "theo"

# Profil suivi (voir .env.example) : identifiant du joueur et coéquipiers à comparer.
# Source « theo » sans réglage : profil de Théo et ses coéquipiers habituels (comportement d'avant la
# généralisation). Pour toute autre source, vide par défaut (détecté par l'application).
_THEO = SOURCE == "theo"
PLAYER = os.getenv("RLPI_PLAYER", "").strip() or ("Steam:76561198078330309" if _THEO else "")
COMPARE = [s.strip() for s in (os.getenv("RLPI_COMPARE", "").strip() or ("LAinox,Rileq" if _THEO else "")).split(",")
           if s.strip()]


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
