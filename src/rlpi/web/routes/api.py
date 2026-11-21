"""API JSON du tableau de bord. Toutes les routes exigent une session ; /api/joueurs/{id}/… seulement pour soi.

Le contenu vient des agrégats écrits par les workers (rlpi.dashboard.storage) : quelques centaines de ms au plus,
puis gardé en mémoire (rlpi.web.cache). Les réponses du tableau de bord portent un ETag (version des données du
joueur, référence, filtres, code) : le navigateur revalide et reçoit 304 tant que rien n'a changé.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import time
import warnings
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from starlette.concurrency import run_in_threadpool

from rlpi import account, events, store
from rlpi.web import clips, schemas
from rlpi.web.cache import JsonCache, etag
from rlpi.web.deps import CurrentPlayer, OwnPlayer, SameOrigin

router = APIRouter(prefix="/api", tags=["api"])
CACHE = JsonCache()
CLIPS = clips.ClipService()
CLIP_CACHE_CONTROL = "private, no-cache"  # gardé par le navigateur mais revalidé à chaque fois (304 par l'ETag) :
# un changement de format du clip (clips.VERSION) n'est jamais masqué par une copie gardée
DAY = r"^\d{4}-\d{2}-\d{2}$"
ID_LIST = Annotated[str, Query(max_length=400, description="Identifiants séparés par des virgules")]
NOT_READY = "Aucune partie prête pour ce joueur (import ou calcul en cours)."
JSON_RESPONSES: dict[int | str, dict[str, Any]] = {
    304: {"description": "Inchangé depuis la version du navigateur (en-tête If-None-Match)"},
    401: {"description": "Pas de session"},
    403: {"description": "Joueur différent du joueur connecté"},
    404: {"description": "Aucune partie prête, ou partie inconnue"},
}


def not_modified(request: Request, tag: str) -> bool:
    return tag in [t.strip() for t in request.headers.get("if-none-match", "").split(",")]


def json_response(request: Request, gz: bytes, tag: str, cache_control: str = "private, no-cache") -> Response:
    """Réponse JSON compressée (envoyée telle quelle si le navigateur accepte gzip) avec son ETag."""
    headers = {"ETag": tag, "Cache-Control": cache_control, "Vary": "Accept-Encoding, Cookie"}
    if not_modified(request, tag):
        return Response(status_code=304, headers=headers)
    if "gzip" in request.headers.get("accept-encoding", "").lower():
        return Response(gz, media_type="application/json", headers=headers | {"Content-Encoding": "gzip"})
    return Response(gzip.decompress(gz), media_type="application/json", headers=headers)


def ids(raw: str) -> list[str]:
    return [x for x in (v.strip() for v in raw.split(",")) if x]


def load(player: str):
    """(parties agrégées du joueur, référence) ; 404 s'il n'a encore aucune partie prête."""
    from rlpi.dashboard import storage

    games, _n, _pending = storage.player_games(player)
    if games is None:
        raise HTTPException(404, NOT_READY)
    return games, storage.reference(), storage.reference_fingerprint()


# ------------------------------------------------------------------------------------------------ moi


@router.get("/moi", response_model=schemas.Moi, summary="Joueur connecté et état de l'import")
def me(player: CurrentPlayer) -> dict:
    from rlpi.dashboard import storage

    with store.db() as c:
        version, n, pending = storage.player_state(c, player)
        row = c.execute(
            "SELECT mp.player_name FROM match_players mp JOIN matches m ON m.id = mp.match_id "
            "WHERE mp.player_id = %s AND mp.player_name IS NOT NULL ORDER BY m.played_at DESC NULLS LAST LIMIT 1",
            (player,),
        ).fetchone()
    return {
        "id": player,
        "nom": row[0] if row else None,
        "parties": n,
        "en_preparation": pending,
        "version": version,
        "import": account.import_state(player),
    }


@router.post(
    "/moi/actualiser",
    response_model=schemas.Actualisation,
    dependencies=[SameOrigin],
    summary="Chercher maintenant ses nouvelles parties (au plus une fois toutes les 5 minutes)",
)
def refresh(player: CurrentPlayer) -> dict:
    if account.refresh(player):
        return {"lancee": True, "message": "Recherche lancée : les nouvelles parties arrivent dans quelques minutes."}
    return {"lancee": False, "message": "Recherche déjà faite il y a moins de 5 minutes."}


@router.get(
    "/moi/evenements",
    response_class=EventSourceResponse,
    summary="Flux d'événements : « nouveau match traité » (Server-Sent Events)",
    description='Événement `partie` : `{"match": <id>, "parties": <nombre de parties prêtes>}`. Un commentaire '
    "« ping » toutes les 15 s (FastAPI) garde la connexion ouverte à travers le proxy de Coolify.",
)
async def stream(request: Request, player: CurrentPlayer) -> AsyncIterator[ServerSentEvent]:
    import redis.asyncio as aioredis

    r = aioredis.Redis.from_url(store.url("REDIS_URL", ("redis://", "rediss://")), decode_responses=True)
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(events.channel(player))
        yield ServerSentEvent(event="connecte", data={"joueur": player})
        while not await request.is_disconnected():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is not None and msg.get("type") == "message":
                yield ServerSentEvent(event="partie", raw_data=msg["data"])
    finally:
        try:
            await asyncio.shield(pubsub.aclose())
            await asyncio.shield(r.aclose())
        except Exception:  # noqa: BLE001 — connexion déjà coupée
            pass


# ------------------------------------------------------------------------------------------------ joueur


@router.get(
    "/joueurs/{id}/profil",
    response_model=schemas.Profil,
    responses=JSON_RESPONSES,
    summary="Pseudo, coéquipiers proposés, parties par jour",
)
def profile(request: Request, player: OwnPlayer, id: Annotated[str, Path(max_length=100)]) -> Response:
    from rlpi.dashboard import content

    games, _ref, _fp = load(player)
    tag = etag("profil", player, games.version, len(games))

    def build() -> dict:
        joueurs, noms, jours = content.profile_ids(games, player)
        return {"id": player, "joueurs": joueurs, "noms": noms, "jours": jours}

    return json_response(request, CACHE.compute(tag, build), tag)


@router.get(
    "/joueurs/{id}/tableau",
    response_model=schemas.Tableau,
    responses=JSON_RESPONSES,
    summary="Contenu du tableau de bord pour ces filtres",
)
def dashboard(
    request: Request,
    player: OwnPlayer,
    id: Annotated[str, Path(max_length=100)],
    du: Annotated[str | None, Query(pattern=DAY, description="Premier jour (AAAA-MM-JJ)")] = None,
    au: Annotated[str | None, Query(pattern=DAY, description="Dernier jour (AAAA-MM-JJ)")] = None,
    avec: ID_LIST = "",
    sans: ID_LIST = "",
    j: Annotated[
        str | None, Query(max_length=100, description="Joueur affiché : toi (défaut) ou un coéquipier proposé")
    ] = None,
    ref: Annotated[str | None, Query(pattern=r"^(ssl|rlcs)$", description="Ne garder que cette référence")] = None,
) -> Response:
    from rlpi.dashboard import content

    games, reference, fp = load(player)
    params = {"du": du, "au": au, "avec": ids(avec), "sans": ids(sans), "j": j, "ref": ref}
    tag = etag("tableau", player, games.version, len(games), fp, params)

    def build() -> dict:
        d = content.dashboard(games, reference, player, j, du, au, params["avec"], params["sans"])
        pay = d["contenu"]
        if pay and ref and ref in pay["refs"]:
            pay["refs"] = {ref: pay["refs"][ref]}
            pay["default_ref"] = ref
        return d

    return json_response(request, CACHE.compute(tag, build), tag)


@router.get(
    "/joueurs/{id}/matchs/{match}",
    response_model=schemas.Match,
    responses=JSON_RESPONSES,
    summary="Détail d'un match du joueur (onglet « Ce match »)",
)
def match(
    request: Request,
    player: OwnPlayer,
    id: Annotated[str, Path(max_length=100)],
    match: Annotated[str, Path(max_length=200)],
) -> Response:
    games, reference, fp = load(player)
    g = next((g for g in games.games if g.match_id == match and player in g.players), None)
    if g is None:
        raise HTTPException(404, "Partie inconnue, ou tu n'y as pas joué.")
    tag = etag("match", player, games.version, match, fp)
    return json_response(request, CACHE.compute(tag, lambda: match_detail(games, reference, player, g)), tag)


def match_detail(games, reference: dict, player: str, g) -> dict:
    from rlpi.dashboard import perf, value

    games.ensure_details(player)
    with warnings.catch_warnings():  # moyennes sur un seul match : listes vides possibles, sans conséquence
        warnings.simplefilter("ignore", RuntimeWarning)
        val = value.section(reference["value"], games, player, [g.replay])
        prf = perf.section(reference["perf"], games, player, [g.replay], {})
    pg = g.players[player]
    team = g.team_of.get(player, pg.cols.get("team"))
    won = pg.cols.get("won")
    return {
        "id": g.match_id,
        "replay": g.replay,
        "date": g.date,
        "duree_s": g.play_s,
        "score": g.score,
        "equipe": team,
        "victoire": None if won is None else bool(won),
        "joueurs": [
            {
                "id": pid,
                "nom": p.cols.get("player_name"),
                "equipe": g.team_of.get(pid, p.cols.get("team")),
                "bot": bool(p.cols.get("is_bot")),
            }
            for pid, p in sorted(g.players.items(), key=lambda kv: (g.team_of.get(kv[0], 9), kv[0]))
        ],
        "courbe": (val or {}).get("curves", {}).get(g.replay),
        "indices": (prf or {}).get("matches", []),
        "pires": (val or {}).get("worst", []),
        "meilleures": (val or {}).get("best", []),
    }


@router.get(
    "/joueurs/{id}/matchs/{match}/clips/{i}",
    response_model=schemas.Clip,
    responses=JSON_RESPONSES
    | {
        404: {"description": "Partie inconnue (ou pas la sienne), touche inconnue, ou replay non conservé"},
        422: {"description": "Touche impossible à retrouver dans le replay, ou trop près de son début ou de sa fin"},
    },
    summary="Clip 3D d'une touche (4 s avant, 2 s après, 30 images/s), découpé dans le replay",
    description="Le replay brut est lu au premier clic sur un match (moins d'une seconde) ; les clips suivants du "
    "même match et les clips déjà vus sont servis depuis la mémoire.",
)
async def clip(
    request: Request,
    player: OwnPlayer,
    id: Annotated[str, Path(max_length=100)],
    match: Annotated[str, Path(max_length=200)],
    i: Annotated[int, Path(ge=0, le=100_000, description="Indice de l'image de la touche (10 images/s)")],
) -> Response:
    # Asynchrone : un clip déjà gardé est servi sans attendre, et les demandes qui attendent une place de lecture
    # (ClipService.aclip) n'occupent pas de thread du serveur.
    def game() -> tuple | None:
        with store.db() as c:
            return c.execute(
                "SELECT m.replay_key, m.updated_at FROM match_players mp JOIN matches m ON m.id = mp.match_id "
                "WHERE mp.match_id = %s AND mp.player_id = %s AND m.status IN ('ok', 'partiel')",
                (match, player),
            ).fetchone()

    row = await run_in_threadpool(game)
    if row is None:
        raise HTTPException(404, "Partie inconnue, ou tu n'y as pas joué.")
    replay_key, version = row[0] or f"replays/{match}.replay", row[1].isoformat()  # version : partie réanalysée
    tag = clips.tag(match, version, i, player)
    if not_modified(request, tag):
        return json_response(request, b"", tag, CLIP_CACHE_CONTROL)
    try:
        gz = await CLIPS.aclip(match, replay_key, i, player, version)
    except clips.ClipError as e:
        raise HTTPException(e.status, e.message) from None
    return json_response(request, gz, tag, CLIP_CACHE_CONTROL)


# ------------------------------------------------------------------------------------------------ modèles

_models: tuple[float, bytes, str] | None = None
MODELS_TTL_S = 600


@router.get("/modeles", response_model=schemas.Modeles, summary="Contenu de la page « Les modèles »")
def models(request: Request, _player: CurrentPlayer) -> Response:
    """Rapports des modèles et tables de référence du volume de données ; relus au plus toutes les 10 minutes."""
    global _models
    if _models is None or time.monotonic() - _models[0] > MODELS_TTL_S:
        from rlpi import models_page
        from rlpi.dashboard import storage

        data = models_page.content(storage.reference_context(), sources=("rlcs", "ssl"))
        data.pop("genere", None)
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
        tag = etag("modeles", raw.decode())
        _models = (time.monotonic(), gzip.compress(raw), tag)
    return json_response(request, _models[1], _models[2])
