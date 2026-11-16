"""Dépendances communes des routes : configuration, joueur connecté, droits, origine des requêtes d'écriture."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from rlpi.web import sessions
from rlpi.web.settings import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _resolve(request: Request, settings: Settings) -> str | None:
    """Joueur de la session du cookie. Un ancien cookie signé encore valide est remplacé par une session : le
    nouveau cookie est posé sur la réponse par le middleware (request.state.set_cookie)."""
    token = request.cookies.get(sessions.COOKIE)
    if not token:
        return None
    if "|" in token:  # ancien format « joueur|expiration|signature » (rlpi.account, avant la phase E)
        from rlpi import account

        pid = account.session_player(f"{sessions.COOKIE}={token}")
        if pid is None:
            return None
        request.state.set_cookie = sessions.cookie(sessions.create(pid), settings.https)
        return pid
    return sessions.player(token)


async def optional_player(request: Request, settings: SettingsDep) -> str | None:
    if not hasattr(request.state, "player"):
        request.state.player = await run_in_threadpool(_resolve, request, settings)
    return request.state.player


OptionalPlayer = Annotated[str | None, Depends(optional_player)]


async def current_player(player: OptionalPlayer) -> str:
    if player is None:
        raise HTTPException(401, "Connexion nécessaire (/auth/steam).")
    return player


CurrentPlayer = Annotated[str, Depends(current_player)]


async def own_player(id: str, player: CurrentPlayer) -> str:
    """Routes /api/joueurs/{id}/… : chacun ne voit que le sien."""
    if id != player:
        raise HTTPException(403, "Tu ne peux consulter que ton propre tableau de bord.")
    return player


OwnPlayer = Annotated[str, Depends(own_player)]


def same_origin(request: Request, settings: SettingsDep) -> None:
    """Protection CSRF des requêtes d'écriture (en plus de SameSite=Lax) : en-tête Origin, sinon Referer, égal à
    l'origine de RLPI_PUBLIC_URL."""
    from urllib.parse import urlparse

    origin = (request.headers.get("origin") or "").strip()
    if origin:
        ok = origin.rstrip("/").lower() == settings.origin
    else:
        ref = urlparse((request.headers.get("referer") or "").strip())
        ok = f"{ref.scheme}://{ref.netloc}".lower() == settings.origin
    if not ok:
        raise HTTPException(403, "Requête refusée (origine inconnue).")


SameOrigin = Depends(same_origin)
