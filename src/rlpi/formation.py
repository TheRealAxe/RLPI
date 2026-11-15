"""Formation à trois (prototype) : où se tiendrait une équipe RLCS dans cette situation, les trois joueurs ENSEMBLE ?

Remplace l'approche et le placement joueur par joueur, qui donnaient des positions idéales calculées séparément
(trois joueurs « idéaux » qui se chevauchent). Ici :
  1. un modèle apprend, sur les matchs RLCS, les positions des trois rôles d'une équipe — rôle 0 = le plus proche
     de la balle (celui qui la joue), rôle 1 = le 2e, rôle 2 = le 3e — RELATIVES À LA BALLE, à partir de la balle
     et des adversaires seulement (pas de la position de nos joueurs, sinon il recopierait notre placement) ;
  2. chaque joueur réel reçoit un rôle : celui qui minimise le déplacement total des trois, avec une pénalité
     de changement de rôle d'une image à l'autre (Viterbi) pour éviter que les rôles clignotent.
Repère de l'équipe : elle attaque vers +y.

Usage :
    python -m rlpi.formation train
"""
from __future__ import annotations

import argparse
import itertools
import json

import numpy as np
import polars as pl

from rlpi.config import FRAMES, MODELS
from rlpi.value import load_replay

NAMES = (["ball_x", "ball_y", "ball_z", "ball_vx", "ball_vy", "ball_vz", "seconds_remaining"]
         + [f"opp{r}_{c}" for r in range(3) for c in ("x", "y", "vx", "vy", "boost")])
ROLE_FR = ["sur la balle", "2e joueur", "3e joueur"]
PERMS = list(itertools.permutations(range(3)))   # PERMS[p][joueur] = rôle
SWITCH_PENALTY = 900.0                            # uu : coût d'un changement de rôle d'une image à l'autre
MIN_GAP = 1000.0          # uu : écart minimal entre deux rôles (les prédictions « moyennes » sont trop resserrées :
                          # écart minimal médian prédit 1 200 uu contre 2 000 chez les pros)
ROLE0_WEIGHT = 3.0        # le rôle « sur la balle » revient d'abord à celui qui peut l'atteindre


def situation(a: dict, m: dict, ks: np.ndarray, team: int) -> np.ndarray:
    s = 1.0 if team == 0 else -1.0
    bx, by = s * a["ball_x"][ks], s * a["ball_y"][ks]
    cols = [bx, by, a["ball_z"][ks], s * a["ball_vx"][ks], s * a["ball_vy"][ks], a["ball_vz"][ks],
            a["seconds_remaining"][ks]]
    opps = [p["slot"] for p in m["players"] if p["team"] != team]
    n, ar = len(ks), np.arange(len(ks))
    X = np.stack([s * a[f"p{k}_x"][ks] for k in opps]); Y = np.stack([s * a[f"p{k}_y"][ks] for k in opps])
    D = np.where(np.stack([a[f"p{k}_demo"][ks] for k in opps]) > 0, 1e5, np.hypot(X - bx, Y - by))
    order = np.argsort(D, axis=0)
    for r in range(3):
        if r < len(opps):
            idx = order[r]
            for c in ("x", "y", "vx", "vy"):
                arr = np.stack([(s if c != "boost" else 1.0) * a[f"p{k}_{c}"][ks] for k in opps])
                cols.append(arr[idx, ar])
            cols.append(np.stack([a[f"p{k}_boost"][ks] for k in opps])[idx, ar])
        else:
            cols += [np.full(n, np.nan, np.float32)] * 5
    return np.column_stack(cols).astype(np.float32)


def own_positions(a: dict, m: dict, ks: np.ndarray, team: int):
    """Positions de nos 3 joueurs (repère de l'équipe) : (slots, P de forme (3, n, 2))."""
    s = 1.0 if team == 0 else -1.0
    slots = [p["slot"] for p in m["players"] if p["team"] == team]
    P = np.stack([np.column_stack([s * a[f"p{k}_x"][ks], s * a[f"p{k}_y"][ks]]) for k in slots])
    return slots, P


