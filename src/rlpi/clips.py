"""Clips 3D autour d'une touche, lus dans le replay brut (Swipe et bouton « Revoir » du site).

Trois étapes, séparées pour pouvoir être appelées par le worker (Swipe) comme par l'API (clip à la demande) :

- `read_replay(path)` : lecture unique du replay par subtr-actor, à 120 images/s (balle, voitures, boost) ;
- `locate(track, i10, ball_xy)` : instant exact de la touche à 120 images/s, à partir de son index à 10 images/s et
  de la position (x, y) de la balle notée à ce moment-là ;
- `cut(track, meta, j, judged_id)` : la carte `SwipeCard` (3 s avant, 1 s après, 30 images/s) lue par le lecteur
  web (`web/src/swipe/player.ts`).

Pour la vue joueur du lecteur : `read_cameras(path)` relève les réglages caméra de chaque joueur (FOV, distance,
hauteur, angle, raideur) et ses bascules caméra balle / caméra voiture ; `cut(..., cams=...)` les ajoute au clip.
Cette lecture est lourde (1,5 à 3 s, environ 250 Mo) : le worker l'écrit une fois par partie (`<replay>.cameras.json`).

Pas de dépendance au modèle ni à ballchasing : ce module est importable par l'API.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

SRC_FPS = 120       # lecture fine du replay pour dater chaque vraie mise à jour
FRAMES_FPS = 10     # fréquence des images stockées (frames/<source>/<replay>.parquet) et de l'index `i` des touches
FPS = 30            # images par seconde du clip livré
BEFORE, AFTER = 3.0, 1.0
MAX_GAP = 50.0      # écart maximal (uu) entre la balle notée et la balle du replay pour accepter le calage
TIME_HEADER = "current time"
CAM_KEYS = ("fov", "distance", "height", "angle", "stiffness")


@dataclass(frozen=True)
class Track:
    """Replay lu à `fps` images/s : une ligne par image, colonnes globales (balle) puis un bloc par voiture."""

    a: np.ndarray
    global_headers: list[str]
    player_headers: list[str]
    fps: int = SRC_FPS

    def __len__(self) -> int:
        return len(self.a)

    def ball_col(self, name: str) -> int:
        return self.global_headers.index(f"Ball - {name}")

    def car_col(self, slot: int, name: str) -> int:
        return len(self.global_headers) + slot * len(self.player_headers) + self.player_headers.index(name)

    def times(self) -> np.ndarray:
        """Temps du replay (s) de chaque image ; à défaut de colonne de temps, index / fps."""
        if TIME_HEADER in self.global_headers:
            return self.a[:, self.global_headers.index(TIME_HEADER)].astype(np.float64)
        return np.arange(len(self.a)) / self.fps

    @property
    def boost_header(self) -> str:
        return next(h for h in self.player_headers if "boost" in h.lower())


def read_replay(path: str | Path, fps: int = SRC_FPS) -> Track:
    """Lecture unique du replay brut (environ 0,3 s et 20 Mo pour une partie de 5 min à 120 images/s)."""
    import subtr_actor as sa

    cols, arr = sa.get_ndarray_with_info_from_replay_filepath(
        str(path), ["BallRigidBody", "CurrentTime"], ["PlayerRigidBodyBasis", "PlayerBoost"], fps=fps, dtype="f32")
    h = cols["column_headers"]
    return Track(np.asarray(arr), list(h["global_headers"]), list(h["player_headers"]), fps)


def _pid(remote_id) -> str:
    """Identifiant joueur, comme dans meta.json (rlpi.frames._pid, sans importer rlpi.frames)."""
    if isinstance(remote_id, dict):
        k, v = next(iter(remote_id.items()))
        return f"{k}:{v}"
    return str(remote_id)


def read_cameras(path: str | Path) -> dict:
    """Caméra de chaque joueur : `{"players": {id: {"settings": {fov, distance, height, angle, stiffness} | None,
    "ball_cam": [[temps (s), 0/1], ...]}}}`, temps du replay comme la colonne « current time » de `read_replay`.
    Le swivel (stick droit) n'est presque jamais enregistré dans les replays : il n'est pas relevé."""
    import subtr_actor as sa

    d = sa.get_replay_frames_data(str(path))
    times = [f["time"] for f in d["frame_data"]["metadata_frames"]]
    m = d.get("meta") or {}
    players: dict[str, dict] = {}
    for p in [*(m.get("team_zero") or []), *(m.get("team_one") or [])]:
        cs = p.get("camera_settings") or {}
        ok = all(isinstance(cs.get(k), int | float) for k in CAM_KEYS)
        players[_pid(p.get("remote_id"))] = {
            "settings": {k: round(float(cs[k]), 3) for k in CAM_KEYS} if ok else None, "ball_cam": []}
    for rid, events in d.get("player_camera_events") or []:
        entry = players.setdefault(_pid(rid), {"settings": None, "ball_cam": []})
        last = None
        for e in events:
            b, f = e.get("ball_cam_active"), e.get("frame")
            if b is None or f is None or not 0 <= f < len(times) or b == last:
                continue
            entry["ball_cam"].append([round(times[f], 3), int(b)])
            last = b
    return {"players": players}


def cam_for(cams: dict, player_id: str, t: np.ndarray) -> dict | None:
    """Caméra du joueur `player_id` aux temps `t` : réglages et caméra balle (0/1) à chaque image. None si le joueur
    n'a ni réglages ni bascule relevés."""
    c = (cams.get("players") or {}).get(player_id)
    if not c or (not c.get("settings") and not c.get("ball_cam")):
        return None
    ev = c.get("ball_cam") or []
    et = np.array([e[0] for e in ev], dtype=np.float64)
    k = np.searchsorted(et, t, side="right") - 1
    first = ev[0][1] if ev else 1  # avant la 1re bascule : l'état de la 1re (en général caméra balle)
    ball = [int(ev[j][1]) if j >= 0 else int(first) for j in k] if ev else [1] * len(t)
    return {**(c.get("settings") or {}), "known": bool(c.get("settings")), "ball_cam": ball}


