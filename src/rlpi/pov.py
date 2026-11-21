"""Clips « ▶ Revoir » au format du player 3D (web/src/pov/scene.ts, repris de la vue embarquée reports/pov.html).

Fait à partir du replay déjà lu par `rlpi.clips` (`Track` à 120 images/s), sans le relire : même découpe que le
Swipe (`clips.cut` : vraies mises à jour du replay, Hermite cubique, objet immobile tenu), puis mise au format du
player :

- positions et vecteurs avant / haut dans le repère de l'équipe de l'auteur de la touche (elle attaque vers +y), x
  vers la GAUCHE comme dans Rocket League (le player retourne x pour un affichage « comme dans le jeu ») ;
- nom et rôle de chaque voiture par rapport à l'auteur : me, mate1, mate2 (ordre de la partie), opp ;
- boost (0 à 100), saut / double saut / dodge à chaque image ;
- caméra de l'auteur (`clips.cam_for`, depuis le `cameras.json` du worker) : ses réglages et l'état de sa caméra
  balle à chaque image, ou None (le player prend alors les réglages par défaut du jeu, caméra balle allumée).

Pas de dépendance au modèle ni à ballchasing : ce module est importable par l'API.
"""

from __future__ import annotations

import numpy as np

from rlpi import clips

FORMAT = 2  # 1 : carte du Swipe (vue de biais) ; 2 : player 3D
FPS = 30
JUMPS = {"jump": "jump active", "djump": "double jump active", "dodge": "dodge active"}


def kinds(players: list[dict], player_id: str) -> tuple[int, dict[str, str]]:
    """Équipe du joueur et rôle de chaque voiture : me, mate1, mate2 (ordre de la partie), opp."""
    me = next(p for p in players if p["id"] == player_id)
    out, n = {}, 0
    for p in players:
        if p["id"] == player_id:
            out[p["id"]] = "me"
        elif p["team"] == me["team"] and n < 2:
            n += 1
            out[p["id"]] = f"mate{n}"
        else:
            out[p["id"]] = "opp"
    return int(me["team"]), out


def active(counter: np.ndarray) -> list[int]:
    """Saut, double saut, dodge : compteur du jeu, qui augmente à chaque activation et reste IMPAIR pendant
    qu'elle dure (absent : 0)."""
    return [int(v) % 2 for v in np.nan_to_num(counter).astype(int)]


def clip(
    track: clips.Track,
    meta: dict,
    j: int,
    author_id: str,
    before: float,
    after: float,
    cams: dict | None = None,
) -> dict | None:
    """Clip au format du player 3D (sans id) autour de l'image `j` du replay : `before` s avant, `after` s après, à
    30 images/s ; `author_id` : auteur de la touche (« me » du player). None dans les cas de `clips.cut`."""
    card = clips.cut(track, meta, j, author_id, before=before, after=after, fps=FPS, cams=cams)
    if card is None:
        return None
    team, role = kinds(meta["players"], author_id)
    s = np.array([1, 1, 1] if team == 0 else [-1, -1, 1])  # repère de l'équipe de l'auteur : x et y retournés
    n = len(card["ball"])
    idx = j - int(before * track.fps) + (track.fps // FPS) * np.arange(n)  # images du replay lues par cut

    def xyz(rows: list, cast: type = int) -> dict[str, list]:
        a = np.asarray(rows) * s
        return {c: [cast(v) for v in a[:, k]] for k, c in enumerate("xyz")}

    def vec(rows: list) -> list[list[float]]:
        a = np.asarray(rows) * s
        return [[round(float(v), 3) for v in a[:, k]] for k in range(3)]

    cars = []
    for p, c in zip(meta["players"], card["cars"]):
        flags = {}
        for key, header in JUMPS.items():
            col = track.car_col(p["slot"], header) if header in track.player_headers else None
            flags[key] = active(track.a[idx, col]) if col is not None else [0] * n
        cars.append(
            {
                "name": p.get("name") or "",
                "kind": role[p["id"]],
                **xyz(c["pos"]),
                "fwd": vec(c["fw"]),
                "up": vec(c["up"]),
                "boost": c["boost"],
                **flags,
            }
        )
    cam = card.get("cam")
    return {
        "format": FORMAT,
        "fps": FPS,
        "t0": card["action_frame"],
        "ball": xyz(card["ball"]),
        "cars": cars,
        "cam": None
        if cam is None
        else {
            "settings": {k: cam[k] for k in clips.CAM_KEYS if k in cam} if cam.get("known") else {},
            "ballcam": cam["ball_cam"],
        },
    }
