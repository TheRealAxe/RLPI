"""Garde-fou de la refonte : le contenu du tableau de bord calculé sur le jeu d'essai ne doit pas bouger.

Compare le contenu de /moi (agrégats des parties → rlpi.dashboard.content.page) pour plusieurs combinaisons de
filtres à tests/snapshots/tableau_de_bord.json. Seuls changent d'une exécution à l'autre, et sont donc retirés : la
date de calcul (« generated »). Les nombres à virgule sont arrondis à 10 chiffres significatifs, pour que de
minuscules écarts de calcul entre Windows et Linux ne fassent pas échouer le test ; tout autre changement le fait
échouer.

L'instantané a été écrit en phase B avec l'ancien calcul (tables de toutes les parties rassemblées) ; depuis la
phase D, le contenu est calculé à partir des agrégats de chaque partie, et il doit rester identique, y compris après
un passage par Postgres.

Changement voulu des indicateurs (hors refonte) : régénérer avec
    .venv/Scripts/python -m pytest tests/test_snapshot.py --update-snapshot
et noter la raison dans le journal.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tests.payload import aggregates, game_dirs, games, payload, reference, reference_context

SNAPSHOT = Path(__file__).parent / "snapshots" / "tableau_de_bord.json"


def normalize(x):
    if isinstance(x, dict):
        return {k: normalize(v) for k, v in x.items() if k != "generated"}
    if isinstance(x, list):
        return [normalize(v) for v in x]
    if isinstance(x, float):
        if not math.isfinite(x) or x == 0:
            return x
        return float(f"{x:.10g}")
    return x


def cases(j: dict) -> dict[str, dict]:
    m1, m2 = j["coequipiers"]
    return {
        "defaut": {},
        "coequipier": {"j": m1},
        "periode": {"since": "2026-01-01", "until": "2026-12-31"},
        "avec": {"avec": m1},
        "sans": {"sans": f"{m1},{m2}"},
    }


@pytest.fixture(scope="module")
def aggs():
    return aggregates()


@pytest.fixture(scope="module")
def ref():
    return reference()


def check_snapshot(g, ref, joueurs, request) -> None:
    me = joueurs["principal"]
    got = {name: normalize(payload(g, ref, me, **f)) for name, f in cases(joueurs).items()}
    text = json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if request.config.getoption("--update-snapshot") or not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(text, encoding="utf-8", newline="\n")
        pytest.skip(f"instantané écrit : {SNAPSHOT.name}")
    want = SNAPSHOT.read_text(encoding="utf-8")
    if text != want:
        diff = Path(request.config.rootpath) / ".pytest_cache" / "tableau_de_bord.obtenu.json"
        diff.parent.mkdir(exist_ok=True)
        diff.write_text(text, encoding="utf-8", newline="\n")
        pytest.fail(f"le contenu du tableau de bord a changé ; obtenu écrit dans {diff} (comparer avec {SNAPSHOT})")


def test_instantane_tableau_de_bord(aggs, ref, joueurs, request):
    check_snapshot(games(aggs), ref, joueurs, request)


def test_instantane_couvre_les_sections(aggs, ref, joueurs):
    """Le jeu d'essai remplit bien toutes les sections (sinon l'instantané ne garderait pas grand-chose)."""
    out = payload(games(aggs), ref, joueurs["principal"])
    assert out["error"] is None
    p = out["profiles"][joueurs["principal"]]
    assert set(out["order"]) == {joueurs["principal"], *joueurs["coequipiers"]}
    for k in (
        "refs",
        "value",
        "peers",
        "passes",
        "heat",
        "perf",
        "synergy",
        "compo",
        "tech",
        "record",
        "style",
        "advice",
        "progress",
    ):
        assert p.get(k), f"section vide : {k}"
    assert set(p["refs"]) == {"rlcs", "ssl"}


def test_aucun_sous_processus(joueurs, monkeypatch):
    """Agrégats et contenu calculés dans le processus, sans sous-processus."""
    import subprocess

    def interdit(*a, **k):
        raise AssertionError(f"sous-processus lancé : {a[:1]}")

    monkeypatch.setattr(subprocess, "Popen", interdit)
    assert payload(games(aggregates(game_dirs()[:2])), reference(), joueurs["principal"])["error"] is None


def test_deux_joueurs_dans_le_meme_processus(aggs, ref, joueurs):
    """Deux ensembles de parties calculés l'un après l'autre : rien n'est mélangé."""
    me = joueurs["principal"]
    a = payload(games(aggs), ref, me)["profiles"][me]
    b = payload(games(aggs[:3]), ref, me)["profiles"][me]
    assert (a["n_matches"], b["n_matches"]) == (8, 3)
    assert len(b["value"]["matches"]) == 3
    assert payload(games(aggs), ref, me)["profiles"][me]["n_matches"] == 8


