"""Simulation de la balle seule (sans voiture), vectorisée sur plusieurs balles à la fois.

Sert à répondre à « que serait devenue la balle sans cette touche ? » (audit F2) et à calculer des variables de
trajectoire réalistes pour le modèle de valeur (audit L1, gravité et rebonds au lieu d'une ligne droite).

Physique (constantes mesurées par la communauté RLBot, modèle de rebond de « chip », puis ajustées sur des replays,
voir `python -m rlpi.ballsim valider`) :
- gravité −650 uu/s², frottement de l'air dv/dt = −DRAG·v, vitesse max 6 000 uu/s, rotation max 6 rad/s ;
- rebond sur une surface de normale n : composante normale renvoyée avec un coefficient RESTITUTION, composante
  tangentielle freinée selon le glissement du point de contact (frottement de Coulomb, coefficients MU et Y),
  rotation mise à jour en conséquence (ANG) ;
- terrain standard (« soccar ») : sol, plafond 2 044, murs latéraux ±4 096, murs du fond ±5 120, pans coupés des
  coins |x| + |y| ≤ 8 064, raccords arrondis entre les surfaces (FLOOR_R, CEIL_R, CORNER_R) ; cages 1 786 × 642 × 880,
  poteaux et barre transversale.

Limites : les terrains non standard (Wasteland, anciens Neo Tokyo…) ont une autre géométrie ; les raccords sont
des arrondis uniformes ; aucune voiture n'est simulée (un adversaire peut finir l'action, un coéquipier sauver).

Repère Rocket League : l'équipe 0 (bleue) marque en y > 0 (but 0), l'équipe 1 en y < 0 (but 1).
"""
from __future__ import annotations

import numpy as np

R = 91.25                 # rayon de la balle
GRAVITY = -650.0
DRAG = 0.0305
MAX_SPEED = 6000.0
MAX_ANG = 6.0
RESTITUTION = 0.6
MU = 0.285
Y_FRIC = 2.0
ANG = 2.5 / R             # Δω = ANG · (Δv_tangentielle × n) : sphère pleine (I = 0,4 m R²)
FLOOR_R, CEIL_R, CORNER_R = 256.0, 512.0, 256.0  # rayons des raccords (ajustés sur replays)

FLOOR, CEIL = 0.0, 2044.0
SIDE_X, BACK_Y, DIAG = 4096.0, 5120.0, 8064.0
GOAL_HW, GOAL_H, GOAL_DEPTH = 892.755, 642.775, 880.0
GOAL_SCORE_Y = BACK_Y + R  # la balle a entièrement franchi la ligne
DT = 1.0 / 120.0
_S2 = np.sqrt(0.5)


def _fillet(a: np.ndarray, b: np.ndarray, r: float) -> np.ndarray:
    """Distance à un raccord arrondi de rayon r entre deux parois (distances a et b aux deux parois)."""
    near = (a < r) & (b < r)
    return np.where(near, r - np.sqrt((r - np.minimum(a, r)) ** 2 + (r - np.minimum(b, r)) ** 2), np.inf)


def _field_sdf(p: np.ndarray, radii: tuple[float, float, float] | None = None) -> np.ndarray:
    """Distance (positive à l'intérieur) entre un point et les parois du terrain hors cages, raccords arrondis :
    rayon FLOOR_R entre le sol et les murs, CEIL_R entre le plafond et les murs, CORNER_R entre deux murs."""
    rf, rc, rv = radii or (FLOOR_R, CEIL_R, CORNER_R)
    x, y, z = np.abs(p[:, 0]), np.abs(p[:, 1]), p[:, 2]
    mouth = (x < GOAL_HW) & (z < GOAL_H)
    fl, ce, sd = z - FLOOR, CEIL - z, SIDE_X - x
    bk = np.where(mouth, 1e5, BACK_Y - y)
    dg = (DIAG - x - y) * _S2
    walls = (sd, bk, dg)
    d = np.minimum.reduce([fl, ce, sd, bk, dg])
    for w in walls:
        d = np.minimum(d, np.minimum(_fillet(fl, w, rf), _fillet(ce, w, rc)))
    return np.minimum.reduce([d, _fillet(sd, dg, rv), _fillet(bk, dg, rv)])


