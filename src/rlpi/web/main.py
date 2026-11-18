"""Serveur web RLPI (FastAPI) : API JSON du tableau de bord, connexion Steam et interface Vue.

    uvicorn --factory rlpi.web.main:create_app --host 0.0.0.0 --port 3001 --workers 2 --no-access-log
    python -m rlpi.web [--port 8765]        (développement : un seul processus, 127.0.0.1 par défaut)

- /health : le processus répond ; /ready : Postgres, Redis et Garage joignables (503 sinon) ;
- /api/… : contenu en JSON (rlpi.web.routes.api), documenté sur /docs ;
- /auth/… : connexion Steam, sessions (rlpi.web.routes.auth) ;
- /moi, /tableau_de_bord, /v2/… : anciennes adresses, redirigées (rlpi.web.routes.redirects) ;
- le reste : interface Vue (web/dist, rlpi.web.spa), index.html pour chacun de ses chemins.

Journal d'accès : une ligne par requête (méthode, chemin sans paramètres, statut, durée, identifiant de requête),
jamais de cookie ; les sondes /health réussies ne sont pas écrites. L'identifiant de requête vient de l'en-tête
X-Request-ID s'il est sûr (proxy), sinon il est tiré au hasard ; il est renvoyé dans X-Request-ID et ajouté à toute
ligne de journal écrite pendant la requête (rlpi.logs). Configuration : rlpi.web.settings.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from rlpi import logs
from rlpi.web.settings import get_settings

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
    (b"x-frame-options", b"DENY"),
]
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")


def _request_id(scope: Scope) -> str:
    for k, v in scope.get("headers", []):
        if k == b"x-request-id":
            rid = v.decode("latin-1")
            if SAFE_REQUEST_ID.fullmatch(rid):
                return rid
    return secrets.token_hex(8)


class AccessLog:
    """Journal d'accès, en-têtes de sécurité et cookie de session renouvelé (request.state.set_cookie, posé par
    rlpi.web.deps lors de la transition depuis un ancien cookie signé). Middleware ASGI pur : le flux
    d'événements (SSE) passe sans être mis en mémoire."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        status = 500
        rid = _request_id(scope)
        token = logs.request_id.set(rid)

        async def wrapped(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers += SECURITY_HEADERS
                headers.append((b"x-request-id", rid.encode("ascii")))
                cookie = scope.get("state", {}).get("set_cookie")
                if cookie:
                    headers.append((b"set-cookie", cookie.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, wrapped)
        finally:
            path = scope.get("path") or "-"
            if not (path == "/health" and status == 200):
                ms = round((time.perf_counter() - t0) * 1000)
                method = scope.get("method", "-")
                if logs.json_mode():
                    logs.log("requête", method=method, path=path, status=status, ms=ms)
                else:
                    logs.log(f"{method} {path} {status} {ms} ms")
            logs.request_id.reset(token)


def _warm_reference() -> None:
    """Au démarrage : référence du tableau de bord relue, ou recalculée si ses fichiers ont changé."""
    from rlpi.dashboard import storage

    try:
        storage.reference()
    except Exception as e:  # noqa: BLE001 — recalculée à la première demande si besoin
        logs.warning("référence du tableau de bord indisponible", erreur=f"{type(e).__name__}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from rlpi import store

    s = get_settings()
    if s.dev_login:
        logs.warning("ATTENTION : connexion de développement active (/dev/connexion), sans Steam")
    try:  # pool Postgres ouvert et version du schéma vérifiée une fois, au démarrage
        store.init()
        threading.Thread(target=_warm_reference, daemon=True).start()
    except store.SchemaError:
        raise
    except Exception as e:  # noqa: BLE001 — base momentanément injoignable : /ready le dira, on réessaiera
        logs.error("Postgres indisponible au démarrage", erreur=f"{type(e).__name__}: {e}")
    yield


def ready() -> tuple[bool, dict[str, str]]:
    from rlpi import store

    checks: dict[str, str] = {}
    try:
        with store.db() as c:
            c.execute("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["postgres"] = type(e).__name__
    try:
        store.redis_client().ping()
        checks["redis"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["redis"] = type(e).__name__
    try:
        store.s3().head_bucket(Bucket=store.bucket())
        checks["garage"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["garage"] = type(e).__name__
    return all(v == "ok" for v in checks.values()), checks


def create_app() -> FastAPI:
    from rlpi.web import spa
    from rlpi.web.routes import api, auth, redirects, swipe

    logs.configure("web")
    settings = get_settings()  # configuration vérifiée tout de suite : le serveur ne démarre pas si elle manque
    app = FastAPI(
        title="RLPI",
        summary="Rocket League Player Index : tableau de bord de tes parties",
        version="2",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(AccessLog)

    @app.get("/health", include_in_schema=False)
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/ready", tags=["exploitation"], summary="Postgres, Redis et Garage joignables")
    def is_ready() -> JSONResponse:
        ok, checks = ready()
        return JSONResponse(checks, status_code=200 if ok else 503)

    app.include_router(auth.router)
    app.include_router(api.router)
    app.include_router(swipe.router)
    app.include_router(redirects.router)
    spa.mount(app, settings.web_dist, "")  # en dernier : tout chemin non pris par le serveur
    return app
