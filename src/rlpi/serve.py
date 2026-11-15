"""Serveur local des rapports, avec un tableau de bord filtrable généré à la demande.

    python -m rlpi.serve [--port 8765] [--since 2026-11-14]

- Sert le dossier reports/ (page d'accueil, swipe, archives…).
- /tableau_de_bord.html est calculé à chaque demande selon l'adresse :
    ?j=<id du joueur affiché>&du=AAAA-MM-JJ&au=AAAA-MM-JJ&avec=<id>,<id>&sans=<id>
  (sans paramètre : profil d'Axe, parties à partir de --since). Environ 2 s par nouvelle combinaison,
  puis mise en cache tant que les données ne changent pas.
- N'écoute que sur 127.0.0.1 par défaut.
- /health répond « ok » (contrôle de santé du conteneur).

En production (conteneur Coolify), tout se règle par variables d'environnement :
    RLPI_HOST=0.0.0.0  PORT=3001  RLPI_REPORTS=/app/data/reports
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import polars as pl

from rlpi.config import ROOT
from rlpi.dashboard import FEAT, make_payload

REPORTS = Path(os.getenv("RLPI_REPORTS") or ROOT / "reports")
TEMPLATE = Path(__file__).parent / "dashboard_template.html"
PLAYERS = ["Steam:76561198078330309", "LAinox", "Rileq"]  # profils proposés (le premier par défaut)
STATS = FEAT / "player_match_stats_theo.parquet"


def roster() -> tuple[list[str], dict[str, str], list[dict]]:
    """Identifiants et pseudos des profils, et nombre de parties par jour (pour la plage de dates)."""
    df = pl.read_parquet(STATS, columns=["player_id", "player_name", "date", "replay_file"])
    ids, names = [], {}
    for q in PLAYERS:
        d = df.filter((pl.col("player_id") == q) | (pl.col("player_name").str.to_lowercase() == q.lower()))
        if d.is_empty():
            continue
        pid = d["player_id"].mode()[0]
        ids.append(pid)
        names[pid] = d.filter(pl.col("player_id") == pid).sort("date")["player_name"][-1]
    me = df.filter(pl.col("player_id") == ids[0]).unique("replay_file")
    days = (me.with_columns(pl.col("date").str.slice(0, 10).alias("d")).group_by("d").agg(pl.len().alias("n"))
            .sort("d").to_dicts())
    return ids, names, days


class Handler(SimpleHTTPRequestHandler):
    since_default: str | None = None
    cache: dict = {}

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(REPORTS), **kw)

    def log_message(self, fmt, *args):  # journal discret
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path in ("/tableau_de_bord.html", "/tableau_de_bord"):
            return self.dashboard(parse_qs(u.query))
        return super().do_GET()

    def dashboard(self, q: dict) -> None:
        ids, names, days = roster()
        get = lambda k: (q.get(k) or [""])[0].strip() or None  # noqa: E731
        sel = get("j") if get("j") in ids else ids[0]
        since = get("du") if "du" in q else self.since_default
        until = get("au")
        avec = [x for x in (get("avec") or "").split(",") if x in ids and x != sel]
        sans = [x for x in (get("sans") or "").split(",") if x in ids and x != sel and x not in avec]
        key = (sel, since, until, tuple(avec), tuple(sans), STATS.stat().st_mtime, TEMPLATE.stat().st_mtime)
        html = self.cache.get(key)
        if html is None:
            try:
                payload = make_payload(sel, [i for i in ids if i != sel], since, until, avec, sans)
                err = None
            except SystemExit as e:  # aucune partie pour ce filtre
                payload, err = None, str(e)
            data = {"dynamic": True, "default": sel, "order": ids, "names": names, "days": days,
                    "filters": {"j": sel, "du": since, "au": until, "avec": avec, "sans": sans},
                    "profiles": {sel: payload} if payload else {}, "error": err}
            html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
            self.cache[key] = html
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.getenv("RLPI_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8765")))
    ap.add_argument("--since", default=os.getenv("RLPI_SINCE"), help="date de début par défaut (AAAA-MM-JJ)")
    a = ap.parse_args()
    Handler.since_default = a.since
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Rapports sur http://{a.host}:{a.port}/ (dossier {REPORTS}, Ctrl+C pour arrêter)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
