"""Paquet d'actions à juger (« swipe ») : clips de 4 s autour d'une touche, à l'aveugle.

Chaque carte = une touche d'un joueur, 3 s avant et 1 s après (la suite est cachée pour juger la
décision, pas le résultat). Positions, orientation (vecteurs avant / haut), vitesses et boost des
6 voitures et de la balle, à 30 images par seconde (fréquence d'enregistrement du replay).

Tirage stratifié par origine du joueur jugé (cachée à l'écran) : l'utilisateur, ses coéquipiers suivis,
les autres joueurs de ses parties, SSL, RLCS.

Usage : python -m rlpi.swipe --n 40  → reports/swipe/deck.json
"""
from __future__ import annotations

import argparse
import json
import random

import numpy as np
import polars as pl

from rlpi import config
from rlpi.config import FEATURES, FRAMES, ROOT, SOURCE

FPS = 30        # images par seconde du clip livré
SRC_FPS = 120   # lecture fine du replay pour dater chaque vraie mise à jour
BEFORE, AFTER = 3.0, 1.0
PERSO = config.PLAYER
PEERS = set(config.COMPARE)
MIX = {"perso": .4, "peer": .15, "lobby": .15, "ssl": .15, "rlcs": .15}


def candidates() -> pl.DataFrame:
    rows = []
    for src in (SOURCE, "ssl", "rlcs"):
        t = pl.read_parquet(FEATURES / f"touch_values_{src}.parquet").select("replay", "i", "player_id", "player_name", "action")
        if src == SOURCE:
            t = t.with_columns(pl.when(pl.col("player_id") == PERSO).then(pl.lit("perso"))
                               .when(pl.col("player_name").is_in(list(PEERS))).then(pl.lit("peer"))
                               .otherwise(pl.lit("lobby")).alias("origin"))
        else:
            t = t.with_columns(pl.lit(src).alias("origin"))
        rows.append(t.with_columns(pl.lit(src).alias("source")))
    return pl.concat(rows)


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


def extract(source: str, replay: str, picks: list[dict]) -> list[dict]:
    import subtr_actor as sa

    meta = json.loads((FRAMES / source / f"{replay}.meta.json").read_text(encoding="utf-8"))
    f10 = pl.read_parquet(FRAMES / source / f"{replay}.parquet", columns=["ball_x", "ball_y", "ball_z"])
    cols, arr = sa.get_ndarray_with_info_from_replay_filepath(
        meta["path"], ["BallRigidBody"], ["PlayerRigidBodyBasis", "PlayerBoost"], fps=SRC_FPS, dtype="f32")
    a = np.asarray(arr)
    gh, ph = cols["column_headers"]["global_headers"], cols["column_headers"]["player_headers"]
    ng, npl = len(gh), len(ph)
    gi = {h: gh.index(h) for h in gh}
    bh = next(h for h in ph if "boost" in h.lower())
    out = []
    for p in picks:
        i10 = p["i"]
        target = np.array([f10["ball_x"][i10], f10["ball_y"][i10], f10["ball_z"][i10]])
        r = SRC_FPS // 10
        lo, hi = max(0, r * i10 - 10 * r), min(len(a), r * i10 + 10 * r)
        d = np.linalg.norm(a[lo:hi, [gi["Ball - position x"], gi["Ball - position y"], gi["Ball - position z"]]] - target, axis=1)
        j = lo + int(np.argmin(d))
        if d.min() > 50:
            continue  # alignement douteux : carte écartée
        j0, j1 = j - int(BEFORE * SRC_FPS), j + int(AFTER * SRC_FPS) + 1
        if j0 < 0 or j1 > len(a):
            continue
        seg = a[j0:j1]
        n_out = int((BEFORE + AFTER) * FPS) + 1
        g = lambda name: seg[:, gi[name]]  # noqa: E731
        pc = lambda k, name: seg[:, ng + k * npl + ph.index(name)]  # noqa: E731
        xyz = lambda f: np.column_stack([f("x"), f("y"), f("z")])  # noqa: E731
        cars = []
        step = SRC_FPS // FPS
        for pl_ in meta["players"]:
            k = pl_["slot"]
            pos = xyz(lambda c: pc(k, f"position {c}")); vel = xyz(lambda c: pc(k, f"linear velocity {c}"))
            P_, V_ = resample(pos, vel, SRC_FPS, n_out, FPS)
            fw = resample_dir(xyz(lambda c: pc(k, f"forward {c}")), pos, SRC_FPS, n_out, FPS)
            up = resample_dir(xyz(lambda c: pc(k, f"up {c}")), pos, SRC_FPS, n_out, FPS)
            cars.append({
                "team": pl_["team"], "judged": pl_["id"] == p["player_id"],
                "pos": np.round(P_).astype(int).tolist(), "vel": np.round(V_).astype(int).tolist(),
                "fw": np.round(fw, 3).tolist(), "up": np.round(up, 3).tolist(),
                "boost": np.round(pc(k, bh)[::step][:n_out] / 2.55).astype(int).tolist(),
            })
        if not any(c["judged"] for c in cars) or np.isnan(seg[:, :3]).any():
            continue
        out.append({
            "id": f"{source}:{replay}:{i10}", "origin": p["origin"], "action": p["action"],
            "fps": FPS, "action_frame": int(BEFORE * FPS), **dict(zip(("ball", "ball_v"), (lambda bp, bv: (np.round(bp).astype(int).tolist(), np.round(bv).astype(int).tolist()))(
                *resample(xyz(lambda c: g(f"Ball - position {c}")), xyz(lambda c: g(f"Ball - linear velocity {c}")), SRC_FPS, n_out, FPS)))),
            "cars": cars,
        })
    return out


def build(n: int, seed: int = 1) -> None:
    rng = random.Random(seed)
    cand = candidates()
    want = {o: max(1, round(n * w)) for o, w in MIX.items()}
    chosen = []
    for origin, k in want.items():
        pool = cand.filter(pl.col("origin") == origin)
        idx = rng.sample(range(pool.height), min(pool.height, k * 2))  # marge pour les cartes écartées
        chosen += [pool.row(x, named=True) for x in idx]
    by_replay: dict[tuple[str, str], list[dict]] = {}
    for c in chosen:
        by_replay.setdefault((c["source"], c["replay"]), []).append(c)
    cards = []
    for (src, rp), picks in by_replay.items():
        cards += extract(src, rp, picks)
    deck = []
    for origin, k in want.items():
        deck += [c for c in cards if c["origin"] == origin][:k]
    rng.shuffle(deck)
    out = ROOT / "reports" / "swipe"
    out.mkdir(parents=True, exist_ok=True)
    (out / "deck.json").write_text(json.dumps({"seed": seed, "cards": deck}), encoding="utf-8")
    from collections import Counter
    print(f"→ {out / 'deck.json'} : {len(deck)} cartes", dict(Counter(c["origin"] for c in deck)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    build(a.n, a.seed)


if __name__ == "__main__":
    main()
