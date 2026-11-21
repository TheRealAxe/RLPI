"""Clips 3D à la demande (bouton « ▶ Revoir » des onglets Matchs et À travailler).

Le clip d'une touche est découpé au clic dans le replay brut gardé sur Garage (`replays/<partie>.replay`), avec
`rlpi.clips` (lecture à 120 images/s, calage de la touche) et `rlpi.pov` (clip au format du player 3D, 30 images/s) :

1. `games/<partie>/frames/partie/<replay>.meta.json` (joueurs) et `games/<partie>/features/touch_values_partie.parquet`
   (touches : index d'image, auteur, position de la balle) sont téléchargés : quelques Ko ;
2. la touche `i` y est cherchée (inconnue → 404, sans lire le replay) ;
3. le replay est téléchargé et lu (environ 0,3 s et 20 Mo), puis le clip découpé ;
4. la caméra du joueur (« ta caméra » du player) vient de `<replay>.cameras.json`, écrit par le worker (`python -m rlpi.worker
   backfill-cameras` pour les parties traitées avant lui). Le serveur ne la lit jamais dans le replay (environ
   250 Mo) : sans ce fichier, le clip part sans caméra (le player prend alors les réglages par défaut du jeu).

Protection du serveur web :
- un clip déjà gardé est servi tout de suite (`aclip`, route asynchrone) ; les autres sont faits dans un thread, au
  plus `MAX_READS` à la fois (`anyio.CapacityLimiter`) : les suivants attendent leur tour sans occuper de thread ;
- la dernière partie lue reste en mémoire : les clics suivants sur le même match ne relisent pas le replay ;
- tout ce qui est gardé (partie lue, clips, ETag) porte la version de la partie (`matches.updated_at`) : une partie
  réanalysée n'est jamais servie périmée ;
- les clips produits (environ 50 Ko en gzip) sont gardés dans un cache LRU de `MAX_CLIPS` entrées ;
- une partie demandée deux fois en même temps n'est lue qu'une fois (verrou par partie).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import threading
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import anyio
import polars as pl

from rlpi import clips, pov, store
from rlpi.web.cache import JsonCache, KeyedLocks

VERSION = (
    4  # version de la découpe : à augmenter quand le contenu d'un clip change (ETag) ; 3 : 4 s / 2 s ; 4 : player 3D
)
BEFORE_S, AFTER_S = 4.0, 2.0  # secondes montrées avant et après la touche (le Swipe garde 3 s / 1 s)
MAX_READS = 2
MAX_CLIPS = 300
GAME_SOURCE = "partie"  # comme rlpi.game
TOUCH_COLUMNS = ["i", "player_id", "ball_x", "ball_y"]
log = logging.getLogger(__name__)


class ClipError(Exception):
    """Erreur montrée telle quelle à l'utilisateur (code HTTP et message en français)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


REPLAY_MISSING = ClipError(404, "Replay non conservé pour cette partie.")
GAME_MISSING = ClipError(404, "Données de la partie introuvables dans le stockage.")
TOUCH_UNKNOWN = ClipError(404, "Touche inconnue dans cette partie.")
NOT_LOCATED = ClipError(422, "Impossible de retrouver cette touche dans le replay.")
AT_EDGE = ClipError(422, "Touche trop près du début ou de la fin du replay pour en faire un clip.")


@dataclass
class Game:
    """Partie prête à découper : joueurs (meta.json), touches (touch_values) et, une fois lu, le replay."""

    match_id: str
    version: str
    meta: dict
    touches: pl.DataFrame
    track: clips.Track | None = None
    cams: dict | None = None

    def touch(self, i: int, viewer: str) -> tuple[str, tuple[float, float]]:
        """(auteur, position (x, y) de la balle dans le repère du terrain) de la touche `i`. Deux joueurs peuvent
        toucher la balle dans la même image à 10 Hz : on préfère alors la touche du joueur connecté."""
        rows = self.touches.filter(pl.col("i") == i).rows(named=True)
        if not rows:
            raise TOUCH_UNKNOWN
        r = next((r for r in rows if r["player_id"] == viewer), rows[0])
        team = next((p["team"] for p in self.meta["players"] if p["id"] == r["player_id"]), None)
        if team is None or r["ball_x"] is None or r["ball_y"] is None:
            raise NOT_LOCATED
        return r["player_id"], clips.world_xy(r["ball_x"], r["ball_y"], team)


def tag(match_id: str, version: str, i: int, viewer: str) -> str:
    """ETag d'un clip : version de la découpe, partie et sa version (réanalyse), touche, et joueur connecté (sa
    touche est préférée quand deux joueurs touchent la balle dans la même image)."""
    raw = json.dumps(["clip", VERSION, match_id, version, i, viewer])
    return '"clip-' + hashlib.sha1(raw.encode()).hexdigest()[:20] + '"'


