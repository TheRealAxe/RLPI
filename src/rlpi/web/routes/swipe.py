"""Swipe en ligne : juger des actions à l'aveugle (voir rlpi.swipe_online).

GET  /api/swipe/deck         dernier paquet du joueur (cartes sans leur origine, jugements déjà faits)
POST /api/swipe/deck         demander un nouveau paquet (fabriqué par un worker en une minute environ)
POST /api/swipe/jugements    juger une carte : bien, pas_bien ou ? (le dernier jugement compte)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field

from rlpi import store, swipe_online
from rlpi.web.deps import CurrentPlayer, SameOrigin
from rlpi.web.schemas import Strict

router = APIRouter(prefix="/api/swipe", tags=["swipe"])


class Paquet(Strict):
    id: int | None = Field(description="Null si le joueur n'a encore demandé aucun paquet")
    statut: Literal["aucun", "en_attente", "pret", "erreur"]
    erreur: str | None = None
    cree_le: datetime | None = None
    n_cartes: int = 0
    cartes: list[dict[str, Any]] = Field(
        default=[],
        description="Cartes (positions, vitesses, orientation, boost des 6 voitures et de la balle à 30 images/s) ; "
        "l'origine du joueur jugé n'est jamais envoyée",
    )
    jugements: dict[str, str] = Field(default={}, description="Jugement déjà donné, par identifiant de carte")


class Demande(Strict):
    id: int
    statut: Literal["en_attente"]


class Jugement(Strict):
    paquet: int
    carte: Annotated[str, Field(max_length=100)]
    verdict: Literal["bien", "pas_bien", "?"]


def reference_pool_path():
    from rlpi.dashboard import storage

    return storage.reference_context().data / "swipe" / "reference_cards.json"


@router.get("/deck", response_model=Paquet, summary="Dernier paquet de cartes à juger")
def get_deck(player: CurrentPlayer) -> Response:
    with store.db() as c:
        deck = swipe_online.latest(c, player)
    body = deck or {"id": None, "statut": "aucun"}
    return Response(
        json.dumps(body, default=str, ensure_ascii=False),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/deck",
    response_model=Demande,
    status_code=202,
    dependencies=[SameOrigin],
    summary="Demander un nouveau paquet (un seul en préparation à la fois)",
)
def new_deck(player: CurrentPlayer) -> dict:
    with store.db() as c:
        current = swipe_online.pending(c, player)
        if current is not None:
            return {"id": current, "statut": "en_attente"}
        did = swipe_online.create(c, player, swipe_online.reference_pool(reference_pool_path()))
    store.redis_client().lpush(store.QUEUE, json.dumps({"type": "swipe", "deck": did}))
    return {"id": did, "statut": "en_attente"}


@router.post("/jugements", status_code=204, dependencies=[SameOrigin], summary="Juger une carte")
def judge(player: CurrentPlayer, j: Jugement) -> Response:
    with store.db() as c:
        if not swipe_online.judge(c, player, j.paquet, j.carte, j.verdict):
            raise HTTPException(404, "Carte inconnue dans tes paquets prêts.")
    return Response(status_code=204)
