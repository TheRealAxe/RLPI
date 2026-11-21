"""Worker : traitement de tâches simulées (file Redis, statuts Postgres, reprise, essais, doublons).

Redis est simulé (fakeredis), le stockage S3 aussi ; l'analyse d'une partie (rlpi.game.run) est remplacée par une
fonction qui écrit une sortie minimale. Postgres est réel (base de test migrée).
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import fakeredis
import psycopg
import pytest

from rlpi import game, store, worker

PLAYERS = [{"slot": i, "id": f"Steam:7656119000000010{i}", "name": f"Joueur {i}", "team": i // 3} for i in range(6)]


class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload_file(self, path, bucket, key):
        self.objects[key] = Path(path).read_bytes()

    def download_file(self, bucket, key, path):
        if key not in self.objects:
            raise FileNotFoundError(key)
        Path(path).write_bytes(self.objects[key])

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body

    def get_paginator(self, name):
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in sorted(objects) if k.startswith(Prefix)]}

        return Paginator()


@pytest.fixture
def env(db, monkeypatch, tmp_path):
    r, s3 = fakeredis.FakeRedis(decode_responses=True), FakeS3()
    monkeypatch.setattr(store, "redis_client", lambda: r)
    monkeypatch.setattr(store, "s3", lambda: s3)
    monkeypatch.setenv("RLPI_WORKER_ID", "test-1")
    monkeypatch.setenv("RLPI_SYNC_MINUTES", "0")
    monkeypatch.setenv("RLPI_STATE_MINUTES", "0")  # ligne « état » appelée à la main dans les tests
    monkeypatch.setenv("RLPI_BACKUP_HOUR", "off")
    monkeypatch.setenv("RLPI_BACKFILL_DELAY", "3600")  # rattrapage des agrégats : seulement dans ses tests
    monkeypatch.setattr(worker.time, "sleep", lambda s: None)
    models = tmp_path / "models"
    models.mkdir()
    for m in worker.REQUIRED_MODELS:
        (models / m).write_bytes(b"")
    monkeypatch.setattr(worker, "models_dir", lambda: models)
    monkeypatch.setattr(worker, "HEARTBEAT", tmp_path / "heartbeat")
    return r, s3


def fake_game(status="ok", guid="GUID-1"):
    def run(replay, out, models, timeout=None):
        assert Path(replay).read_bytes() == b"replay"
        (Path(out) / "features").mkdir(parents=True)
        (Path(out) / "features" / "player_match_stats_partie.parquet").write_bytes(b"parquet")
        (Path(out) / "result.json").write_text("{}", encoding="utf-8")
        res = {"status": status, "match_guid": guid, "date": "2026-11-01 20-00-00", "players": PLAYERS, "wall_s": 1.5}
        if status == "erreur":
            res["error"] = "Traceback : plantage simulé"
        return res

    return run


def add_match(db, s3, mid: str, status="en_attente"):
    s3.objects[f"replays/{mid}.replay"] = b"replay"
    with psycopg.connect(db, autocommit=True) as c:
        c.execute(
            "INSERT INTO matches (id, source, status, replay_key) VALUES (%s, 'fichier', %s, %s)",
            (mid, status, f"replays/{mid}.replay"),
        )


def run_tasks(n: int) -> worker.Worker:
    """Lance la vraie boucle du worker et l'arrête après n tâches."""
    w = worker.Worker()
    done = []
    orig = w.process

    def process(raw):
        orig(raw)
        done.append(raw)
        if len(done) >= n:
            w.stop = True

    w.process = process
    w.run()
    return w


def row(db, mid):
    with psycopg.connect(db) as c:
        return c.execute(
            "SELECT status, attempts, worker, match_guid, played_at, error FROM matches WHERE id = %s", (mid,)
        ).fetchone()


def n_players(db, mid):
    with psycopg.connect(db) as c:
        return c.execute("SELECT count(*) FROM match_players WHERE match_id = %s", (mid,)).fetchone()[0]


