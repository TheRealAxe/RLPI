"""Session (cookie signé) et vérification de la connexion Steam (réponse de Steam simulée)."""

from __future__ import annotations

import io
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from rlpi import account

PUBLIC = "https://rlpi.example.test"
STEAM_ID = "76561190000000001"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("RLPI_PUBLIC_URL", PUBLIC)
    monkeypatch.setenv("RLPI_SECRET", "secret-de-test-0123456789abcdef0123456789")


def cookie_value(set_cookie: str) -> str:
    return set_cookie.split(";", 1)[0]


# ------------------------------------------------------------------------------------------------ session


def test_cookie_valide():
    c = account.make_cookie(f"Steam:{STEAM_ID}")
    assert account.session_player(cookie_value(c)) == f"Steam:{STEAM_ID}"
    assert account.session_player(f"autre=1; {cookie_value(c)}; x=y") == f"Steam:{STEAM_ID}"
    assert "HttpOnly" in c and "SameSite=Lax" in c and "Secure" in c


def test_cookie_sans_secure_en_http(monkeypatch):
    monkeypatch.setenv("RLPI_PUBLIC_URL", "http://localhost:3001")
    assert "Secure" not in account.make_cookie("Steam:1")


def test_cookie_expire(monkeypatch):
    c = cookie_value(account.make_cookie("Steam:1"))
    real = time.time
    monkeypatch.setattr(account.time, "time", lambda: real() + (account.SESSION_DAYS + 1) * 86400)
    assert account.session_player(c) is None


def test_cookie_falsifie():
    c = cookie_value(account.make_cookie("Steam:1"))
    name, _, v = c.partition("=")
    pid, exp, sig = v.split("|")
    assert account.session_player(f"{name}=Steam:2|{exp}|{sig}") is None  # autre joueur
    assert account.session_player(f"{name}={pid}|{int(exp) + 999}|{sig}") is None  # expiration prolongée
    assert account.session_player(f"{name}={pid}|{exp}|{'0' * len(sig)}") is None  # signature inventée
    assert account.session_player(f"{name}={pid}|{exp}") is None  # mal formé
    assert account.session_player(None) is None


def test_cookie_signe_avec_un_autre_secret(monkeypatch):
    c = cookie_value(account.make_cookie("Steam:1"))
    monkeypatch.setenv("RLPI_SECRET", "un-autre-secret-0123456789abcdef0123456789")
    assert account.session_player(c) is None


# ------------------------------------------------------------------------------------------------ Steam


def steam_reply(**over) -> dict[str, list[str]]:
    q = {
        "openid.mode": "id_res",
        "openid.op_endpoint": account.STEAM_OPENID,
        "openid.return_to": f"{PUBLIC}/auth/steam/retour",
        "openid.claimed_id": f"https://steamcommunity.com/openid/id/{STEAM_ID}",
        "openid.identity": f"https://steamcommunity.com/openid/id/{STEAM_ID}",
        "openid.sig": "abc",
        "openid.signed": "signed,op_endpoint,claimed_id",
    } | over
    return {k: [v] for k, v in q.items()}


class FakeSteam:
    def __init__(self, answer: str):
        self.answer, self.requests = answer, []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        return io.BytesIO(self.answer.encode())


def test_url_de_connexion_steam():
    u = urlsplit(account.steam_login_url())
    q = parse_qs(u.query)
    assert f"{u.scheme}://{u.netloc}{u.path}" == account.STEAM_OPENID
    assert q["openid.return_to"] == [f"{PUBLIC}/auth/steam/retour"] and q["openid.realm"] == [PUBLIC]


def test_steam_valide(monkeypatch):
    fake = FakeSteam("ns:http://specs.openid.net/auth/2.0\nis_valid:true\n")
    monkeypatch.setattr(account.urllib.request, "urlopen", fake)
    assert account.steam_verify(steam_reply()) == STEAM_ID
    body = parse_qs(fake.requests[0].data.decode())
    assert body["openid.mode"] == ["check_authentication"]  # vérification renvoyée à Steam


def test_steam_ancienne_adresse_de_retour(monkeypatch):
    """Connexion commencée avant le passage à /auth/steam/retour (déploiement de la phase E) : acceptée."""
    monkeypatch.setattr(account.urllib.request, "urlopen", FakeSteam("is_valid:true\n"))
    assert account.steam_verify(steam_reply(**{"openid.return_to": f"{PUBLIC}/connexion/retour"})) == STEAM_ID


def test_steam_refuse(monkeypatch):
    monkeypatch.setattr(account.urllib.request, "urlopen", FakeSteam("is_valid:false\n"))
    assert account.steam_verify(steam_reply()) is None


@pytest.mark.parametrize(
    "over",
    [
        {"openid.mode": "cancel"},
        {"openid.op_endpoint": "https://attaquant.example/openid/login"},
        {"openid.return_to": "https://attaquant.example/connexion/retour"},
        {"openid.claimed_id": "https://attaquant.example/openid/id/76561190000000001"},
        {"openid.claimed_id": "https://steamcommunity.com/openid/id/123"},
    ],
)
def test_steam_reponse_invalide_sans_appel(monkeypatch, over):
    fake = FakeSteam("is_valid:true\n")
    monkeypatch.setattr(account.urllib.request, "urlopen", fake)
    assert account.steam_verify(steam_reply(**over)) is None
    assert fake.requests == []  # rejetée avant même d'interroger Steam
