"""Anciennes adresses du tableau de bord, redirigées vers l'interface Vue (servie à la racine, rlpi.web.spa).

    GET /moi, /tableau_de_bord(.html)   →  /ma-forme (mêmes filtres de période, coéquipiers, joueur affiché)
    GET /v2/…                           →  même chemin sans /v2 (adresses de la transition, phase F)

L'ancien gabarit a été supprimé en phase H : il ne reste que ces redirections.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter(include_in_schema=False)
FILTERS = ("du", "au", "avec", "sans", "j")


def _with_filters(path: str, request: Request) -> str:
    q = {k: v for k, v in request.query_params.items() if k in FILTERS and v}
    return path + ("?" + urlencode(q) if q else "")


@router.get("/moi")
@router.get("/tableau_de_bord.html")
@router.get("/tableau_de_bord")
def old_dashboard(request: Request) -> RedirectResponse:
    return RedirectResponse(_with_filters("/ma-forme", request), status_code=303)


@router.get("/v2")
@router.get("/v2/{path:path}")
def transition(request: Request, path: str = "") -> RedirectResponse:
    q = request.url.query
    return RedirectResponse("/" + path + ("?" + q if q else ""), status_code=301)