def test_partie_traitee(env, db, monkeypatch):
    r, s3 = env
    monkeypatch.setattr(game, "run", fake_game())
    add_match(db, s3, "m1")
    store.push_match(r, "m1")
    run_tasks(1)
    assert row(db, "m1") == ("ok", 1, "test-1", "GUID-1", datetime(2026, 11, 1, 20, tzinfo=UTC), None)
    assert n_players(db, "m1") == 6
    assert {"games/m1/result.json", "games/m1/features/player_match_stats_partie.parquet"} <= set(s3.objects)
    assert "replays/m1.replay" in s3.objects  # gardé par défaut (RLPI_KEEP_REPLAYS=1)
    assert r.llen(store.QUEUE) == 0 and r.llen(store.PROCESSING + "test-1") == 0


def test_erreur_remise_en_file_puis_abandon(env, db, monkeypatch):
    r, s3 = env
    monkeypatch.setattr(game, "run", fake_game("erreur"))
    add_match(db, s3, "m2")
    store.push_match(r, "m2")
    run_tasks(worker.MAX_ATTEMPTS)
    status, attempts, *_, err = row(db, "m2")
    assert (status, attempts) == ("erreur", worker.MAX_ATTEMPTS) and "plantage simulé" in err
    assert r.llen(store.QUEUE) == 0  # plus remise en file après le dernier essai
    assert not any(k.startswith("games/m2/") for k in s3.objects)
    # … mais en lettre morte, avec sa cause, puis relancée à la main avec 0 essai
    (dead_id, kind, task, attempts, error) = dead_rows(db)[0]
    assert (kind, task, attempts) == ("match", {"type": "match", "match": "m2"}, worker.MAX_ATTEMPTS)
    assert "plantage simulé" in error
    assert worker.retry([dead_id], False) == 1
    assert row(db, "m2")[:2] == ("en_attente", 0) and json.loads(r.lpop(store.QUEUE)) == task
    assert dead_rows(db) == [] and worker.retry([], True) == 0  # plus rien en attente


def test_replay_introuvable(env, db, monkeypatch):
    r, s3 = env
    monkeypatch.setattr(game, "run", fake_game())
    add_match(db, s3, "m3")
    del s3.objects["replays/m3.replay"]
    store.push_match(r, "m3")
    run_tasks(1)
    status, attempts, *_, err = row(db, "m3")
    assert (status, attempts) == ("erreur", 1) and "FileNotFoundError" in err
    assert r.llen(store.QUEUE) == 1  # retentée plus tard


def test_doublon(env, db, monkeypatch):
    r, s3 = env
    monkeypatch.setattr(game, "run", fake_game(guid="GUID-X"))
    add_match(db, s3, "a")
    add_match(db, s3, "b")
    store.push_match(r, "a")
    store.push_match(r, "b")
    run_tasks(2)
    assert row(db, "a")[0] == "ok" and row(db, "b")[0] == "doublon"
    assert n_players(db, "b") == 0 and not any(k.startswith("games/b/") for k in s3.objects)
    with psycopg.connect(db) as c:
        assert c.execute("SELECT result->>'doublon_de' FROM matches WHERE id = 'b'").fetchone()[0] == "a"


def test_reprise_apres_arret_brutal(env, db, monkeypatch):
    r, s3 = env
    monkeypatch.setattr(game, "run", fake_game())
    add_match(db, s3, "m4", status="en_cours")
    # Tâche restée « en cours » chez ce worker (arrêt brutal pendant le traitement)
    r.lpush(store.PROCESSING + "test-1", json.dumps({"type": "match", "match": "m4"}))
    run_tasks(1)
    assert row(db, "m4")[:2] == ("ok", 1)
    assert r.llen(store.PROCESSING + "test-1") == 0


def dead_rows(db) -> list[tuple]:
    with psycopg.connect(db) as c:
        return c.execute(
            "SELECT id, kind, task, attempts, error FROM dead_tasks WHERE retried_at IS NULL ORDER BY id"
        ).fetchall()


def test_tache_inconnue_en_lettre_morte(env, db):
    r, _ = env
    r.lpush(store.QUEUE, json.dumps({"type": "autre"}))
    r.lpush(store.QUEUE, "{pas du json")
    run_tasks(2)
    assert r.llen(store.QUEUE) == 0
    got = sorted((kind, task) for _, kind, task, _, _ in dead_rows(db))
    assert got == [("illisible", {"brut": "{pas du json"}), ("inconnue", {"type": "autre"})]


