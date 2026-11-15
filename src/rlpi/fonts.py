"""Polices des pages RLPI, hébergées localement (avant : Google Fonts, qui bloquait l'affichage jusqu'à 5 s à
la première ouverture).

Source : src/rlpi/assets/fonts (versionné, donc présent dans l'image Docker du serveur).
- Pages générées et « autonomes » (tableau de bord local et serveur, modèles) : polices intégrées en base64
  dans la page (font_css(embed=True)), pour qu'elle reste lisible même copiée ailleurs ou envoyée à quelqu'un.
- Pages écrites à la main dans reports/ : lien <link rel="stylesheet" href="fonts/fonts.css"> vers la copie
  locale reports/fonts (reports/ n'est pas versionné).
"""
from __future__ import annotations

import base64
import re
from functools import lru_cache
from pathlib import Path

FONTS_DIR = Path(__file__).parent / "assets" / "fonts"
PLACEHOLDER = "/*__FONTS__*/"


@lru_cache(maxsize=2)
def font_css(embed: bool = True) -> str:
    """Les @font-face de reports/fonts/fonts.css ; embed=True remplace chaque fichier par son contenu base64."""
    css = (FONTS_DIR / "fonts.css").read_text(encoding="utf-8")
    if not embed:
        return css

    def data_uri(m: re.Match) -> str:
        b64 = base64.b64encode((FONTS_DIR / m.group(1)).read_bytes()).decode("ascii")
        return f'url("data:font/woff2;base64,{b64}")'

    return re.sub(r'url\("([^"]+\.woff2)"\)', data_uri, css)