def _goal_sdf(p: np.ndarray) -> np.ndarray:
    x, y, z = np.abs(p[:, 0]), np.abs(p[:, 1]), p[:, 2]
    return np.minimum.reduce([GOAL_HW - x, GOAL_H - z, z - FLOOR, BACK_Y + GOAL_DEPTH - y])


def _post_dist(p: np.ndarray) -> np.ndarray:
    """Distance aux poteaux (segments verticaux) et à la barre transversale des deux cages."""
    x, y, z = p[:, 0], np.abs(p[:, 1]), p[:, 2]
    dy = y - BACK_Y
    zc = np.clip(z, FLOOR, GOAL_H)
    d_post = np.sqrt((np.abs(x) - GOAL_HW) ** 2 + dy ** 2 + (z - zc) ** 2)
    xc = np.clip(x, -GOAL_HW, GOAL_HW)
    d_bar = np.sqrt((x - xc) ** 2 + dy ** 2 + (z - GOAL_H) ** 2)
    return np.minimum(d_post, d_bar)


def sdf(p: np.ndarray) -> np.ndarray:
    """Distance signée entre le centre de chaque balle (N, 3) et les parois (positive = dans l'espace de jeu)."""
    in_goal = np.abs(p[:, 1]) > BACK_Y
    base = np.where(in_goal, _goal_sdf(p), _field_sdf(p))
    return np.minimum(base, _post_dist(p))


def _normal(p: np.ndarray, h: float = 2.0) -> np.ndarray:
    g = np.empty_like(p)
    for k in range(3):
        dp = np.zeros(3)
        dp[k] = h
        g[:, k] = sdf(p + dp) - sdf(p - dp)
    return g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)


def step(x: np.ndarray, v: np.ndarray, w: np.ndarray, dt: float = DT,
         params: dict | None = None) -> None:
    """Avance toutes les balles d'un pas (modifie x, v, w en place)."""
    prm = params or {}
    drag, e = prm.get("drag", DRAG), prm.get("restitution", RESTITUTION)
    mu, yf, ang = prm.get("mu", MU), prm.get("y_fric", Y_FRIC), prm.get("ang", ANG)
    v[:, 2] += GRAVITY * dt
    v *= 1.0 - drag * dt
    sp = np.linalg.norm(v, axis=1, keepdims=True)
    v *= np.minimum(1.0, MAX_SPEED / np.maximum(sp, 1e-9))
    x += v * dt
    d = sdf(x)
    hit = np.where(d < R)[0]
    if hit.size:
        xh = x[hit]
        n = _normal(xh)
        xh += (R - d[hit])[:, None] * n
        x[hit] = xh
        vh, wh = v[hit], w[hit]
        vn = (vh * n).sum(axis=1)
        go = vn < 0
        if go.any():
            n, vh, wh, vn, idx = n[go], vh[go], wh[go], vn[go], hit[go]
            v_perp = vn[:, None] * n
            v_para = vh - v_perp
            s = v_para + R * np.cross(n, wh)
            s_norm = np.maximum(np.linalg.norm(s, axis=1), 1e-6)
            k = np.minimum(1.0, yf * np.abs(vn) / s_norm) * mu
            dv_para = -k[:, None] * s
            v[idx] = vh + dv_para - (1.0 + e) * v_perp
            w[idx] = wh + ang * np.cross(dv_para, n)
    wn = np.linalg.norm(w, axis=1, keepdims=True)
    w *= np.minimum(1.0, MAX_ANG / np.maximum(wn, 1e-9))