def test_ligne_etat(env, db, monkeypatch, capsys):
    r, s3 = env
    monkeypatch.setenv("RLPI_LOG_FORMAT", "json")
    monkeypatch.setattr(game, "run", fake_game())
    add_match(db, s3, "m5")
    store.push_match(r, "m5")
    run_tasks(1)
    out = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    fin = next(x for x in out if x["msg"] == "fin de partie")
    assert fin["match"] == "m5" and fin["t_analyse"] == 1.5 and {"t_replay", "t_envoi", "t_agregats"} <= set(fin)
    w = worker.Worker()
    w.report_state()
    etat = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")][-1]
    assert etat["msg"] == "état" and etat["parties_1h"] == 1 and etat["duree_moy_s_1h"] == 1.5
    # les fichiers de la fausse partie sont illisibles : ses agrégats échouent et partent en lettre morte
    assert [(kind, task) for _, kind, task, _, _ in dead_rows(db)] == [
        ("aggregate", {"type": "aggregate", "match": "m5"})
    ]
    assert etat["file"] == 0 and etat["bloquees"] == 0 and etat["lettre_morte"] == 1 and etat["level"] == "warning"
    w.report_state()  # une seule ligne par intervalle, tous workers confondus
    assert '"état"' not in capsys.readouterr().out


def test_partie_inconnue_ignoree(env, db):
    r, _ = env
    store.push_match(r, "absente")
    run_tasks(1)
    assert row(db, "absente") is None


# ------------------------------------------------------------------------------------------------ agrégats

FIXTURE_GAMES = Path(__file__).parent / "fixtures" / "games"


def fixture_game(name: str):
    """Analyse simulée qui recopie une vraie partie du jeu d'essai : les agrégats peuvent être calculés."""

    def run(replay, out, models, timeout=None):
        shutil.copytree(FIXTURE_GAMES / name, out, dirs_exist_ok=True)
        res = json.loads((FIXTURE_GAMES / name / "result.json").read_text(encoding="utf-8"))
        return res | {"wall_s": 1.0}

    return run


def aggregates(db, mid):
    with psycopg.connect(db) as c:
        g = c.execute("SELECT version, replay FROM game_aggregates WHERE match_id = %s", (mid,)).fetchone()
        n = c.execute("SELECT count(*) FROM player_game_aggregates WHERE match_id = %s", (mid,)).fetchone()[0]
    return g, n


def test_agregats_apres_partie(env, db, monkeypatch, joueurs):
    from rlpi.dashboard import aggregate

    r, s3 = env
    monkeypatch.setattr(game, "run", fixture_game("partie-01"))
    add_match(db, s3, "partie-01")
    store.push_match(r, "partie-01")
    run_tasks(1)
    assert row(db, "partie-01")[0] == "ok"
    assert aggregates(db, "partie-01") == ((aggregate.VERSION, "partie-01"), 6)
    with psycopg.connect(db) as c:
        assert c.execute(
            "SELECT version FROM player_versions WHERE player_id = %s", (joueurs["principal"],)
        ).fetchone() == (1,)


def test_rattrapage_au_demarrage(env, db, joueurs, monkeypatch):
    """Partie traitée avant les agrégats : mise en file par le rattrapage, calculée depuis le stockage."""
    r, s3 = env
    monkeypatch.setenv("RLPI_BACKFILL_DELAY", "0")
    src = FIXTURE_GAMES / "partie-02"
    for f in src.rglob("*"):
        if f.is_file():
            s3.objects[f"games/partie-02/{f.relative_to(src).as_posix()}"] = f.read_bytes()
    add_match(db, s3, "partie-02", status="ok")
    run_tasks(1)
    assert aggregates(db, "partie-02")[1] == 6
    assert r.llen(store.QUEUE) == 0
    # Redémarrage dans l'heure : pas de nouveau rattrapage ; une tâche pour une partie à jour est sautée
    r.lpush(store.QUEUE, json.dumps({"type": "aggregate", "match": "partie-02"}))
    run_tasks(1)
    assert r.llen(store.QUEUE) == 0


