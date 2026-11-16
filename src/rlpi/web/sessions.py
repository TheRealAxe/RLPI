"""Sessions révocables (table sessions, migrations/V6__sessions_swipe.sql).

Le cookie `rlpi_session` contient un jeton aléatoire de 256 bits ; la base n'en garde que l'empreinte SHA-256.
- se déconnecter supprime la session ; « se déconnecter partout » supprime toutes celles du joueur ;
- changer RLPI_SECRET ne déconnecte plus personne (il ne sert qu'à lire les anciens cookies signés) ;
- transition : un ancien cookie signé (rlpi.account, « joueur|expiration|signature ») encore valide est accepté et
  remplacé aussitôt par une session (voir rlpi.web.deps.current_player).
"""

from __future__ import annotations

import hashlib
import secrets

from rlpi import store

COOKIE = "rlpi_session"
SESSION_DAYS = 30
TOUCH_EVERY = "1 hour"  # « dernière utilisation » mise à jour au plus une fois par heure (pas une écriture par requête)


def _id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(player_id: str) -> str:
    """Ouvre une session ; retourne le jeton à mettre dans le cookie. Les sessions expirées sont effacées au
    passage."""
    token = secrets.token_urlsafe(32)
    with store.db() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < now()")
        c.execute(
            "INSERT INTO sessions (id, player_id, expires_at) VALUES (%s, %s, now() + make_interval(days => %s))",
            (_id(token), player_id, SESSION_DAYS),
        )
    return token


def player(token: str | None) -> str | None:
    """Joueur de la session, ou None (jeton inconnu, révoqué ou expiré)."""
    if not token or len(token) > 100:
        return None
    sid = _id(token)
    with store.db() as c:
        row = c.execute("SELECT player_id FROM sessions WHERE id = %s AND expires_at > now()", (sid,)).fetchone()
        if row is None:
            return None
        c.execute(
            f"UPDATE sessions SET last_used = now() WHERE id = %s AND last_used < now() - interval '{TOUCH_EVERY}'",
            (sid,),
        )
    return row[0]


def delete(token: str | None) -> None:
    if token:
        with store.db() as c:
            c.execute("DELETE FROM sessions WHERE id = %s", (_id(token),))


def delete_all(player_id: str) -> int:
    """Ferme toutes les sessions du joueur ; retourne leur nombre."""
    with store.db() as c:
        return c.execute("DELETE FROM sessions WHERE player_id = %s", (player_id,)).rowcount


def cookie(token: str, https: bool) -> str:
    secure = "; Secure" if https else ""
    return f"{COOKIE}={token}; Path=/; Max-Age={SESSION_DAYS * 86400}; HttpOnly; SameSite=Lax{secure}"


def clear_cookie(https: bool) -> str:
    secure = "; Secure" if https else ""
    return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax{secure}"
