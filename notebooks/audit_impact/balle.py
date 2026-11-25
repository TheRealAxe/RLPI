"""Trajectoire simplifiée d'une balle libre (gravité, rebonds sol / plafond / murs, sans effet ni voitures)."""

import numpy as np

R = 92.75


def sim(b, v, T=3.0, dt=1 / 120):
    """Issue de la balle libre pendant T s : ('but0' = but en y < 0 | 'but1' = y > 0 | None, délai en s)."""
    b, v = np.array(b, float), np.array(v, float)
    for k in range(int(T / dt)):
        v[2] -= 650 * dt
        b += v * dt
        if b[2] < R:
            b[2] = R
            v[2] = -0.6 * v[2]
            v[:2] *= 0.95
        if b[2] > 2044 - R:
            b[2] = 2044 - R
            v[2] = -0.6 * v[2]
        if abs(b[0]) > 4096 - R:
            b[0] = np.sign(b[0]) * (4096 - R)
            v[0] = -0.6 * v[0]
        mouth = abs(b[0]) < 893 - R and b[2] < 642 - R
        if abs(b[1]) > 5120 + R and mouth:
            return ("but1" if b[1] > 0 else "but0"), (k + 1) * dt
        if abs(b[1]) > 5120 - R and not mouth:
            b[1] = np.sign(b[1]) * (5120 - R)
            v[1] = -0.6 * v[1]
    return None, None
