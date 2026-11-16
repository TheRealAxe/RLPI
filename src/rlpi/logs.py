"""Journaux du serveur et du worker : une ligne par événement, en JSON en production, lisible en local.

    log("fin de la partie", match="abc", status="ok", wall_s=21.4)
    → {"ts": "2026-11-18T03:00:00.123Z", "level": "info", "service": "worker", "msg": "fin de la partie",
       "match": "abc", "status": "ok", "wall_s": 21.4}                                (RLPI_LOG_FORMAT=json)
    → 2026-11-18 03:00:00 fin de la partie match=abc status=ok wall_s=21.4          (par défaut)

- RLPI_LOG_FORMAT : « json » dans les images Docker (lu par Coolify), « texte » sinon.
- Le service (« web », « worker »…) et les champs communs (identifiant du worker) sont posés une fois par
  `configure()` ; l'identifiant de requête de l'API (`request_id`, rlpi.web.main) est ajouté de lui-même à toute
  ligne écrite pendant la requête, y compris depuis les fils de calcul (contextvars).
- JsonFormatter met au même format les journaux de la librairie standard (uvicorn) : voir
  config/journal_uvicorn.json, passé à uvicorn par le Dockerfile.

Jamais de cookie, de jeton ni d'URL de connexion dans un journal.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id: ContextVar[str | None] = ContextVar("rlpi_request_id", default=None)
_common: dict[str, Any] = {}


def json_mode() -> bool:
    return os.getenv("RLPI_LOG_FORMAT", "texte").strip().lower() == "json"


def configure(service: str, **fields: Any) -> None:
    """Service et champs ajoutés à chaque ligne de ce processus."""
    _common.clear()
    _common.update(service=service, **fields)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _line(level: str, msg: str, fields: dict[str, Any]) -> str:
    rid = request_id.get()
    if json_mode():
        rec: dict[str, Any] = {"ts": _now_iso(), "level": level, **_common, "msg": msg}
        if rid:
            rec["request_id"] = rid
        rec.update({k: v for k, v in fields.items() if v is not None})
        return json.dumps(rec, ensure_ascii=False, default=str)
    extra = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    prefix = "" if level == "info" else f"[{level}] "
    return f"{time.strftime('%Y-%m-%d %H:%M:%S')} {prefix}{msg}" + (f" {extra}" if extra else "")


def log(msg: str, level: str = "info", **fields: Any) -> None:
    """Une ligne de journal sur la sortie standard (`level` : info, warning, error)."""
    print(_line(level, msg, fields), file=sys.stdout, flush=True)


def warning(msg: str, **fields: Any) -> None:
    log(msg, "warning", **fields)


def error(msg: str, **fields: Any) -> None:
    log(msg, "error", **fields)


class JsonFormatter(logging.Formatter):
    """Lignes de la librairie standard (uvicorn) au format de log() ; service lu dans RLPI_SERVICE."""

    def format(self, record: logging.LogRecord) -> str:
        if not _common:
            configure(os.getenv("RLPI_SERVICE", "web"))
        msg = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        level = {"WARNING": "warning", "ERROR": "error", "CRITICAL": "error"}.get(record.levelname, "info")
        return _line(level, msg, {"logger": record.name})
