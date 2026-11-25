"""Modèle de valeur d'une situation (phase 4, étape 1) et valeur ajoutée par touche.

Idée : P(l'équipe T marque dans les H secondes | situation vue par T). Un seul modèle sert aux deux
équipes grâce à la symétrie : on retourne le terrain pour que T attaque toujours vers y > 0.
    V_T(s) = P_T(marquer) − P_adverse(marquer)        ∈ [-1, 1]
Valeur d'une touche du joueur j (équipe T) à l'image i :
    ΔV = V_T(juste avant la touche suivante, au plus +1 s) − V_T(0,2 s avant la touche)
    (si un but tombe entre les deux : V = +1 ou −1)
Corrections de l'audit du 24/11/2026 (docs/AUDIT_IMPACT_2026-11-24.md) :
    F3  une seule touche par joueur et par image ; crédit partagé entre coéquipiers sur la même image (`share`) ;
    F1  un but de l'équipe du toucheur sans autre touche dans les 4 s est rattaché à la touche (tirs de loin) ;
    F2  si la balle, laissée libre, entrait déjà dans le but du toucheur (rlpi.ballsim), ΔV ne peut pas être
        négatif (`going_in_own`) : on ne punit pas une tentative d'arrêt sur un but déjà fait.

Usage :
    python -m rlpi.value train [--horizon 10]     → data/models/value_h10.txt + rapport
    python -m rlpi.value touches --source rlcs    → data/features/touch_values_rlcs.parquet
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

from rlpi.config import FEATURES, FRAMES, MODELS

FPS = 10
GOAL_Y = 5120.0


# --------------------------------------------------------------------------- variables
def _player_block(f: pl.DataFrame, k: int, s: float) -> dict[str, np.ndarray]:
    g = lambda c: f[f"p{k}_{c}"].to_numpy().astype(np.float32)  # noqa: E731
    return {"x": s * g("x"), "y": s * g("y"), "z": g("z"), "vx": s * g("vx"), "vy": s * g("vy"),
            "vz": g("vz"), "boost": g("boost"), "demo": g("demo"),
            "yaw": g("rz") + (0.0 if s > 0 else np.pi)}


_TRAJ_CACHE: dict[tuple, dict[str, np.ndarray]] = {}


def trajectory(f: pl.DataFrame) -> dict[str, np.ndarray]:
    """Variables de trajectoire simulées (rlpi.ballsim.goal_lines, 4 s) pour chaque image, dans le repère du
    terrain. Mises en cache : `features` est appelée pour les deux équipes et par plusieurs étapes."""
    from rlpi import ballsim

    bx, by = f["ball_x"].to_numpy(), f["ball_y"].to_numpy()
    key = (f.height, float(bx[: 50].sum()), float(by[-50:].sum()), float(np.nansum(bx)))
    if key not in _TRAJ_CACHE:
        if len(_TRAJ_CACHE) > 8:
            _TRAJ_CACHE.clear()
        g = lambda c: f[c].to_numpy().astype(np.float64)  # noqa: E731
        x = np.column_stack([g("ball_x"), g("ball_y"), g("ball_z")])
        v = np.column_stack([g("ball_vx"), g("ball_vy"), g("ball_vz")])
        w = np.column_stack([g("ball_wx"), g("ball_wy"), g("ball_wz")]) if "ball_wx" in f.columns else None
        ok = np.isfinite(x).all(1) & np.isfinite(v).all(1)
        out = {k: np.full(f.height, d, np.float32) for k, d in
               (("t_pos", 10.0), ("t_neg", 10.0), ("in_pos", 0.0), ("in_neg", 0.0), ("x_pos", 4096.0), ("x_neg", 4096.0))}
        if ok.any():
            r = ballsim.goal_lines(x[ok], v[ok], None if w is None else w[ok], 4.0)
            for k in out:
                out[k][ok] = r[k]
        _TRAJ_CACHE[key] = out
    return _TRAJ_CACHE[key]


def features(f: pl.DataFrame, team: int, score_diff: np.ndarray) -> np.ndarray:
    """Matrice (n_images, n_variables) du point de vue de `team` (attaque vers y > 0)."""
    s = 1.0 if team == 0 else -1.0
    bx, by, bz = s * f["ball_x"].to_numpy(), s * f["ball_y"].to_numpy(), f["ball_z"].to_numpy()
    bvx, bvy, bvz = s * f["ball_vx"].to_numpy(), s * f["ball_vy"].to_numpy(), f["ball_vz"].to_numpy()
    cols = [bx, by, bz, bvx, bvy, bvz, np.sqrt(bvx**2 + bvy**2 + bvz**2),
            np.hypot(bx, GOAL_Y - by), np.hypot(bx, GOAL_Y + by)]
    # Trajectoire de la balle vers chaque but : simulée avec gravité et rebonds (rlpi.ballsim, audit L1)
    tr = trajectory(f)
    for c in (("pos", "neg") if team == 0 else ("neg", "pos")):  # but adverse puis but de l'équipe
        cols += [tr[f"t_{c}"], tr[f"in_{c}"], tr[f"x_{c}"]]
    for side, slots in (("own", [0, 1, 2] if team == 0 else [3, 4, 5]),
                        ("opp", [3, 4, 5] if team == 0 else [0, 1, 2])):
        blocks = [_player_block(f, k, s) for k in slots]
        dist = np.stack([np.sqrt((b["x"] - bx) ** 2 + (b["y"] - by) ** 2 + (b["z"] - bz) ** 2) for b in blocks])
        dist = np.where(np.stack([b["demo"] for b in blocks]) > 0, 1e5, dist)  # démoli = « loin »
        order = np.argsort(dist, axis=0)  # le plus proche de la balle d'abord
        n = len(bx)
        for rank in range(3):
            idx = order[rank]
            pick = lambda key: np.stack([b[key] for b in blocks])[idx, np.arange(n)]  # noqa: E731
            px, py, pz, pvx, pvy = pick("x"), pick("y"), pick("z"), pick("vx"), pick("vy")
            d = np.minimum(dist[idx, np.arange(n)], 2e4)
            # vitesse de rapprochement vers la balle
            closing = (pvx * (bx - px) + pvy * (by - py)) / np.maximum(np.hypot(bx - px, by - py), 1)
            goalside = (py < by) if side == "own" else (py > by)
            facing = np.cos(pick("yaw") - np.arctan2(by - py, bx - px))  # 1 = face à la balle
            cols += [px, py, pz, pvx, pvy, pick("vz"), np.hypot(pvx, pvy), pick("boost"), pick("demo"),
                     d, closing, goalside.astype(np.float32), facing]
        ys = np.stack([b["y"] for b in blocks])
        cols += [(ys < by).sum(0) if side == "own" else (ys > by).sum(0),  # nb de joueurs du bon côté
                 np.stack([b["boost"] for b in blocks]).mean(0)]
    cols += [f["seconds_remaining"].to_numpy(), np.clip(score_diff, -3, 3)]
    return np.column_stack(cols).astype(np.float32)


FEATURE_NAMES = (
    ["ball_x", "ball_y", "ball_z", "ball_vx", "ball_vy", "ball_vz", "ball_speed", "ball_dist_opp_goal",
     "ball_dist_own_goal", "ball_t_opp_goal", "ball_on_target_opp", "ball_x_at_opp_line",
     "ball_t_own_goal", "ball_on_target_own", "ball_x_at_own_line"]
    + [f"{side}{r}_{c}" for side in ("own", "opp") for r in (list(range(3)) + ["team"])
       for c in (["x", "y", "z", "vx", "vy", "vz", "speed", "boost", "demo", "dist_ball", "closing",
                  "goalside", "facing_ball"] if r != "team" else ["n_goalside", "mean_boost"])]
    + ["seconds_remaining", "score_diff"]
)


def load_replay(meta_path: Path):
    m = json.loads(meta_path.read_text(encoding="utf-8"))
    f = pl.read_parquet(meta_path.with_name(m["replay"] + ".parquet"))
    return m, f


def labels_and_score(m: dict, n: int, team: int, horizon: int):
    """y = 1 si `team` marque le prochain but dans les `horizon` s ; diff de score courante."""
    goals = sorted(m["goals"], key=lambda g: g["i"])
    gi = np.array([g["i"] for g in goals] + [10**9])
    gt = np.array([g["team"] for g in goals] + [-1])
    idx = np.arange(n)
    nxt = np.searchsorted(gi, idx, side="left")
    y = ((gi[nxt] - idx) <= horizon * FPS) & (gt[nxt] == team)
    sign = np.where(gt[:-1] == team, 1, -1)
    cum = np.concatenate([[0], np.cumsum(sign)]) if len(goals) else np.zeros(1)
    prev = np.searchsorted(gi[:-1], idx, side="right") if len(goals) else np.zeros(n, int)
    return y.astype(np.int8), cum[prev].astype(np.float32)


def build_dataset(source: str, horizon: int, step: int = 2):
    X, Y, G = [], [], []
    for mp in sorted((FRAMES / source).glob("*.meta.json")):
        m, f = load_replay(mp)
        if len(m["goals"]) != m["n_header_goals"]:
            continue  # buts mal détectés : on écarte le replay
        play = f["phase"].to_numpy() == 1
        keep = np.where(play)[0][::step]
        for team in (0, 1):
            y, sd = labels_and_score(m, f.height, team, horizon)
            X.append(features(f, team, sd)[keep]); Y.append(y[keep]); G += [m["replay"]] * len(keep)
    return np.vstack(X), np.concatenate(Y), np.array(G)


# --------------------------------------------------------------------------- entraînement
def train(horizon: int) -> None:
    import lightgbm as lgb
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    X, y, groups = build_dataset("rlcs", horizon)
    reps = np.unique(groups)
    rng = np.random.default_rng(0)
    test_reps = set(rng.choice(reps, size=max(1, len(reps) // 5), replace=False))
    te = np.isin(groups, list(test_reps))
    print(f"{len(reps)} matchs RLCS, {len(y):,} situations (×2 équipes), taux de but à {horizon}s : {y.mean():.3%}")
    print(f"apprentissage {(~te).sum():,} / test {te.sum():,} (matchs séparés)")

    params = dict(objective="binary", learning_rate=0.05, num_leaves=63, min_data_in_leaf=200,
                  feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1)
    dtr = lgb.Dataset(X[~te], y[~te], feature_name=FEATURE_NAMES)
    dte = lgb.Dataset(X[te], y[te], reference=dtr)
    booster = lgb.train(params, dtr, num_boost_round=2000, valid_sets=[dte],
                        callbacks=[lgb.early_stopping(50, verbose=False)])
    p = booster.predict(X[te], num_iteration=booster.best_iteration)
    base = np.full_like(p, y[~te].mean())
    report = {
        "horizon_s": horizon, "n_matches": int(len(reps)), "n_test_matches": len(test_reps),
        "n_rows": int(len(y)), "goal_rate": float(y.mean()), "best_iteration": int(booster.best_iteration),
        "auc": float(roc_auc_score(y[te], p)),
        "logloss": float(log_loss(y[te], p)), "logloss_base": float(log_loss(y[te], base)),
        "brier": float(brier_score_loss(y[te], p)), "brier_base": float(brier_score_loss(y[te], base)),
    }
    # Calibration : prédit vs observé par tranche
    bins = [0, .01, .02, .05, .1, .2, .3, .5, .7, 1.0]
    cal = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        mk = (p >= lo) & (p < hi)
        if mk.sum() >= 50:
            cal.append({"tranche": f"{lo:.0%}–{hi:.0%}", "n": int(mk.sum()),
                        "predit": float(p[mk].mean()), "observe": float(y[te][mk].mean())})
    report["calibration"] = cal
    imp = booster.feature_importance("gain")
    report["top_features"] = [FEATURE_NAMES[i] for i in np.argsort(-imp)[:15]]

    # Modèle final sur tous les matchs, même nombre d'itérations
    final = lgb.train(params, lgb.Dataset(X, y, feature_name=FEATURE_NAMES),
                      num_boost_round=booster.best_iteration)
    MODELS.mkdir(parents=True, exist_ok=True)
    final.save_model(str(MODELS / f"value_h{horizon}.txt"))
    (MODELS / f"value_h{horizon}_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False),
                                                          encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "calibration"}, indent=1, ensure_ascii=False))
    print("calibration (prédit → observé) :")
    for c in cal:
        print(f"  {c['tranche']:>8} n={c['n']:>7,}  {c['predit']:.3f} → {c['observe']:.3f}")


# --------------------------------------------------------------------------- valeur des touches
def value_series(booster, m: dict, f: pl.DataFrame, horizon: int) -> dict[int, np.ndarray]:
    """V_T pour chaque image et chaque équipe (+1/−1 forcés dans les phases « but »)."""
    p = {}
    for team in (0, 1):
        _, sd = labels_and_score(m, f.height, team, horizon)
        p[team] = booster.predict(features(f, team, sd))
    v = {0: p[0] - p[1], 1: p[1] - p[0]}
    phase = f["phase"].to_numpy()
    goals = sorted(m["goals"], key=lambda g: g["i"])
    for g in goals:  # pendant la célébration : résultat acquis
        end = g["i"]
        while end < len(phase) and (phase[end] != 0):
            end += 1
        for team in (0, 1):
            v[team][g["i"]:end] = 1.0 if g["team"] == team else -1.0
    return v


# Priorité des actions quand un joueur a plusieurs touches sur la même image (contrôle puis tir à moins de 0,1 s)
ACTION_RANK = {"shot": 0, "save": 1, "pass": 2, "boom": 3, "clear": 4}  # action absente (contrôle…) : en dernier
GOAL_LINK_S = 4.0  # un but sans autre touche dans les 4 s suivant une touche lui est rattaché


def merge_same_frame(t: pl.DataFrame) -> pl.DataFrame:
    """Une seule ligne par joueur et par image (audit F3) : les événements de subtr-actor à moins de 0,1 s
    tombent sur la même image à 10 i/s et seraient valorisés deux fois avec la même fenêtre. On garde l'action
    la plus forte et la somme des changements de vitesse de la balle. Colonne `share` : 1 / nombre de
    coéquipiers qui touchent sur la même image (le crédit est partagé entre eux)."""
    if t.is_empty():
        return t.with_columns(pl.lit(1.0).alias("share"))
    rank = pl.col("action").replace_strict(ACTION_RANK, default=9, return_dtype=pl.Int64)
    t = (t.with_columns(rank.alias("_rank"))
         .sort("i", "slot", "_rank")
         .group_by("i", "slot", maintain_order=True)
         .agg(pl.all().exclude("ball_speed_change").first(), pl.col("ball_speed_change").sum())
         .drop("_rank"))
    n_mates = pl.col("slot").filter(pl.col("slot") >= 0).n_unique().over("i", "team")
    return t.with_columns((1.0 / pl.max_horizontal(n_mates, pl.lit(1))).alias("share")).sort("i", "slot")


def touch_window(i: int, nxt: int, n: int, goals: list[dict], team: int) -> int:
    """Image où l'on mesure la conséquence d'une touche : juste avant la touche suivante, au plus 1 s après.
    Si le prochain événement est un but de l'équipe du toucheur (aucune touche entre les deux, au plus GOAL_LINK_S),
    on va jusqu'au but (audit F1) : sans ça, un tir de loin qui met plus d'1 s à rentrer n'est crédité à personne.
    Pas pour un but encaissé : la dernière touche d'un défenseur sur un ballon qui rentrait déjà serait punie du
    but entier (voir audit F2 et ballsim)."""
    after = int(min(i + FPS, max(nxt - 1, i + 1), n - 1))
    g = next((g for g in goals if g["i"] > i), None)
    if g is not None and g["team"] == team and g["i"] <= nxt and g["i"] - i <= GOAL_LINK_S * FPS and g["i"] > after:
        after = min(int(g["i"]), n - 1)
    return after


GOING_IN_S = 3.0  # horizon de la simulation « sans la touche »


def going_in(f: pl.DataFrame, starts: np.ndarray) -> np.ndarray:
    """Pour chaque image de départ : but où la balle libre serait entrée dans les GOING_IN_S secondes
    (0 : but en y > 0, marqué par l'équipe 0 ; 1 : but en y < 0 ; −1 : aucun). Voir rlpi.ballsim (validé sur
    replays : 96 % des buts vus, 0,4 % de faux buts). Rotation de la balle prise en compte si les images l'ont."""
    from rlpi import ballsim

    if len(starts) == 0:
        return np.zeros(0, np.int8)
    col = lambda c: f[c].to_numpy()[starts]  # noqa: E731
    x = np.column_stack([col("ball_x"), col("ball_y"), col("ball_z")])
    v = np.column_stack([col("ball_vx"), col("ball_vy"), col("ball_vz")])
    w = np.column_stack([col("ball_wx"), col("ball_wy"), col("ball_wz")]) if "ball_wx" in f.columns else None
    return ballsim.simulate(x, v, w, GOING_IN_S)[0]