def world_xy(x: float, y: float, team: int) -> tuple[float, float]:
    """Position notée dans le repère de l'équipe du toucheur (tables touch_values, tableau de bord) → repère du
    terrain (replay) : l'équipe 1 a x et y inversés."""
    s = 1 if team == 0 else -1
    return s * x, s * y


def locate(track: Track, i10: int, ball_xy: tuple[float, float], window: float = 1.0,
           max_gap: float = MAX_GAP) -> int | None:
    """Index (à `track.fps`) de la touche `i10` (à 10 images/s) : image où la balle est la plus proche de sa
    position notée `ball_xy` (repère du terrain), à ± `window` secondes. None si l'écart dépasse `max_gap`."""
    r = track.fps // FRAMES_FPS
    w = int(window * track.fps)
    lo, hi = max(0, r * i10 - w), min(len(track), r * i10 + w)
    if lo >= hi:
        return None
    seg = track.a[lo:hi][:, [track.ball_col("position x"), track.ball_col("position y")]]
    d = np.linalg.norm(seg - np.asarray(ball_xy, dtype=np.float64), axis=1)
    if np.isnan(d).all() or np.nanmin(d) > max_gap:
        return None
    return lo + int(np.nanargmin(d))


def resample(pos: np.ndarray, vel: np.ndarray, src_fps: int, out_n: int, out_fps: int) -> tuple[np.ndarray, np.ndarray]:
    """Les voitures ne sont mises à jour qu'environ 15 fois par seconde dans le replay : entre deux mises à jour,
    la position reste figée puis saute. On garde les vraies mises à jour (position qui change) et on
    reconstruit une trajectoire continue entre elles (Hermite cubique avec les vitesses enregistrées)."""
    keys = [0] + [k for k in range(1, len(pos)) if np.any(pos[k] != pos[k - 1])]
    kt = np.array(keys) / src_fps
    kp, kv = pos[keys], vel[keys]
    out_t = np.arange(out_n) / out_fps
    P, Vv = np.zeros((out_n, 3)), np.zeros((out_n, 3))
    for n, t in enumerate(out_t):
        j = int(np.searchsorted(kt, t, side="right") - 1)
        if j < 0:
            P[n], Vv[n] = kp[0], kv[0]; continue
        if j >= len(kt) - 1:
            dt = t - kt[-1]; P[n], Vv[n] = kp[-1] + kv[-1] * dt, kv[-1]; continue
        h = kt[j + 1] - kt[j]; u = (t - kt[j]) / h
        u2, u3 = u * u, u * u * u
        P[n] = (2 * u3 - 3 * u2 + 1) * kp[j] + (u3 - 2 * u2 + u) * h * kv[j] + (-2 * u3 + 3 * u2) * kp[j + 1] + (u3 - u2) * h * kv[j + 1]
        Vv[n] = kv[j] + (kv[j + 1] - kv[j]) * u
    return P, Vv