class ClipService:
    def __init__(self, max_reads: int = MAX_READS, max_clips: int = MAX_CLIPS, s3: Any = None, bucket: str = ""):
        self.limiter = anyio.CapacityLimiter(max_reads)
        self.clips = JsonCache(max_clips)
        self.lock = threading.Lock()
        self.game_locks = KeyedLocks()
        self.last: Game | None = None
        self._s3, self._bucket = s3, bucket
        self.replay_reads = 0  # nombre de replays lus (tests, suivi)

    # -------------------------------------------------------------------------------------------- stockage

    def storage(self) -> tuple[Any, str]:
        if self._s3 is None:

            with self.lock:
                if self._s3 is None:
                    self._s3, self._bucket = store.s3(), store.bucket()
        return self._s3, self._bucket

    def download(self, key: str, dest: Path, missing: ClipError) -> Path:
        cli, bucket = self.storage()
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            cli.download_file(bucket, key, str(dest))
        except Exception as e:
            if store.is_missing(e):
                raise missing from None
            raise
        return dest

    def meta_key(self, match_id: str) -> str:
        """Clé du meta.json de la partie (nommé d'après le fichier replay analysé par le worker)."""
        cli, bucket = self.storage()
        prefix = f"games/{match_id}/frames/{GAME_SOURCE}/"
        keys = [
            o["Key"]
            for page in cli.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
            for o in page.get("Contents", [])
            if o["Key"].endswith(".meta.json")
        ]
        if len(keys) != 1:
            raise GAME_MISSING
        return keys[0]

    # -------------------------------------------------------------------------------------------- parties

    def load(
        self, match_id: str, replay_key: str, i: int, viewer: str, version: str = ""
    ) -> tuple[Game, str, tuple[float, float]]:
        """Partie lue (replay compris) et touche `i` : (partie, auteur, balle). La dernière partie reste en mémoire,
        tant que sa version (`matches.updated_at`) ne change pas."""
        last = self.last
        if last is not None and (last.match_id, last.version) == (match_id, version):
            return last, *last.touch(i, viewer)
        with self.game_locks(match_id):
            last = self.last
            if last is not None and (last.match_id, last.version) == (match_id, version):
                return last, *last.touch(i, viewer)
            tmp = Path(tempfile.mkdtemp(prefix="rlpi_clip_"))
            try:
                meta_key = self.meta_key(match_id)
                meta = json.loads(self.download(meta_key, tmp / "meta.json", GAME_MISSING).read_text(encoding="utf-8"))
                tv = self.download(
                    f"games/{match_id}/features/touch_values_{GAME_SOURCE}.parquet",
                    tmp / "touch_values.parquet",
                    GAME_MISSING,
                )
                game = Game(match_id, version, meta, pl.read_parquet(tv, columns=TOUCH_COLUMNS))
                touch = game.touch(i, viewer)  # touche inconnue : 404 sans télécharger le replay
                raw = self.download(replay_key, tmp / "partie.replay", REPLAY_MISSING)
                game.track = clips.read_replay(raw)
                self.replay_reads += 1
                game.cams = self.cameras(meta_key, tmp)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            self.last = game
            return game, *touch

    def cameras(self, meta_key: str, tmp: Path) -> dict | None:
        """Caméras des joueurs, écrites par le worker ; absentes ou illisibles : clip sans caméra."""
        key = meta_key.removesuffix(".meta.json") + ".cameras.json"
        try:
            return json.loads(self.download(key, tmp / "cameras.json", GAME_MISSING).read_text(encoding="utf-8"))
        except ClipError:
            return None  # partie traitée avant le cameras.json, rattrapage pas encore passé
        except Exception as e:  # noqa: BLE001 — stockage indisponible
            log.warning("caméras illisibles (%s) : %s", key, e)
            return None

    # -------------------------------------------------------------------------------------------- clips

    def build(self, match_id: str, replay_key: str, i: int, viewer: str, version: str = "") -> dict:
        game, judged, ball_xy = self.load(match_id, replay_key, i, viewer, version)
        assert game.track is not None
        j = clips.locate(game.track, i, ball_xy)
        if j is None:
            raise NOT_LOCATED
        out = pov.clip(game.track, game.meta, j, judged, BEFORE_S, AFTER_S, cams=game.cams or {})
        if out is None:
            raise AT_EDGE
        return {"id": f"{match_id}:{i}", **out}

    @staticmethod
    def key(match_id: str, version: str, i: int, viewer: str) -> str:
        return json.dumps([match_id, version, i, viewer])

    def clip(self, match_id: str, replay_key: str, i: int, viewer: str, version: str = "") -> bytes:
        """Clip en JSON gzip, gardé en mémoire (les erreurs ne sont pas gardées). `version` : version de la partie
        (`matches.updated_at`), pour ne jamais servir le clip d'une analyse remplacée."""
        return self.clips.compute(
            self.key(match_id, version, i, viewer), lambda: self.build(match_id, replay_key, i, viewer, version)
        )

    async def aclip(self, match_id: str, replay_key: str, i: int, viewer: str, version: str = "") -> bytes:
        """`clip` pour la route asynchrone : clip gardé servi tout de suite, sinon fait dans un thread, au plus
        `MAX_READS` à la fois (les demandes suivantes attendent sans occuper de thread)."""
        gz = self.clips.get(self.key(match_id, version, i, viewer))
        if gz is not None:
            return gz
        return await anyio.to_thread.run_sync(
            partial(self.clip, match_id, replay_key, i, viewer, version), limiter=self.limiter
        )
