"""Worker RLPI : traite les parties de la file d'attente et va chercher les nouvelles parties sur ballchasing.

Tâches de la file Redis (voir rlpi.store) :
    {"type": "match", "match": <id>}   télécharger replays/<id>.replay, lancer rlpi.game run (processus séparé),
                                       envoyer le résultat dans games/<id>/, noter le statut et les 6 joueurs
                                       dans Postgres (matches, match_players)
    {"type": "sync", "player": <id>}   chercher sur ballchasing les nouvelles parties de ce joueur (rlpi.collector)
    {"type": "aggregate", "match": <id>}  (re)calculer les agrégats du tableau de bord d'une partie déjà traitée,
                                       à partir de games/<id>/ (rlpi.dashboard.storage)
    {"type": "swipe", "deck": <id>}    fabriquer un paquet de cartes à juger demandé sur le site (rlpi.swipe_online)

Après chaque partie traitée, le worker calcule ses agrégats (rlpi.dashboard.aggregate) et les écrit dans Postgres :
le serveur n'a plus qu'à les lire. Cinq minutes après son démarrage (RLPI_BACKFILL_DELAY), puis une fois par heure,
un des workers met en file les parties dont les agrégats manquent ou sont d'une version de calcul plus ancienne
(rattrapage automatique après un déploiement). Le délai laisse à Coolify le temps d'arrêter l'ancien worker, qui
jetterait les tâches qu'il ne connaît pas.

Chaque worker signale qu'il est vivant (clé Redis rlpi:worker:vivant:<id>, rafraîchie toutes les 30 s). Les tâches
« en cours » d'un worker sans signal de vie depuis 10 minutes (conteneur supprimé) sont remises en file.

En plus, toutes les RLPI_SYNC_MINUTES (défaut 15), un des workers passe sur tous les joueurs inscrits, et chaque
jour un des workers sauvegarde la base dans Garage (rlpi.backup).
Une tâche interrompue (redémarrage) est remise en file au démarrage ; une partie en erreur est retentée 3 fois.
Une tâche abandonnée (partie en erreur après ses 3 essais, agrégats impossibles, tâche illisible) va en « lettre
morte » (table dead_tasks) avec sa cause : `dead` les liste, `retry` les remet en file.
Un même match envoyé deux fois sur ballchasing (même GUID) n'est compté qu'une fois (statut « doublon »).

Commandes (dans le conteneur du worker, ou via `docker exec <conteneur> …`) :
    python -m rlpi.worker run                         # boucle principale (commande par défaut de l'image)
    python -m rlpi.worker check                       # vérifie modèles, Redis, Postgres, stockage, ballchasing
    python -m rlpi.worker add-player Steam:7656…      # inscrire un joueur sans passer par le site, puis sync
    python -m rlpi.worker sync [--player Steam:…]     # chercher maintenant les nouvelles parties
    python -m rlpi.worker enqueue a.replay …          # traiter des fichiers .replay
    python -m rlpi.worker enqueue --ballchasing-id <id> …
    python -m rlpi.worker status                      # parties par statut, dernières erreurs, joueurs inscrits
    python -m rlpi.worker dead [--all]                # tâches en lettre morte (cause, essais)
    python -m rlpi.worker retry <id> … | --all        # les remettre en file
    python -m rlpi.worker rebuild-aggregates [--all]  # agrégats manquants (ou tous) remis en file
    python -m rlpi.worker rebuild-aggregates --here [--parallel 3]   # … ou calculés tout de suite ici,
                                                      # 3 parties à la fois (téléchargements Garage en parallèle)
    python -m rlpi.worker backfill-cameras            # cameras.json (vue joueur de « ▶ Revoir ») des parties
                                                      # traitées avant lui, une à la fois, processus séparé

Variables d'environnement :
    REDIS_URL, DATABASE_URL                       URL internes données par Coolify
    S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY     Garage ; S3_BUCKET (rlpi), S3_REGION (garage)
    BALLCHASING_TOKEN                             clé API ballchasing du serveur (recherche des parties)
    RLPI_MODELS                                   dossier des modèles (/app/models dans l'image)
    RLPI_SYNC_MINUTES                             intervalle des recherches automatiques (défaut 15, 0 = jamais)
    RLPI_FIRST_SYNC                               parties importées au premier passage d'un joueur (défaut 50)
    RLPI_BC_DOWNLOAD_INTERVAL                     secondes entre deux téléchargements ballchasing, tous workers
                                                  confondus (défaut 18 : compte « regular », 200 par heure)
    RLPI_KEEP_REPLAYS                             1 (défaut) garde le .replay dans le stockage, 0 le supprime
    RLPI_GAME_TIMEOUT                             durée maximale d'une partie en secondes (défaut 900)
    RLPI_SCHEMA_WAIT                              secondes d'attente au démarrage si la base n'est pas encore à
                                                  la version attendue (défaut 300 : le serveur migre au même
                                                  moment, voir rlpi.migrate)
    RLPI_BACKUP_HOUR                              heure UTC de la sauvegarde quotidienne de la base vers Garage
                                                  (défaut 3, « off » : jamais ; voir rlpi.backup)
    RLPI_BACKUP_DAYS, RLPI_BACKUP_MONTHS          rétention des sauvegardes (défaut 14 jours, 6 mois)
    RLPI_BACKFILL_DELAY                           secondes entre le démarrage et le premier rattrapage des
                                                  agrégats (défaut 300)
    RLPI_STATE_MINUTES                            intervalle de la ligne « état » du journal (file, tâches en
                                                  cours, parties bloquées), écrite par un seul worker (défaut 5)
    RLPI_LOG_FORMAT                               json dans l'image (journaux structurés, rlpi.logs) ; les
                                                  commandes autres que run écrivent toujours en texte

Journal : une ligne par événement (rlpi.logs), avec le worker, et la partie (match) quand il y en a une. « fin de
partie » donne la durée de chaque étape (t_replay : récupération du replay, t_analyse : rlpi.game avec le détail
par étape dans `etapes`, t_envoi : envoi vers Garage, t_agregats) ; la ligne « état » donne aussi les parties
terminées dans la dernière heure, leur durée moyenne et le nombre de tâches en lettre morte.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, cast

from rlpi import collector, logs, store
from rlpi.store import PROCESSING, QUEUE, safe

MAX_ATTEMPTS = 3
HEARTBEAT = Path(tempfile.gettempdir()) / "rlpi_worker_heartbeat"
BACKFILL_LOCK = "rlpi:aggregate:backfill:"  # + version du calcul : un seul rattrapage par heure et par version
ALIVE = "rlpi:worker:vivant:"  # + id du worker : signal de vie (clé qui expire, rafraîchie par un fil)
ALIVE_TTL = 90
ALIVE_EVERY = 30
ORPHAN = "rlpi:worker:orphelin:"  # + id : moment où sa liste « en cours » a été vue sans signal de vie
ORPHAN_GRACE = 600  # secondes sans signal de vie avant de remettre ses tâches en file
ORPHAN_CHECK = 60
STATE_LOCK = "rlpi:worker:etat"  # une seule ligne « état » par intervalle, tous workers confondus
STUCK_MINUTES = 30  # une partie « en_cours » depuis plus longtemps est signalée comme bloquée
REQUIRED_MODELS = ["value_h5.txt", "policy_touch.txt", "q_touch.txt", "placement_x.txt", "placement_y.txt",
                   "perf_reference.npz"]


def log(msg: str, level: str = "info", **fields: Any) -> None:
    logs.log(msg, level, **fields)


def models_dir() -> Path:
    from rlpi.config import MODELS

    return MODELS


# --------------------------------------------------------------------------------------------------------------
# Mise en file manuelle


def enqueue_files(files: list[str]) -> None:
    r, cli, b, conn = store.redis_client(), store.s3(), store.bucket(), store.connect()
    for f in map(Path, files):
        if f.suffix.lower() != ".replay" or not f.is_file():
            log(f"ignoré (pas un fichier .replay) : {f}")
            continue
        mid = safe(f.stem)
        key = f"replays/{mid}.replay"
        cli.upload_file(str(f), b, key)
        conn.execute("""INSERT INTO matches (id, source, status, replay_key) VALUES (%s, 'fichier', 'en_attente', %s)
                        ON CONFLICT (id) DO UPDATE SET status = 'en_attente', error = NULL, attempts = 0,
                        updated_at = now()""", (mid, key))
        store.push_match(r, mid)
        log(f"en file : {mid}")


def enqueue_ballchasing(ids: list[str]) -> None:
    from rlpi.config import ballchasing_api

    api, tmp = ballchasing_api(), Path(tempfile.mkdtemp(prefix="rlpi_bc_"))
    try:
        enqueue_files([str(api.download_replay(i, tmp)) for i in ids])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def add_player(player_id: str, name: str | None = None) -> None:
    conn, r = store.connect(), store.redis_client()
    conn.execute("INSERT INTO accounts (player_id, name) VALUES (%s, %s) ON CONFLICT (player_id) DO NOTHING",
                 (player_id, name))
    store.push_sync(r, player_id)
    log(f"joueur inscrit : {player_id} ; recherche de ses parties en file")


# --------------------------------------------------------------------------------------------------------------
# Boucle du worker


def wait_for_schema(timeout: float | None = None) -> None:
    """Au démarrage : attend que la base soit à la version attendue (le serveur lance les migrations Flyway au
    même moment lors d'un déploiement), puis s'arrête avec un message clair si elle ne l'est toujours pas."""
    timeout = float(os.getenv("RLPI_SCHEMA_WAIT", "300")) if timeout is None else timeout
    end = time.time() + timeout
    while True:
        try:
            store.connect().close()
            return
        except store.SchemaError as e:
            if time.time() >= end:
                raise SystemExit(f"Arrêt du worker : {e}") from None
            log(f"en attente des migrations : {e}")
            time.sleep(10)


class Worker:
    def __init__(self) -> None:
        self.id = safe(os.getenv("RLPI_WORKER_ID") or socket.gethostname())
        self.processing = PROCESSING + self.id
        self.stop = False
        self.keep_replays = os.getenv("RLPI_KEEP_REPLAYS", "1").strip() != "0"
        self.timeout = float(os.getenv("RLPI_GAME_TIMEOUT", "900"))
        self.sync_every = float(os.getenv("RLPI_SYNC_MINUTES", "15")) * 60
        self.last_sync = 0.0
        self.state_every = float(os.getenv("RLPI_STATE_MINUTES", "5")) * 60
        self.last_state = 0.0
        self.last_backup_check = 0.0
        # Rattrapage des agrégats décalé : au redéploiement, l'ancien worker tourne encore quelques instants et
        # jetterait les tâches qu'il ne connaît pas. Ensuite, un passage par heure (verrou commun).
        self.next_backfill = time.time() + float(os.getenv("RLPI_BACKFILL_DELAY", "300"))
        self.last_orphan_check = 0.0
        self.alive_stop = threading.Event()
        logs.configure("worker", worker=self.id)
        self.r, self.s3, self.bucket = store.redis_client(), store.s3(), store.bucket()
        self.conn = store.connect()

    def bc_api(self) -> Any:
        if getattr(self, "_bc", None) is None:
            from rlpi.config import ballchasing_api

            self._bc = ballchasing_api()
        return self._bc

    # Arrêt propre : Coolify envoie SIGTERM au redéploiement ; on finit la tâche en cours.
    def _on_signal(self, *_: object) -> None:
        log("arrêt demandé : fin de la tâche en cours puis sortie")
        self.stop = True

    def recover(self) -> None:
        """Remet dans la file les tâches restées « en cours » chez ce worker (arrêt brutal précédent)."""
        n = 0
        while self.r.lmove(self.processing, QUEUE, "RIGHT", "RIGHT"):  # reprises traitées en premier
            n += 1
        if n:
            log(f"{n} tâche(s) interrompue(s) remise(s) dans la file")

    def beat(self) -> None:
        self.r.set(ALIVE + self.id, "1", ex=ALIVE_TTL)

    def _alive_loop(self) -> None:
        """Fil : signal de vie toutes les ALIVE_EVERY secondes, même pendant une longue partie."""
        while not self.alive_stop.wait(ALIVE_EVERY):
            try:
                self.beat()
            except Exception as e:  # noqa: BLE001 — Redis indisponible un instant : on réessaie au tour suivant
                log("signal de vie : échec", "warning", erreur=f"{type(e).__name__}: {e}"[:300])

    def reclaim_orphans(self) -> int:
        """Remet en file les tâches « en cours » d'un worker disparu (aucun signal de vie depuis ORPHAN_GRACE
        secondes : conteneur supprimé au redéploiement, machine arrêtée). Retourne le nombre de tâches reprises."""
        now, n = time.time(), 0
        for key in list(self.r.scan_iter(PROCESSING + "*")):
            wid = str(key)[len(PROCESSING):]
            if wid == self.id:
                continue
            if self.r.exists(ALIVE + wid):
                self.r.delete(ORPHAN + wid)
                continue
            self.r.set(ORPHAN + wid, str(now), nx=True, ex=ORPHAN_GRACE * 6)
            seen = float(cast("str", self.r.get(ORPHAN + wid)) or now)
            if now - seen < ORPHAN_GRACE:
                continue
            k = 0
            while self.r.lmove(key, QUEUE, "RIGHT", "RIGHT"):  # traitées en premier, comme une reprise
                k += 1
            self.r.delete(ORPHAN + wid)
            if k:
                log(f"{k} tâche(s) du worker disparu {wid} remise(s) dans la file", worker_disparu=wid)
            n += k
        return n

    def set_status(self, mid: str, status: str, **fields) -> None:
        from psycopg import sql
        from psycopg.types.json import Jsonb

        cols = sql.SQL("").join(sql.SQL(", {} = %s").format(sql.Identifier(k)) for k in fields)
        vals = [Jsonb(v) if k == "result" else v for k, v in fields.items()]
        self.conn.execute(sql.SQL("UPDATE matches SET status = %s{}, worker = %s, updated_at = now() WHERE id = %s")
                          .format(cols), [status, *vals, self.id, mid])

    def upload_dir(self, local: Path, prefix: str) -> int:
        n = 0
        for f in local.rglob("*"):
            if f.is_file():
                self.s3.upload_file(str(f), self.bucket, f"{prefix}/{f.relative_to(local).as_posix()}")
                n += 1
        return n

    def requeue(self, raw: str, attempts: int, mid: str, error: str | None) -> None:
        """Nouvel essai d'une partie en erreur, ou lettre morte après MAX_ATTEMPTS essais."""
        if attempts < MAX_ATTEMPTS:
            self.r.lpush(QUEUE, raw)
            log(f"remise en file ({attempts}/{MAX_ATTEMPTS})", match=mid)
            time.sleep(5)
        else:
            self.bury("match", mid, raw, error or "erreur inconnue", attempts)

    def bury(self, kind: str, ref: str | None, raw: str, error: str, attempts: int = 1,
             version: int | None = None) -> None:
        """Tâche abandonnée → lettre morte (dead_tasks), consultable avec `dead`, relançable avec `retry`.
        version : celle du calcul des agrégats (tâches aggregate) ; le rattrapage les reprend quand elle change."""
        from psycopg.types.json import Jsonb

        try:
            task = json.loads(raw)
        except ValueError:
            task = {"brut": raw[:2000]}
        try:
            self.conn.execute(
                "INSERT INTO dead_tasks (kind, ref, task, error, attempts, worker, version) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (kind, ref, Jsonb(task), error[:4000], attempts, self.id, version),
            )
        except Exception as e:  # noqa: BLE001 — la tâche reste au moins visible dans le journal
            log("lettre morte : écriture impossible", "error", erreur=f"{type(e).__name__}: {e}"[:300])
        log("lettre morte", "error", type=kind, match=ref, essais=attempts, erreur=error[:300])

    def process_match(self, raw: str, mid: str) -> None:
        from rlpi import game

        row = self.conn.execute("UPDATE matches SET status = 'en_cours', attempts = attempts + 1, worker = %s, "
                                "updated_at = now() WHERE id = %s RETURNING attempts, replay_key",
                                (self.id, mid)).fetchone()
        if row is None:
            log(f"partie inconnue dans Postgres, ignorée : {mid}")
            return
        attempts, key = row
        log("début de partie", match=mid, essai=attempts)
        tmp = Path(tempfile.mkdtemp(prefix="rlpi_"))
        err: str | None = None
        try:
            t = time.time()
            if not key:  # partie trouvée sur ballchasing : on la télécharge maintenant (limite commune de débit)
                key = collector.fetch_replay(mid, self.conn, self.r, self.s3, self.bc_api())
            local = tmp / f"{mid}.replay"
            self.s3.download_file(self.bucket, key, str(local))
            t_replay = round(time.time() - t, 2)
            out = tmp / "partie"
            res = game.run(local, out, models_dir(), timeout=self.timeout)
            status = res["status"] if res["status"] in ("ok", "partiel", "rejetee") else "erreur"
            guid = res.get("match_guid")
            if status in ("ok", "partiel") and guid:
                dup = self.conn.execute("SELECT id FROM matches WHERE match_guid = %s AND id <> %s AND status IN "
                                        "('ok', 'partiel')", (guid, mid)).fetchone()
                if dup:
                    status = "doublon"
                    res["doublon_de"] = dup[0]
            t = time.time()
            n = self.upload_dir(out, f"games/{mid}") if status in ("ok", "partiel") else 0
            t_envoi = round(time.time() - t, 2)
            t_agregats = None
            err = res.get("reason") or (json.dumps(res["errors"], ensure_ascii=False) if res.get("errors") else None)
            if status == "erreur":
                err = res.get("error", "erreur inconnue")[-2000:]
            summary = {k: v for k, v in res.items() if not k.startswith("traceback_")}
            self.set_status(mid, status, result=summary, error=err, wall_s=res.get("wall_s"), match_guid=guid,
                            played_at=store.played_at(res.get("date")))
            if status in ("ok", "partiel"):
                self.conn.execute("DELETE FROM match_players WHERE match_id = %s", (mid,))
                for p in res.get("players", []):
                    self.conn.execute("INSERT INTO match_players (match_id, player_id, player_name, team) "
                                      "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                                      (mid, p["id"], p.get("name"), p.get("team")))
                t = time.time()
                self.aggregate_dir(mid, out)
                t_agregats = round(time.time() - t, 2)
            if status != "erreur" and not self.keep_replays:
                self.s3.delete_object(Bucket=self.bucket, Key=key)
            log("fin de partie", "error" if status == "erreur" else "info", match=mid, statut=status,
                duree_s=res.get("wall_s"), fichiers=n, t_replay=t_replay, t_analyse=res.get("wall_s"),
                t_envoi=t_envoi, t_agregats=t_agregats, etapes=res.get("steps") or None,
                erreur=err[:200] if err else None)
            if status == "erreur":
                self.requeue(raw, attempts, mid, err)
        except Exception as e:  # noqa: BLE001 — stockage ou base indisponible, replay introuvable…
            msg = f"{type(e).__name__}: {e}"[:2000]
            log("échec de partie", "error", match=mid, erreur=msg)
            try:
                self.set_status(mid, "erreur", error=msg)
            except Exception as e2:  # noqa: BLE001
                log("impossible de noter l'erreur dans Postgres", "error", match=mid, erreur=str(e2)[:300])
            self.requeue(raw, attempts, mid, msg)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def aggregate_dir(self, mid: str, out: Path) -> None:
        """Agrégats du tableau de bord d'une partie qui vient d'être traitée (dossier local, rien à télécharger).
        Un échec n'annule pas la partie : elle sera reprise au prochain rattrapage."""
        from rlpi.dashboard import aggregate, storage

        t = time.time()
        try:
            agg = aggregate.compute(aggregate.from_game_dir(out, mid))
            storage.write(self.conn, agg)
            log("agrégats écrits", match=mid, duree_s=round(time.time() - t, 2))
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            log("agrégats : échec", "error", match=mid, erreur=msg[:500])
            self.bury("aggregate", mid, json.dumps({"type": "aggregate", "match": mid}), msg,
                      version=aggregate.VERSION)
            return
        self.announce(mid, agg)

    def announce(self, mid: str, agg: dict) -> None:
        """« Nouveau match traité » pour les joueurs inscrits de la partie (voir rlpi.events). Un échec ne change
        rien à la partie : le tableau de bord le verra à sa prochaine lecture."""
        from rlpi import events

        try:
            events.publish_match(self.r, self.conn, mid, sorted(agg["players"]))
        except Exception as e:  # noqa: BLE001
            log("annonce : échec", "warning", match=mid, erreur=f"{type(e).__name__}: {e}"[:300])

    def process_aggregate(self, mid: str, raw: str) -> None:
        from rlpi.dashboard import aggregate, storage

        if storage.is_current(self.conn, mid):
            return
        t = time.time()
        try:
            agg = storage.compute_match(self.conn, self.s3, self.bucket, mid)
            log("agrégats écrits", match=mid, duree_s=round(time.time() - t, 2))
        except Exception as e:  # noqa: BLE001 — pas de nouvel essai automatique : lettre morte
            msg = f"{type(e).__name__}: {e}"
            log("agrégats : échec", "error", match=mid, erreur=msg[:500])
            self.bury("aggregate", mid, raw, msg, version=aggregate.VERSION)
            return
        self.announce(mid, agg)

    def process_swipe(self, deck_id: int) -> None:
        """Paquet de cartes à juger demandé sur le site (voir rlpi.swipe_online). Pas de nouvel essai : le joueur
        voit l'erreur et peut demander un autre paquet."""
        from rlpi import swipe_online

        t = time.time()
        try:
            n = swipe_online.build(self.conn, self.s3, self.bucket, deck_id, log)
            log("paquet swipe prêt", paquet=deck_id, cartes=n, duree_s=round(time.time() - t))
        except Exception as e:  # noqa: BLE001
            log("paquet swipe : échec", "error", paquet=deck_id, erreur=f"{type(e).__name__}: {e}"[:500])

    def backfill(self) -> None:
        """Met en file les parties sans agrégats à jour (un seul worker, une fois par heure et par version), sauf
        celles dont le calcul de cette version attend en lettre morte (relancer avec `retry`)."""
        from rlpi.dashboard import aggregate, storage

        if not self.r.set(BACKFILL_LOCK + str(aggregate.VERSION), self.id, nx=True, ex=3600):
            return
        ids = storage.missing(self.conn, skip_dead=True)
        for mid in ids:
            self.r.lpush(QUEUE, json.dumps({"type": "aggregate", "match": mid}))
        if ids:
            log(f"rattrapage : {len(ids)} partie(s) sans agrégats à jour mise(s) en file", parties=len(ids))

    def report_state(self) -> None:
        """Ligne « état » du journal : taille de la file, tâches en cours, parties bloquées « en_cours », erreurs
        des dernières 24 h. Un seul worker l'écrit par intervalle (verrou Redis)."""
        try:
            if not self.r.set(STATE_LOCK, self.id, nx=True, ex=max(int(self.state_every) - 10, 30)):
                return
            busy = sum(int(cast("int", self.r.llen(k))) for k in self.r.scan_iter(PROCESSING + "*"))
            row = self.conn.execute(
                "SELECT count(*) FILTER (WHERE status = 'en_cours' AND updated_at < now() - make_interval(mins => %s)),"
                " count(*) FILTER (WHERE status = 'erreur' AND updated_at > now() - interval '24 hours'),"
                " count(*) FILTER (WHERE status IN ('ok', 'partiel', 'doublon', 'rejetee')"
                "                  AND updated_at > now() - interval '1 hour'),"
                " avg(wall_s) FILTER (WHERE status IN ('ok', 'partiel') AND updated_at > now() - interval '1 hour'),"
                " (SELECT count(*) FROM dead_tasks WHERE retried_at IS NULL) FROM matches",
                (STUCK_MINUTES,),
            ).fetchone()
            stuck, errors, per_hour, avg_s, dead = row if row else (0, 0, 0, None, 0)
            log("état", "warning" if stuck or dead else "info", file=int(cast("int", self.r.llen(QUEUE))),
                en_cours=busy, bloquees=stuck, erreurs_24h=errors, parties_1h=per_hour,
                duree_moy_s_1h=round(float(avg_s), 1) if avg_s is not None else None, lettre_morte=dead)
        except Exception as e:  # noqa: BLE001 — jamais bloquant
            log("état : échec", "warning", erreur=f"{type(e).__name__}: {e}"[:300])

    def process(self, raw: str) -> None:
        try:
            task = json.loads(raw)
            if not isinstance(task, dict):
                raise ValueError("pas un objet JSON")
        except ValueError as e:
            self.bury("illisible", None, raw, f"tâche illisible : {e}")
            return
        if task.get("type") == "sync":
            try:
                collector.sync_player(task["player"], log, self.conn, self.r, api=self.bc_api())
            except Exception as e:  # noqa: BLE001
                log("sync : échec", "error", joueur=task["player"], erreur=f"{type(e).__name__}: {e}"[:500])
        elif task.get("type") == "match":
            self.process_match(raw, task["match"])
        elif task.get("type") == "aggregate":
            self.process_aggregate(task["match"], raw)
        elif task.get("type") == "swipe":
            self.process_swipe(int(task["deck"]))
        else:
            self.bury("inconnue", None, raw, f"type de tâche inconnu : {task.get('type')!r}")

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        missing = [m for m in REQUIRED_MODELS if not (models_dir() / m).exists()]
        if missing:
            raise SystemExit(f"Modèles manquants dans {models_dir()} : {', '.join(missing)}")
        self.beat()
        threading.Thread(target=self._alive_loop, name="vivant", daemon=True).start()
        self.recover()
        log(f"worker {self.id} prêt (modèles : {models_dir()}, recherche ballchasing toutes les "
            f"{self.sync_every / 60:.0f} min)")
        try:
            self.loop()
        finally:
            self.alive_stop.set()
            try:
                self.r.delete(ALIVE + self.id)
            except Exception:  # noqa: BLE001, S110 — la clé expirera d'elle-même
                pass
        log("worker arrêté")

    def loop(self) -> None:
        while not self.stop:
            HEARTBEAT.touch()
            if time.time() >= self.next_backfill:
                self.next_backfill = time.time() + 600  # verrou d'une heure : la plupart des passages ne font rien
                try:
                    self.backfill()
                except Exception as e:  # noqa: BLE001
                    log("rattrapage des agrégats : échec", "error", erreur=f"{type(e).__name__}: {e}"[:500])
            if time.time() - self.last_orphan_check > ORPHAN_CHECK:
                self.last_orphan_check = time.time()
                try:
                    self.reclaim_orphans()
                except Exception as e:  # noqa: BLE001
                    log("reprise des tâches orphelines : échec", "warning", erreur=f"{type(e).__name__}: {e}"[:300])
            if self.sync_every and time.time() - self.last_sync > self.sync_every and os.getenv("BALLCHASING_TOKEN"):
                self.last_sync = time.time()
                try:
                    collector.sync_all(log, self.conn, self.r)
                except Exception as e:  # noqa: BLE001
                    log("recherche automatique : échec", "error", erreur=f"{type(e).__name__}: {e}"[:500])
            if time.time() - self.last_backup_check > 300:
                self.last_backup_check = time.time()
                from rlpi import backup

                backup.maybe_run(self.r, self.id)
            if self.state_every and time.time() - self.last_state > self.state_every:
                self.last_state = time.time()
                self.report_state()
            raw = cast("str | None", self.r.blmove(QUEUE, self.processing, timeout=20, src="RIGHT", dest="LEFT"))
            if raw is None:
                continue
            self.process(raw)
            self.r.lrem(self.processing, 1, raw)


# --------------------------------------------------------------------------------------------------------------
# Contrôles


def check() -> None:
    ok = True

    def line(name: str, fn) -> None:
        nonlocal ok
        try:
            log(f"OK      {name} : {fn()}")
        except BaseException as e:  # noqa: BLE001
            ok = False
            log(f"ÉCHEC   {name} : {type(e).__name__}: {e}")

    def models() -> str:
        import subtr_actor  # noqa: F401 — le parseur de replays est installé

        missing = [m for m in REQUIRED_MODELS if not (models_dir() / m).exists()]
        if missing:
            raise FileNotFoundError(f"manquants dans {models_dir()} : {', '.join(missing)}")
        return f"{len(REQUIRED_MODELS)} fichiers présents dans {models_dir()}"

    def red() -> str:
        r = store.redis_client()
        r.ping()
        return f"connecté, {r.llen(QUEUE)} tâche(s) en file"

    def pg() -> str:
        with store.connect() as c:
            n = store.scalar(c, "SELECT count(*) FROM matches")
            a = store.scalar(c, "SELECT count(*) FROM accounts")
            return f"connecté, {n} partie(s), {a} joueur(s) inscrit(s)"

    def stockage() -> str:
        cli, b = store.s3(), store.bucket()
        cli.put_object(Bucket=b, Key="_check/ping.txt", Body=b"ok")
        cli.delete_object(Bucket=b, Key="_check/ping.txt")
        return f"bucket {b} : écriture et suppression OK"

    def ballchasing() -> str:
        from rlpi.config import ballchasing_api

        info = ballchasing_api().ping()
        return f"clé valide (compte {info.get('name')}, abonné : {'oui' if info.get('chaser') else 'non'})"

    line("modèles", models)
    line("Redis", red)
    line("Postgres", pg)
    line("stockage", stockage)
    line("ballchasing", ballchasing)
    sys.exit(0 if ok else 1)


def status() -> None:
    with store.connect() as c:
        for st, n, avg in c.execute("SELECT status, count(*), avg(wall_s) FROM matches GROUP BY status "
                                    "ORDER BY status").fetchall():
            log(f"{st:<11} {n:>5} partie(s)" + (f", {avg:.1f} s en moyenne" if avg else ""))
        for mid, st, err in c.execute("SELECT id, status, error FROM matches WHERE error IS NOT NULL "
                                      "ORDER BY updated_at DESC LIMIT 5").fetchall():
            log(f"  {mid} [{st}] {err[:200]}")
        for pid, name, last, n in c.execute(
                "SELECT a.player_id, a.name, a.last_sync, (SELECT count(*) FROM match_players mp JOIN matches m "
                "ON m.id = mp.match_id WHERE mp.player_id = a.player_id AND m.status IN ('ok', 'partiel')) "
                "FROM accounts a ORDER BY a.created_at").fetchall():
            log(f"joueur {pid} ({name or '?'}) : {n} partie(s) traitée(s), dernière recherche {last or 'jamais'}")
        dead = store.scalar(c, "SELECT count(*) FROM dead_tasks WHERE retried_at IS NULL")
    log(f"file Redis : {store.redis_client().llen(QUEUE)} tâche(s) en attente")
    if dead:
        log(f"lettre morte : {dead} tâche(s) abandonnée(s) — python -m rlpi.worker dead")


def dead(show_all: bool = False, limit: int = 50) -> None:
    """Tâches en lettre morte, les plus récentes d'abord (seulement celles pas encore relancées, sauf --all)."""
    with store.connect() as c:
        rows = c.execute(
            "SELECT id, created_at, kind, ref, attempts, worker, error, retried_at FROM dead_tasks "
            + ("" if show_all else "WHERE retried_at IS NULL ")
            + "ORDER BY created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
    for i, at, kind, ref, attempts, worker, error, retried in rows:
        state = f" (relancée le {retried:%d/%m %H:%M})" if retried else ""
        log(f"#{i} {at:%d/%m %H:%M} {kind} {ref or '-'} : {attempts} essai(s), {worker or '?'}{state}")
        log(f"     {error[:300]}")
    log(f"{len(rows)} tâche(s)" + ("" if show_all else " en attente ; relancer : python -m rlpi.worker retry <id> | --all"))


def retry(ids: list[int], everything: bool) -> int:
    """Remet en file des tâches en lettre morte (une partie repart avec 0 essai) ; retourne leur nombre."""
    conn, r = store.connect(), store.redis_client()
    if everything:
        rows = conn.execute("SELECT id, kind, ref, task FROM dead_tasks WHERE retried_at IS NULL ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT id, kind, ref, task FROM dead_tasks WHERE retried_at IS NULL AND id = ANY(%s) ORDER BY id", (ids,)
        ).fetchall()
    for i, kind, ref, task in rows:
        if kind == "match" and ref:
            conn.execute(
                "UPDATE matches SET status = 'en_attente', attempts = 0, error = NULL, updated_at = now() "
                "WHERE id = %s",
                (ref,),
            )
        r.lpush(QUEUE, json.dumps(task))
        conn.execute("UPDATE dead_tasks SET retried_at = now() WHERE id = %s", (i,))
        log(f"#{i} remise en file : {kind} {ref or '-'}")
    log(f"{len(rows)} tâche(s) remise(s) en file")
    return len(rows)


def rebuild_aggregates(everything: bool, here: bool, parallel: int = 3) -> None:
    from rlpi.dashboard import storage

    conn = store.connect()
    ids = storage.missing(conn, everything)
    if not here:
        r = store.redis_client()
        for mid in ids:
            r.lpush(QUEUE, json.dumps({"type": "aggregate", "match": mid}))
        log(f"{len(ids)} partie(s) mise(s) en file pour leurs agrégats")
        return
    cli, b = store.s3(), store.bucket()
    t0 = time.time()

    def done(k: int, mid: str, err: Exception | None) -> None:
        if err:
            log("agrégats : échec", "error", match=mid, erreur=f"{type(err).__name__}: {err}"[:500])
        if k % 10 == 0 or k == len(ids):
            log(f"{k}/{len(ids)} parties ({time.time() - t0:.0f} s)")

    ok = storage.rebuild(conn, cli, b, ids, parallel, done)
    log(f"reconstruction : {ok}/{len(ids)} partie(s) en {time.time() - t0:.1f} s ({parallel} à la fois)")


def backfill_cameras() -> dict[str, int]:
    """Dépose le `<replay>.cameras.json` des parties traitées avant lui (vue joueur du bouton « ▶ Revoir »).

    Une partie à la fois, chaque lecture (environ 250 Mo) dans un processus séparé (rlpi.game.cameras) : le serveur
    web ne lit jamais les caméras lui-même. Sans risque à relancer : les parties qui l'ont déjà sont passées, comme
    celles dont le replay n'est plus gardé (RLPI_KEEP_REPLAYS=0)."""
    from rlpi import game
    from rlpi.web.clips import is_missing

    conn, cli, b = store.connect(), store.s3(), store.bucket()
    rows = conn.execute("SELECT id, replay_key FROM matches WHERE status IN ('ok', 'partiel') ORDER BY id").fetchall()
    counts = {"faites": 0, "deja_la": 0, "sans_replay": 0, "echecs": 0}
    t0 = time.time()
    for k, (mid, key) in enumerate(rows, 1):
        if k % 10 == 0:
            log(f"caméras : {k}/{len(rows)} parties vues ({time.time() - t0:.0f} s)")
        prefix = f"games/{mid}/frames/{game.GAME_SOURCE}/"
        keys = {o["Key"] for page in cli.get_paginator("list_objects_v2").paginate(Bucket=b, Prefix=prefix)
                for o in page.get("Contents", [])}
        metas = [x for x in keys if x.endswith(".meta.json")]
        if len(metas) != 1:
            continue  # partie sans données dans le stockage : rien à compléter
        dest = metas[0].removesuffix(".meta.json") + ".cameras.json"
        if dest in keys:
            counts["deja_la"] += 1
            continue
        tmp = Path(tempfile.mkdtemp(prefix="rlpi_cam_"))
        try:
            local = tmp / f"{mid}.replay"
            try:
                cli.download_file(b, key or f"replays/{mid}.replay", str(local))
            except Exception as e:  # noqa: BLE001
                if not is_missing(e):
                    raise
                counts["sans_replay"] += 1
                continue
            try:
                game.cameras(local, tmp / "cameras.json")
            except Exception as e:  # noqa: BLE001 — replay sans caméras lisibles : le clip part sans caméra
                counts["echecs"] += 1
                log("caméras : échec", "error", match=mid, erreur=f"{type(e).__name__}: {e}"[:500])
                continue
            cli.put_object(Bucket=b, Key=dest, Body=(tmp / "cameras.json").read_bytes())
            counts["faites"] += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    log(f"caméras : {counts['faites']} déposée(s), {counts['deja_la']} déjà là, {counts['sans_replay']} sans "
        f"replay, {counts['echecs']} échec(s) en {time.time() - t0:.0f} s")
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description="Worker RLPI")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run")
    sub.add_parser("check")
    sub.add_parser("status")
    s = sub.add_parser("add-player")
    s.add_argument("player_id", help="identifiant comme dans les replays, ex. Steam:7656119800000000x")
    s.add_argument("--name")
    s = sub.add_parser("sync")
    s.add_argument("--player", help="un seul joueur (sinon tous)")
    s = sub.add_parser("enqueue")
    s.add_argument("files", nargs="*")
    s.add_argument("--ballchasing-id", nargs="+", default=[], metavar="ID", help="identifiants de replays ballchasing")
    s = sub.add_parser("dead", help="tâches en lettre morte")
    s.add_argument("--all", action="store_true", help="aussi celles déjà relancées")
    s.add_argument("--limit", type=int, default=50)
    s = sub.add_parser("retry", help="remettre en file des tâches en lettre morte")
    s.add_argument("ids", nargs="*", type=int, help="numéros donnés par « dead »")
    s.add_argument("--all", action="store_true", help="toutes celles en attente")
    s = sub.add_parser("rebuild-aggregates", help="(re)calculer les agrégats du tableau de bord")
    s.add_argument("--all", action="store_true", help="toutes les parties traitées, pas seulement celles à mettre à jour")
    s.add_argument("--here", action="store_true", help="calculer dans ce processus au lieu de mettre en file")
    s.add_argument("--parallel", type=int, default=3, help="avec --here : parties traitées à la fois (défaut 3)")
    sub.add_parser("backfill-cameras", help="déposer les caméras (vue joueur) des parties traitées avant elles")
    a = ap.parse_args()
    if a.cmd not in (None, "run"):
        os.environ["RLPI_LOG_FORMAT"] = "texte"  # commandes lancées à la main : sortie lisible
    if a.cmd in (None, "run"):
        logs.configure("worker")
        wait_for_schema()
        Worker().run()
    elif a.cmd == "check":
        check()
    elif a.cmd == "status":
        status()
    elif a.cmd == "add-player":
        add_player(a.player_id, a.name)
    elif a.cmd == "dead":
        dead(a.all, a.limit)
    elif a.cmd == "retry":
        if not (a.ids or a.all):
            ap.error("donner des numéros (voir « dead ») ou --all")
        retry(a.ids, a.all)
    elif a.cmd == "rebuild-aggregates":
        rebuild_aggregates(a.all, a.here, max(1, a.parallel))
    elif a.cmd == "backfill-cameras":
        backfill_cameras()
    elif a.cmd == "sync":
        n = collector.sync_player(a.player, log) if a.player else collector.sync_all(log)
        log(f"{n} partie(s) mise(s) en file")
    else:
        if not (a.files or a.ballchasing_id):
            ap.error("donner des fichiers .replay ou --ballchasing-id ID…")
        if a.ballchasing_id:
            enqueue_ballchasing(a.ballchasing_id)
        if a.files:
            enqueue_files(a.files)


if __name__ == "__main__":
    main()
