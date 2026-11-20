"""Ralentis au format du player 3D (vue embarquée) : touches réextraites du replay brut à 30 images/s.

Pour chaque touche : balle et 6 voitures (position lissée, vecteurs avant / haut, boost, saut / double saut / dodge),
de BEFORE_S avant à AFTER_S après la touche, et les réglages caméra du joueur enregistrés dans le replay (champ de
vision, distance, hauteur, angle, rigidité, transition) avec l'état de sa caméra balle à chaque image. Les positions
sont dans le repère de l'équipe du joueur (elle attaque vers +y) et dans le repère de Rocket League (x vers la
GAUCHE) : le player retourne x pour un affichage « comme dans le jeu ».

Repris de la vue embarquée locale (reports/pov.html, rlpi.bestplay.hd_block) : extraction à 60 i/s pour situer les
vraies mises à jour du replay, trajectoires lissées (_smooth_track), recalage sur la balle des images à 10 i/s.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

FORMAT = 2  # 1 : format du swipe (vue de biais) ; 2 : player 3D
RAW_FPS = 60.0
FPS = 30.0
SETTINGS = ("fov", "distance", "height", "angle", "stiffness", "swivel", "transition")


def car_axes(rx: np.ndarray, ry: np.ndarray, rz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vecteurs « avant » et « haut » d'une voiture à partir de rx, ry, rz (convention vérifiée sur les données :
    M = Rx(rx) · Ry(−ry) · Rz(rz), avant = colonne 0, haut = colonne 2)."""

    def rot(axis: int, a: np.ndarray) -> np.ndarray:
        c, s_ = np.cos(a), np.sin(a)
        m = np.zeros((len(a), 3, 3))
        m[:, axis, axis] = 1
        j, k = [q for q in range(3) if q != axis]
        m[:, j, j] = c
        m[:, k, k] = c
        m[:, j, k] = -s_
        m[:, k, j] = s_
        return m

    m = rot(0, rx) @ rot(1, -ry) @ rot(2, rz)
    return m[:, :, 0], m[:, :, 2]


def smooth_track(
    pos: np.ndarray, vel: np.ndarray, t_out: np.ndarray, extra: list[np.ndarray]
) -> tuple[np.ndarray, list[np.ndarray]]:
    """Trajectoire lissée entre les vraies mises à jour du replay (une image sur deux ou trois, mal horodatées) :
    intégrale de la vitesse enregistrée + correction lente vers les positions (gaussienne ~0,13 s). Les vecteurs
    `extra` (avant, haut) sont interpolés entre images clés. Temps `t_out` en images de `pos` (60 i/s)."""
    n = len(pos)
    step = np.r_[np.inf, np.linalg.norm(np.diff(pos, axis=0), axis=1)]
    keys = np.where(step > 0.5)[0]
    if len(keys) < 2:
        keys = np.arange(n)
    grid = np.arange(n, dtype=float)
    v_lin = np.column_stack([np.interp(grid, keys, vel[keys, c]) for c in range(3)])
    p_int = np.vstack([np.zeros(3), np.cumsum(0.5 * (v_lin[1:] + v_lin[:-1]), axis=0) / RAW_FPS])
    resid = pos[keys] - p_int[keys]
    sig = 8.0
    out_p = np.zeros((len(t_out), 3))
    out_e = [np.zeros((len(t_out), e.shape[1])) for e in extra]
    for m, u in enumerate(t_out):
        w = np.exp(-0.5 * ((keys - u) / sig) ** 2)
        out_p[m] = np.array([np.interp(u, grid, p_int[:, c]) for c in range(3)]) + (w[:, None] * resid).sum(0) / max(
            w.sum(), 1e-9
        )
        j = int(np.searchsorted(keys, u, side="right") - 1)
        if 0 <= j < len(keys) - 1:
            k0, k1 = keys[j], keys[j + 1]
            x = (u - k0) / (k1 - k0)
            for e, o in zip(extra, out_e):
                o[m] = e[k0] * (1 - x) + e[k1] * x
        else:
            jn = int(np.clip(j, 0, len(keys) - 1))
            for e, o in zip(extra, out_e):
                o[m] = e[keys[jn]]
    return out_p, out_e