def resample_dir(vec: np.ndarray, pos: np.ndarray, src_fps: int, out_n: int, out_fps: int) -> np.ndarray:
    """Même chose pour un vecteur d'orientation : interpolation linéaire normalisée entre vraies mises à jour."""
    keys = [0] + [k for k in range(1, len(pos)) if np.any(pos[k] != pos[k - 1]) or np.any(vec[k] != vec[k - 1])]
    kt, kv = np.array(keys) / src_fps, vec[keys]
    out = np.zeros((out_n, 3))
    for n, t in enumerate(np.arange(out_n) / out_fps):
        j = int(np.clip(np.searchsorted(kt, t, side="right") - 1, 0, len(kt) - 1))
        if j >= len(kt) - 1:
            out[n] = kv[-1]; continue
        u = (t - kt[j]) / (kt[j + 1] - kt[j]); v = kv[j] + (kv[j + 1] - kv[j]) * u
        out[n] = v / (np.linalg.norm(v) or 1)
    return out


def _r(x: np.ndarray) -> list:
    return np.round(x).astype(int).tolist()


def cut(track: Track, meta: dict, j: int, judged_id: str, before: float = BEFORE, after: float = AFTER,
        fps: int = FPS, cams: dict | None = None) -> dict | None:
    """Clip `SwipeCard` (sans id, origine ni action) autour de l'image `j` : `before` s avant, `after` s après, à
    `fps` images/s. `meta` : meta.json de la partie (joueurs : slot, équipe, identifiant) ; `judged_id` : voiture
    mise en avant ; `cams` (lu par `read_cameras`) : ajoute `cam`, la caméra de la voiture mise en avant (None si
    inconnue). None si le clip sort du replay, si la voiture n'est pas dans la partie ou si la balle manque."""
    src = track.fps
    j0, j1 = j - int(before * src), j + int(after * src) + 1
    if j0 < 0 or j1 > len(track):
        return None
    seg = track.a[j0:j1]
    if np.isnan(seg[:, :3]).any():
        return None
    n_out = int((before + after) * fps) + 1
    step = src // fps

    def xyz(col) -> np.ndarray:
        return np.column_stack([seg[:, col(c)] for c in "xyz"])

    cars = []
    for p in meta["players"]:
        k = p["slot"]
        pos = xyz(lambda c, k=k: track.car_col(k, f"position {c}"))
        vel = xyz(lambda c, k=k: track.car_col(k, f"linear velocity {c}"))
        P, V = resample(pos, vel, src, n_out, fps)
        fw = resample_dir(xyz(lambda c, k=k: track.car_col(k, f"forward {c}")), pos, src, n_out, fps)
        up = resample_dir(xyz(lambda c, k=k: track.car_col(k, f"up {c}")), pos, src, n_out, fps)
        boost = seg[:, track.car_col(k, track.boost_header)]
        cars.append({
            "team": p["team"], "judged": p["id"] == judged_id,
            "pos": _r(P), "vel": _r(V), "fw": np.round(fw, 3).tolist(), "up": np.round(up, 3).tolist(),
            "boost": np.round(boost[::step][:n_out] / 2.55).astype(int).tolist(),
        })
    if not any(c["judged"] for c in cars):
        return None
    bp, bv = resample(xyz(lambda c: track.ball_col(f"position {c}")),
                      xyz(lambda c: track.ball_col(f"linear velocity {c}")), src, n_out, fps)
    card = {"fps": fps, "action_frame": int(before * fps), "ball": _r(bp), "ball_v": _r(bv), "cars": cars}
    if cams is not None:
        card["cam"] = cam_for(cams, judged_id, track.times()[j0:j1][::step][:n_out])
    return card