def touches(source: str, horizon: int) -> None:
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(MODELS / f"value_h{horizon}.txt"))
    rows, curves = [], []
    for mp in sorted((FRAMES / source).glob("*.meta.json")):
        m, f = load_replay(mp)
        t = merge_same_frame(pl.read_parquet(mp.with_name(m["replay"] + ".touches.parquet")).sort("i"))
        v = value_series(booster, m, f, horizon)
        phase = f["phase"].to_numpy()
        n = f.height
        ti = t["i"].to_numpy()
        goals = sorted(m["goals"], key=lambda g: g["i"])
        players = {p["slot"]: p for p in m["players"]}
        # Audit F2 : la balle, laissée libre juste avant la touche, entrait-elle dans le but du toucheur ?
        touch_frames = set(ti.tolist())
        cand = np.array([i - 1 for i in ti if 1 <= i < n and (i - 1) not in touch_frames], dtype=np.int64)
        free_goal = dict(zip((cand + 1).tolist(), going_in(f, cand).tolist()))
        for j, r in enumerate(t.iter_rows(named=True)):
            i, slot, team = r["i"], r["slot"], r["team"]
            if slot < 0 or i < 2 or i >= n - 1 or phase[i - 2] != 1:
                continue
            nxt = next((ti[k] for k in range(j + 1, len(ti)) if ti[k] > i), n - 1)
            after = touch_window(i, int(nxt), n, goals, team)
            before = i - 2
            sh = r["share"]
            # balle qui rentrait dans son propre but sans la touche : la touche n'est pas responsable du but
            g_free = free_goal.get(i, -1)
            in_own = g_free == 1 - team
            clip = (lambda d: max(d, 0.0)) if in_own else (lambda d: d)
            rows.append({
                "replay": m["replay"], "date": m["date"], "i": i, "t_s": round(i / FPS, 1),
                "clock": float(f["seconds_remaining"][i]), "match_type": m.get("match_type"),
                "player_id": players[slot]["id"], "player_name": players[slot]["name"], "team": team,
                "action": r["action"], "kind": r["kind"], "height": r["height"], "role": r["role"],
                "v_before": float(v[team][before]), "v_after": float(v[team][after]),
                "dv": clip(sh * float(v[team][after] - v[team][before])),
                # conséquences à 2 s et 3 s, quelle que soit la touche suivante
                "dv_2s": clip(sh * float(v[team][min(i + 2 * FPS, n - 1)] - v[team][before])),
                "dv_3s": clip(sh * float(v[team][min(i + 3 * FPS, n - 1)] - v[team][before])),
                "share": sh, "after_i": after,
                "going_in_own": in_own, "going_in_opp": g_free == team,
                "ball_x": float(f["ball_x"][i]) * (1 if team == 0 else -1),
                "ball_y": float(f["ball_y"][i]) * (1 if team == 0 else -1),
            })
        play = phase == 1
        curves.append({"replay": m["replay"], "v_team0": v[0][::5].round(3).tolist(),
                       "play": play[::5].astype(int).tolist(), "goals": m["goals"]})
    out = pl.DataFrame(rows)
    out.write_parquet(FEATURES / f"touch_values_{source}.parquet")
    (FEATURES / f"value_curves_{source}.json").write_text(json.dumps(curves), encoding="utf-8")
    print(f"→ {out.height:,} touches valorisées ({source}), ΔV moyen {out['dv'].mean():+.4f}")


