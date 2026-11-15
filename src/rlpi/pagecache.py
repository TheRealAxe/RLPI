"""Cache des pages calculées par le serveur (tableau de bord général et espace joueur).

Avant : un dictionnaire en mémoire, sans limite, perdu à chaque redémarrage → 3 à 9 s de calcul à la première
ouverture de chaque combinaison (joueur, période, filtres).

- Mémoire : les MEM_MAX pages les plus récentes (LRU).
- Disque : pages compressées (gzip) dans <dossier>/<empreinte>.html.gz, au plus DISK_MAX_FILES fichiers et
  DISK_MAX_BYTES octets (les plus anciennes supprimées d'abord). Survit aux redémarrages ; survit aussi aux
  redéploiements si le dossier est sur un volume persistant (en production : /app/cache/pages).
- Un verrou par page : deux demandes simultanées de la même page (ou le pré-calcul et un visiteur) ne
  déclenchent qu'un seul calcul.
- La clé de chaque page inclut une empreinte du code (src/rlpi + gabarit + polices) : après un changement de
  code, les anciennes pages ne sont plus servies.

Dossier : RLPI_PAGES_CACHE, sinon <RLPI_USERS_CACHE>/pages, sinon data/cache/pages.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable

from rlpi.config import ROOT

MEM_MAX = 24
DISK_MAX_FILES = 300
DISK_MAX_BYTES = 500 * 1024 * 1024


def _default_dir() -> Path:
    if os.getenv("RLPI_PAGES_CACHE"):
        return Path(os.environ["RLPI_PAGES_CACHE"])
    if os.getenv("RLPI_USERS_CACHE"):
        return Path(os.environ["RLPI_USERS_CACHE"]) / "pages"
    return ROOT / "data" / "cache" / "pages"


def code_version() -> str:
    """Empreinte du contenu du code qui produit les pages (pas des dates : elles changent à chaque déploiement)."""
    src = Path(__file__).parent
    h = hashlib.sha1()
    files = sorted(src.glob("*.py")) + [src / "dashboard_template.html"] + sorted((src / "assets").rglob("*.css"))
    for f in files:
        if f.exists():
            h.update(f.name.encode()); h.update(f.read_bytes())
    return h.hexdigest()[:12]


class PageCache:
    def __init__(self, root: Path | None = None):
        self.root = root or _default_dir()
        self.version = code_version()
        self.mem: OrderedDict[str, str] = OrderedDict()
        self.lock = threading.Lock()
        self.key_locks: dict[str, threading.Lock] = {}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.disk = os.access(self.root, os.W_OK)
        except OSError:
            self.disk = False
        if not self.disk:
            print(f"cache des pages : dossier {self.root} non accessible en écriture, mémoire seulement", flush=True)

    def _id(self, key) -> str:
        return hashlib.sha1(json.dumps([self.version, key], default=str, ensure_ascii=False).encode()).hexdigest()

    def get(self, key) -> str | None:
        k = self._id(key)
        with self.lock:
            if k in self.mem:
                self.mem.move_to_end(k)
                return self.mem[k]
        if self.disk:
            f = self.root / f"{k}.html.gz"
            try:
                html = gzip.decompress(f.read_bytes()).decode("utf-8")
                os.utime(f)                                     # « récemment utilisée » pour le ménage
            except (OSError, EOFError):
                return None
            self._mem_put(k, html)
            return html
        return None

    def _mem_put(self, k: str, html: str) -> None:
        with self.lock:
            self.mem[k] = html
            self.mem.move_to_end(k)
            while len(self.mem) > MEM_MAX:
                self.mem.popitem(last=False)

    def put(self, key, html: str) -> None:
        k = self._id(key)
        self._mem_put(k, html)
        if not self.disk:
            return
        f = self.root / f"{k}.html.gz"
        tmp = f.with_suffix(f".{threading.get_ident()}.tmp")
        try:
            tmp.write_bytes(gzip.compress(html.encode("utf-8"), compresslevel=6))
            os.replace(tmp, f)
            self._prune()
        except OSError as e:
            print(f"cache des pages : écriture impossible ({e})", flush=True)

    def _prune(self) -> None:
        files = sorted(self.root.glob("*.html.gz"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        while files and (len(files) > DISK_MAX_FILES or total > DISK_MAX_BYTES):
            p = files.pop(0)
            total -= p.stat().st_size
            p.unlink(missing_ok=True)

    def compute(self, key, build: Callable[[], str]) -> str:
        """La page en cache, sinon calculée une seule fois même si plusieurs demandes arrivent en même temps."""
        html = self.get(key)
        if html is not None:
            return html
        k = self._id(key)
        with self.lock:
            kl = self.key_locks.setdefault(k, threading.Lock())
        with kl:
            html = self.get(key)                               # calculée pendant qu'on attendait le verrou ?
            if html is None:
                html = build()
                self.put(key, html)
        with self.lock:
            self.key_locks.pop(k, None)
        return html