def camera_timeline(raw: bytes, player_name: str) -> tuple[dict | None, list[tuple[float, bool]]]:
    """Réglages caméra du joueur et chaque activation / coupure de sa caméra balle (secondes depuis la 1re image),
    lus dans les acteurs CameraSettingsActor_TA du replay."""
    import subtr_actor as sa

    r = sa.parse_replay(raw)
    oid = {name: i for i, name in enumerate(r["objects"])}
    o_ball = oid.get("TAGame.CameraSettingsActor_TA:bUsingSecondaryCamera")
    o_set = oid.get("TAGame.CameraSettingsActor_TA:ProfileSettings")
    o_pri = oid.get("TAGame.CameraSettingsActor_TA:PRI")
    o_name = oid.get("Engine.PlayerReplicationInfo:PlayerName")
    frames = r["network_frames"]["frames"]
    t_first = frames[0]["time"]
    cam_pri: dict[Any, Any] = {}
    pri_name: dict[Any, Any] = {}
    settings, timeline = None, []
    for fr in frames:
        for u in fr.get("updated_actors", []):
            o, a, aid = u["object_id"], u["attribute"], u["actor_id"]
            if o == o_name:
                pri_name[aid] = a.get("String")
            elif o == o_pri:
                cam_pri[aid] = (a.get("ActiveActor") or {}).get("actor")
            elif o in (o_set, o_ball) and pri_name.get(cam_pri.get(aid)) == player_name:
                if o == o_set:
                    settings = a.get("CamSettings")
                else:
                    timeline.append((fr["time"] - t_first, bool(a.get("Boolean"))))
    keep = {k: round(float(settings[k]), 3) for k in SETTINGS if settings and k in settings} if settings else None
    return keep, timeline


def ballcam_at(timeline: list[tuple[float, bool]], times_s: np.ndarray) -> list[int]:
    """État de la caméra balle à chaque instant (allumée par défaut, comme dans le jeu)."""
    ts = np.array([t for t, _ in timeline]) if timeline else np.array([])
    out = []
    for t in times_s:
        k = int(np.searchsorted(ts, float(t), side="right") - 1)
        out.append(int(timeline[k][1]) if k >= 0 else 1)
    return out


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


