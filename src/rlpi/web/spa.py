"""Interface Vue (web/, compilée dans web/dist) servie par FastAPI.

    GET {base}/assets/…     fichiers compilés (nom avec empreinte) : cache d'un an, immuables
    GET {base}/…            tout autre chemin : index.html (mode historique de vue-router : un lien ou une
                            actualisation sur /ma-forme, /matchs/<partie>… fonctionne), jamais mis en cache

L'interface est servie à la racine depuis la fin de la phase F (avant : sous /v2, à côté de l'ancien gabarit). Les
chemins réservés au serveur (API, connexion, documentation, sondes) ne renvoient jamais index.html : une adresse
inconnue sous /api/… reste une 404. Le dossier compilé est RLPI_WEB_DIST (web/dist par défaut ; /app/web/dist dans
l'image). S'il manque, l'interface n'est pas servie et le journal le dit : le reste du serveur fonctionne.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from rlpi import logs

# Premiers segments de chemin qui appartiennent au serveur, pas à l'interface
RESERVED = {"api", "auth", "dev", "docs", "openapi.json", "health", "ready", "connexion", "assets"}
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
NO_CACHE = {"Cache-Control": "no-cache"}


def mount(app: FastAPI, dist: Path, base: str) -> bool:
    """Ajoute les routes de l'interface ; False (et rien d'ajouté) si `dist` n'a pas d'index.html."""
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file():
        logs.warning(f"interface Vue absente ({root}) : {base or '/'} non servi")
        return False
    base = base.rstrip("/")

    def page() -> FileResponse:
        return FileResponse(index, media_type="text/html", headers=NO_CACHE)

    @app.get(f"{base}/assets/{{name:path}}", include_in_schema=False)
    def asset(name: str) -> FileResponse:
        f = (root / "assets" / name).resolve()
        if not f.is_file() or not f.is_relative_to(root / "assets"):
            raise HTTPException(404)
        return FileResponse(f, headers=IMMUTABLE)

    @app.get(base or "/", include_in_schema=False)
    def home() -> FileResponse:
        return page()

    @app.get(f"{base}/{{path:path}}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.split("/", 1)[0] in RESERVED:
            raise HTTPException(404)
        f = (root / path).resolve()
        if path and f.is_file() and f.is_relative_to(root):  # fichiers de public/ (aucun pour l'instant)
            return FileResponse(f, headers=NO_CACHE)
        return page()

    return True
