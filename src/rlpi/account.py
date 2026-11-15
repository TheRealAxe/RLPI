"""Comptes joueurs : connexion avec Steam (OpenID 2.0), session, page personnelle /moi.

Un joueur se connecte avec son compte Steam : Steam nous renvoie son SteamID, qui est exactement l'identifiant
présent dans les replays (« Steam:7656… »). Aucun mot de passe n'est géré ici.
À la première connexion, le compte est créé (table accounts) et une recherche de ses parties sur ballchasing est
mise en file (les workers s'en chargent, voir rlpi.collector).

Pages (servies par rlpi.serve) :
    /connexion             redirige vers Steam
    /connexion/retour      retour de Steam : vérification, création du compte, cookie de session
    /deconnexion
    /moi                   tableau de bord du joueur connecté (ou état de l'import en cours)
    POST /moi/actualiser   chercher maintenant ses nouvelles parties (au plus une fois toutes les 5 minutes)

Variables : RLPI_PUBLIC_URL (ex. https://rlpi.lainox.quest), RLPI_SECRET (longue chaîne aléatoire, signe les
cookies de session), plus DATABASE_URL, REDIS_URL et S3_* (voir rlpi.store).
"""
from __future__ import annotations

import hashlib
import hmac
import html
import os
import re
import time
import urllib.request
from urllib.parse import urlencode

from rlpi import store

STEAM_OPENID = "https://steamcommunity.com/openid/login"
COOKIE = "rlpi_session"
SESSION_DAYS = 30
REFRESH_EVERY = 300  # secondes entre deux recherches manuelles


REQUIRED = ("RLPI_PUBLIC_URL", "RLPI_SECRET", "DATABASE_URL", "REDIS_URL", "S3_ENDPOINT", "S3_ACCESS_KEY",
            "S3_SECRET_KEY")


def missing() -> list[str]:
    """Variables obligatoires absentes (noms seulement, jamais les valeurs)."""
    return [k for k in REQUIRED if not os.getenv(k, "").strip().strip("\"'")]


def configured() -> bool:
    return not missing()


def base_url() -> str:
    return store.env("RLPI_PUBLIC_URL").rstrip("/")


# --------------------------------------------------------------------------------------------------------------
# Steam OpenID


def steam_login_url() -> str:
    b = base_url()
    return STEAM_OPENID + "?" + urlencode({
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": f"{b}/connexion/retour",
        "openid.realm": b,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    })


def steam_verify(query: dict[str, list[str]]) -> str | None:
    """Vérifie auprès de Steam la réponse reçue sur /connexion/retour. Retourne le SteamID64 ou None."""
    q = {k: v[0] for k, v in query.items() if k.startswith("openid.")}
    if q.get("openid.mode") != "id_res" or q.get("openid.op_endpoint") != STEAM_OPENID:
        return None
    if not q.get("openid.return_to", "").startswith(f"{base_url()}/connexion/retour"):
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
# Session (cookie signé)


