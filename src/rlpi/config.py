"""Chemins du projet et chargement des secrets (.env)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
FRAMES = DATA / "frames"
FEATURES = DATA / "features"
MODELS = DATA / "models"
CONFIG = ROOT / "config"

# Décisions validées avec Théo (voir docs/JOURNAL.md)
GAME_MODE = "ranked-standard"  # 3v3

load_dotenv(ROOT / ".env")


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