def test_rattrapage_decale(env, db):
    """Pas de rattrapage au démarrage : l'ancien worker, encore actif pendant un redéploiement, jetterait les tâches."""
    r, s3 = env
    add_match(db, s3, "sans-agregats", status="ok")
    w = worker.Worker()
    w.r.lpush(store.QUEUE, json.dumps({"type": "autre"}))  # une tâche pour que la boucle tourne une fois
    w.process = lambda raw: setattr(w, "stop", True)
    w.run()
    assert r.llen(store.QUEUE) == 0 and not r.keys(worker.BACKFILL_LOCK + "*")


def test_rattrapage_sans_les_lettres_mortes(env, db):
    """Une partie dont le calcul est en lettre morte n'est pas remise en file à chaque rattrapage… sauf si la lettre
    morte date d'une version de calcul plus ancienne : la nouvelle version corrige peut-être l'échec."""
    from rlpi.dashboard import aggregate, storage

    r, s3 = env
    add_match(db, s3, "casse", status="ok")
    add_match(db, s3, "a-faire", status="ok")
    add_match(db, s3, "ancienne", status="ok")
    with psycopg.connect(db, autocommit=True) as c:
        c.execute(
            "INSERT INTO dead_tasks (kind, ref, task, error, version) VALUES "
            "('aggregate', 'casse', '{}', 'x', %s), ('aggregate', 'ancienne', '{}', 'x', %s), "
            "('aggregate', 'ancienne', '{}', 'x', NULL)",
            (aggregate.VERSION, aggregate.VERSION - 1),
        )
        assert storage.missing(c, skip_dead=True) == ["a-faire", "ancienne"]
        assert storage.missing(c) == ["a-faire", "ancienne", "casse"]
    w = worker.Worker()
    w.backfill()
    assert [json.loads(x)["match"] for x in r.lrange(store.QUEUE, 0, -1)] == ["ancienne", "a-faire"]


def test_lettre_morte_agregats_porte_la_version(env, db, monkeypatch):
    """Un calcul d'agrégats abandonné garde la version du calcul (le rattrapage s'en sert)."""
    from rlpi.dashboard import aggregate, storage

    _, s3 = env
    add_match(db, s3, "casse", status="ok")

    def boom(*a, **k):
        raise RuntimeError("calcul impossible")

    monkeypatch.setattr(storage, "compute_match", boom)
    w = worker.Worker()
    w.process_aggregate("casse", json.dumps({"type": "aggregate", "match": "casse"}))
    with psycopg.connect(db, autocommit=True) as c:
        assert c.execute("SELECT kind, ref, version FROM dead_tasks").fetchall() == [
            ("aggregate", "casse", aggregate.VERSION)
        ]
        assert storage.missing(c, skip_dead=True) == []


def test_taches_orphelines_reprises(env, db, monkeypatch):
    """Tâches « en cours » d'un worker disparu : remises en file après ORPHAN_GRACE sans signal de vie."""
    r, _ = env
    task = json.dumps({"type": "aggregate", "match": "m"})
    r.lpush(store.PROCESSING + "disparu", task)
    r.lpush(store.PROCESSING + "vivant", task)
    r.set(worker.ALIVE + "vivant", "1")
    w = worker.Worker()
    assert w.reclaim_orphans() == 0  # vu sans signal de vie : délai de grâce
    assert r.llen(store.PROCESSING + "disparu") == 1
    now = worker.time.time()
    monkeypatch.setattr(worker.time, "time", lambda: now + worker.ORPHAN_GRACE + 1)
    assert w.reclaim_orphans() == 1
    assert r.lrange(store.QUEUE, 0, -1) == [task]
    assert r.llen(store.PROCESSING + "disparu") == 0 and r.llen(store.PROCESSING + "vivant") == 1
    assert not r.exists(worker.ORPHAN + "disparu")


def test_signal_de_vie(env, db):
    r, _ = env
    w = worker.Worker()
    w.r.lpush(store.QUEUE, json.dumps({"type": "autre"}))
    seen = []

    def process(raw):
        seen.append(r.ttl(worker.ALIVE + "test-1"))
        w.stop = True

    w.process = process
    w.run()
    assert 0 < seen[0] <= worker.ALIVE_TTL
    assert not r.exists(worker.ALIVE + "test-1")  # effacé à l'arrêt


