"""Journaux structurés (rlpi.logs) et identifiant de requête du serveur."""

from __future__ import annotations

import json
import logging

from rlpi import logs


def lines(capsys) -> list[str]:
    return [x for x in capsys.readouterr().out.splitlines() if x.strip()]


def test_json(monkeypatch, capsys):
    monkeypatch.setenv("RLPI_LOG_FORMAT", "json")
    logs.configure("worker", worker="w1")
    logs.log("fin de partie", match="abc", statut="ok", erreur=None)
    rec = json.loads(lines(capsys)[-1])
    assert rec["msg"] == "fin de partie" and rec["service"] == "worker" and rec["worker"] == "w1"
    assert rec["match"] == "abc" and rec["level"] == "info" and rec["ts"].endswith("Z")
    assert "erreur" not in rec  # champs vides omis


def test_identifiant_de_requete(monkeypatch, capsys):
    monkeypatch.setenv("RLPI_LOG_FORMAT", "json")
    logs.configure("web")
    token = logs.request_id.set("abcd1234")
    try:
        logs.error("échec")
    finally:
        logs.request_id.reset(token)
    rec = json.loads(lines(capsys)[-1])
    assert rec["request_id"] == "abcd1234" and rec["level"] == "error"


def test_texte(monkeypatch, capsys):
    monkeypatch.setenv("RLPI_LOG_FORMAT", "texte")
    logs.log("état", file=3, bloquees=0)
    line = lines(capsys)[-1]
    assert line.endswith("état file=3 bloquees=0") and not line.startswith("{")


def test_formateur_uvicorn(monkeypatch):
    monkeypatch.setenv("RLPI_LOG_FORMAT", "json")
    logs.configure("web")
    rec = logging.LogRecord("uvicorn.error", logging.WARNING, __file__, 1, "Started %s", ("x",), None)
    out = json.loads(logs.JsonFormatter().format(rec))
    assert out["msg"] == "Started x" and out["level"] == "warning" and out["logger"] == "uvicorn.error"
