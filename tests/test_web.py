"""Serveur FastAPI (rlpi.web) : routes, droits, sessions, contenu de l'API comparé à l'instantané, swipe, événements.

Les tests sans base tournent partout ; ceux qui ont besoin de Postgres utilisent la fixture `db` (sautés sans
RLPI_TEST_DATABASE_URL, obligatoires en CI). Redis est remplacé par fakeredis.
"""

from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

import fakeredis
import psycopg
import pytest
from fastapi.testclient import TestClient

from rlpi import account, store
from rlpi.web import cache, schemas, sessions
from rlpi.web.settings import Settings, get_settings
from tests.payload import aggregates, reference_context
from tests.test_snapshot import SNAPSHOT, cases, fill_database, normalize
from tests.test_worker import FakeS3

PUBLIC = "http://testserver"
ENV = {
    "RLPI_PUBLIC_URL": PUBLIC,
    "RLPI_SECRET": "secret-de-test-0123456789abcdef0123456789",
    "DATABASE_URL": "postgresql://personne@127.0.0.1:1/rien",
    "REDIS_URL": "redis://127.0.0.1:1/0",
    "S3_ENDPOINT": "http://127.0.0.1:1",
    "S3_ACCESS_KEY": "x",
    "S3_SECRET_KEY": "y",
}
ME = "Steam:76561190000000009"


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("RLPI_DEV_LOGIN", raising=False)
    dist = tmp_path / "dist"  # interface Vue compilée (factice)
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=app></div>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("hors de dist", encoding="utf-8")
    monkeypatch.setenv("RLPI_WEB_DIST", str(dist))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(env):
    """Application sans démarrage (pas de connexion à la base) : routes qui n'en ont pas besoin."""
    from rlpi.web.main import create_app

    return TestClient(create_app(), follow_redirects=False)


# ------------------------------------------------------------------------------------------------ configuration


def test_configuration_manquante_nomme_les_variables(monkeypatch):
    from pydantic import ValidationError

    from rlpi.web.settings import describe

    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RLPI_PUBLIC_URL", PUBLIC)
    with pytest.raises(ValidationError) as e:
        Settings(_env_file=None)  # type: ignore[call-arg]
    msg = describe(e.value)
    assert "RLPI_SECRET : manquante" in msg and "DATABASE_URL : manquante" in msg and "RLPI_PUBLIC_URL" not in msg


def test_valeurs_nettoyees_et_origine(env, monkeypatch):
    monkeypatch.setenv("RLPI_PUBLIC_URL", ' "https://RLPI.example.test/" ')
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.public_url == "https://RLPI.example.test" and s.origin == "https://rlpi.example.test" and s.https


def test_connexion_de_developpement_interdite_en_https(env, monkeypatch):
    monkeypatch.setenv("RLPI_PUBLIC_URL", "https://rlpi.example.test")
    monkeypatch.setenv("RLPI_DEV_LOGIN", "1")
    with pytest.raises(Exception, match="RLPI_DEV_LOGIN=1 est interdit"):
        Settings(_env_file=None)  # type: ignore[call-arg]


# ------------------------------------------------------------------------------------------------ sans base


def test_health_et_entetes_de_securite(client):
    r = client.get("/health")
    assert (r.status_code, r.text) == (200, "ok")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "same-origin"