def goal_values(source: str, horizon: int = 5) -> None:
    """Valeur du modèle 0,2 s avant que la balle franchisse la ligne, pour chaque but (vue de l'équipe 0).
    Sert à créditer une touche de but comme un tir (« xV ») au lieu du +1 / −1 forcé."""
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(MODELS / f"value_h{horizon}.txt"))
    rows = []
    for mp in sorted((FRAMES / source).glob("*.meta.json")):
        m, f = load_replay(mp)
        if not m["goals"]:
            continue
        ph = f["phase"].to_numpy()
        idx = []
        for g in m["goals"]:
            j = g["i"] - 1
            while j > 0 and ph[j] != 1:
                j -= 1
            idx.append(max(j - 2, 0))
        p = {t: booster.predict(features(f, t, labels_and_score(m, f.height, t, horizon)[1])[idx]) for t in (0, 1)}
        rows += [{"replay": m["replay"], "goal_i": g["i"], "scorer_team": g["team"], "v_team0": float(p[0][k] - p[1][k])}
                 for k, g in enumerate(m["goals"])]
    pl.DataFrame(rows).write_parquet(FEATURES / f"goal_xv_{source}.parquet")
    print(f"→ goal_xv_{source}.parquet : {len(rows)} buts")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("train"); s.add_argument("--horizon", type=int, default=10)
    s = sub.add_parser("touches"); s.add_argument("--source", required=True); s.add_argument("--horizon", type=int, default=10)
    s = sub.add_parser("goals"); s.add_argument("--source", required=True); s.add_argument("--horizon", type=int, default=5)
    a = ap.parse_args()
    if a.cmd == "train":
        train(a.horizon)
    elif a.cmd == "goals":
        goal_values(a.source, a.horizon)
    else:
        touches(a.source, a.horizon)


if __name__ == "__main__":
    main()
