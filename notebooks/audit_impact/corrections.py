"""Corrections F1 (buts de loin), F2 (arrets sur ballon qui rentrait), F3 (touches en double) et nouvelle note.
Usage : python notebooks/audit_impact/corrections.py <dossier contenant games/>"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import glob
import json
import os
import sys

import polars as pl
from balle import sim  # noqa: E402

from rlpi.perf import _score, _z, load_reference, xv

pl.Config.set_tbl_rows(40)
pl.Config.set_tbl_width_chars(220)
S = sys.argv[1]
ref = load_reference()
dirs = [
    d
    for d in glob.glob(S + "/games/*")
    if os.path.exists(d + "/done") and os.path.exists(d + "/features/perf_partie.parquet")
]
allT, allP, stats = [], [], {"F1": [0, 0.0], "F2": [0, 0.0], "F3": [0, 0.0]}
for d in dirs:
    rep = os.path.basename(d)
    m = json.load(open(glob.glob(f"{d}/frames/*/{rep}.meta.json")[0], encoding="utf-8"))
    f = pl.read_parquet(glob.glob(f"{d}/frames/*/{rep}.parquet")[0])
    gx = (
        pl.read_parquet(f"{d}/features/goal_xv_partie.parquet")
        if os.path.exists(f"{d}/features/goal_xv_partie.parquet")
        else None
    )
    T = xv(pl.read_parquet(f"{d}/features/touch_values_partie.parquet"), gx).sort("i").with_row_index("k")
    bx, by, bz, vx, vy, vz = (f[c].to_numpy() for c in ("ball_x", "ball_y", "ball_z", "ball_vx", "ball_vy", "ball_vz"))
    new = T["dv_xv"].to_numpy().copy()
    # F3 : même joueur, même image → on garde une seule ligne
    dup = T.with_columns(pl.int_range(pl.len()).over(["i", "player_id"]).alias("r")).filter(pl.col("r") > 0)
    for r in dup.iter_rows(named=True):
        stats["F3"][0] += 1
        stats["F3"][1] += new[r["k"]]
        new[r["k"]] = 0.0
    td = T.to_dicts()
    # F1 : but marqué plus d'1 s après la dernière touche (de l'équipe buteuse) → crédit = xV du but − V avant
    for g in m["goals"]:
        last = [t for t in td if t["i"] <= g["i"]]
        if not last or gx is None:
            continue
        lt = last[-1]
        if lt["team"] != g["team"] or (g["i"] - lt["i"]) <= 10:
            continue
        v_goal = gx.filter(pl.col("goal_i") == g["i"])["v_team0"][0] * (1 if g["team"] == 0 else -1)
        same_i = [t for t in last if t["i"] == lt["i"] and t["player_id"] == lt["player_id"]]
        k = same_i[0]["k"]
        delta = (v_goal - lt["v_before"]) - new[k]
        if delta > 0:
            stats["F1"][0] += 1
            stats["F1"][1] += delta
            new[k] += delta
    # F2 : touche défensive négative sur un ballon qui rentrait → 0
    for t in td:
        if t["ball_y"] < -1700 and new[t["k"]] < 0 and t["i"] >= 2:
            j = t["i"] - 2
            s = 1 if t["team"] == 0 else -1
            out, _ = sim([s * bx[j], s * by[j], bz[j]], [s * vx[j], s * vy[j], vz[j]])
            if out == "but0":
                stats["F2"][0] += 1
                stats["F2"][1] += new[t["k"]]
                new[t["k"]] = 0.0
    T = T.with_columns(pl.Series("dv_fix", new))
    allT.append(T.select("replay", "player_id", "player_name", "dv_xv", "dv_fix"))
    allP.append(pl.read_parquet(f"{d}/features/perf_partie.parquet"))
print({k: (v[0], round(v[1], 2)) for k, v in stats.items()})
T = pl.concat(allT, how="diagonal_relaxed")
P = pl.concat(allP, how="diagonal_relaxed")
adj = T.group_by("replay", "player_id").agg((pl.col("dv_fix") - pl.col("dv_xv")).sum().alias("delta"))
Q = P.join(adj, on=["replay", "player_id"], how="left").with_columns(
    (pl.col("impact") + pl.col("delta").fill_null(0) / pl.col("play_s") * 300).alias("impact")
)
Q = _score(Q, _z(Q, ref["mu"], ref["sd"]), ref)
C = P.select("replay", "player_id", "player_name", pl.col("index").alias("avant")).join(
    Q.select("replay", "player_id", pl.col("index").alias("apres")), on=["replay", "player_id"]
)
C = C.with_columns((pl.col("apres") - pl.col("avant")).alias("diff"))
print(
    "joueurs-matchs :",
    C.height,
    "| changés de plus de 5 points :",
    C.filter(pl.col("diff").abs() > 5).height,
    "| de plus de 15 :",
    C.filter(pl.col("diff").abs() > 15).height,
)
print(C.sort(pl.col("diff").abs(), descending=True).head(12))
print(
    C.filter(pl.col("player_name").is_in(["Axe", "LAinox"]))
    .group_by("player_name")
    .agg(pl.len(), pl.col("avant").mean().round(1), pl.col("apres").mean().round(1))
)
C.write_parquet(S + "/audit_rescore.parquet")
