"""Comptes joueurs : connexion avec Steam (OpenID 2.0), comptes, recherche des parties.

Un joueur se connecte avec son compte Steam : Steam nous renvoie son SteamID, qui est exactement l'identifiant
présent dans les replays (« Steam:7656… »). Aucun mot de passe n'est géré ici.
À la première connexion, le compte est créé (table accounts) et une recherche de ses parties sur ballchasing est
mise en file (les workers s'en chargent, voir rlpi.collector).

Routes (rlpi.web) : /auth/steam, /auth/steam/retour, POST /auth/deconnexion, POST /api/moi/actualiser ; les pages
sont dans l'interface Vue (web/).
Les sessions sont en base (rlpi.web.sessions) ; les fonctions de cookie signé ci-dessous (make_cookie,
session_player) ne servent plus qu'à accepter une dernière fois les cookies ouverts avant la phase E.

Développement seulement : RLPI_DEV_LOGIN=1 active /dev/connexion, qui ouvre une session pour n'importe quel joueur
sans passer par Steam ; la page de connexion liste les joueurs connus (/dev/joueurs). Le serveur refuse de démarrer
avec cette variable si RLPI_PUBLIC_URL est en https://.

Variables : RLPI_PUBLIC_URL (ex. https://rlpi.lainox.quest), RLPI_SECRET (longue chaîne aléatoire, signait les
anciens cookies), plus DATABASE_URL, REDIS_URL et S3_* (voir rlpi.store).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
import urllib.request
from typing import Any
from urllib.parse import urlencode

from rlpi import store

STEAM_OPENID = "https://steamcommunity.com/openid/login"
COOKIE = "rlpi_session"
SESSION_DAYS = 30
REFRESH_EVERY = 300  # secondes entre deux recherches manuelles


def base_url() -> str:
    return store.env("RLPI_PUBLIC_URL").rstrip("/")


# --------------------------------------------------------------------------------------------------------------
# Steam OpenID


RETURN_PATHS = ("/auth/steam/retour", "/connexion/retour")  # le second : connexions commencées avant la phase E


def steam_login_url() -> str:
    b = base_url()
    return STEAM_OPENID + "?" + urlencode({
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": f"{b}{RETURN_PATHS[0]}",
        "openid.realm": b,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    })


def steam_verify(query: dict[str, list[str]]) -> str | None:
    """Vérifie auprès de Steam la réponse reçue sur /connexion/retour. Retourne le SteamID64 ou None."""
    q = {k: v[0] for k, v in query.items() if k.startswith("openid.")}
    if q.get("openid.mode") != "id_res" or q.get("openid.op_endpoint") != STEAM_OPENID:
        return None
    if not q.get("openid.return_to", "").startswith(tuple(f"{base_url()}{p}" for p in RETURN_PATHS)):
        return None
    m = re.fullmatch(r"https://steamcommunity\.com/openid/id/(\d{17})", q.get("openid.claimed_id", ""))
    if not m:
        return None
    q["openid.mode"] = "check_authentication"
    req = urllib.request.Request(STEAM_OPENID, data=urlencode(q).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        answer = r.read().decode("utf-8", "replace")
    return m.group(1) if "is_valid:true" in answer else None


# --------------------------------------------------------------------------------------------------------------
# Anciens cookies signés (avant la phase E) : acceptés une dernière fois, puis remplacés par une session


def _sign(payload: str) -> str:
    return hmac.new(store.env("RLPI_SECRET").encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_cookie(player_id: str) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    payload = f"{player_id}|{exp}"
    secure = "; Secure" if base_url().startswith("https://") else ""
    return (f"{COOKIE}={payload}|{_sign(payload)}; Path=/; Max-Age={SESSION_DAYS * 86400}; HttpOnly; "
            f"SameSite=Lax{secure}")


def session_player(cookie_header: str | None) -> str | None:
    """Identifiant du joueur connecté, ou None."""
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k != COOKIE or v.count("|") != 2:
            continue
        pid, exp, sig = v.split("|")
        if hmac.compare_digest(sig, _sign(f"{pid}|{exp}")) and exp.isdigit() and int(exp) > time.time():
            return pid
    return None


# --------------------------------------------------------------------------------------------------------------
# Comptes


def login(steam_id: str) -> str:
    """Crée le compte au besoin et lance la recherche de ses parties. Retourne l'identifiant « Steam:… »."""
    pid = f"Steam:{steam_id}"
    with store.db() as c:
        new = store.scalar(c, "INSERT INTO accounts (player_id, last_login) VALUES (%s, now()) "
                              "ON CONFLICT (player_id) DO UPDATE SET last_login = now() "
                              "RETURNING (xmax = 0)", (pid,))
    if new:
        store.push_sync(store.redis_client(), pid)
    return pid


def dev_login_enabled() -> bool:
    return os.getenv("RLPI_DEV_LOGIN", "").strip().strip("\"'") == "1"


def dev_login(player_id: str) -> str:
    """Connexion de développement : crée le compte au besoin, sans lancer de recherche sur ballchasing (le bouton
    « Chercher mes nouvelles parties » le fait à la demande)."""
    if not dev_login_enabled():
        raise PermissionError("connexion de développement désactivée")
    with store.db() as c:
        c.execute("INSERT INTO accounts (player_id, last_login) VALUES (%s, now()) "
                  "ON CONFLICT (player_id) DO UPDATE SET last_login = now()", (player_id,))
    return player_id


def known_players(limit: int = 30) -> list[tuple[str, str | None, int]]:
    """Joueurs présents dans les parties traitées (identifiant, dernier pseudo, nombre de parties)."""
    with store.db() as c:
        return c.execute(
            "SELECT mp.player_id, max(mp.player_name), count(*) AS n FROM match_players mp "
            "JOIN matches m ON m.id = mp.match_id WHERE m.status IN ('ok', 'partiel') "
            "GROUP BY mp.player_id ORDER BY n DESC, mp.player_id LIMIT %s", (limit,)).fetchall()


def refresh(player_id: str) -> bool:
    """Recherche manuelle de nouvelles parties ; False si la précédente date de moins de 5 minutes."""
    r = store.redis_client()
    if not r.set(f"rlpi:refresh:{player_id}", "1", nx=True, ex=REFRESH_EVERY):
        return False
    store.push_sync(r, player_id)
    return True


def import_state(player_id: str) -> dict[str, Any]:
    with store.db() as c:
        acc = c.execute("SELECT last_sync, sync_started FROM accounts WHERE player_id = %s", (player_id,)).fetchone()
        done = store.scalar(c, "SELECT count(*) FROM match_players mp JOIN matches m ON m.id = mp.match_id "
                               "WHERE mp.player_id = %s AND m.status IN ('ok', 'partiel')", (player_id,))
        waiting = store.scalar(c, "SELECT count(*) FROM matches WHERE status IN ('en_attente', 'en_cours')")
    running = bool(acc and acc[1] and (acc[0] is None or acc[1] > acc[0]))
    return {"last_sync": acc[0] if acc else None, "running": running, "done": done, "waiting": waiting}