def test_identifiant_de_requete(client, monkeypatch, capsys):
    import json as _json

    monkeypatch.setenv("RLPI_LOG_FORMAT", "json")
    r = client.get("/api/moi", headers={"X-Request-ID": "proxy-1234abcd"})
    assert r.headers["x-request-id"] == "proxy-1234abcd"
    rec = [_json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")][-1]
    assert rec | {"ms": 0} == rec | {
        "msg": "requête",
        "method": "GET",
        "path": "/api/moi",
        "status": 401,
        "request_id": "proxy-1234abcd",
        "ms": 0,
    }
    rid = client.get("/health", headers={"X-Request-ID": "<script>"}).headers["x-request-id"]
    assert rid != "<script>" and len(rid) == 16  # en-tête douteux : identifiant tiré au hasard


@pytest.mark.parametrize(
    "path", ["/", "/ma-forme", "/matchs/abc-123?du=2026-01-01", "/indicateurs", "/swipe", "/modeles"]
)
def test_interface_vue_index_pour_chaque_chemin(client, path):
    r = client.get(path)
    assert r.status_code == 200 and r.text == "<div id=app></div>"
    assert r.headers["cache-control"] == "no-cache" and r.headers["content-type"].startswith("text/html")


def test_interface_vue_fichiers_immuables(client):
    r = client.get("/assets/index-abc123.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert client.get("/assets/absent.js").status_code == 404


@pytest.mark.parametrize("path", ["/api/inconnu", "/auth/inconnu", "/dev/x", "/health/x", "/assets"])
def test_chemins_du_serveur_jamais_l_interface(client, path):
    r = client.get(path)
    assert r.status_code == 404 and "<div id=app>" not in r.text


@pytest.mark.parametrize(
    ("path", "to"), [("/v2", "/"), ("/v2/", "/"), ("/v2/matchs/abc?du=2026-01-01", "/matchs/abc?du=2026-01-01")]
)
def test_adresses_de_la_transition_redirigees(client, path, to):
    r = client.get(path)
    assert r.status_code == 301 and r.headers["location"] == to


@pytest.mark.parametrize(
    "path", ["/assets/..%2F..%2Fsecret.txt", "/..%2Fsecret.txt", "/assets/../../secret.txt", "/%2E%2E/secret.txt"]
)
def test_interface_vue_reste_dans_son_dossier(client, path):
    r = client.get(path)
    assert "hors de dist" not in r.text


def test_interface_vue_absente(env, monkeypatch, tmp_path):
    from rlpi.web.main import create_app

    monkeypatch.setenv("RLPI_WEB_DIST", str(tmp_path / "rien"))
    get_settings.cache_clear()
    c = TestClient(create_app(), follow_redirects=False)
    assert c.get("/ma-forme").status_code == 404 and c.get("/health").status_code == 200


def test_anciennes_adresses_vers_l_interface(client):
    """Plus de tableau de bord public ni d'ancien gabarit : l'interface demande la connexion (/api/moi → 401)."""
    for path in (
        "/tableau_de_bord.html?du=2026-01-01&x=1",
        "/tableau_de_bord?du=2026-01-01",
        "/moi?du=2026-01-01&recherche=1",
    ):
        r = client.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/ma-forme?du=2026-01-01"
    r = client.get("/ma-forme")
    assert "<div id=app>" in r.text and "Steam" not in r.text


def test_api_sans_session(client):
    for path in ("/api/moi", f"/api/joueurs/{ME}/tableau", f"/api/joueurs/{ME}/profil", "/api/swipe/deck"):
        assert client.get(path).status_code == 401, path


def test_ancien_cookie_falsifie_refuse(client):
    client.cookies.set(sessions.COOKIE, "Steam:1|9999999999|abc")
    assert client.get("/api/moi").status_code == 401


@pytest.mark.parametrize("path", ["/auth/steam", "/connexion"])
def test_connexion_redirige_vers_steam(client, path):
    r = client.get(path)
    assert r.status_code == 303 and r.headers["location"].startswith(account.STEAM_OPENID)
    assert "auth%2Fsteam%2Fretour" in r.headers["location"]


@pytest.mark.parametrize("path", ["/auth/steam/retour", "/connexion/retour"])
def test_retour_steam_invalide(client, path):
    r = client.get(path + "?openid.mode=cancel")
    assert r.status_code == 303 and r.headers["location"] == "/?connexion=echec" and "set-cookie" not in r.headers


def test_connexion_de_developpement_inactive(client):
    assert client.get("/dev/connexion").status_code == 404
    assert client.get("/dev/connexion?joueur=Steam:1").status_code == 404
    assert client.get("/dev/joueurs").status_code == 404


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://attaquant.example"}, {"Referer": "https://x.example/"}])
def test_ecritures_refusent_une_origine_inconnue(client, headers):
    for path in ("/auth/deconnexion", "/auth/deconnexion-partout", "/api/moi/actualiser", "/api/swipe/deck"):
        assert client.post(path, headers=headers).status_code == 403, path


def test_documentation_de_l_api(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in (
        "/ready",
        "/auth/steam",
        "/auth/steam/retour",
        "/auth/deconnexion",
        "/auth/deconnexion-partout",
        "/api/moi",
        "/api/moi/actualiser",
        "/api/moi/evenements",
        "/api/joueurs/{id}/profil",
        "/api/joueurs/{id}/tableau",
        "/api/joueurs/{id}/matchs/{match}",
        "/api/modeles",
        "/api/swipe/deck",
        "/api/swipe/jugements",
    ):
        assert p in paths, p
    assert client.get("/docs").status_code == 200


def test_json_sans_nan_ni_infini():
    assert json.loads(cache.dumps({"a": math.nan, "b": [math.inf, -math.inf, 1.5, -0.0], "c": "é"})) == {
        "a": None,
        "b": [None, None, 1.5, -0.0],
        "c": "é",
    }


def test_cache_calcule_une_seule_fois():
    c = cache.JsonCache(max_entries=2)
    calls = []
    build = lambda: calls.append(1) or {"x": 1}  # noqa: E731
    assert json.loads(gzip.decompress(c.compute("a", build))) == {"x": 1}
    c.compute("a", build)
    assert len(calls) == 1
    c.compute("b", build), c.compute("c", build)
    assert c.get("a") is None  # le plus ancien est sorti


def wait_until(pred, timeout: float = 5.0) -> None:
    import time

    end = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < end, "attente trop longue"
        time.sleep(0.01)


def test_cache_un_seul_calcul_a_la_fois_meme_apres_un_echec():
    """Un calcul qui échoue n'est pas gardé : les demandes qui l'attendaient le refont une par une, et une demande
    arrivée entre-temps attend son tour au lieu de calculer en parallèle (le verrou de la clé n'est retiré que
    quand plus personne ne l'attend)."""
    import contextlib
    import threading
    import time

    c = cache.JsonCache()
    guard, gates = threading.Lock(), [threading.Event() for _ in range(3)]
    running, peak, started = [0], [0], []

    def build(n):
        def f():
            with guard:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
                started.append(n)
            try:
                gates[n].wait(5)
                raise RuntimeError("échec")
            finally:
                with guard:
                    running[0] -= 1

        return f

    def ask(n):
        with contextlib.suppress(RuntimeError):
            c.compute("k", build(n))

    threads = [threading.Thread(target=ask, args=(n,)) for n in range(3)]
    try:
        threads[0].start()
        wait_until(lambda: started == [0])
        threads[1].start()
        time.sleep(0.1)  # la deuxième demande attend le verrou de la clé
        gates[0].set()
        wait_until(lambda: len(started) == 2)  # la première a échoué, la deuxième calcule
        threads[2].start()
        time.sleep(0.1)  # la troisième arrive pendant ce calcul : elle doit attendre
        assert started == [0, 1]
    finally:
        for g in gates:
            g.set()
        for t in threads:
            t.join(5)
    assert started == [0, 1, 2] and peak[0] == 1
    assert len(c.key_locks) == 0  # rien ne reste en mémoire


def test_schemas_decrivent_tout_l_instantane():
    """Chaque profil de l'instantané (toutes les combinaisons de filtres) correspond exactement au schéma."""
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    n = 0
    for case in snap.values():
        for prof in case["profiles"].values():
            schemas.Contenu.model_validate({**prof, "generated": "17/11/2026 12:00"})
            n += 1
    assert n == len(snap)


def test_models_content_sur_le_jeu_d_essai():
    from rlpi import models_page

    c = models_page.content(reference_context())
    schemas.Modeles.model_validate({k: v for k, v in c.items() if k != "genere"})
    assert [f["anchor"] for f in c["fiches"]] == ["lecture", "valeur", "placement"]
    assert set(c["absents"]) == {"models/q_touch_report.json", "features/perf_ssl.parquet"}


# ------------------------------------------------------------------------------------------------ avec base


@pytest.fixture
def app_db(env, db, monkeypatch):
    """Application démarrée sur la base de test, Redis simulé, référence du jeu d'essai."""
    from rlpi.dashboard import storage
    from rlpi.web.main import create_app
    from rlpi.web.routes import api

    monkeypatch.setenv("DATABASE_URL", db)
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(store, "redis_client", lambda: r)
    monkeypatch.setattr(storage, "_cache", type(storage._cache)())
    monkeypatch.setattr(storage, "_ref", None)
    monkeypatch.setattr(storage, "reference_context", reference_context)
    monkeypatch.setattr(api, "CACHE", cache.JsonCache())
    with TestClient(create_app(), follow_redirects=False) as c:
        c.headers["Origin"] = PUBLIC
        yield c, r, db


def login(c: TestClient, pid: str, db: str) -> str:
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute("INSERT INTO accounts (player_id) VALUES (%s) ON CONFLICT DO NOTHING", (pid,))
    token = sessions.create(pid)
    c.cookies.set(sessions.COOKIE, token)
    return token


@pytest.fixture(scope="module")
def aggs():
    return aggregates()


@pytest.fixture
def filled(app_db, aggs, joueurs):
    c, r, db = app_db
    with psycopg.connect(db, autocommit=True) as conn:
        fill_database(conn, aggs)
    login(c, joueurs["principal"], db)
    return c, r, db


def test_session_en_base_seulement_son_empreinte(app_db):
    c, _, db = app_db
    token = login(c, ME, db)
    with psycopg.connect(db) as conn:
        ids = [x[0] for x in conn.execute("SELECT id FROM sessions").fetchall()]
    assert ids and token not in ids and len(ids[0]) == 64
    r = c.get("/api/moi")
    assert r.status_code == 200 and r.json()["id"] == ME and r.json()["parties"] == 0
    schemas.Moi.model_validate(r.json())


def test_deconnexion_et_deconnexion_partout(app_db):
    c, _, db = app_db
    t1 = login(c, ME, db)
    t2 = sessions.create(ME)
    r = c.post("/auth/deconnexion")
    assert r.status_code == 303 and r.headers["location"] == "/" and "Max-Age=0" in r.headers["set-cookie"]
    assert sessions.player(t1) is None and sessions.player(t2) == ME
    c.cookies.set(sessions.COOKIE, t2)
    assert c.post("/auth/deconnexion-partout").status_code == 303
    assert sessions.player(t2) is None


def test_session_expiree(app_db):
    c, _, db = app_db
    token = login(c, ME, db)
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute("UPDATE sessions SET expires_at = now() - interval '1 second'")
    assert sessions.player(token) is None and c.get("/api/moi").status_code == 401


def test_ancien_cookie_signe_remplace_par_une_session(app_db):
    c, _, db = app_db
    old = account.make_cookie(ME).split(";", 1)[0].split("=", 1)[1]
    c.cookies.set(sessions.COOKIE, old)
    r = c.get("/api/moi")
    assert r.status_code == 200 and r.json()["id"] == ME
    new = r.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    assert "|" not in new and "HttpOnly" in r.headers["set-cookie"] and sessions.player(new) == ME


def test_connexion_de_developpement(app_db, monkeypatch):
    c, r, db = app_db
    monkeypatch.setattr(get_settings(), "dev_login", True)
    monkeypatch.setenv("RLPI_DEV_LOGIN", "1")  # vérifié aussi par account.dev_login
    pseudo = "</script><b>x"
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute("INSERT INTO matches (id, source, status) VALUES ('m1', 'fichier', 'ok')")
        conn.execute("INSERT INTO match_players VALUES ('m1', 'Steam:76561190000000007', %s, 0)", (pseudo,))
    p = c.get("/dev/joueurs")  # en JSON : la page de connexion (Vue) l'affiche comme texte, jamais comme HTML
    assert p.json() == [{"id": "Steam:76561190000000007", "pseudo": pseudo, "parties": 1}]
    assert p.headers["content-type"].startswith("application/json")
    assert c.get("/dev/connexion").headers["location"] == "/"
    p = c.get("/dev/connexion?joueur=Steam:76561190000000007")
    assert p.status_code == 303 and c.get("/api/moi").json()["id"] == "Steam:76561190000000007"
    assert r.llen(store.QUEUE) == 0  # pas de recherche ballchasing lancée par la connexion de développement


def test_actualiser(app_db):
    c, r, db = app_db
    login(c, ME, db)
    assert c.post("/api/moi/actualiser").json()["lancee"] is True
    assert c.post("/api/moi/actualiser").json()["lancee"] is False  # moins de 5 minutes après
    assert [json.loads(x) for x in r.lrange(store.QUEUE, 0, -1)] == [{"type": "sync", "player": ME}]


def test_moi_sans_partie_affiche_l_import(app_db):
    c, _, db = app_db
    login(c, ME, db)
    moi = c.get("/api/moi").json()  # l'interface affiche alors la page d'import
    assert moi["parties"] == 0 and set(moi["import"]) == {"last_sync", "running", "done", "waiting"}
    assert c.get(f"/api/joueurs/{ME}/tableau").status_code == 404


def test_chacun_ne_voit_que_le_sien(filled, joueurs):
    c, _, _ = filled
    other = joueurs["coequipiers"][0]
    for path in ("tableau", "profil", "matchs/partie-01"):
        assert c.get(f"/api/joueurs/{other}/{path}").status_code == 403, path


def test_tableau_identique_a_l_instantane(filled, joueurs):
    """L'API renvoie exactement le contenu de l'instantané, pour chaque combinaison de filtres."""
    c, _, _ = filled
    me = joueurs["principal"]
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for name, f in cases(joueurs).items():
        params = {
            "du": f.get("since"),
            "au": f.get("until"),
            "avec": f.get("avec"),
            "sans": f.get("sans"),
            "j": f.get("j"),
        }
        r = c.get(f"/api/joueurs/{me}/tableau", params={k: v for k, v in params.items() if v})
        assert r.status_code == 200, name
        body = r.json()
        schemas.Tableau.model_validate(body)
        want = snap[name]
        assert body["joueur"] == want["default"] and body["filtres"] == want["filters"], name
        assert normalize(body["contenu"]) == want["profiles"][body["joueur"]], name


def test_profil(filled, joueurs):
    c, _, _ = filled
    me = joueurs["principal"]
    body = c.get(f"/api/joueurs/{me}/profil").json()
    schemas.Profil.model_validate(body)
    want = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["defaut"]
    assert body["joueurs"] == want["order"] and body["noms"] == want["names"] and body["jours"] == want["days"]


def test_etag_gzip_et_304(filled, joueurs):
    c, _, _ = filled
    url = f"/api/joueurs/{joueurs['principal']}/tableau"
    r = c.get(url, headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip" and r.headers["etag"].startswith('"')
    assert c.get(url, headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    assert c.get(url + "?du=2026-01-01", headers={"If-None-Match": r.headers["etag"]}).status_code == 200
    plain = c.get(url, headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.json()["joueur"] == joueurs["principal"]


def test_etag_change_avec_une_nouvelle_partie(filled, joueurs, aggs):
    from rlpi.dashboard import storage

    c, _, db = filled
    url = f"/api/joueurs/{joueurs['principal']}/tableau"
    tag = c.get(url).headers["etag"]
    with psycopg.connect(db, autocommit=True) as conn:
        storage.write(conn, aggs[0])  # partie recalculée : version des données du joueur augmentée
    r = c.get(url, headers={"If-None-Match": tag})
    assert r.status_code == 200 and r.headers["etag"] != tag


def test_reference_unique(filled, joueurs):
    c, _, _ = filled
    body = c.get(f"/api/joueurs/{joueurs['principal']}/tableau?ref=rlcs").json()
    assert list(body["contenu"]["refs"]) == ["rlcs"] and body["contenu"]["default_ref"] == "rlcs"
    assert c.get(f"/api/joueurs/{joueurs['principal']}/tableau?ref=autre").status_code == 422


def test_parametres_invalides(filled, joueurs):
    c, _, _ = filled
    for q in ("du=hier", "au=2026-1-1", "ref=autre", "avec=" + "x" * 500):
        assert c.get(f"/api/joueurs/{joueurs['principal']}/tableau?{q}").status_code == 422, q


def test_aucune_partie_pour_ces_filtres(filled, joueurs):
    c, _, _ = filled
    body = c.get(f"/api/joueurs/{joueurs['principal']}/tableau?du=2099-01-01").json()
    assert body["contenu"] is None and body["erreur"]


def test_detail_d_un_match(filled, joueurs, aggs):
    c, _, _ = filled
    me = joueurs["principal"]
    mid = next(a["match_id"] for a in aggs if me in a["players"] and a["game"].get("curve"))
    body = c.get(f"/api/joueurs/{me}/matchs/{mid}").json()
    schemas.Match.model_validate(body)
    assert body["id"] == mid and len(body["joueurs"]) == 6 and body["courbe"] is not None
    assert len(body["indices"]) <= 1 and body["equipe"] in (0, 1)
    assert c.get(f"/api/joueurs/{me}/matchs/inconnu").status_code == 404


def test_modeles(filled):
    c, _, _ = filled
    body = c.get("/api/modeles").json()
    schemas.Modeles.model_validate(body)
    assert [f["anchor"] for f in body["fiches"]] == ["lecture", "valeur", "placement"]


def test_ready(app_db, monkeypatch):
    c, _, _ = app_db

    class S3:
        def head_bucket(self, Bucket):
            return {}

    monkeypatch.setattr(store, "s3", lambda: S3())
    r = c.get("/ready")
    assert r.status_code == 200 and r.json() == {"postgres": "ok", "redis": "ok", "garage": "ok"}
    monkeypatch.setattr(store, "s3", lambda: (_ for _ in ()).throw(ConnectionError("garage")))
    assert c.get("/ready").status_code == 503


# ------------------------------------------------------------------------------------------------ événements


def test_evenement_publie_pour_les_joueurs_inscrits(db, aggs, joueurs):
    from rlpi import events

    r = fakeredis.FakeRedis(decode_responses=True)
    me = joueurs["principal"]
    sub = r.pubsub()
    sub.subscribe(events.channel(me))
    sub.get_message(timeout=1)
    with psycopg.connect(db, autocommit=True) as conn:
        fill_database(conn, aggs)
        conn.execute("INSERT INTO accounts (player_id) VALUES (%s)", (me,))
        n = events.publish_match(r, conn, aggs[0]["match_id"], sorted(aggs[0]["players"]))
    assert n == (1 if me in aggs[0]["players"] else 0)
    if n:
        msg = sub.get_message(timeout=1)
        assert msg is not None and json.loads(msg["data"]) == {"match": aggs[0]["match_id"], "parties": 8}


# ------------------------------------------------------------------------------------------------ swipe


def pool_file(tmp_path: Path) -> Path:
    cards = [
        {"id": f"{o}:r{k}:{k}", "origin": o, "action": "tir", "fps": 30, "cars": []}
        for o in ("ssl", "rlcs")
        for k in range(10)
    ]
    f = tmp_path / "pool.json"
    f.write_text(json.dumps({"seed": 1, "cards": cards}), encoding="utf-8")
    return f


def test_swipe_paquet_a_l_aveugle(app_db, tmp_path, monkeypatch):
    from rlpi import swipe_online
    from rlpi.web.routes import swipe

    c, r, db = app_db
    login(c, ME, db)
    monkeypatch.setattr(swipe, "reference_pool_path", lambda: pool_file(tmp_path))
    assert c.get("/api/swipe/deck").json()["statut"] == "aucun"
    d = c.post("/api/swipe/deck")
    assert d.status_code == 202 and d.json()["statut"] == "en_attente"
    did = d.json()["id"]
    assert c.post("/api/swipe/deck").json()["id"] == did  # un seul paquet en préparation à la fois
    assert [json.loads(x) for x in r.lrange(store.QUEUE, 0, -1)] == [{"type": "swipe", "deck": did}]
    got = c.get("/api/swipe/deck").json()
    assert got["statut"] == "en_attente" and got["cartes"] == []
    # Ce que fait le worker, sans replays : cartes du joueur ajoutées, mélange, identifiants neutres
    with psycopg.connect(db, autocommit=True) as conn:
        ref_cards = conn.execute("SELECT cards FROM swipe_decks WHERE id = %s", (did,)).fetchone()[0]
        assert sorted(x["origin"] for x in ref_cards) == ["rlcs"] * 6 + ["ssl"] * 6
        mine = [{"id": f"perso:r:{k}", "origin": "perso", "action": None, "cars": []} for k in range(3)]
        cards = swipe_online.finalize([*ref_cards, *mine], did)
        from psycopg.types.json import Jsonb

        conn.execute(
            "UPDATE swipe_decks SET status = 'pret', cards = %s, n_cards = %s WHERE id = %s",
            (Jsonb(cards), len(cards), did),
        )
    got = c.get("/api/swipe/deck").json()
    assert got["statut"] == "pret" and len(got["cartes"]) == 15
    text = json.dumps(got["cartes"])
    assert "origin" not in text and "ssl" not in text and "rlcs" not in text and "perso" not in text
    card = got["cartes"][0]["id"]
    ok = c.post("/api/swipe/jugements", json={"paquet": did, "carte": card, "verdict": "bien"})
    assert ok.status_code == 204
    c.post("/api/swipe/jugements", json={"paquet": did, "carte": card, "verdict": "pas_bien"})
    assert c.get("/api/swipe/deck").json()["jugements"] == {card: "pas_bien"}
    with psycopg.connect(db) as conn:
        origin = conn.execute("SELECT origin FROM swipe_judgments").fetchone()[0]
    assert origin == next(x["origin"] for x in cards if x["id"] == card)
    bad = c.post("/api/swipe/jugements", json={"paquet": did, "carte": "inconnue", "verdict": "bien"})
    assert bad.status_code == 404
    assert c.post("/api/swipe/jugements", json={"paquet": did, "carte": card, "verdict": "bof"}).status_code == 422


# ------------------------------------------------------------------------------------------------ clips 3D (Revoir)

CLIP_MATCH = "partie-clip"
CLIP_KEY = f"replays/{CLIP_MATCH}.replay"
CLIP_PLAYERS = [{"slot": k, "team": k // 3, "id": ME if k == 4 else f"Steam:{k}"} for k in range(6)]


def clip_storage(meta: dict, touches: list[dict], replay: bytes | None = b"replay", cams: dict | None = None) -> FakeS3:
    """Stockage d'une partie traitée par le worker : meta.json, touch_values et (si donnés) le replay brut et le
    cameras.json (SYNTH_CAMS par défaut, plus bas)."""
    import io

    import polars as pl

    s3 = FakeS3()
    base = f"games/{CLIP_MATCH}/"
    s3.objects[f"{base}frames/partie/{meta['replay']}.meta.json"] = json.dumps(meta).encode()
    s3.objects[f"{base}frames/partie/{meta['replay']}.parquet"] = b"images a 10 Hz"
    buf = io.BytesIO()
    schema = {"i": pl.Int64, "player_id": pl.String, "ball_x": pl.Float64, "ball_y": pl.Float64}
    pl.DataFrame(touches, schema=schema).write_parquet(buf)
    s3.objects[f"{base}features/touch_values_partie.parquet"] = buf.getvalue()
    if replay is not None:
        s3.objects[CLIP_KEY] = replay
    cams = SYNTH_CAMS if cams is None else cams
    if cams:
        s3.objects[f"{base}frames/partie/{meta['replay']}.cameras.json"] = json.dumps(cams).encode()
    return s3


# Caméras relevées dans le replay fictif (10 s à 120 images/s, temps = index / 120) : le joueur connecté passe en
# caméra voiture à 4,9 s, soit 0,1 s avant la touche i = 50 (image 600 = 5 s).
SYNTH_CAMS = {
    "players": {
        ME: {
            "settings": {"fov": 105.0, "distance": 250.0, "height": 90.0, "angle": -4.0, "stiffness": 0.4},
            "ball_cam": [[0.0, 1], [4.9, 0]],
        }
    }
}


@pytest.fixture
def synthetic_replay(monkeypatch):
    """Replay remplacé par la partie fictive de test_clips (balle en x = 10 × image, y = 500) : la touche i = 50
    (10 Hz) est à l'image 600 (120 Hz), balle en (6000, 500). Le joueur connecté (slot 4) est dans l'équipe 1 : la
    balle notée dans touch_values est dans le repère de son équipe, (−6000, −500)."""
    from rlpi import clips as rclips
    from tests.test_clips import synthetic

    monkeypatch.setattr(rclips, "read_replay", lambda path, fps=120: synthetic())

    def no_cameras(path):
        raise AssertionError("le serveur web ne lit jamais les caméras dans le replay (rattrapage : worker)")

    monkeypatch.setattr(rclips, "read_cameras", no_cameras)
    meta = {"replay": CLIP_MATCH, "players": CLIP_PLAYERS}
    touches = [
        {"i": 50, "player_id": ME, "ball_x": -6000.0, "ball_y": -500.0},
        {"i": 50, "player_id": "Steam:0", "ball_x": 6000.0, "ball_y": 500.0},  # même image, autre joueur
        {"i": 60, "player_id": "Steam:1", "ball_x": 7200.0, "ball_y": 500.0},
        {"i": 70, "player_id": ME, "ball_x": 0.0, "ball_y": 0.0},  # balle loin de la position notée
        {"i": 98, "player_id": ME, "ball_x": -11760.0, "ball_y": -500.0},  # moins d'1 s avant la fin
    ]
    return meta, touches


def judged(body: dict) -> list[bool]:
    return [c["kind"] == "me" for c in body["cars"]]


def ball_at(body: dict, k: int) -> list[int]:
    return [body["ball"][c][k] for c in "xyz"]


def test_clip_service_partie_fictive(synthetic_replay):
    from rlpi.web import clips as wclips

    meta, touches = synthetic_replay
    svc = wclips.ClipService(s3=clip_storage(meta, touches), bucket="b")
    body = json.loads(gzip.decompress(svc.clip(CLIP_MATCH, CLIP_KEY, 50, ME)))
    schemas.Clip.model_validate(body)
    assert body["id"] == f"{CLIP_MATCH}:50" and body["fps"] == 30 and body["t0"] == 120 and body["format"] == 2
    # balle en (6000, 500) sur le terrain ; le joueur connecté est dans l'équipe 1 : x et y retournés
    assert ball_at(body, 120) == [-6000, -500, 93]
    assert judged(body) == [k == 4 for k in range(6)]  # deux touches dans l'image : celle du joueur connecté
    assert [c["kind"] for c in body["cars"]] == ["opp", "opp", "opp", "mate1", "me", "mate2"]
    other = json.loads(gzip.decompress(svc.clip(CLIP_MATCH, CLIP_KEY, 50, "Steam:0")))
    assert judged(other) == [k == 0 for k in range(6)] and ball_at(other, 120) == [6000, 500, 93]  # équipe 0
    mate = json.loads(gzip.decompress(svc.clip(CLIP_MATCH, CLIP_KEY, 60, ME)))
    assert judged(mate) == [k == 1 for k in range(6)]  # touche d'un autre : son auteur est mis en avant
    assert svc.replay_reads == 1  # la dernière partie lue reste en mémoire
    cam = body["cam"]  # caméra du joueur connecté : réglages relevés, caméra voiture 0,1 s avant la touche
    assert cam["settings"]["fov"] == 105.0 and len(cam["ballcam"]) == len(body["ball"]["x"])
    assert cam["ballcam"][116] == 1 and cam["ballcam"][118] == 0 and cam["ballcam"][120] == 0
    assert other["cam"] is None  # pas de caméra relevée pour ce joueur
    for i, status in ((70, 422), (98, 422), (51, 404)):
        with pytest.raises(wclips.ClipError) as e:
            svc.clip(CLIP_MATCH, CLIP_KEY, i, ME)
        assert e.value.status == status, i


def test_clip_service_sans_cameras(synthetic_replay, monkeypatch):
    """Partie analysée avant le cameras.json (rattrapage pas encore passé) : clip sans caméra, le replay n'est lu
    qu'une fois (pas de lecture des caméras, environ 250 Mo, dans le serveur web)."""
    from rlpi import clips as rclips
    from rlpi.web import clips as wclips

    meta, touches = synthetic_replay
    lus = []
    monkeypatch.setattr(rclips, "read_cameras", lambda path: lus.append(path) or SYNTH_CAMS)
    s3 = clip_storage(meta, touches, cams={})
    svc = wclips.ClipService(s3=s3, bucket="b")
    body = json.loads(gzip.decompress(svc.clip(CLIP_MATCH, CLIP_KEY, 50, ME)))
    assert body["cam"] is None and svc.replay_reads == 1 and lus == []
    assert not any(k.endswith(".cameras.json") for k in s3.objects)


def test_clip_service_partie_reanalysee(synthetic_replay):
    """Une nouvelle version de la partie (matches.updated_at) relit le replay et change l'ETag ; l'ETag dépend aussi
    du joueur connecté (sa touche est préférée dans une image partagée)."""
    from rlpi.web import clips as wclips

    meta, touches = synthetic_replay
    svc = wclips.ClipService(s3=clip_storage(meta, touches), bucket="b")
    svc.clip(CLIP_MATCH, CLIP_KEY, 50, ME, "v1")
    svc.clip(CLIP_MATCH, CLIP_KEY, 50, ME, "v1")
    assert svc.replay_reads == 1
    svc.clip(CLIP_MATCH, CLIP_KEY, 50, ME, "v2")  # partie réanalysée : ni la partie ni le clip gardés ne servent
    assert svc.replay_reads == 2 and svc.last is not None and svc.last.version == "v2"
    tags = {wclips.tag(CLIP_MATCH, v, 50, who) for v in ("v1", "v2") for who in (ME, "Steam:0")}
    assert len(tags) == 4


def test_clip_service_async_clip_garde_servi_pendant_une_lecture(synthetic_replay, monkeypatch):
    """Route asynchrone : un clip déjà gardé est servi tout de suite, même quand toutes les places de lecture sont
    prises ; les demandes en trop attendent leur place sans occuper de thread."""
    import threading

    import anyio

    from rlpi import clips as rclips
    from rlpi.web import clips as wclips
    from tests.test_clips import synthetic

    meta, touches = synthetic_replay
    svc = wclips.ClipService(max_reads=1, s3=clip_storage(meta, touches), bucket="b")
    first = svc.clip(CLIP_MATCH, CLIP_KEY, 50, ME, "v1")
    gate, reading = threading.Event(), threading.Event()

    def slow(path, fps=120):
        reading.set()
        gate.wait(5)
        return synthetic()

    monkeypatch.setattr(rclips, "read_replay", slow)

    async def main():
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(svc.aclip, CLIP_MATCH, CLIP_KEY, 50, ME, "v2")  # partie réanalysée : lecture lente
                tg.start_soon(svc.aclip, CLIP_MATCH, CLIP_KEY, 60, ME, "v3")  # pas de place : attend
                await anyio.to_thread.run_sync(reading.wait, 5)
                await anyio.sleep(0.05)
                with anyio.fail_after(1):
                    assert await svc.aclip(CLIP_MATCH, CLIP_KEY, 50, ME, "v1") == first
                stats = svc.limiter.statistics()
                assert stats.borrowed_tokens == 1 and stats.tasks_waiting == 1
                gate.set()
        finally:
            gate.set()

    anyio.run(main)
    assert svc.replay_reads == 3


def test_clip_service_stockage_incomplet(synthetic_replay):
    from rlpi.web import clips as wclips

    meta, touches = synthetic_replay
    svc = wclips.ClipService(s3=clip_storage(meta, touches, replay=None), bucket="b")
    with pytest.raises(wclips.ClipError) as e:
        svc.clip(CLIP_MATCH, CLIP_KEY, 51, ME)  # touche inconnue : le replay n'est pas demandé
    assert e.value is wclips.TOUCH_UNKNOWN
    with pytest.raises(wclips.ClipError) as e:
        svc.clip(CLIP_MATCH, CLIP_KEY, 50, ME)
    assert e.value is wclips.REPLAY_MISSING and svc.replay_reads == 0
    with pytest.raises(wclips.ClipError) as e:
        wclips.ClipService(s3=FakeS3(), bucket="b").clip("autre", "replays/autre.replay", 50, ME)
    assert e.value is wclips.GAME_MISSING


def test_clip_vrai_replay(tmp_path):
    """Sur un vrai replay de data/raw/ (sauté s'il n'y en a pas) : chaque touche notée donne un clip calé."""
    import polars as pl

    from rlpi import frames
    from rlpi.web import clips as wclips
    from tests.test_clips import RAW

    if not RAW:
        pytest.skip("aucun replay dans data/raw/")
    frames.extract(str(RAW[0]), str(tmp_path))
    rid = RAW[0].stem
    meta = json.loads((tmp_path / f"{rid}.meta.json").read_text(encoding="utf-8"))
    by_slot = {p["slot"]: p for p in meta["players"]}
    f10 = pl.read_parquet(tmp_path / f"{rid}.parquet", columns=["ball_x", "ball_y"])
    picks = pl.read_parquet(tmp_path / f"{rid}.touches.parquet").filter(
        (pl.col("slot") >= 0) & (pl.col("i") >= 40) & (pl.col("i") < f10.height - 20)
    )
    touches = []
    for i, s in picks.select("i", "slot").unique("i", keep="first", maintain_order=True).head(8).iter_rows():
        sgn = 1 if by_slot[s]["team"] == 0 else -1  # touch_values : repère de l'équipe du toucheur
        bx, by = f10["ball_x"][i], f10["ball_y"][i]
        touches.append({"i": i, "player_id": by_slot[s]["id"], "ball_x": sgn * bx, "ball_y": sgn * by})
    svc = wclips.ClipService(s3=clip_storage(meta, touches, RAW[0].read_bytes()), bucket="b")
    for t in touches:
        body = json.loads(gzip.decompress(svc.clip(CLIP_MATCH, CLIP_KEY, t["i"], ME)))
        schemas.Clip.model_validate(body)
        assert judged(body).count(True) == 1
        bx, by, _ = ball_at(body, body["t0"])  # repère de l'équipe de l'auteur, comme touch_values
        assert abs(bx - t["ball_x"]) < 60 and abs(by - t["ball_y"]) < 60
    assert svc.replay_reads == 1


def test_clip_sans_session(client):
    assert client.get(f"/api/joueurs/{ME}/matchs/{CLIP_MATCH}/clips/50").status_code == 401


@pytest.fixture
def clip_app(app_db, synthetic_replay, monkeypatch):
    from rlpi.web import clips as wclips
    from rlpi.web.routes import api

    c, _, db = app_db
    meta, touches = synthetic_replay
    svc = wclips.ClipService(s3=clip_storage(meta, touches), bucket="b")
    monkeypatch.setattr(api, "CLIPS", svc)
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO matches (id, source, status, replay_key) VALUES (%s, 'fichier', 'ok', %s)",
            (CLIP_MATCH, CLIP_KEY),
        )
        conn.execute("INSERT INTO matches (id, source, status) VALUES ('partie-autre', 'fichier', 'ok')")
        conn.execute("INSERT INTO match_players VALUES (%s, %s, 'Moi', 1)", (CLIP_MATCH, ME))
        conn.execute("INSERT INTO match_players VALUES ('partie-autre', 'Steam:0', 'Autre', 0)")
    login(c, ME, db)
    return c, svc, db


def test_clip_api(clip_app):
    c, svc, db = clip_app
    url = f"/api/joueurs/{ME}/matchs/{CLIP_MATCH}/clips"
    r = c.get(f"{url}/50", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    assert r.headers["cache-control"] == "private, max-age=86400" and r.headers["etag"].startswith('"clip-')
    body = r.json()
    schemas.Clip.model_validate(body)
    assert body["id"] == f"{CLIP_MATCH}:50" and ball_at(body, body["t0"]) == [-6000, -500, 93]
    assert c.get(f"{url}/50", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    assert c.get(f"{url}/60").status_code == 200 and svc.replay_reads == 1  # même partie : replay gardé
    svc.last = None  # partie oubliée : le clip déjà fait vient du cache des clips, sans relire le replay
    assert c.get(f"{url}/50").json() == body and svc.replay_reads == 1
    assert c.get("/api/joueurs/Steam:0/matchs/partie-autre/clips/50").status_code == 403
    assert c.get(f"/api/joueurs/{ME}/matchs/partie-autre/clips/50").status_code == 404  # pas sa partie
    assert c.get(f"/api/joueurs/{ME}/matchs/inconnue/clips/50").status_code == 404
    with psycopg.connect(db, autocommit=True) as conn:  # partie réanalysée : nouvel ETag, replay relu
        conn.execute("UPDATE matches SET updated_at = now() + interval '1 second' WHERE id = %s", (CLIP_MATCH,))
    r2 = c.get(f"{url}/50", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 200 and r2.headers["etag"] != r.headers["etag"] and svc.replay_reads == 2
    r = c.get(f"{url}/51")
    assert r.status_code == 404 and r.json()["detail"] == "Touche inconnue dans cette partie."
    r = c.get(f"{url}/70")
    assert r.status_code == 422 and r.json()["detail"] == "Impossible de retrouver cette touche dans le replay."
    assert c.get(f"{url}/-1").status_code == 422
    with psycopg.connect(db, autocommit=True) as conn:  # replay supprimé (RLPI_KEEP_REPLAYS=0)
        conn.execute("UPDATE matches SET replay_key = 'replays/efface.replay' WHERE id = %s", (CLIP_MATCH,))
    svc.last = None
    svc.clips.mem.clear()
    r = c.get(f"{url}/50")
    assert r.status_code == 404 and r.json()["detail"] == "Replay non conservé pour cette partie."
