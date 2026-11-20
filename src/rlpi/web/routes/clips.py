"""Ralentis des touches les plus coûteuses (voir rlpi.clips).

POST /api/clips                     demander le ralenti d'une de ses touches (fabriqué par un worker en ~30 s)
GET  /api/clips/{partie}/{image}    état du ralenti, et le ralenti quand il est prêt
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field

from rlpi import clips, store
from rlpi.web.deps import CurrentPlayer, SameOrigin
from rlpi.web.schemas import Strict

router = APIRouter(prefix="/api/clips", tags=["ralentis"])

Statut = Literal["aucun", "en_attente", "pret", "erreur"]


class DemandeRalenti(Strict):
    partie: Annotated[str, Field(max_length=100, description="Identifiant de la partie (champ `match` d'une touche)")]
    image: Annotated[int, Field(ge=0, description="Image de la touche à 10 images/s (champ `i` d'une touche)")]


class EtatRalenti(Strict):
    statut: Statut


class Ralenti(Strict):
    statut: Statut
    erreur: str | None = None
    clip: dict[str, Any] | None = Field(
        default=None,
        description="Ralenti (même format qu'une carte du swipe : balle et 6 voitures à 30 images/s, "
        "`action_frame` = image de la touche, voiture `judged` = le joueur) ; présent quand le statut est « pret »",
    )


@router.post(
    "",
    response_model=EtatRalenti,
    status_code=202,
    dependencies=[SameOrigin],
    summary="Demander le ralenti d'une de ses touches",
)
def ask(player: CurrentPlayer, d: DemandeRalenti) -> dict:
    with store.db() as c:
        if not clips.plays_in(c, player, d.partie):
            raise HTTPException(404, "Partie inconnue parmi tes parties analysées.")
        status, enqueue = clips.request(c, player, d.partie, d.image)
    if enqueue:
        store.redis_client().lpush(store.QUEUE, json.dumps({"type": "clip", "match": d.partie, "player": player}))
    return {"statut": status}


@router.get("/{partie}/{image}", response_model=Ralenti, summary="État du ralenti, et le ralenti quand il est prêt")
def read(player: CurrentPlayer, partie: str, image: int) -> Response:
    with store.db() as c:
        body = clips.get(c, player, partie, image)
    return Response(
        json.dumps(body, ensure_ascii=False),
        media_type="application/json",
        headers={"Cache-Control": "no-store" if body["statut"] != "pret" else "private, max-age=86400"},
    )
