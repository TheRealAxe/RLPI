"""Meilleur jeu calculé (prototype) : pour une touche, quelle DIRECTION donner à la balle ?

Plus fin que les 5 actions de `decisions` : on apprend sur les touches RLCS
  - P(direction | situation) : 16 secteurs de 22,5° + « contrôle » → ce qui est faisable ici ;
  - Q(situation, direction) : gain de valeur ΔV (même cible que `decisions`) pour une balle envoyée
    dans cette direction (la force n'est pas modélisée : elle dépend trop de l'issue).
Meilleur jeu = argmax de Q parmi les directions que les pros jouent au moins 10 % du temps (+ celle jouée).
Les positions idéales des coéquipiers viennent du modèle de placement (`placement_<source>.parquet`).

Tout est dans le repère du toucheur (il attaque vers +y). Angle 90° = droit vers le but adverse.

Usage :
    python -m rlpi.bestplay extract --source rlcs     # long : toutes les touches RLCS
    python -m rlpi.bestplay extract --source perso
    python -m rlpi.bestplay train
    python -m rlpi.bestplay export --player <pseudo ou identifiant> --since 2026-11-14 [--rank 0]
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np
import polars as pl

import os

from rlpi.config import FEATURES, FRAMES, MODELS, SOURCE
from rlpi.decisions import ACTION_FR, TARGET, TOUCHER
from rlpi.value import FEATURE_NAMES, features, labels_and_score, load_replay

N_BINS = 16
CONTROL = N_BINS
MIN_P = 0.10          # comme MIN_POLICY dans decisions : une option que les pros jouent au moins 1 fois sur 10
MIN_P_RARE = 0.03     # entre les deux : possible mais rare (affiché hachuré, jamais recommandé)
APPROACH_MAX = 18     # approche montrée jusqu à 1,8 s avant la touche
SPEEDS = [2000.0]  # vitesse neutre pour la balle simulée de la page
SPEED_FR = {2000.0: ""}
BEFORE, AFTER = 40, 30          # 4 s avant la touche (l'approche), 3 s après


def exit_dir(f: pl.DataFrame, i: int, slot: int, s: float, nxt: int):
    """Direction de la balle JUSTE après la touche (image suivante) : lue plus tard, elle serait déjà déviée par un
    contre et la mesure dépendrait de l'issue. Si un autre joueur touche la balle dès l'image suivante (tir arrêté,
    duel), on prend l'image de la touche si la balle y a déjà changé de vitesse ; sinon la direction est
    impossible à mesurer → None. « Contrôle » reste défini à 0,3 s comme dans `decisions`."""
    if nxt > i + 1:
        j1 = int(min(i + 1, f.height - 1))
    else:
        dvx = f["ball_vx"][i] - f["ball_vx"][i - 1]
        dvy = f["ball_vy"][i] - f["ball_vy"][i - 1]
        if math.hypot(dvx, dvy) < 300:
            return None
        j1 = i
    vx, vy = s * f["ball_vx"][j1], s * f["ball_vy"][j1]
    j = int(min(i + 3, max(nxt - 1, i + 1), f.height - 1))
    bx, by, bz = s * f["ball_x"][j], s * f["ball_y"][j], f["ball_z"][j]
    px, py, pz = s * f[f"p{slot}_x"][j], s * f[f"p{slot}_y"][j], f[f"p{slot}_z"][j]
    sp3 = math.sqrt(f["ball_vx"][j] ** 2 + f["ball_vy"][j] ** 2 + f["ball_vz"][j] ** 2)
    near = math.sqrt((bx - px) ** 2 + (by - py) ** 2 + (bz - pz) ** 2) < 350
    return math.atan2(vy, vx), math.hypot(vx, vy), bool(near and sp3 < 1800)


def sector_density(pol16: np.ndarray, angles: np.ndarray) -> np.ndarray:
    """Part des pros à un angle donné, interpolée linéairement entre les centres des 16 secteurs."""
    w = 2 * np.pi / N_BINS
    pos = np.mod(angles, 2 * np.pi) / w - 0.5              # 0 = centre du secteur 0
    lo = np.floor(pos).astype(int) % N_BINS
    hi = (lo + 1) % N_BINS
    f = pos - np.floor(pos)
    return pol16[:, lo] * (1 - f) + pol16[:, hi] * f


def angle_bin(a: np.ndarray) -> np.ndarray:
    return (np.floor((np.mod(a, 2 * np.pi)) / (2 * np.pi / N_BINS))).astype(int) % N_BINS


def extract(source: str) -> None:
    tv_all = pl.read_parquet(FEATURES / f"touch_values_{source}.parquet")      # arrêts compris : touche suivante
    tv = tv_all.filter(pl.col("action").fill_null("") != "save")
    X, rows, n_skip = [], [], 0
    for n, ((replay,), grp) in enumerate(tv.group_by("replay")):
        try:
            m, f = load_replay(FRAMES / source / f"{replay}.meta.json")
        except FileNotFoundError:
            continue
        slot_of = {p["id"]: p["slot"] for p in m["players"]}
        feats = {}
        for team in (0, 1):
            _, sd = labels_and_score(m, f.height, team, 5)
            feats[team] = features(f, team, sd)
        tis = sorted(tv_all.filter(pl.col("replay") == replay)["i"].to_list())
        for r in grp.iter_rows(named=True):
            if r["player_id"] not in slot_of or r["i"] < 2:
                continue
            team, slot = r["team"], slot_of[r["player_id"]]
            s = 1.0 if team == 0 else -1.0
            nxt = next((t for t in tis if t > r["i"]), f.height - 1)
            ed = exit_dir(f, r["i"], slot, s, nxt)
            if ed is None:
                n_skip += 1
                continue
            ang, sp, ctrl = ed
            i = r["i"] - 2
            me = [s * f[f"p{slot}_x"][i], s * f[f"p{slot}_y"][i], f[f"p{slot}_z"][i], s * f[f"p{slot}_vx"][i],
                  s * f[f"p{slot}_vy"][i], f[f"p{slot}_vz"][i], f[f"p{slot}_boost"][i]]
            X.append(np.concatenate([feats[team][i], np.array(me, dtype=np.float32)]))
            rows.append({"replay": replay, "i": r["i"], "player_id": r["player_id"], "player_name": r["player_name"],
                         "team": team, "angle": ang, "speed": sp, "control": ctrl, "dv": r[TARGET]})
        if n % 200 == 0:
            print(f"  {n} matchs…", flush=True)
    np.save(FEATURES / f"bestplay_X_{source}.npy", np.vstack(X))
    pl.DataFrame(rows).write_parquet(FEATURES / f"bestplay_rows_{source}.parquet")
    print(f"→ bestplay_{{X,rows}}_{source} : {len(rows):,} touches ({n_skip:,} contrées aussitôt, direction non mesurable)")


_FI = {n: k for k, n in enumerate(FEATURE_NAMES)}


def lane_features(X: np.ndarray, ang: np.ndarray) -> np.ndarray:
    """Pour une direction donnée : couloir libre ? cadré ? (calculé à partir des positions de la situation)."""
    bx, by = X[:, _FI["ball_x"]], X[:, _FI["ball_y"]]
    c, s = np.cos(ang), np.sin(ang)
    perp_min = np.full(len(X), 5000.0, np.float32)
    along_min = np.full(len(X), 5000.0, np.float32)
    for side in ("opp", "own"):
        best = np.full(len(X), 5000.0, np.float32)
        for r in range(3 if side == "opp" else 2):
            r_ = r if side == "opp" else r + 1  # own0 = souvent le toucheur lui-même
            dx = X[:, _FI[f"{side}{r_}_x"]] - bx
            dy = X[:, _FI[f"{side}{r_}_y"]] - by
            along = dx * c + dy * s
            perp = np.abs(-dx * s + dy * c)
            ok = (along > 0) & (along < 3500)
            d = np.where(ok, perp, 5000.0)
            if side == "opp":
                closer = d < perp_min
                along_min = np.where(closer, along, along_min)
                perp_min = np.minimum(perp_min, d)
            else:
                best = np.minimum(best, d)
        if side == "own":
            mate_lane = best
    # cadré : la ligne droite coupe la ligne de but adverse entre les poteaux
    t = np.where(s > 0.05, (5120.0 - by) / np.maximum(s, 0.05), 1e5)
    x_at = bx + c * t
    on_target = ((s > 0.05) & (np.abs(x_at) < 893)).astype(np.float32)
    own_goal = np.where(s < -0.05, (-5120.0 - by) / np.minimum(s, -0.05), 1e5)
    to_own = ((s < -0.05) & (np.abs(bx + c * own_goal) < 893)).astype(np.float32)
    return np.column_stack([perp_min, along_min, mate_lane, on_target, np.clip(x_at, -6000, 6000), to_own]).astype(np.float32)


LANE = ["lane_opp_perp", "lane_opp_along", "lane_mate_perp", "dir_on_target", "dir_x_at_line", "dir_to_own_goal"]


def _q_input(X: np.ndarray, ang: np.ndarray, sp: np.ndarray, ctrl: np.ndarray) -> np.ndarray:
    # La force n'entre pas dans Q : trop liée à l'issue (un tir contré « sort » moins vite).
    return np.hstack([X, np.column_stack([np.cos(ang), np.sin(ang), ctrl]).astype(np.float32), lane_features(X, ang)])


def train() -> None:
    import lightgbm as lgb

    X = np.load(FEATURES / "bestplay_X_rlcs.npy")
    R = pl.read_parquet(FEATURES / "bestplay_rows_rlcs.parquet")
    ang, sp = R["angle"].to_numpy(), R["speed"].to_numpy()
    ctrl = R["control"].to_numpy().astype(np.float32)
    ycls = np.where(ctrl > 0, CONTROL, angle_bin(ang))
    dv = R["dv"].to_numpy()
    reps = R["replay"].to_numpy()
    rng = np.random.default_rng(0)
    test_reps = set(rng.choice(np.unique(reps), size=len(np.unique(reps)) // 5, replace=False))
    te = np.array([r in test_reps for r in reps]); tr = ~te
    names = FEATURE_NAMES + TOUCHER
    qn = names + ["dir_cos", "dir_sin", "control"] + LANE
    pp = dict(objective="multiclass", num_class=N_BINS + 1, learning_rate=0.05, num_leaves=31,
              min_data_in_leaf=100, feature_fraction=0.8, verbose=-1)
    qp = dict(objective="regression", learning_rate=0.03, num_leaves=63, min_data_in_leaf=200,
              feature_fraction=0.8, lambda_l2=5.0, verbose=-1)
    pm = lgb.train(pp, lgb.Dataset(X[tr], ycls[tr], feature_name=names), 2000,
                   valid_sets=[lgb.Dataset(X[te], ycls[te])], callbacks=[lgb.early_stopping(50, verbose=False)])
    Q = _q_input(X, ang, sp, ctrl)
    qm = lgb.train(qp, lgb.Dataset(Q[tr], dv[tr], feature_name=qn), 4000,
                   valid_sets=[lgb.Dataset(Q[te], dv[te])], callbacks=[lgb.early_stopping(100, verbose=False)])
    pred = qm.predict(Q[te], num_iteration=qm.best_iteration)
    r2 = 1 - np.mean((dv[te] - pred) ** 2) / np.var(dv[te])
    pt = pm.predict(X[te], num_iteration=pm.best_iteration)
    acc = np.mean(pt.argmax(1) == ycls[te])
    # Le secteur réellement joué est-il « faisable » (≥ 3 %) selon le modèle ? (doit être ~toujours vrai)
    cover = np.mean(pt[np.arange(te.sum()), ycls[te]] >= MIN_P)
    rep = {"n": int(len(X)), "r2_q_holdout": float(r2), "policy_top1": float(acc), "played_feasible": float(cover),
           "p_rounds": pm.best_iteration, "q_rounds": qm.best_iteration}
    print(json.dumps(rep, indent=1))
    pm = lgb.train(pp, lgb.Dataset(X, ycls, feature_name=names), pm.best_iteration)
    qm = lgb.train(qp, lgb.Dataset(Q, dv, feature_name=qn), qm.best_iteration)
    pm.save_model(str(MODELS / "bestplay_policy.txt")); qm.save_model(str(MODELS / "bestplay_q.txt"))
    (MODELS / "bestplay_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print("→ bestplay_{policy,q}.txt")


# --------------------------------------------------------------------------- export pour la page
def formation_block(f: pl.DataFrame, m: dict, i: int, slot: int, team: int) -> dict:
    """Formation idéale à trois (modèle `formation`) sur la fenêtre : rôle et position cible de chacun de nos
    joueurs, à qui revenait la balle avant la touche, et valeur de l'équipe réelle vs « les trois placés
    comme une formation pro » (adversaires et balle inchangés)."""
    import lightgbm as lgb
    from rlpi.formation import ROLE_FR, assign, own_positions, predict

    s = 1.0 if team == 0 else -1.0
    lo, hi = max(0, i - BEFORE), min(f.height - 1, i + AFTER)
    a = {c: f[c].to_numpy().astype(np.float32) for c in f.columns if c != "state"}
    ks = np.arange(lo, hi + 1)
    ks = ks[f["phase"].to_numpy()[ks] == 1]
    slots, P = own_positions(a, m, ks, team)
    R = predict(a, m, ks, team)                      # (3 rôles, n, 2)
    roles = assign(P, R)                             # (3 joueurs, n)
    T = np.stack([R[roles[j], np.arange(len(ks))] for j in range(3)])     # cible de chaque joueur (3, n, 2)
    # à qui revenait la balle : rôle 0 entre −0,6 s et −0,2 s ; « disputée » si les deux mieux placés pour le
    # rôle 0 en sont à moins de 300 uu d'écart (on ne tranche pas arbitrairement)
    near = (ks >= i - 6) & (ks <= i - 2)
    owner, contested = None, []
    if near.any():
        votes = [int(np.sum(roles[j][near] == 0)) for j in range(3)]
        owner = slots[int(np.argmax(votes))]
        d0 = np.array([np.median(np.hypot(*(P[j][near] - R[0][near]).T)) for j in range(3)])
        o = np.argsort(d0)
        if d0[o[1]] - d0[o[0]] < 300:
            contested = [slots[int(o[0])], slots[int(o[1])]]
    me_j = slots.index(slot)
    me_role_touch = int(np.bincount(roles[me_j][near], minlength=3).argmax()) if near.any() else None
    # valeur réelle vs formation (les trois joueurs déplacés, vitesse et orientation cohérentes avec leur chemin)
    vb = lgb.Booster(model_file=str(MODELS / "value_h5.txt"))
    w = f.slice(lo, hi - lo + 1)
    sd = {t: labels_and_score(m, f.height, t, 5)[1][lo:hi + 1] for t in (0, 1)}
    def v_of(frame):
        return vb.predict(features(frame, team, sd[team])) - vb.predict(features(frame, 1 - team, sd[1 - team]))
    v_real = v_of(w)
    rel = ks - lo
    upd = []
    for j, k in enumerate(slots):
        tx, ty = T[j, :, 0], T[j, :, 1]
        vx = np.gradient(tx) * 10 if len(ks) > 1 else np.zeros(len(ks))
        vy = np.gradient(ty) * 10 if len(ks) > 1 else np.zeros(len(ks))
        sc = np.where(np.hypot(vx, vy) > 2300, 2300 / np.maximum(np.hypot(vx, vy), 1), 1.0)
        vx, vy = vx * sc, vy * sc
        bx, by = s * a["ball_x"][ks], s * a["ball_y"][ks]
        yaw = np.where(np.hypot(vx, vy) > 300, np.arctan2(vy, vx), np.arctan2(by - ty, bx - tx))
        cols = {c: w[f"p{k}_{c}"].to_numpy().astype(np.float64).copy() for c in ("x", "y", "vx", "vy", "rz")}
        cols["x"][rel], cols["y"][rel] = s * tx, s * ty
        cols["vx"][rel], cols["vy"][rel] = s * vx, s * vy
        cols["rz"][rel] = yaw + (0.0 if s > 0 else np.pi)
        upd += [pl.Series(f"p{k}_{c}", v.astype(np.float32)) for c, v in cols.items()]
    v_team = v_of(w.with_columns(upd))
    before = rel[ks < i]
    gain = (v_team - v_real)[before] if len(before) else np.zeros(1)
    name_of = {p["slot"]: p["name"] for p in m["players"]}
    rr = lambda x: [round(float(v)) for v in x]  # noqa: E731
    return {
        "frames": [int(v) for v in rel], "role_fr": ROLE_FR,
        "players": [{"slot": int(k), "name": name_of[k], "me": k == slot, "role": [int(v) for v in roles[j]],
                     "x": rr(T[j, :, 0]), "y": rr(T[j, :, 1])} for j, k in enumerate(slots)],
        "owner": name_of.get(owner), "owner_is_me": owner == slot, "me_role_touch": me_role_touch,
        "contested": [name_of[k] for k in contested], "contested_me": slot in contested,
        "value": {"real": [round(float(v), 3) for v in v_real], "team": [round(float(v), 3) for v in v_team]},
        "gain_max": float(gain.max()), "gain_max_i": int(before[int(gain.argmax())]) if len(before) else 0,
        "gain_mean": float(gain.mean()),
    }


def approach_block(f: pl.DataFrame, m: dict, i: int, slot: int, team: int) -> dict:
    """Approche idéale du toucheur (modèle `approach`) et coût du placement : valeur de l'équipe image par image,
    réelle et « si tu étais à la position idéale » (le reste de la scène inchangé)."""
    import lightgbm as lgb
    from rlpi.approach import TAUS, _arrays, situation

    s = 1.0 if team == 0 else -1.0
    lo, hi = max(0, i - BEFORE), min(f.height - 1, i + AFTER)
    a = _arrays(f)
    taus = np.arange(TAUS.min(), APPROACH_MAX + 1)   # au-delà de 1,8 s, le modèle est trop imprécis (écart médian > 900 uu)
    ks = i - taus
    ok = (ks >= lo) & (f["phase"].to_numpy()[np.clip(ks, 0, None)] == 1)
    ks, taus = ks[ok], taus[ok].astype(np.float32)
    Xa = situation(a, m, ks, slot, team, taus)
    dx = lgb.Booster(model_file=str(MODELS / "approach_dx.txt")).predict(Xa)
    dy = lgb.Booster(model_file=str(MODELS / "approach_dy.txt")).predict(Xa)
    ix = s * a["ball_x"][ks] + dx            # repère du toucheur
    iy = s * a["ball_y"][ks] + dy
    # valeur réelle et contrefactuelle (modèle de valeur à 5 s), sur la fenêtre
    vb = lgb.Booster(model_file=str(MODELS / "value_h5.txt"))
    w = f.slice(lo, hi - lo + 1)
    sd = {t: labels_and_score(m, f.height, t, 5)[1][lo:hi + 1] for t in (0, 1)}
    def v_of(frame):
        return vb.predict(features(frame, team, sd[team])) - vb.predict(features(frame, 1 - team, sd[1 - team]))
    v_real = v_of(w)
    rel = ks - lo
    # Position idéale + vitesse et orientation COHÉRENTES : la vitesse suit le chemin idéal (10 images/s) et la voiture
    # regarde dans le sens du déplacement (ou vers la balle si elle est presque arrêtée). Sinon on placerait une
    # voiture devant la balle mais qui file vers son propre but.
    o = np.argsort(ks)
    kso, ixo, iyo = ks[o], ix[o], iy[o]
    ivx = np.gradient(ixo) * 10 if len(kso) > 1 else np.zeros(len(kso))
    ivy = np.gradient(iyo) * 10 if len(kso) > 1 else np.zeros(len(kso))
    sp = np.hypot(ivx, ivy)
    scale = np.where(sp > 2300, 2300 / np.maximum(sp, 1), 1.0)      # vitesse max d'une voiture
    ivx, ivy = ivx * scale, ivy * scale
    bxo, byo = s * a["ball_x"][kso], s * a["ball_y"][kso]
    iyaw = np.where(np.hypot(ivx, ivy) > 300, np.arctan2(ivy, ivx), np.arctan2(byo - iyo, bxo - ixo))
    relo = kso - lo
    cols = {c: w[f"p{slot}_{c}"].to_numpy().astype(np.float64).copy() for c in ("x", "y", "vx", "vy", "rz")}
    cols["x"][relo], cols["y"][relo] = s * ixo, s * iyo                  # retour au repère du monde
    cols["vx"][relo], cols["vy"][relo] = s * ivx, s * ivy
    cols["rz"][relo] = iyaw + (0.0 if s > 0 else np.pi)
    w2 = w.with_columns([pl.Series(f"p{slot}_{c}", v.astype(np.float32)) for c, v in cols.items()])
    v_ideal = v_of(w2)
    order = np.argsort(rel)
    r = lambda x: [round(float(v), 3) for v in x]  # noqa: E731
    gain = (v_ideal - v_real)[rel[order]]
    return {"ideal": {"i": [int(v) for v in rel[order]], "x": [round(float(v)) for v in ix[order]],
                      "y": [round(float(v)) for v in iy[order]]},
            "value": {"real": r(v_real), "ideal": r(v_ideal), "approach_i": [int(v) for v in rel[order]]},
            "gain_max": float(gain.max()) if len(gain) else 0.0,
            "gain_max_i": int(rel[order][int(gain.argmax())]) if len(gain) else 0,
            "gain_mean": float(gain.mean()) if len(gain) else 0.0}


def _track(f, m, i, slot, team, place: pl.DataFrame) -> dict:
    s = 1.0 if team == 0 else -1.0
    lo, hi = max(0, i - BEFORE), min(f.height - 1, i + AFTER)
    w = f.slice(lo, hi - lo + 1)
    r = lambda a: [round(float(v)) for v in a]  # noqa: E731
    out = {"ball": {"x": r(s * w["ball_x"]), "y": r(s * w["ball_y"]), "z": r(w["ball_z"])}, "t0": i - lo, "cars": []}
    mates = 0
    for p in m["players"]:
        k = p["slot"]
        yaw = w[f"p{k}_rz"].to_numpy().astype(float) + (0 if s > 0 else np.pi)
        kind = "me" if k == slot else ("mate1" if mates == 0 else "mate2") if p["team"] == team else "opp"
        if p["team"] == team and k != slot:
            mates += 1
        car = {"name": p["name"], "kind": kind, "x": r(s * w[f"p{k}_x"]), "y": r(s * w[f"p{k}_y"]),
               "z": r(w[f"p{k}_z"]), "yaw": [round(float(v), 2) for v in yaw]}
        # position idéale (modèle de placement, une valeur toutes les 0,5 s) pour mes coéquipiers et moi
        if p["team"] == team:
            pk = place.filter((pl.col("slot") == k) & (pl.col("i") >= lo - 5) & (pl.col("i") <= hi + 5)).sort("i")
            if pk.height:
                car["ideal"] = {"i": [int(v - lo) for v in pk["i"]], "x": r(pk["px"]), "y": r(pk["py"]),
                                "rank": pk["rank"].to_list()}
        out["cars"].append(car)
    return out


def export(player: str, since: str, rank: int, out: str, at: str = "", dates: list[str] | None = None) -> dict:
    import lightgbm as lgb

    X = np.load(FEATURES / f"bestplay_X_{SOURCE}.npy")
    R = pl.read_parquet(FEATURES / f"bestplay_rows_{SOURCE}.parquet").with_row_index("k")
    dec = pl.read_parquet(FEATURES / f"touch_decisions_{SOURCE}.parquet").select("replay", "i", "player_id", "date", "t_s")
    R = R.join(dec, on=["replay", "i", "player_id"], how="inner").filter(
        ((pl.col("player_name") == player) | (pl.col("player_id") == player)) & (pl.col("date").is_in(dates) if dates else pl.col("date") >= since))
    pm = lgb.Booster(model_file=str(MODELS / "bestplay_policy.txt"))
    qm = lgb.Booster(model_file=str(MODELS / "bestplay_q.txt"))

    # Recommandation par GRANDE DIRECTION (16 secteurs de 22,5°), comme un coach : chercher l'angle exact au
    # maximum de Q parmi les angles « faisables » tombe toujours à la frontière de la zone faisable, juste à côté
    # d'options rares mais rentables (ex. tirer en étant dos au but). Un secteur est noté sur sa valeur moyenne.
    step = 2.5
    angles = np.deg2rad(np.arange(0, 360, step) + step / 2)        # 9 angles par secteur
    per = int(round(22.5 / step))
    Xs = X[R["k"].to_numpy()]
    pol = pm.predict(Xs)
    n, na = len(Xs), len(angles)
    rep_X = np.repeat(Xs, na, axis=0)
    A = np.tile(angles, n)
    q_dir = qm.predict(_q_input(rep_X, A, np.zeros(len(A)), np.zeros(len(A), np.float32))).reshape(n, na)
    q_sec = q_dir.reshape(n, N_BINS, per).mean(2)                    # (n, 16)
    q_ctrl = qm.predict(_q_input(Xs, np.full(n, np.pi / 2), np.full(n, 300.0), np.ones(n, np.float32)))
    ctrl_played = R["control"].to_numpy()
    sec_played = angle_bin(R["angle"].to_numpy())
    p_sec = pol[:, :N_BINS]
    feas = p_sec >= MIN_P
    feas[np.arange(n), sec_played] |= ~ctrl_played                 # le secteur joué est toujours comparé
    ctrl_ok = (pol[:, CONTROL] >= MIN_P) | ctrl_played
    q_played = np.where(ctrl_played, q_ctrl, q_sec[np.arange(n), sec_played])
    qbest_sec = np.where(feas, q_sec, -np.inf)
    best_q = np.maximum(qbest_sec.max(1), np.where(ctrl_ok, q_ctrl, -np.inf))
    regret = best_q - q_played
    order = np.argsort(-regret)
    t = order[rank]
    if at:  # moment précis : "AAAA-MM-JJ HH-MM-SS@t_s"
        date, ts = at.split("@")
        hit = np.where((R["date"].to_numpy() == date) & (np.abs(R["t_s"].to_numpy() - float(ts)) < 0.05))[0]
        t = int(hit[0])
    row = R.row(int(t), named=True)
    m, f = load_replay(FRAMES / SOURCE / f"{row['replay']}.meta.json")
    slot = next(p["slot"] for p in m["players"] if p["id"] == row["player_id"])
    team = row["team"]
    place = pl.read_parquet(FEATURES / f"placement_{SOURCE}.parquet").filter(
        (pl.col("replay") == row["replay"]) & (pl.col("team") == team))

    k_best = int(np.argmax(qbest_sec[t]))
    best_is_ctrl = bool(ctrl_ok[t] and q_ctrl[t] > qbest_sec[t, k_best])
    sectors = [{"k": k, "deg0": k * 22.5, "deg1": (k + 1) * 22.5, "q": float(q_sec[t, k]), "p": float(p_sec[t, k]),
                "feasible": bool(feas[t, k]), "rare": bool(not feas[t, k] and p_sec[t, k] >= MIN_P_RARE)}
               for k in range(N_BINS)]
    data = {
        "player": player, "date": row["date"], "t_s": row["t_s"],
        "played": {"deg": float(np.rad2deg(row["angle"])), "sector": int(sec_played[t]), "control": row["control"],
                   "q": float(q_played[t]), "p": float(p_sec[t, sec_played[t]]), "dv_real": row["dv"]},
        "best": {"control": best_is_ctrl, "sector": k_best, "deg": k_best * 22.5 + 11.25,
                 "q": float(best_q[t]), "p": float(pol[t, CONTROL] if best_is_ctrl else p_sec[t, k_best]),
                 "speed": 2000.0},
        "control": {"q": float(q_ctrl[t]), "p": float(pol[t, CONTROL])},
        "regret": float(regret[t]), "sectors": sectors,
        "thresholds": {"feasible": MIN_P, "rare": MIN_P_RARE},
        "track": _track(f, m, row["i"], slot, team, place),
        "formation": formation_block(f, m, row["i"], slot, team),
        "formation_report": json.loads((MODELS / "formation_report.json").read_text(encoding="utf-8")),
        "report": json.loads((MODELS / "bestplay_report.json").read_text(encoding="utf-8")),
        "candidates": [{"rank": int(k), "t_s": float(R["t_s"][int(order[k])]), "date": R["date"][int(order[k])],
                        "regret": float(regret[order[k]])} for k in range(min(8, n))],
    }
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("window.BESTPLAY = " + json.dumps(data, ensure_ascii=False) + ";\n")
    print(f"{row['date']} t={row['t_s']:.1f}s  écart={regret[t]:+.3f}  joué secteur {sec_played[t] * 22.5:.0f}° "
          f"(Q {q_played[t]:+.2f}) → meilleur {'contrôle' if best_is_ctrl else f'secteur {k_best * 22.5:.0f}°'} "
          f"(Q {best_q[t]:+.2f})")
    return data


def worst(player: str, n_games: int, k: int, outdir: str = "reports") -> None:
    """Les k pires actions des n dernières parties du joueur → bestplay_data_0..k-1.js + bestplay_index.js.
    Pire = plus grand écart entre la touche jouée et le meilleur jeu réaliste. Écartés : les duels (adversaire
    à < 250 uu de la balle : la direction dépend aussi de lui) et les touches à < 3 s d'une action déjà retenue
    dans la même partie (une seule touche par action)."""
    import os

    dec = pl.read_parquet(FEATURES / f"touch_decisions_{SOURCE}.parquet").filter((pl.col("player_name") == player) | (pl.col("player_id") == player))
    dates = sorted(dec["date"].unique().to_list(), reverse=True)[:n_games]
    tmp = os.path.join(outdir, "_bestplay_tmp.js")
    kept, rank, n_dup, n_duel = [], 0, 0, 0
    while len(kept) < k and rank < 200:
        try:
            d = export(player, "", rank, tmp, dates=dates)
        except IndexError:
            break
        rank += 1
        tr = d["track"]; t0 = tr["t0"]
        b = (tr["ball"]["x"][t0], tr["ball"]["y"][t0], tr["ball"]["z"][t0])
        opp = min(math.dist((c["x"][t0], c["y"][t0], c["z"][t0]), b) for c in tr["cars"] if c["kind"] == "opp")
        if opp < 250:
            n_duel += 1
            continue
        if any(e["date"] == d["date"] and abs(e["t_s"] - d["t_s"]) < 3 for e in kept):
            n_dup += 1
            continue
        os.replace(tmp, os.path.join(outdir, f"bestplay_data_{len(kept)}.js"))
        nature = ("touche manquée ?" if (not d["played"]["control"] and d["played"]["p"] < 0.05)
                  else "balle d'un coéquipier" if (d["formation"]["owner"] and not d["formation"]["owner_is_me"]
                                                   and not d["formation"]["contested"]) else "choix de direction")
        kept.append({"date": d["date"], "t_s": d["t_s"], "regret": d["regret"], "nature": nature})
    if os.path.exists(tmp):
        os.remove(tmp)
    for j in range(len(kept), 20):          # anciens fichiers en trop
        f = os.path.join(outdir, f"bestplay_data_{j}.js")
        if os.path.exists(f):
            os.remove(f)
    idx = [{"m": str(j), "title": f"Action {j + 1}",
            "sub": f"{e['date'][8:10]}/{e['date'][5:7]} {e['date'][11:13]}h{e['date'][14:16]} · {e['t_s']:.1f} s · "
                   f"écart +{e['regret']:.2f} · {e['nature']}".replace(".", ",", 1).replace("+0.", "+0,")}
           for j, e in enumerate(kept)]
    meta = {"player": player, "n_games": len(dates), "first": min(dates), "last": max(dates), "k": len(kept),
            "n_duel": n_duel, "n_dup": n_dup}
    with open(os.path.join(outdir, "bestplay_index.js"), "w", encoding="utf-8") as fh:
        fh.write("window.BESTPLAY_INDEX = " + json.dumps(idx, ensure_ascii=False) + ";\n")
        fh.write("window.BESTPLAY_META = " + json.dumps(meta, ensure_ascii=False) + ";\n")
    print(f"→ {len(kept)} pires actions sur les {len(dates)} dernières parties ({n_duel} duels et {n_dup} doublons écartés)")
    for e in kept:
        print(f"   {e['date']} t={e['t_s']:.1f}s écart +{e['regret']:.2f} · {e['nature']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["extract", "train", "export", "worst"])
    ap.add_argument("--source", default="rlcs")
    ap.add_argument("--player", default=os.getenv("RLPI_PLAYER", ""))
    ap.add_argument("--since", default="2026-11-14")
    ap.add_argument("--rank", type=int, default=0)
    ap.add_argument("--at", default="", help="moment précis : \"AAAA-MM-JJ HH-MM-SS@t_s\"")
    ap.add_argument("--out", default="reports/bestplay_data.js")
    ap.add_argument("--games", type=int, default=10, help="worst : nombre de dernières parties")
    ap.add_argument("--k", type=int, default=5, help="worst : nombre d'actions")
    a = ap.parse_args()
    if a.cmd == "extract":
        extract(a.source)
    elif a.cmd == "train":
        train()
    elif a.cmd == "worst":
        worst(a.player, a.games, a.k)
    else:
        export(a.player, a.since, a.rank, a.out, a.at)


if __name__ == "__main__":
    main()