def _sign(payload: str) -> str:
    return hmac.new(store.env("RLPI_SECRET").encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_cookie(player_id: str) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    payload = f"{player_id}|{exp}"
    secure = "; Secure" if base_url().startswith("https://") else ""
    return (f"{COOKIE}={payload}|{_sign(payload)}; Path=/; Max-Age={SESSION_DAYS * 86400}; HttpOnly; "
            f"SameSite=Lax{secure}")


def clear_cookie() -> str:
    return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


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
        new = c.execute("INSERT INTO accounts (player_id, last_login) VALUES (%s, now()) "
                        "ON CONFLICT (player_id) DO UPDATE SET last_login = now() "
                        "RETURNING (xmax = 0)", (pid,)).fetchone()[0]
    if new:
        store.push_sync(store.redis_client(), pid)
    return pid


def refresh(player_id: str) -> bool:
    """Recherche manuelle de nouvelles parties ; False si la précédente date de moins de 5 minutes."""
    r = store.redis_client()
    if not r.set(f"rlpi:refresh:{player_id}", "1", nx=True, ex=REFRESH_EVERY):
        return False
    store.push_sync(r, player_id)
    return True


def import_state(player_id: str) -> dict:
    with store.db() as c:
        acc = c.execute("SELECT last_sync, created_at FROM accounts WHERE player_id = %s", (player_id,)).fetchone()
        done = c.execute("SELECT count(*) FROM match_players mp JOIN matches m ON m.id = mp.match_id "
                         "WHERE mp.player_id = %s AND m.status IN ('ok', 'partiel')", (player_id,)).fetchone()[0]
        waiting = c.execute("SELECT count(*) FROM matches WHERE status IN ('en_attente', 'en_cours')").fetchone()[0]
    return {"last_sync": acc[0] if acc else None, "done": done, "waiting": waiting}


# --------------------------------------------------------------------------------------------------------------
# Pages


STYLE = """<style>
:root{--bg:#f6f7f9;--fg:#1d2330;--muted:#5b6475;--card:#fff;--accent:#2f6fde;--line:#dfe3ea}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--fg:#e8ebf1;--muted:#9aa3b3;--card:#1b2029;--accent:#6b9cff;--line:#2b3240}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:560px;margin:12vh auto;padding:0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:28px}
h1{font-size:1.4rem;margin:0 0 8px}p{color:var(--muted);margin:.5em 0}
.btn{display:inline-block;margin-top:16px;padding:10px 18px;border-radius:10px;background:var(--accent);color:#fff;
text-decoration:none;border:0;font:inherit;cursor:pointer}
.note{font-size:.9rem}
</style>"""


def page(title: str, body: str, refresh_s: int | None = None) -> str:
    meta = f'<meta http-equiv="refresh" content="{refresh_s}">' if refresh_s else ""
    return (f'<!doctype html><html lang="fr"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">{meta}'
            f"<title>{html.escape(title)}</title>{STYLE}</head><body><main><div class='card'>{body}</div></main>"
            "</body></html>")


def login_page() -> str:
    return page("RLPI — connexion", "<h1>RLPI — Rocket League Player Index</h1>"
                "<p>Connecte-toi avec ton compte Steam pour voir les statistiques de tes parties 3v3.</p>"
                "<p class='note'>Tes parties sont récupérées automatiquement sur ballchasing.com : il faut qu'elles "
                "y soient envoyées (par toi ou un coéquipier, avec l'envoi automatique de BakkesMod par exemple).</p>"
                "<a class='btn' href='/connexion'>Se connecter avec Steam</a>")


def import_page(player_id: str, st: dict) -> str:
    last = st["last_sync"].strftime("%d/%m %H:%M") if st["last_sync"] else "en attente"
    return page("RLPI — import en cours", "<h1>Import de tes parties</h1>"
                f"<p>Compte : {html.escape(player_id)}</p>"
                f"<p>Recherche sur ballchasing : {last}. Parties traitées : {st['done']}. "
                f"Parties en file (tous joueurs) : {st['waiting']}.</p>"
                "<p class='note'>Compte 15 à 40 secondes par partie. La page se met à jour toute seule. "
                "Si aucune partie n'apparaît, vérifie que tes replays sont publics sur ballchasing.com.</p>"
                "<a class='btn' href='/deconnexion'>Se déconnecter</a>", refresh_s=30)


def toolbar(player_id: str, n_games: int, message: str | None = None) -> str:
    """Petit bandeau ajouté en bas du tableau de bord : nombre de parties, actualiser, déconnexion."""
    msg = f"<span style='margin-right:12px'>{html.escape(message)}</span>" if message else ""
    return ("<div style=\"position:fixed;right:16px;bottom:16px;z-index:9999;display:flex;gap:8px;align-items:center;"
            "flex-wrap:wrap;justify-content:flex-end;max-width:calc(100vw - 32px);font:14px system-ui,sans-serif;"
            "background:rgba(20,24,32,.92);color:#fff;padding:8px 12px;border-radius:12px\">"
            f"{msg}<span>{n_games} partie(s)</span>"
            "<form method='post' action='/moi/actualiser' style='margin:0'><button style='font:inherit;padding:4px 10px;"
            "border-radius:8px;border:0;cursor:pointer'>Chercher mes nouvelles parties</button></form>"
            "<a href='/deconnexion' style='color:#cfd8ff'>Se déconnecter</a></div>")
