"""Usage : python notebooks/audit_impact/audit.py <dossier contenant games/>
Audit du calcul de l'impact sur les parties analysées par rlpi.game (scratchpad/games/*)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import glob
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import polars as pl
from balle import sim  # noqa: E402

from rlpi.config import MODELS
from rlpi.perf import xv
from rlpi.value import value_series

S = sys.argv[1]
FPS = 10
bst = lgb.Booster(model_file=str(MODELS / "value_h5.txt"))
goals_rows, def_rows, miss_rows, unattr_rows, same_rows, calib_rows, window_rows = [], [], [], [], [], [], []
dirs = [
    d
    for d in glob.glob(S + "/games/*")
    if os.path.exists(d + "/done") and os.path.exists(d + "/features/perf_partie.parquet")
]
for d in dirs:
    rep = os.path.basename(d)
    m = json.load(open(glob.glob(f"{d}/frames/*/{rep}.meta.json")[0], encoding="utf-8"))
    f = pl.read_parquet(glob.glob(f"{d}/frames/*/{rep}.parquet")[0])
    gx = (
        pl.read_parquet(f"{d}/features/goal_xv_partie.parquet")
        if os.path.exists(f"{d}/features/goal_xv_partie.parquet")
        else None
    )
    T = xv(pl.read_parquet(f"{d}/features/touch_values_partie.parquet"), gx).sort("i")
    raw = pl.read_parquet(glob.glob(f"{d}/frames/*/{rep}.touches.parquet")[0]).sort("i")
    V = value_series(bst, m, f, 5)
    n = f.height
    bx, by, bz, vx, vy, vz = (f[c].to_numpy() for c in ("ball_x", "ball_y", "ball_z", "ball_vx", "ball_vy", "ball_vz"))
    phase = f["phase"].to_numpy()
    clock = f["seconds_remaining"].to_numpy()
    names = {p["slot"]: p["name"] for p in m["players"]}
    td = T.to_dicts()
    # 1) buts : crédit reçu par le buteur vs valeur du but
    for g in m["goals"]:
        gi, team = g["i"], g["team"]
        last = [t for t in td if t["i"] <= gi]
        if not last:
            continue
        lt = last[-1]
        dt = (gi - lt["i"]) / FPS
        v_goal = (
            (gx.filter(pl.col("goal_i") == gi)["v_team0"][0] * (1 if team == 0 else -1))
            if gx is not None and gx.filter(pl.col("goal_i") == gi).height
            else None
        )
        goals_rows.append(
            {
                "replay": rep,
                "clock": clock[gi],
                "equipe_buteuse": team,
                "dernier": lt["player_name"],
                "dernier_equipe": lt["team"],
                "action": lt["action"],
                "delai_s": dt,
                "credit": lt["dv_xv"],
                "v_before": lt["v_before"],
                "v_after": lt["v_after"],
                "xv_but": v_goal,
                "contre_son_camp": lt["team"] != team,
            }
        )
    # 2) touches défensives sur balle qui rentrait (toutes équipes)
    for t in td:
        if t["ball_y"] < -1700 and t["dv_xv"] < 0 and t["i"] >= 2:
            k = t["i"] - 2
            s = 1 if t["team"] == 0 else -1
            out, tt = sim([s * bx[k], s * by[k], bz[k]], [s * vx[k], s * vy[k], vz[k]])
            if out == "but0":
                def_rows.append(
                    {
                        "replay": rep,
                        "clock": clock[t["i"]],
                        "joueur": t["player_name"],
                        "action": t["action"],
                        "dv": t["dv_xv"],
                        "v_before": t["v_before"],
                        "v_after": t["v_after"],
                        "but_dans_s": tt,
                    }
                )
    # 3) touches manquées : changement brusque de vitesse de balle sans touche détectée
    ti = raw["i"].to_numpy()
    dvel = np.sqrt(np.diff(vx) ** 2 + np.diff(vy) ** 2 + np.diff(vz) ** 2)
    for i in np.where(dvel > 900)[0]:
        j = int(i + 1)
        if phase[i] != 1 or phase[j] != 1:
            continue
        if np.any(np.abs(ti - j) <= 2):
            continue
        near_floor = bz[i] < 200 or bz[j] < 200
        near_wall = abs(bx[j]) > 3700 or abs(by[j]) > 4800 or bz[j] > 1850
        if near_floor or near_wall:
            continue
        # joueur le plus proche
        dmin, who = 1e9, None
        for sl in range(6):
            dd = np.sqrt(
                (f[f"p{sl}_x"][j] - bx[j]) ** 2 + (f[f"p{sl}_y"][j] - by[j]) ** 2 + (f[f"p{sl}_z"][j] - bz[j]) ** 2
            )
            if dd < dmin:
                dmin, who = dd, names.get(sl)
        miss_rows.append(
            {
                "replay": rep,
                "i": j,
                "clock": clock[j],
                "dvit": float(dvel[i]),
                "z": float(bz[j]),
                "proche": who,
                "dist": float(dmin),
                "dV0": float(V[0][min(j + 10, n - 1)] - V[0][max(j - 2, 0)]),
            }
        )
    # 4) valeur non attribuée : variation de V entre les fenêtres des touches (hors célébration)
    covered = np.zeros(n, bool)
    for t in td:
        nxt = next((u["i"] for u in td if u["i"] > t["i"]), n - 1)
        a = int(min(t["i"] + FPS, max(nxt - 1, t["i"] + 1), n - 1))
        covered[max(t["i"] - 2, 0) : a + 1] = True
    dV = np.abs(np.diff(V[0]))
    play = (phase[1:] == 1) & (phase[:-1] == 1)
    unattr_rows.append(
        {"replay": rep, "total": float(dV[play].sum()), "non_attribue": float(dV[play & ~covered[1:]].sum())}
    )
    # 5) touches simultanées (même image) : même équipe = crédit en double
    dup = (
        T.group_by("i")
        .agg(pl.col("team").n_unique().alias("nt"), pl.len().alias("n"), pl.col("player_name"), pl.col("dv_xv"))
        .filter(pl.col("n") > 1)
    )
    for r in dup.iter_rows(named=True):
        same_rows.append(
            {
                "replay": rep,
                "i": r["i"],
                "meme_equipe": r["nt"] == 1,
                "joueurs": ", ".join(r["player_name"]),
                "dv": r["dv_xv"],
            }
        )
    # 6) calibration : V de l'équipe buteuse 0,5 s avant le but, et la physique dit-elle but ?
    for g in m["goals"]:
        k = g["i"] - 5
        if k < 0:
            continue
        s = 1 if g["team"] == 0 else -1
        out, tt = sim([s * bx[k], s * by[k], bz[k]], [s * vx[k], s * vy[k], vz[k]])
        calib_rows.append(
            {
                "replay": rep,
                "clock": clock[g["i"]],
                "V_05s": float(V[g["team"]][k]),
                "physique": out,
                "z": float(bz[k]),
                "dist_but": float(5120 - s * by[k]),
            }
        )
    # 7) fenêtre d'1 s : écart entre dv (1 s) et dv à 3 s
    for t in td:
        window_rows.append(
            {"replay": rep, "joueur": t["player_name"], "dv": t["dv_xv"], "dv_3s": t["dv_3s"], "action": t["action"]}
        )

out = {}
for name, rows in [
    ("buts", goals_rows),
    ("defense", def_rows),
    ("manquees", miss_rows),
    ("non_attr", unattr_rows),
    ("simult", same_rows),
    ("calib", calib_rows),
    ("fenetre", window_rows),
]:
    df = pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()
    df.write_parquet(f"{S}/audit_{name}.parquet")
    out[name] = df.height
print(len(dirs), "parties", out)