def simulate(x0: np.ndarray, v0: np.ndarray, w0: np.ndarray | None = None, t_max: float = 3.0,
             sample_every: float | None = None, dt: float = DT, params: dict | None = None):
    """Simule N balles pendant t_max secondes.

    Renvoie (but, t_but, positions) :
    - but      (N,) : 0 si la balle entre dans le but 0 (y > 0), 1 dans le but 1, −1 sinon ;
    - t_but    (N,) : instant du but (s), inf sinon ;
    - positions : (n_échantillons, N, 3) toutes les `sample_every` s (None si sample_every est None).
    Une balle qui a marqué n'est plus avancée.
    """
    x = np.array(x0, dtype=np.float64, ndmin=2).copy()
    v = np.array(v0, dtype=np.float64, ndmin=2).copy()
    w = np.zeros_like(x) if w0 is None else np.array(w0, dtype=np.float64, ndmin=2).copy()
    n = len(x)
    goal = np.full(n, -1, np.int8)
    t_goal = np.full(n, np.inf)
    n_steps = int(round(t_max / dt))
    every = None if sample_every is None else max(1, int(round(sample_every / dt)))
    samples = []
    alive = np.arange(n)
    for s in range(1, n_steps + 1):
        if alive.size:
            xa, va, wa = x[alive], v[alive], w[alive]
            step(xa, va, wa, dt, params)
            x[alive], v[alive], w[alive] = xa, va, wa
            scored = np.abs(xa[:, 1]) > GOAL_SCORE_Y
            if scored.any():
                idx = alive[scored]
                goal[idx] = np.where(xa[scored, 1] > 0, 0, 1)
                t_goal[idx] = s * dt
                alive = alive[~scored]
        if every and s % every == 0:
            samples.append(x.copy())
    return goal, t_goal, (np.stack(samples) if every else None)


LINE_Y = BACK_Y - R  # la balle touche le plan de la ligne de but


def goal_lines(x0: np.ndarray, v0: np.ndarray, w0: np.ndarray | None = None, t_max: float = 4.0,
               dt: float = 1.0 / 60.0) -> dict[str, np.ndarray]:
    """Variables de trajectoire vers chaque but, avec gravité et rebonds (remplace la ligne droite du modèle de
    valeur, audit L1). Pour chaque côté c (« pos » : but en y > 0, « neg » : but en y < 0) :
    - t_c    : instant où la balle entre dans ce but (t_max + 6 s si elle n'y entre pas, comme l'ancien « 10 ») ;
    - in_c   : 1 si elle y entre dans les t_max secondes ;
    - x_c    : |x| de la balle quand elle atteint pour la première fois la ligne de ce côté (4 096 sinon).
    Pas de 1/60 s : assez précis pour ces variables, deux fois plus rapide."""
    x = np.array(x0, dtype=np.float64, ndmin=2).copy()
    v = np.array(v0, dtype=np.float64, ndmin=2).copy()
    w = np.zeros_like(x) if w0 is None else np.nan_to_num(np.array(w0, dtype=np.float64, ndmin=2)).copy()
    n = len(x)
    never = t_max + 6.0
    out = {f"{k}_{c}": np.full(n, d) for c in ("pos", "neg") for k, d in (("t", never), ("in", 0.0), ("x", SIDE_X))}
    reached = {"pos": np.zeros(n, bool), "neg": np.zeros(n, bool)}
    alive = np.arange(n)
    for s in range(1, int(round(t_max / dt)) + 1):
        if not alive.size:
            break
        xa, va, wa = x[alive], v[alive], w[alive]
        step(xa, va, wa, dt)
        x[alive], v[alive], w[alive] = xa, va, wa
        for c, sign in (("pos", 1.0), ("neg", -1.0)):
            hit = (sign * xa[:, 1] >= LINE_Y) & ~reached[c][alive]
            if hit.any():
                idx = alive[hit]
                reached[c][idx] = True
                out[f"x_{c}"][idx] = np.minimum(np.abs(xa[hit, 0]), SIDE_X)
            sc = sign * xa[:, 1] > GOAL_SCORE_Y
            if sc.any():
                idx = alive[sc]
                out[f"t_{c}"][idx] = s * dt
                out[f"in_{c}"][idx] = 1.0
        alive = alive[np.abs(xa[:, 1]) <= GOAL_SCORE_Y]
    return out