def extract(
    raw_path: str | Path,
    meta: dict,
    ball10: np.ndarray,
    player_id: str,
    touches: list[int],
    before_s: float,
    after_s: float,
) -> dict[int, dict]:
    """Ralentis des touches `touches` (images à 10 i/s) du joueur. `ball10` : positions de la balle à 10 i/s (n, 3),
    pour recaler le replay brut. Une touche trop près du début ou de la fin de la partie est sautée."""
    import subtr_actor as sa

    raw = Path(raw_path).read_bytes()
    info, arr = sa.get_ndarray_with_info_from_replay_filepath(
        str(raw_path), ["BallRigidBody"], ["PlayerRigidBody", "PlayerBoost", "PlayerJump"], fps=RAW_FPS, dtype="f32"
    )
    a = np.asarray(arr)
    gh, ph = info["column_headers"]["global_headers"], info["column_headers"]["player_headers"]
    g = len(gh)
    gi = {name: gh.index(name) for name in gh}
    col = {name: ph.index(name) for name in ph}
    bv = [gi.get(f"Ball - linear velocity {c}", gi.get(f"linear velocity {c}", 6 + k)) for k, c in enumerate("xyz")]
    team, role = kinds(meta["players"], player_id)
    me_name = next(p["name"] for p in meta["players"] if p["id"] == player_id)
    try:
        settings, timeline = camera_timeline(raw, me_name)
    except Exception:  # noqa: BLE001 — sans réglages, le player prend ceux du jeu par défaut
        settings, timeline = None, []
    s = 1.0 if team == 0 else -1.0
    ratio = int(RAW_FPS / 10)
    sub = int(RAW_FPS / FPS)
    n_before, n_after = int(before_s * FPS), int(after_s * FPS)
    out: dict[int, dict] = {}

    def rnd(v: np.ndarray) -> list[int]:
        return [round(float(x)) for x in v]

    def rnd3(v: np.ndarray) -> list[float]:
        return [round(float(x), 3) for x in v]

    for i in touches:
        ks = range(max(0, i - 3), min(len(ball10), i + 4))
        ref = ball10[list(ks)]
        best, j0 = 1e18, ratio * i
        for off in range(-3 * ratio, 3 * ratio + 1):
            js = [ratio * k + off for k in ks]
            if min(js) < 0 or max(js) >= len(a):
                continue
            d = float(np.sum(np.linalg.norm(a[js, :3] - ref, axis=1)))
            if d < best:
                best, j0 = d, ratio * i + off
        if best / max(1, len(ref)) > 150:
            continue  # recalage douteux
        t_out = j0 + sub * np.arange(-n_before, n_after + 1)
        if t_out[0] < 0 or t_out[-1] >= len(a):
            continue
        lo, hi = max(0, int(t_out[0]) - 30), min(len(a) - 1, int(t_out[-1]) + 30)
        w = a[lo : hi + 1]
        if np.isnan(w[:, :3]).any():
            continue
        tl = (t_out - lo).astype(float)
        near = np.clip(np.round(tl).astype(int), 0, len(w) - 1)
        bp, _ = smooth_track(w[:, :3].astype(float), w[:, bv].astype(float), tl, [])
        cars = []
        for k, p in enumerate(meta["players"]):
            b = g + k * len(ph)
            fwd, up = car_axes(w[:, b + 3].astype(float), w[:, b + 4].astype(float), w[:, b + 5].astype(float))
            vel = w[:, [b + col["linear velocity x"], b + col["linear velocity y"], b + col["linear velocity z"]]]
            pos = np.nan_to_num(w[:, b : b + 3].astype(float))
            pp, (ff, uu) = smooth_track(
                pos, np.nan_to_num(vel.astype(float)), tl, [np.nan_to_num(fwd), np.nan_to_num(up)]
            )
            ff[:, :2] *= s
            uu[:, :2] *= s

            def flag(name: str, b: int = b) -> list[int]:
                # compteur du jeu : il augmente à chaque activation et il est IMPAIR pendant que c'est actif
                if name not in col:
                    return []
                return [int(int(np.nan_to_num(x)) % 2 == 1) for x in w[near, b + col[name]]]

            cars.append(
                {
                    "name": p["name"],
                    "kind": role[p["id"]],
                    "x": rnd(s * pp[:, 0]),
                    "y": rnd(s * pp[:, 1]),
                    "z": rnd(pp[:, 2]),
                    "fwd": [rnd3(ff[:, 0]), rnd3(ff[:, 1]), rnd3(ff[:, 2])],
                    "up": [rnd3(uu[:, 0]), rnd3(uu[:, 1]), rnd3(uu[:, 2])],
                    "boost": rnd(np.nan_to_num(w[near, b + col["boost level (raw replay units)"]]) / 255 * 100),
                    "jump": flag("jump active"),
                    "djump": flag("double jump active"),
                    "dodge": flag("dodge active"),
                }
            )
        out[i] = {
            "format": FORMAT,
            "fps": FPS,
            "t0": n_before,
            "ball": {"x": rnd(s * bp[:, 0]), "y": rnd(s * bp[:, 1]), "z": rnd(bp[:, 2])},
            "cars": cars,
            "cam": {"settings": settings, "ballcam": ballcam_at(timeline, t_out / RAW_FPS)} if settings else None,
        }
    return out