def rows(source: str, step: int = 5):
    X, Y, G = [], [], []
    for n, mp in enumerate(sorted((FRAMES / source).glob("*.meta.json"))):
        m, f = load_replay(mp)
        a = {c: f[c].to_numpy().astype(np.float32) for c in f.columns if c != "state"}
        ks = np.where(f["phase"].to_numpy() == 1)[0][::step]
        if len(ks) == 0:
            continue
        for team in (0, 1):
            slots, P = own_positions(a, m, ks, team)
            if len(slots) != 3:
                continue
            demo = np.stack([a[f"p{k}_demo"][ks] for k in slots]).max(0) > 0
            s = 1.0 if team == 0 else -1.0
            ball = np.column_stack([s * a["ball_x"][ks], s * a["ball_y"][ks]])
            d = np.hypot(P[..., 0] - ball[:, 0], P[..., 1] - ball[:, 1])        # (3, n)
            order = np.argsort(d, axis=0)
            ar = np.arange(len(ks))
            tgt = np.concatenate([P[order[r], ar] - ball for r in range(3)], axis=1)   # (n, 6)
            ok = ~demo
            X.append(situation(a, m, ks, team)[ok]); Y.append(tgt[ok]); G += [m["replay"]] * int(ok.sum())
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
    pred, rounds = np.zeros((te.sum(), 6)), []
    for j in range(6):
        b = lgb.train(params, lgb.Dataset(X[~te], Y[~te, j], feature_name=NAMES), 3000,
                      valid_sets=[lgb.Dataset(X[te], Y[te, j])], callbacks=[lgb.early_stopping(100, verbose=False)])
        pred[:, j] = b.predict(X[te], num_iteration=b.best_iteration)
        rounds.append(b.best_iteration)
    rep = {"n": int(len(X)), "n_matches": int(len(reps)), "rounds": rounds}
    for r in range(3):
        e = np.hypot(pred[:, 2 * r] - Y[te, 2 * r], pred[:, 2 * r + 1] - Y[te, 2 * r + 1])
        med = np.median(Y[~te][:, 2 * r:2 * r + 2], axis=0)
        eb = np.hypot(med[0] - Y[te, 2 * r], med[1] - Y[te, 2 * r + 1])
        rep[f"role{r}_median_err_uu"] = float(np.median(e))
        rep[f"role{r}_median_err_base_uu"] = float(np.median(eb))
    # écart minimal entre deux rôles prédits (vérifie que la formation ne s'effondre pas)
    gaps = np.min([np.hypot(pred[:, 2 * i] - pred[:, 2 * j], pred[:, 2 * i + 1] - pred[:, 2 * j + 1])
                   for i, j in ((0, 1), (0, 2), (1, 2))], axis=0)
    rep["pred_min_gap_median_uu"] = float(np.median(gaps))
    rep["pred_min_gap_p05_uu"] = float(np.percentile(gaps, 5))
    real_gaps = np.min([np.hypot(Y[te, 2 * i] - Y[te, 2 * j], Y[te, 2 * i + 1] - Y[te, 2 * j + 1])
                        for i, j in ((0, 1), (0, 2), (1, 2))], axis=0)
    rep["real_min_gap_median_uu"] = float(np.median(real_gaps))
    print(json.dumps(rep, indent=1))
    for j in range(6):
        b = lgb.train(params, lgb.Dataset(X, Y[:, j], feature_name=NAMES), rounds[j])
        b.save_model(str(MODELS / f"formation_{j}.txt"))
    (MODELS / "formation_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print("→ formation_{0..5}.txt")


def predict(a: dict, m: dict, ks: np.ndarray, team: int) -> np.ndarray:
    """Positions des 3 rôles (repère de l'équipe), forme (3, n, 2)."""
    import lightgbm as lgb

    X = situation(a, m, ks, team)
    s = 1.0 if team == 0 else -1.0
    ball = np.column_stack([s * a["ball_x"][ks], s * a["ball_y"][ks]])
    out = np.column_stack([lgb.Booster(model_file=str(MODELS / f"formation_{j}.txt")).predict(X) for j in range(6)])
    R = np.stack([out[:, 2 * r:2 * r + 2] + ball for r in range(3)])
    # écart minimal : un rôle trop proche d'un rôle prioritaire est repoussé (vers son but si confondus)
    for r in (1, 2):
        for q in range(r):
            d = R[r] - R[q]
            dist = np.hypot(d[:, 0], d[:, 1])
            u = np.where(dist[:, None] > 1, d / np.maximum(dist, 1)[:, None], np.array([0.0, -1.0]))
            push = dist < MIN_GAP
            R[r][push] = R[q][push] + u[push] * MIN_GAP
    R[..., 0] = np.clip(R[..., 0], -3900, 3900)
    R[..., 1] = np.clip(R[..., 1], -5000, 5000)
    return R


def assign(P: np.ndarray, R: np.ndarray) -> np.ndarray:
    """Rôle de chaque joueur à chaque image (forme (3, n)) : déplacement total minimal + pénalité de changement."""
    n = P.shape[1]
    cost = np.zeros((n, len(PERMS)))
    for p, perm in enumerate(PERMS):
        cost[:, p] = sum((ROLE0_WEIGHT if perm[j] == 0 else 1.0) * np.hypot(*(P[j] - R[perm[j]]).T) for j in range(3))
    acc = cost[0].copy(); back = np.zeros((n, len(PERMS)), int)
    sw = np.array([[0.0 if a == b else SWITCH_PENALTY for b in range(len(PERMS))] for a in range(len(PERMS))])
    for t in range(1, n):
        tot = acc[:, None] + sw                      # précédent → courant
        back[t] = tot.argmin(0)
        acc = tot.min(0) + cost[t]
    path = [int(acc.argmin())]
    for t in range(n - 1, 0, -1):
        path.append(int(back[t, path[-1]]))
    path = path[::-1]
    return np.array([[PERMS[p][j] for p in path] for j in range(3)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train"])
    ap.parse_args()
    train()


if __name__ == "__main__":
    main()
