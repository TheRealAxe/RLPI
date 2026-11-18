"""Connexion Steam (OpenID 2.0), déconnexion, connexion de développement.

    GET  /auth/steam                  redirige vers Steam
    GET  /auth/steam/retour           retour de Steam : vérification, compte créé au besoin, session ouverte
    POST /auth/deconnexion            ferme la session de ce navigateur
    POST /auth/deconnexion-partout    ferme toutes les sessions du joueur
    GET  /dev/connexion?joueur=…      développement seulement (RLPI_DEV_LOGIN=1) : session sans Steam
    GET  /dev/joueurs                 développement seulement : joueurs connus, listés par la page de connexion
Un retour de Steam refusé renvoie sur la page de connexion de l'interface (/?connexion=echec), sans session.
Anciennes adresses gardées pendant la transition : /connexion, /connexion/retour.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from rlpi import account, logs
from rlpi.web import sessions
from rlpi.web.deps import CurrentPlayer, SameOrigin, SettingsDep
from rlpi.web.settings import Settings

router = APIRouter(tags=["connexion"])


def _redirect(to: str, cookie: str | None = None) -> RedirectResponse:
    r = RedirectResponse(to, status_code=303)
    if cookie:
        r.headers.append("set-cookie", cookie)
    return r


@router.get("/auth/steam", summary="Se connecter avec Steam")
@router.get("/connexion", include_in_schema=False)
def steam_login() -> RedirectResponse:
    return _redirect(account.steam_login_url())


@router.get("/auth/steam/retour", summary="Retour de Steam", response_class=RedirectResponse)
@router.get("/connexion/retour", include_in_schema=False)
async def steam_return(request: Request, settings: SettingsDep):
    query = {k: [v] for k, v in request.query_params.items()}

    def verify_and_login() -> str | None:
        steam_id = account.steam_verify(query)
        if not steam_id:
            return None
        return sessions.create(account.login(steam_id))

    try:
        token = await run_in_threadpool(verify_and_login)
    except Exception as e:  # noqa: BLE001 — Steam injoignable
        logs.warning("connexion Steam : vérification impossible", erreur=f"{type(e).__name__}: {e}")
        token = None
    if token is None:
        return _redirect("/?connexion=echec")
    return _redirect("/", sessions.cookie(token, settings.https))


@router.post("/auth/deconnexion", summary="Se déconnecter", dependencies=[SameOrigin], status_code=303)
async def logout(request: Request, settings: SettingsDep) -> RedirectResponse:
    await run_in_threadpool(sessions.delete, request.cookies.get(sessions.COOKIE))
    return _redirect("/", sessions.clear_cookie(settings.https))


@router.post(
    "/auth/deconnexion-partout",
    summary="Se déconnecter sur tous les appareils",
    dependencies=[SameOrigin],
    status_code=303,
)
async def logout_everywhere(player: CurrentPlayer, settings: SettingsDep) -> RedirectResponse:
    await run_in_threadpool(sessions.delete_all, player)
    return _redirect("/", sessions.clear_cookie(settings.https))


def _dev_only(settings: Settings) -> None:
    if not settings.dev_login:
        raise HTTPException(404)


@router.get("/dev/joueurs", include_in_schema=False)
def dev_players(settings: SettingsDep) -> list[dict]:
    _dev_only(settings)
    return [{"id": pid, "pseudo": name, "parties": n} for pid, name, n in account.known_players()]


@router.get("/dev/connexion", include_in_schema=False)
def dev_login(settings: SettingsDep, joueur: Annotated[str, Query(max_length=100)] = "") -> RedirectResponse:
    _dev_only(settings)
    pid = joueur.strip()
    if not pid:
        return _redirect("/")
    token = sessions.create(account.dev_login(pid))
    return _redirect("/", sessions.cookie(token, settings.https))