# ------------------------------------------------------------------------------------------------ schéma


def test_attente_du_schema(make_database, monkeypatch):
    from tests.conftest import reset_store

    monkeypatch.setattr(worker.time, "sleep", lambda s: None)
    monkeypatch.setenv("DATABASE_URL", make_database(migrate=1))  # base restée en version 1
    reset_store(monkeypatch)
    with pytest.raises(SystemExit, match=f"version 1, version {store.SCHEMA_VERSION} attendue"):
        worker.wait_for_schema(timeout=0)
    monkeypatch.setenv("DATABASE_URL", make_database())
    worker.wait_for_schema(timeout=0)


@pytest.mark.parametrize("parallel", [1, 4])
def test_telechargement_garage_en_parallele(tmp_path, parallel):
    from rlpi.dashboard import storage

    s3 = FakeS3()
    files = {f"games/p/sous/f{i}.parquet": bytes([i]) * 10 for i in range(12)} | {"games/autre/x": b"x"}
    s3.objects.update(files)
    d = storage.download_game(s3, "rlpi", "p", tmp_path / "p", parallel=parallel)
    got = {f.relative_to(d).as_posix(): f.read_bytes() for f in d.rglob("*") if f.is_file()}
    assert got == {k.removeprefix("games/p/"): v for k, v in files.items() if k.startswith("games/p/")}
    with pytest.raises(FileNotFoundError):
        storage.download_game(s3, "rlpi", "absente", tmp_path / "a", parallel=parallel)


def test_reconstruction_en_parallele(env, db, monkeypatch):
    from rlpi.dashboard import storage

    written, seen = [], []
    monkeypatch.setattr(storage, "compute_from_storage", lambda cli, b, mid: {"match": mid})
    monkeypatch.setattr(storage, "write", lambda conn, agg: written.append(agg["match"]))
    ok = storage.rebuild(None, None, "rlpi", [f"m{i}" for i in range(7)], 3, lambda k, mid, e: seen.append((k, e)))
    assert ok == 7 and sorted(written) == [f"m{i}" for i in range(7)] and [k for k, _ in seen] == list(range(1, 8))


def test_rattrapage_cameras(env, db, monkeypatch):
    """`backfill-cameras` : les parties traitées avant le cameras.json le reçoivent, lu dans le worker (processus
    séparé) et plus jamais dans le serveur web. Parties sans replay gardé ou au replay illisible : passées."""
    _, s3 = env
    lus = []

    def cameras(replay, dest, timeout=300):
        lus.append(Path(replay).name)
        if Path(replay).read_bytes() == b"abime":
            raise RuntimeError("replay illisible")
        Path(dest).write_text(json.dumps({"players": {"lu": Path(replay).name}}), encoding="utf-8")

    monkeypatch.setattr(game, "cameras", cameras)
    for mid in ("m1", "m2", "m3", "m4", "m5"):
        add_match(db, s3, mid, status="en_attente" if mid == "m4" else "ok")
        s3.objects[f"games/{mid}/frames/partie/R{mid}.meta.json"] = b"{}"
    s3.objects["games/m2/frames/partie/Rm2.cameras.json"] = b'{"deja": 1}'  # déjà là
    del s3.objects["replays/m3.replay"]  # replay non conservé
    s3.objects["replays/m5.replay"] = b"abime"
    counts = worker.backfill_cameras()
    assert counts == {"faites": 1, "deja_la": 1, "sans_replay": 1, "echecs": 1}
    assert json.loads(s3.objects["games/m1/frames/partie/Rm1.cameras.json"]) == {"players": {"lu": "m1.replay"}}
    assert s3.objects["games/m2/frames/partie/Rm2.cameras.json"] == b'{"deja": 1}'
    assert "games/m4/frames/partie/Rm4.cameras.json" not in s3.objects  # partie pas encore traitée
    assert sorted(lus) == ["m1.replay", "m5.replay"]
    assert worker.backfill_cameras() == {"faites": 0, "deja_la": 2, "sans_replay": 1, "echecs": 1}  # sans risque