def test_json_garde_nan_et_infini():
    from rlpi.dashboard.common import decode, encode

    x = {"a": [math.nan, math.inf, -math.inf, 1.5, None, "NaN", -0.0, 0.0], "b": {"c": float("nan")}}
    back = decode(json.loads(json.dumps(encode(x), allow_nan=False)))
    assert math.isnan(back["a"][0]) and back["a"][1:] == [math.inf, -math.inf, 1.5, None, "NaN", 0.0, 0.0]
    assert math.copysign(1, back["a"][6]) == -1 and math.copysign(1, back["a"][7]) == 1
    assert math.isnan(back["b"]["c"])


def test_ligne_de_commande_identique(ref, joueurs):
    """Le chemin de la ligne de commande (dossier de données rassemblé, coupé partie par partie) donne le même
    contenu que les dossiers de parties du worker."""
    import tempfile

    from rlpi import game
    from rlpi.context import DataContext
    from rlpi.dashboard import games_from_context

    me = joueurs["principal"]
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        game.merge(game_dirs(), data, "perso")
        ctx = DataContext(data=data, source="perso", ref=reference_context().ref, models=reference_context().models)
        merged = games_from_context(ctx)
        a = normalize(payload(merged, ref, me))
    b = normalize(payload(games(aggregates()), ref, me))
    assert a == b


# ------------------------------------------------------------------------------------------------ Postgres


def fill_database(conn, aggs: list[dict]) -> None:
    from rlpi.dashboard import storage

    for agg in aggs:
        conn.execute("INSERT INTO matches (id, source, status) VALUES (%s, 'fichier', 'ok')", (agg["match_id"],))
        for p in agg["game"]["players"]:
            conn.execute(
                "INSERT INTO match_players (match_id, player_id, player_name, team) VALUES (%s, %s, %s, %s)",
                (agg["match_id"], p["id"], p["name"], p["team"]),
            )
        storage.write(conn, agg)


def test_instantane_depuis_postgres(db, aggs, joueurs, request, monkeypatch):
    """Agrégats écrits en base puis relus (comme le serveur), référence enregistrée puis relue : même contenu."""
    import psycopg

    from rlpi.dashboard import storage

    monkeypatch.setattr(storage, "_cache", type(storage._cache)())
    monkeypatch.setattr(storage, "_ref", None)
    with psycopg.connect(db, autocommit=True) as c:
        fill_database(c, aggs)
    g, n, pending = storage.player_games(joueurs["principal"])
    assert (n, pending) == (8, 0) and g is not None
    storage.ensure_reference(reference_context())
    monkeypatch.setattr(storage, "_ref", None)  # relue en base, pas gardée en mémoire
    check_snapshot(g, storage.ensure_reference(reference_context()), joueurs, request)


def test_version_et_parties_en_preparation(db, aggs, joueurs, monkeypatch):
    import psycopg

    from rlpi.dashboard import storage

    monkeypatch.setattr(storage, "_cache", type(storage._cache)())
    me = joueurs["principal"]
    with psycopg.connect(db, autocommit=True) as c:
        fill_database(c, aggs[:2])
        assert storage.player_state(c, me)[1:] == (2, 0)
        c.execute("INSERT INTO matches (id, source, status) VALUES ('sans-agregats', 'fichier', 'ok')")
        c.execute("INSERT INTO match_players (match_id, player_id) VALUES ('sans-agregats', %s)", (me,))
        v1, n, pending = storage.player_state(c, me)
        assert (n, pending) == (2, 1)
        assert storage.missing(c) == ["sans-agregats"]
        assert len(storage.missing(c, everything=True)) == 3
        g1 = storage.player_games(me)[0]
        assert storage.player_games(me)[0] is g1  # gardé en mémoire tant que rien ne change
        storage.write(c, aggs[0])  # partie recalculée : version des données augmentée
        assert storage.player_state(c, me)[0] == v1 + 1
        assert storage.player_games(me)[0] is not g1
        c.execute("UPDATE game_aggregates SET version = version - 1 WHERE match_id = %s", (aggs[1]["match_id"],))
        assert set(storage.missing(c)) == {"sans-agregats", aggs[1]["match_id"]}
