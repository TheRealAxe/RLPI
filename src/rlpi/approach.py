"""Approche (prototype) : où se trouve un pro qui VA jouer la balle, dans les 3 s qui précèdent sa touche ?

Pour chaque touche RLCS (hors arrêts), on prend les images 3,0 s → 0,3 s avant (toutes les 0,3 s) et on apprend
la position du futur toucheur RELATIVE À LA BALLE (dx, dy) à partir de :
  balle (position, vitesse), temps restant avant la touche, boost du toucheur,
  2 coéquipiers et 3 adversaires (positions, triés par distance à la balle ; vitesses des adversaires).
Repère du toucheur : il attaque vers +y.

Usage :
    python -m rlpi.approach train
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import polars as pl

from rlpi.config import FEATURES, FRAMES, MODELS
from rlpi.value import load_replay

TAUS = np.arange(3, 31, 3)          # images avant la touche (0,3 s → 3,0 s)
NAMES = (["ball_x", "ball_y", "ball_z", "ball_vx", "ball_vy", "ball_vz", "tau", "my_boost"]
         + [f"mate{r}_{c}" for r in range(2) for c in ("x", "y")]
         + [f"opp{r}_{c}" for r in range(3) for c in ("x", "y", "vx", "vy")])


def _arrays(f: pl.DataFrame) -> dict[str, np.ndarray]:
    return {c: f[c].to_numpy().astype(np.float32) for c in f.columns if c != "state"}


def situation(a: dict, m: dict, ks: np.ndarray, slot: int, team: int, tau: np.ndarray) -> np.ndarray:
    """Variables d'approche pour les images ks (vecteur), vues par le joueur `slot`."""
    s = 1.0 if team == 0 else -1.0
    bx, by, bz = s * a["ball_x"][ks], s * a["ball_y"][ks], a["ball_z"][ks]
    cols = [bx, by, bz, s * a["ball_vx"][ks], s * a["ball_vy"][ks], a["ball_vz"][ks], tau / 10.0,
            a[f"p{slot}_boost"][ks]]
    mates = [p["slot"] for p in m["players"] if p["team"] == team and p["slot"] != slot]
    opps = [p["slot"] for p in m["players"] if p["team"] != team]
    n = len(ks)
    ar = np.arange(n)
    for group, nkeep, vel in ((mates, 2, False), (opps, 3, True)):
        X = np.stack([s * a[f"p{k}_x"][ks] for k in group]) if group else np.zeros((0, n))
        Y = np.stack([s * a[f"p{k}_y"][ks] for k in group]) if group else np.zeros((0, n))
        VX = np.stack([s * a[f"p{k}_vx"][ks] for k in group]) if group else np.zeros((0, n))
        VY = np.stack([s * a[f"p{k}_vy"][ks] for k in group]) if group else np.zeros((0, n))
        order = np.argsort(np.hypot(X - bx, Y - by), axis=0)
        for r in range(nkeep):
            if r < len(group):
                idx = order[r]
                cols += [X[idx, ar], Y[idx, ar]] + ([VX[idx, ar], VY[idx, ar]] if vel else [])
            else:
                cols += [np.full(n, np.nan, np.float32)] * (4 if vel else 2)
    return np.column_stack(cols).astype(np.float32)


def rows(source: str, frac: float = 0.5):
    R = pl.read_parquet(FEATURES / f"bestplay_rows_{source}.parquet")
    rng = np.random.default_rng(1)
    R = R.filter(pl.Series(rng.random(R.height) < frac))
    X, Y, G = [], [], []
    for n, ((replay,), grp) in enumerate(R.group_by("replay")):
        m, f = load_replay(FRAMES / source / f"{replay}.meta.json")
        a = _arrays(f)
        phase = f["phase"].to_numpy()
        slot_of = {p["id"]: p["slot"] for p in m["players"]}
        for r in grp.iter_rows(named=True):
            slot, team = slot_of.get(r["player_id"]), r["team"]
            if slot is None:
                continue
            ks = r["i"] - TAUS
            ok = (ks >= 0) & (phase[np.clip(ks, 0, None)] == 1) & (a[f"p{slot}_demo"][np.clip(ks, 0, None)] == 0)
            ks, tau = ks[ok], TAUS[ok].astype(np.float32)
            if len(ks) == 0:
                continue
            s = 1.0 if team == 0 else -1.0
            X.append(situation(a, m, ks, slot, team, tau))
            Y.append(np.column_stack([s * a[f"p{slot}_x"][ks] - s * a["ball_x"][ks],
                                      s * a[f"p{slot}_y"][ks] - s * a["ball_y"][ks]]))
            G += [replay] * len(ks)
        if n % 200 == 0:
            print(f"  {n} matchs…", flush=True)
    return np.vstack(X), np.vstack(Y).astype(np.float32), np.array(G)


def train() -> None:
    import lightgbm as lgb

    X, Y, G = rows("rlcs")
    reps = np.unique(G)
    rng = np.random.default_rng(0)
    te = np.isin(G, rng.choice(reps, size=len(reps) // 5, replace=False))
    params = dict(objective="regression_l1", learning_rate=0.05, num_leaves=63, min_data_in_leaf=200,
                  feature_fraction=0.9, verbose=-1)
    pred, rounds = np.zeros((te.sum(), 2)), []
    for j in range(2):
        b = lgb.train(params, lgb.Dataset(X[~te], Y[~te, j], feature_name=NAMES), 3000,
                      valid_sets=[lgb.Dataset(X[te], Y[te, j])], callbacks=[lgb.early_stopping(100, verbose=False)])
        pred[:, j] = b.predict(X[te], num_iteration=b.best_iteration)
        rounds.append(b.best_iteration)
    err = np.hypot(*(pred - Y[te]).T)
    # base : décalage médian par tranche de temps avant la touche
    tau = X[te, NAMES.index("tau")]
    base = np.zeros_like(pred)
    for tv in np.unique(X[~te, NAMES.index("tau")]):
        mk_tr = X[~te, NAMES.index("tau")] == tv
        base[tau == tv] = np.median(Y[~te][mk_tr], axis=0)
    err_b = np.hypot(*(base - Y[te]).T)
    by_tau = {f"{tv:.1f}s": float(np.median(err[tau == tv])) for tv in np.unique(tau)}
    rep = {"n": int(len(X)), "n_matches": int(len(reps)), "median_err_uu": float(np.median(err)),
           "median_err_base_uu": float(np.median(err_b)), "median_err_by_tau": by_tau, "rounds": rounds}
    print(json.dumps(rep, indent=1))
    for j, c in enumerate("xy"):
        b = lgb.train(params, lgb.Dataset(X, Y[:, j], feature_name=NAMES), rounds[j])
        b.save_model(str(MODELS / f"approach_d{c}.txt"))
    (MODELS / "approach_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print("→ approach_d{x,y}.txt")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train"])
    a = ap.parse_args()
    train()


if __name__ == "__main__":
    main()
