"""Serveur local des rapports, avec un tableau de bord filtrable généré à la demande.

    python -m rlpi.serve [--port 8765] [--since 2026-11-14]

- Sert le dossier reports/ (page d'accueil, swipe, archives…).
- /tableau_de_bord.html est calculé à chaque demande selon l'adresse :
    ?j=<id du joueur affiché>&du=AAAA-MM-JJ&au=AAAA-MM-JJ&avec=<id>,<id>&sans=<id>
  (sans paramètre : profil RLPI_PLAYER du .env, parties à partir de --since). 3 à 9 s par nouvelle combinaison,
  puis mise en cache (mémoire + disque, voir rlpi.pagecache) tant que les données et le code ne changent pas.
  La page par défaut de chaque profil est pré-calculée au démarrage et dès que de nouvelles parties arrivent.
- N'écoute que sur 127.0.0.1 par défaut.
- /health répond « ok » (contrôle de santé du conteneur).
- Version multi-joueurs (voir rlpi.account et rlpi.players) : /connexion (Steam), /moi (tableau de bord du joueur
  connecté, mêmes paramètres que /tableau_de_bord.html), POST /moi/actualiser, /deconnexion.

En production (conteneur Coolify), tout se règle par variables d'environnement :
    RLPI_HOST=0.0.0.0  PORT=3001  RLPI_REPORTS=/app/data/reports
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import polars as pl

from rlpi import config
from rlpi.config import ROOT, SOURCE
from rlpi.dashboard import FEAT, make_payload
from rlpi.fonts import PLACEHOLDER, font_css  # polices intégrées dans la page (plus de Google Fonts)
from rlpi.pagecache import PageCache

REPORTS = Path(os.getenv("RLPI_REPORTS") or ROOT / "reports")
TEMPLATE = Path(__file__).parent / "dashboard_template.html"
PLAYERS = [p for p in [config.PLAYER, *config.COMPARE] if p]  # profils proposés (le premier par défaut), réglés dans .env
STATS = FEAT / f"player_match_stats_{SOURCE}.parquet"


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


PAGES = PageCache()          # cache des pages : mémoire + disque (voir rlpi.pagecache)
WARM_EVERY_S = 60            # vérification des nouvelles parties pour le pré-calcul


def dashboard_html(ids: list[str], names: dict, days: list, sel: str, since: str | None, until: str | None,
                   avec: list[str], sans: list[str]) -> str:
    """Page du tableau de bord général pour une combinaison de filtres (calculée une fois, puis en cache)."""
    key = ("tdb", sel, since, until, tuple(avec), tuple(sans), STATS.stat().st_mtime)

    def build() -> str:
        try:
            payload = make_payload(sel, [i for i in ids if i != sel], since, until, avec, sans)
            err = None
        except SystemExit as e:  # aucune partie pour ce filtre
            payload, err = None, str(e)
        data = {"dynamic": True, "default": sel, "order": ids, "names": names, "days": days,
                "filters": {"j": sel, "du": since, "au": until, "avec": avec, "sans": sans},
                "profiles": {sel: payload} if payload else {}, "error": err}
        return (TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
                .replace(PLACEHOLDER, font_css()))

    return PAGES.compute(key, build)


def warm_defaults(since: str | None) -> None:
    """Pré-calcule la page par défaut (sans filtre) de chaque profil, pour que le premier visiteur n'attende pas."""
    t0 = time.perf_counter()
    ids, names, days = roster()
    for sel in ids:
        dashboard_html(ids, names, days, sel, since, None, [], [])
    print(f"pré-calcul : {len(ids)} tableaux de bord prêts en {time.perf_counter() - t0:.1f} s", flush=True)


def warm_loop(since: str | None) -> None:
    """Au démarrage puis dès que de nouvelles parties arrivent (le fichier des stats change), pré-calcule."""
    last = None
    while True:
        try:
            m = STATS.stat().st_mtime if STATS.exists() else None
            if m is not None and m != last:
                warm_defaults(since)
                last = m
        except Exception as e:  # noqa: BLE001 — le pré-calcul ne doit jamais faire tomber le serveur
            print(f"pré-calcul : {type(e).__name__}: {e}", flush=True)
        time.sleep(WARM_EVERY_S)


