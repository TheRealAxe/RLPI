"""Notes de décision indépendantes du niveau adverse (phase 4-5, version prototype).

1. Adéquation des touches — Q(s, a) appris sur RLCS :
   - policy P(a | s) : quelles actions les pros choisissent dans cette situation ;
   - Q(s, a)        : gain de valeur ΔV attendu si un pro joue l'action a dans la situation s.
   Options « réalistes » = actions que les pros choisissent au moins 10 % du temps ici (+ l'action jouée).
   adéquation = (Q(jouée) − min Q) / (max Q − min Q) × 100, seulement si max − min ≥ 0,02.
   Comme Q est appris sur des issues pro, une défense adverse faible ne gonfle pas la note.

2. Placement hors ballon — où serait un pro à ta place ?
   Pour le 2e et le 3e joueur le plus proche de la balle, un modèle RLCS prédit la position (x, y)
   à partir de la balle, des coéquipiers et des adversaires. Écart = distance réelle ↔ prédite.

Les scores RLCS sont calculés « hors échantillon » (validation croisée par match, 5 plis) pour être
comparables à ceux de Théo, que le modèle n'a jamais vus.

Usage :
    python -m rlpi.decisions touches
    python -m rlpi.decisions placement
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import polars as pl

from rlpi.config import FEATURES, FRAMES, MODELS
from rlpi.value import FEATURE_NAMES, features, labels_and_score, load_replay

# Actions définies par l'INTENTION (direction donnée à la balle), pas par la réussite :
# un tir non cadré reste un « tir ». La précision relève de l'exécution.
ACTIONS = ["shot", "forward", "side", "back", "control"]
ACTION_FR = {"shot": "Tir (vers le but)", "forward": "Jeu vers l'avant", "side": "Jeu latéral",
             "back": "Jeu vers l'arrière", "control": "Contrôle / conduite"}
MIN_POLICY = 0.10
TARGET = "dv"  # gain de valeur jusqu à la touche suivante (1 s max) : meilleur R² hors échantillon
MIN_SPREAD = 0.02
N_FOLDS = 5


def intent_class(f: pl.DataFrame, i: int, slot: int, s: float, nxt: int) -> str:
    """Direction donnée à la balle 0,3 s après la touche (ou juste avant la touche suivante)."""
    j = int(min(i + 3, max(nxt - 1, i + 1), f.height - 1))
    bx, by = s * f["ball_x"][j], s * f["ball_y"][j]
    vx, vy, vz = s * f["ball_vx"][j], s * f["ball_vy"][j], f["ball_vz"][j]
    px, py, pz = s * f[f"p{slot}_x"][j], s * f[f"p{slot}_y"][j], f[f"p{slot}_z"][j]
    sp = (vx * vx + vy * vy + vz * vz) ** 0.5
    if ((bx - px) ** 2 + (by - py) ** 2 + (f["ball_z"][j] - pz) ** 2) ** 0.5 < 350 and sp < 1800:
        return "control"
    if vy > 300 and by > -1500:
        t = (5120 - by) / vy
        if t < 3 and abs(bx + vx * t) < 1400:
            return "shot"
    if vy > 0.4 * sp:
        return "forward"
    if vy < -0.4 * sp:
        return "back"
    return "side"


def _folds(groups: np.ndarray, k: int = N_FOLDS) -> np.ndarray:
    reps = np.unique(groups)
    rng = np.random.default_rng(0)
    fold_of = dict(zip(rng.permutation(reps), np.arange(len(reps)) % k))
    return np.array([fold_of[g] for g in groups])


# --------------------------------------------------------------------------- touches
def touch_table(source: str) -> tuple[np.ndarray, pl.DataFrame]:
    """Variables de situation (0,2 s avant la touche, vue du toucheur) + infos du toucheur."""
    tv = pl.read_parquet(FEATURES / f"touch_values_{source}.parquet")
    X, rows = [], []
    for replay, grp in tv.group_by("replay"):
        replay = replay[0]
        m, f = load_replay(FRAMES / source / f"{replay}.meta.json")
        slot_of = {p["id"]: p["slot"] for p in m["players"]}
        feats = {}
        for team in (0, 1):
            _, sd = labels_and_score(m, f.height, team, 5)
            feats[team] = features(f, team, sd)
        tis = sorted(grp["i"].to_list())
        for r in grp.iter_rows(named=True):
            if r["action"] == "save":
                continue  # un arrêt est imposé par la situation, pas un choix parmi d'autres
            team, slot = r["team"], slot_of[r["player_id"]]
            s = 1.0 if team == 0 else -1.0
            nxt = next((t for t in tis if t > r["i"]), f.height - 1)
            a = intent_class(f, r["i"], slot, s, nxt)
            i = r["i"] - 2
            me = [s * f[f"p{slot}_x"][i], s * f[f"p{slot}_y"][i], f[f"p{slot}_z"][i], s * f[f"p{slot}_vx"][i],
                  s * f[f"p{slot}_vy"][i], f[f"p{slot}_vz"][i], f[f"p{slot}_boost"][i]]
            X.append(np.concatenate([feats[team][i], np.array(me, dtype=np.float32)]))
            rows.append({**r, "act": a})
    return np.vstack(X), pl.DataFrame(rows)


TOUCHER = ["me_x", "me_y", "me_z", "me_vx", "me_vy", "me_vz", "me_boost"]


def _score(df, pol, q, acts):
    feas = (pol >= MIN_POLICY)
    feas[np.arange(len(acts)), acts] = True
    qf = np.where(feas, q, np.nan)
    qmax, qmin = np.nanmax(qf, 1), np.nanmin(qf, 1)
    best = np.nanargmax(qf, 1)
    qp = q[np.arange(len(acts)), acts]
    spread = qmax - qmin
    adequacy = np.where(spread >= MIN_SPREAD, (qp - qmin) / np.maximum(spread, 1e-9) * 100, np.nan)
    return df.with_columns(
        pl.Series("q_played", qp), pl.Series("q_best", qmax), pl.Series("q_worst", qmin),
        pl.Series("best_action", [ACTIONS[b] for b in best]), pl.Series("spread", spread),
        pl.Series("adequacy", adequacy), pl.Series("regret", qmax - qp),
        pl.Series("p_pro", pol[np.arange(len(acts)), acts]),
        *[pl.Series(f"q_{a}", q[:, k]) for k, a in enumerate(ACTIONS)],
        *[pl.Series(f"p_{a}", pol[:, k]) for k, a in enumerate(ACTIONS)],
    )


def touches(retrain: bool = True) -> None:
    """retrain=False : note seulement les touches de Théo avec les modèles enregistrés (RLCS inchangé)."""
    import lightgbm as lgb

    Xt, tt = touch_table("theo")
    if not retrain:
        pm = lgb.Booster(model_file=str(MODELS / "policy_touch.txt"))
        qm = lgb.Booster(model_file=str(MODELS / "q_touch.txt"))
        a_idx = {a: k for k, a in enumerate(ACTIONS)}
        yt_a = tt["act"].replace_strict(a_idx).to_numpy()
        oh = lambda X, k: np.hstack([X, np.eye(len(ACTIONS), dtype=np.float32)[np.full(len(X), k)]])  # noqa: E731
        q_t = np.column_stack([qm.predict(oh(Xt, k)) for k in range(len(ACTIONS))])
        _score(tt, pm.predict(Xt), q_t, yt_a).write_parquet(FEATURES / "touch_decisions_theo.parquet")
        print(f"→ touch_decisions_theo.parquet : {tt.height:,} touches notées (modèles existants)")
        return
    Xr, tr = touch_table("rlcs")
    names = FEATURE_NAMES + TOUCHER
    a_idx = {a: k for k, a in enumerate(ACTIONS)}
    yr_a = tr["act"].replace_strict(a_idx).to_numpy()
    yr_dv = tr[TARGET].to_numpy()
    groups = tr["replay"].to_numpy()
    folds = _folds(groups)
    print(f"{len(yr_a):,} touches RLCS (hors arrêts) : " +
          ", ".join(f"{a} {np.mean(yr_a == k):.0%}" for a, k in a_idx.items()))

    pol_params = dict(objective="multiclass", num_class=len(ACTIONS), learning_rate=0.05, num_leaves=31,
                      min_data_in_leaf=100, feature_fraction=0.8, verbose=-1)
    q_params = dict(objective="regression", learning_rate=0.03, num_leaves=31, min_data_in_leaf=200,
                    feature_fraction=0.8, lambda_l2=5.0, verbose=-1)

    def onehot_X(X, acts):
        oh = np.zeros((len(X), len(ACTIONS)), np.float32)
        oh[np.arange(len(X)), acts] = 1
        return np.hstack([X, oh])

    q_names = names + [f"act_{a}" for a in ACTIONS]

    def all_q(model, X):
        return np.column_stack([model.predict(onehot_X(X, np.full(len(X), k))) for k in range(len(ACTIONS))])

    # Hors échantillon pour RLCS
    pol_oof = np.zeros((len(Xr), len(ACTIONS)))
    q_oof = np.zeros((len(Xr), len(ACTIONS)))
    q_rounds, p_rounds = [], []
    for k in range(N_FOLDS):
        trn, val = folds != k, folds == k
        pm = lgb.train(pol_params, lgb.Dataset(Xr[trn], yr_a[trn], feature_name=names), 2000,
                       valid_sets=[lgb.Dataset(Xr[val], yr_a[val])], callbacks=[lgb.early_stopping(50, verbose=False)])
        qm = lgb.train(q_params, lgb.Dataset(onehot_X(Xr[trn], yr_a[trn]), yr_dv[trn], feature_name=q_names), 3000,
                       valid_sets=[lgb.Dataset(onehot_X(Xr[val], yr_a[val]), yr_dv[val])],
                       callbacks=[lgb.early_stopping(100, verbose=False)])
        pol_oof[val] = pm.predict(Xr[val], num_iteration=pm.best_iteration)
        q_oof[val] = all_q(qm, Xr[val])
        p_rounds.append(pm.best_iteration); q_rounds.append(qm.best_iteration)

    # Qualité
    q_played = q_oof[np.arange(len(Xr)), yr_a]
    r2 = 1 - np.mean((yr_dv - q_played) ** 2) / np.var(yr_dv)
    base = np.array([yr_dv[yr_a == k].mean() for k in range(len(ACTIONS))])[yr_a]
    r2_base = 1 - np.mean((yr_dv - base) ** 2) / np.var(yr_dv)
    acc = np.mean(pol_oof.argmax(1) == yr_a)
    print(f"Q(s,a) : R² hors échantillon {r2:.3f} (moyenne par action seule : {r2_base:.3f}) ; "
          f"policy : bonne action prédite {acc:.0%} (classe majoritaire {np.mean(yr_a == np.bincount(yr_a).argmax()):.0%})")

    # Modèles finaux → Théo
    pm = lgb.train(pol_params, lgb.Dataset(Xr, yr_a, feature_name=names), int(np.mean(p_rounds)))
    qm = lgb.train(q_params, lgb.Dataset(onehot_X(Xr, yr_a), yr_dv, feature_name=q_names), int(np.mean(q_rounds)))
    pm.save_model(str(MODELS / "policy_touch.txt")); qm.save_model(str(MODELS / "q_touch.txt"))
    yt_a = tt["act"].replace_strict(a_idx).to_numpy()
    pol_t, q_t = pm.predict(Xt), all_q(qm, Xt)

    _score(tr, pol_oof, q_oof, yr_a).write_parquet(FEATURES / "touch_decisions_rlcs.parquet")
    _score(tt, pol_t, q_t, yt_a).write_parquet(FEATURES / "touch_decisions_theo.parquet")
    (MODELS / "q_touch_report.json").write_text(json.dumps(
        {"r2_oof": r2, "r2_action_mean": r2_base, "policy_acc": acc, "n": int(len(Xr)),
         "n_matches": int(len(np.unique(groups)))}, indent=1), encoding="utf-8")
    print("→ touch_decisions_{rlcs,theo}.parquet")


# --------------------------------------------------------------------------- placement
def placement_rows(source: str, step: int):
    """Une ligne par (image, équipe, joueur hors ballon) : situation sans la position du joueur visé."""
    X, Y, meta = [], [], []
    for mp in sorted((FRAMES / source).glob("*.meta.json")):
        m, f = load_replay(mp)
        play = np.where(f["phase"].to_numpy() == 1)[0][::step]
        if len(play) == 0:
            continue
        g = lambda c: f[c].to_numpy()[play].astype(np.float32)  # noqa: E731
        for team in (0, 1):
            s = 1.0 if team == 0 else -1.0
            own = [0, 1, 2] if team == 0 else [3, 4, 5]
            opp = [3, 4, 5] if team == 0 else [0, 1, 2]
            bx, by, bz = s * g("ball_x"), s * g("ball_y"), g("ball_z")
            bvx, bvy, bvz = s * g("ball_vx"), s * g("ball_vy"), g("ball_vz")
            P = {k: (s * g(f"p{k}_x"), s * g(f"p{k}_y"), g(f"p{k}_z"), s * g(f"p{k}_vx"), s * g(f"p{k}_vy"),
                     g(f"p{k}_boost"), g(f"p{k}_demo")) for k in own + opp}
            dist = lambda k: np.hypot(P[k][0] - bx, P[k][1] - by)  # noqa: E731
            od = np.stack([dist(k) for k in own])
            order = np.argsort(od, axis=0)
            opd = np.stack([dist(k) for k in opp])
            oorder = np.argsort(opd, axis=0)
            n = len(play)
            ar = np.arange(n)
            take = lambda slots, idx, j: np.stack([P[k][j] for k in slots])[idx, ar]  # noqa: E731
            opp_cols = []
            for r in range(3):
                idx = oorder[r]
                opp_cols += [take(opp, idx, j) for j in range(5)]
            first = order[0]
            first_cols = [take(own, first, j) for j in range(6)]
            for rank in (1, 2):
                tgt, other = order[rank], order[3 - rank]
                demo = take(own, tgt, 6)
                ok = demo == 0
                cols = [bx, by, bz, bvx, bvy, bvz] + first_cols + [take(own, other, 0), take(own, other, 1),
                         take(own, tgt, 5)] + opp_cols + [g("seconds_remaining"), np.full(n, rank, np.float32)]
                X.append(np.column_stack(cols)[ok])
                Y.append(np.column_stack([take(own, tgt, 0), take(own, tgt, 1)])[ok])
                slot = np.array(own)[tgt][ok]
                meta.append(pl.DataFrame({"replay": m["replay"], "i": play[ok], "team": team, "rank": rank,
                                          "slot": slot}))
    return np.vstack(X), np.vstack(Y), pl.concat(meta)


def placement() -> None:
    import lightgbm as lgb

    Xr, Yr, mr = placement_rows("rlcs", step=5)
    Xt, Yt, mt = placement_rows("theo", step=5)
    groups = mr["replay"].to_numpy()
    folds = _folds(groups)
    params = dict(objective="regression_l1", learning_rate=0.05, num_leaves=63, min_data_in_leaf=200,
                  feature_fraction=0.8, verbose=-1)
    pred = np.zeros_like(Yr)
    rounds = {0: [], 1: []}
    for k in range(N_FOLDS):
        trn, val = folds != k, folds == k
        for j in (0, 1):
            mdl = lgb.train(params, lgb.Dataset(Xr[trn], Yr[trn, j]), 3000,
                            valid_sets=[lgb.Dataset(Xr[val], Yr[val, j])],
                            callbacks=[lgb.early_stopping(100, verbose=False)])
            pred[val, j] = mdl.predict(Xr[val], num_iteration=mdl.best_iteration)
            rounds[j].append(mdl.best_iteration)
    err_r = np.hypot(*(pred - Yr).T)
    naive = np.hypot(*(Yr - np.median(Yr, 0)).T)
    print(f"{len(Yr):,} positions RLCS : écart médian au placement prédit {np.median(err_r):.0f} uu "
          f"(sans modèle : {np.median(naive):.0f} uu)")
    pt = np.zeros_like(Yt)
    for j in (0, 1):
        mdl = lgb.train(params, lgb.Dataset(Xr, Yr[:, j]), int(np.mean(rounds[j])))
        mdl.save_model(str(MODELS / f"placement_{'xy'[j]}.txt"))
        pt[:, j] = mdl.predict(Xt)
    err_t = np.hypot(*(pt - Yt).T)
    for df, err, pr, yy, src in ((mr, err_r, pred, Yr, "rlcs"), (mt, err_t, pt, Yt, "theo")):
        df.with_columns(pl.Series("err", err), pl.Series("x", yy[:, 0]), pl.Series("y", yy[:, 1]),
                        pl.Series("px", pr[:, 0]), pl.Series("py", pr[:, 1])) \
          .write_parquet(FEATURES / f"placement_{src}.parquet")
    print(f"→ placement_{{rlcs,theo}}.parquet ; écart médian Théo et lobbies {np.median(err_t):.0f} uu")


def placement_score(source: str = "theo") -> None:
    """Note le placement d'une source (theo, ssl…) avec les modèles déjà entraînés sur RLCS (sans réentraîner)."""
    import lightgbm as lgb

    Xt, Yt, mt = placement_rows(source, step=5)
    pt = np.column_stack([lgb.Booster(model_file=str(MODELS / f"placement_{c}.txt")).predict(Xt) for c in "xy"])
    err = np.hypot(*(pt - Yt).T)
    mt.with_columns(pl.Series("err", err), pl.Series("x", Yt[:, 0]), pl.Series("y", Yt[:, 1]),
                    pl.Series("px", pt[:, 0]), pl.Series("py", pt[:, 1])).write_parquet(FEATURES / f"placement_{source}.parquet")
    print(f"→ placement_{source}.parquet ({mt['replay'].n_unique()} matchs)")


def placement_score_theo() -> None:
    placement_score("theo")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["touches", "touches-theo", "placement", "placement-theo", "placement-score"])
    ap.add_argument("--source", default="theo")
    a = ap.parse_args()
    if a.cmd == "touches-theo":
        touches(retrain=False)
    elif a.cmd == "placement-score":
        placement_score(a.source)
    else:
        {"touches": touches, "placement": placement, "placement-theo": placement_score_theo}[a.cmd]()


if __name__ == "__main__":
    main()
