"""Réponses JSON calculées, gardées compressées en mémoire (remplace rlpi.pagecache).

La clé d'une réponse est son ETag : empreinte du code, version des données du joueur, empreinte de la référence et
filtres. Une réponse n'est donc jamais périmée : quand une nouvelle partie arrive, la version change et la clé avec.
- au plus MAX_ENTRIES réponses par processus (les plus anciennes sorties d'abord) ;
- un verrou par clé : deux demandes simultanées du même contenu ne le calculent qu'une fois ;
- gardées en gzip (≈ 3 fois plus petites) : envoyées telles quelles aux navigateurs qui acceptent gzip.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import threading
from collections import OrderedDict
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

MAX_ENTRIES = 64
GZIP_LEVEL = 1  # 3 fois plus rapide que 6 (≈ 40 ms de moins pour 1,7 Mo), à peine 15 % plus gros


@lru_cache(maxsize=1)
def code_version() -> str:
    """Empreinte du contenu du code Python (pas des dates : elles changent à chaque déploiement)."""
    src = Path(__file__).resolve().parents[1]
    h = hashlib.sha1()
    for f in sorted(src.rglob("*.py")):
        h.update(f.relative_to(src).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


def etag(*parts: object) -> str:
    raw = json.dumps([code_version(), *parts], default=str, ensure_ascii=False, sort_keys=True)
    return '"' + hashlib.sha1(raw.encode()).hexdigest()[:20] + '"'


def _finite(x):
    """NaN et ±infini → None (le JSON ne sait pas les écrire)."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    return x


def dumps(data) -> bytes:
    """JSON compact ; le contenu n'est parcouru pour remplacer NaN et ±infini que s'il en contient (rare)."""
    try:
        text = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except ValueError:
        text = json.dumps(_finite(data), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return text.encode("utf-8")


class JsonCache:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self.max = max_entries
        self.mem: OrderedDict[str, bytes] = OrderedDict()
        self.lock = threading.Lock()
        self.key_locks: dict[str, threading.Lock] = {}

    def get(self, key: str) -> bytes | None:
        with self.lock:
            gz = self.mem.get(key)
            if gz is not None:
                self.mem.move_to_end(key)
            return gz

    def put(self, key: str, gz: bytes) -> None:
        with self.lock:
            self.mem[key] = gz
            self.mem.move_to_end(key)
            while len(self.mem) > self.max:
                self.mem.popitem(last=False)

    def compute(self, key: str, build: Callable[[], object]) -> bytes:
        """Le JSON compressé (gzip), calculé une seule fois même si plusieurs demandes arrivent en même temps."""
        gz = self.get(key)
        if gz is not None:
            return gz
        with self.lock:
            kl = self.key_locks.setdefault(key, threading.Lock())
        try:
            with kl:
                gz = self.get(key)
                if gz is None:
                    gz = gzip.compress(dumps(build()), compresslevel=GZIP_LEVEL)
                    self.put(key, gz)
        finally:
            with self.lock:
                self.key_locks.pop(key, None)
        return gz