class Handler(SimpleHTTPRequestHandler):
    since_default: str | None = None

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
        if u.path in ("/moi", "/connexion", "/connexion/retour", "/deconnexion"):
            return self.account_route(u.path, parse_qs(u.query))
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path == "/moi/actualiser":
            return self.account_route("/moi/actualiser", {})
        self.send_error(404)

    def send_html(self, html: str, status: int = 200, headers: dict | None = None) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, to: str, cookie: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", to)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def account_route(self, path: str, q: dict) -> None:
        """Connexion Steam et page personnelle (version multi-joueurs)."""
        from rlpi import account

        if not account.configured():
            return self.send_html(account.page("RLPI", "<p>Espace joueur non configuré sur ce serveur.</p>"
                                                       "<p class='note'>Variables manquantes dans Coolify : "
                                                       f"{', '.join(account.missing())}.</p>"), 404)
        if path == "/connexion":
            return self.redirect(account.steam_login_url())
        if path == "/connexion/retour":
            try:
                steam_id = account.steam_verify(q)
            except Exception as e:  # noqa: BLE001 — Steam injoignable
                print(f"connexion Steam : {type(e).__name__}: {e}", flush=True)
                steam_id = None
            if not steam_id:
                return self.send_html(account.page("RLPI", "<p>La connexion Steam n'a pas abouti.</p>"
                                                           "<a class='btn' href='/connexion'>Réessayer</a>"), 403)
            return self.redirect("/moi", account.make_cookie(account.login(steam_id)))
        if path == "/deconnexion":
            return self.redirect("/moi", account.clear_cookie())
        pid = account.session_player(self.headers.get("Cookie"))
        if pid is None:
            return self.send_html(account.login_page())
        if path == "/moi/actualiser":
            done = account.refresh(pid)
            return self.redirect("/moi?recherche=" + ("1" if done else "attente"))
        return self.my_dashboard(pid, q)

    def my_dashboard(self, pid: str, q: dict) -> None:
        from rlpi import account, players

        get = lambda k: (q.get(k) or [""])[0].strip() or None  # noqa: E731
        msg = {"1": "Recherche lancée : les nouvelles parties arrivent dans quelques minutes.",
               "attente": "Recherche déjà faite il y a moins de 5 minutes."}.get(get("recherche") or "")
        try:
            data, n = players.build(pid)
        except Exception as e:  # noqa: BLE001 — stockage ou base indisponible…
            print(f"joueur {pid} : {type(e).__name__}: {e}", flush=True)
            return self.send_html(account.page("RLPI", "<p>Tes données sont momentanément indisponibles. "
                                                       "Réessaie dans un instant.</p>"), 503)
        if data is None:
            return self.send_html(account.import_page(pid, account.import_state(pid)))
        stats = data / "features" / "player_match_stats_perso.parquet"
        args = (get("j"), get("du"), get("au"),
                [x for x in (get("avec") or "").split(",") if x], [x for x in (get("sans") or "").split(",") if x])
        key = ("moi", pid, args[:3], tuple(args[3]), tuple(args[4]),
               stats.stat().st_mtime if stats.exists() else 0)

        def build() -> str:
            d = players.payload(pid, data, *args)
            return (TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(d, ensure_ascii=False))
                    .replace(PLACEHOLDER, font_css()))

        try:
            page_html = PAGES.compute(key, build)
        except Exception as e:  # noqa: BLE001
            print(f"joueur {pid} : {type(e).__name__}: {e}", flush=True)
            return self.send_html(account.page("RLPI", "<p>Ton tableau de bord n'a pas pu être calculé.</p>"), 500)
        self.send_html(page_html.replace("</body>", account.toolbar(pid, n, msg) + "</body>", 1))

    def dashboard(self, q: dict) -> None:
        ids, names, days = roster()
        get = lambda k: (q.get(k) or [""])[0].strip() or None  # noqa: E731
        sel = get("j") if get("j") in ids else ids[0]
        since = get("du") if "du" in q else self.since_default
        until = get("au")
        avec = [x for x in (get("avec") or "").split(",") if x in ids and x != sel]
        sans = [x for x in (get("sans") or "").split(",") if x in ids and x != sel and x not in avec]
        html = dashboard_html(ids, names, days, sel, since, until, avec, sans)
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
    threading.Thread(target=warm_loop, args=(a.since,), daemon=True, name="pre-calcul").start()
    print(f"Rapports sur http://{a.host}:{a.port}/ (dossier {REPORTS}, Ctrl+C pour arrêter)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
