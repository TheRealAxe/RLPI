"""Extraction image par image (phase 2, version prototype) avec subtr-actor.

Pour chaque replay 3v3 :
  data/frames/<source>/<replay>.parquet          une ligne par image (10 i/s)
  data/frames/<source>/<replay>.touches.parquet  une ligne par touche de balle
  data/frames/<source>/<replay>.meta.json        joueurs (slot → id, nom, équipe), buts, contrôles

Conventions : l'équipe 0 (bleue) marque en y > 0, l'équipe 1 (orange) en y < 0.
Slots joueurs 0-2 = équipe 0, 3-5 = équipe 1 (ordre de subtr-actor).

Usage :
    python -m rlpi.frames --source rlcs [--limit 10]
    python -m rlpi.frames --source perso --dir "C:/.../TAGame/Demos"
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import polars as pl

from rlpi.config import FRAMES, RAW

FPS = 10.0
G_ADDERS = ["BallRigidBody", "SecondsRemaining", "ReplicatedGameStateTimeRemaining", "ReplicatedStateName"]
P_ADDERS = ["PlayerRigidBody", "PlayerBoost", "PlayerDemolishedBy"]
STATE_PLAY, STATE_GOAL, STATE_KICKOFF = 74, 123, 68
GOAL_Y = 5150  # la balle franchit la ligne (5120 + rayon partiel)


def detect_goals(ball_x, ball_y, ball_z, play, state):
    """Buts et phase (1 jeu, 2 but, 0 attente) à partir de la balle et de l'état de jeu.

    Un but = la balle franchit la ligne ET le jeu s'arrête dans la seconde et demie qui suit (sinon
    c'est un arrêt sur la ligne). On ne se fie pas au code d'état « but » : selon la version du jeu,
    l'état qui suit un but n'a pas toujours le même code. Phase 2 = la première séquence d'état
    hors jeu qui suit le but (célébration).
    """
    n = len(ball_y)
    phase = np.where(play, 1, 0).astype(np.int8)
    inside = (np.abs(ball_y) > GOAL_Y) & (np.abs(ball_x) < 900) & (ball_z < 650)
    starts = np.where(inside & ~np.r_[False, inside[:-1]])[0]
    goals, last = [], -1000
    for i in starts:
        if i - last > 30 and not play[i:i + 15].all():
            goals.append({"i": int(i), "team": 0 if ball_y[i] > 0 else 1})
            last = i
            j = i
            while j < n and play[j]:
                j += 1
            k = j
            while k < n and not play[k] and state[k] == state[j]:
                k += 1
            phase[j:k] = 2
    return goals, phase


def _pid(remote_id) -> str:
    if isinstance(remote_id, dict):
        k, v = next(iter(remote_id.items()))
        return f"{k}:{v}"
    return str(remote_id)


def extract(path: str, out_dir: str) -> dict:
    import subtr_actor as sa

    meta, a = sa.get_ndarray_with_info_from_replay_filepath(path, G_ADDERS, P_ADDERS, fps=FPS, dtype="f32")
    rm = meta["replay_meta"]
    headers = {h[0]: h[1] for h in rm["all_headers"]}
    players = [(p, 0) for p in rm.get("team_zero") or []] + [(p, 1) for p in rm.get("team_one") or []]
    gh, ph = meta["column_headers"]["global_headers"], meta["column_headers"]["player_headers"]
    n_pl = (a.shape[1] - len(gh)) // len(ph)
    if len(players) != 6 or n_pl != 6 or [t for _, t in players] != [0, 0, 0, 1, 1, 1]:
        raise ValueError(f"pas un 3v3 propre ({len(players)} joueurs, {n_pl} slots)")

    cols = {
        "ball_x": a[:, 0], "ball_y": a[:, 1], "ball_z": a[:, 2],
        "ball_vx": a[:, 6], "ball_vy": a[:, 7], "ball_vz": a[:, 8],
        # rotation de la balle (rad/s ; le replay la stocke ×100), pour la simulation de balle (rlpi.ballsim)
        "ball_wx": a[:, 9] / 100, "ball_wy": a[:, 10] / 100, "ball_wz": a[:, 11] / 100,
        "seconds_remaining": a[:, gh.index("seconds remaining")],
        "state": a[:, gh.index("game state")].astype(np.int16),
    }
    g = len(gh)
    for k in range(6):
        b = g + k * len(ph)
        for name, j in (("x", 0), ("y", 1), ("z", 2), ("rx", 3), ("ry", 4), ("rz", 5), ("vx", 6), ("vy", 7), ("vz", 8)):
            cols[f"p{k}_{name}"] = a[:, b + j]
        cols[f"p{k}_boost"] = a[:, b + ph.index("boost level (raw replay units)")] / 255 * 100
        cols[f"p{k}_demo"] = (a[:, b + ph.index("player demolished by")] >= 0).astype(np.int8) \
            if "player demolished by" in ph else np.zeros(len(a), np.int8)
    df = pl.DataFrame(cols).with_row_index("i")

    # Buts : premières images où la balle a franchi une ligne de but
    n_header_goals = len(headers.get("Goals", []) or [])

    # L'état de jeu est un index de nom qui varie d'un replay à l'autre : on le déduit.
    # Jeu = état le plus fréquent ; attente = état de la 1re image ; but = l'état restant le plus fréquent.
    st = cols["state"]
    vals, cnt = np.unique(st, return_counts=True)
    order = [int(v) for v in vals[np.argsort(-cnt)]]
    play_code, kickoff_code = order[0], int(st[0])
    others = [v for v in order if v not in (play_code, kickoff_code)]
    goal_code = others[0] if others else -999
    goals, phase = detect_goals(cols["ball_x"], cols["ball_y"], cols["ball_z"], st == play_code, st)
    df = df.with_columns(pl.Series("phase", phase))

    # Touches (événements subtr-actor) alignées sur l'index 10 i/s
    events = sa.get_stats_events(path)["events"]
    t0 = next((e["meta"]["timing"].get("start_time", e["meta"]["timing"].get("time"))
               for e in events if e["meta"]["timing"].get("start_frame", e["meta"]["timing"].get("frame")) == 0), None)
    slot_of = {_pid(p["remote_id"]): k for k, (p, _) in enumerate(players)}
    touches = []
    for e in events:
        if e["meta"]["stream"] != "touch":
            continue
        pay = e["payload"]["payload"]
        i = int(round((pay["time"] - (t0 or 0.0)) * FPS))
        tags = {t["group"]: t["value"] for t in pay.get("tags", [])}
        touches.append({
            "i": i, "slot": slot_of.get(_pid(pay["player"]), -1), "team": 0 if pay["is_team_0"] else 1,
            "action": tags.get("action"), "kind": tags.get("kind"), "height": tags.get("height_band"),
            "role": pay.get("role"), "ball_speed_change": pay.get("ball_speed_change"),
        })
    tdf = pl.DataFrame(touches, schema={"i": pl.Int64, "slot": pl.Int64, "team": pl.Int64, "action": pl.Utf8,
                                        "kind": pl.Utf8, "height": pl.Utf8, "role": pl.Utf8,
                                        "ball_speed_change": pl.Float64})
    # Contrôle d'alignement : distance balle-joueur au moment des touches
    ok = tdf.filter((pl.col("slot") >= 0) & (pl.col("i") >= 0) & (pl.col("i") < len(df)))
    d = [float(np.linalg.norm([cols["ball_x"][i] - cols[f"p{s}_x"][i],
                               cols["ball_y"][i] - cols[f"p{s}_y"][i],
                               cols["ball_z"][i] - cols[f"p{s}_z"][i]]))
         for i, s in ok.select("i", "slot").iter_rows()]

    rid = Path(path).stem
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out / f"{rid}.parquet")
    tdf.write_parquet(out / f"{rid}.touches.parquet")
    info = {
        "replay": rid, "path": str(path), "date": headers.get("Date"), "map": headers.get("MapName"),
        "match_type": headers.get("MatchType"), "game_type": (rm.get("game_type") or {}).get("game_type"),
        "team0_score": headers.get("Team0Score", 0), "team1_score": headers.get("Team1Score", 0),
        "players": [{"slot": k, "id": _pid(p["remote_id"]), "name": p["name"], "team": t}
                    for k, (p, t) in enumerate(players)],
        "goals": goals, "n_header_goals": n_header_goals, "n_frames": len(df),
        "n_play_frames": int((phase == 1).sum()), "state_codes": [play_code, goal_code, kickoff_code],
        "n_touches": tdf.height, "touch_dist_median": float(np.median(d)) if d else None,
        "t0": t0,
    }
    (out / f"{rid}.meta.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


def fix_goals(source: str) -> None:
    """Recalcule buts et phases sur les fichiers déjà extraits (sans re-parser les replays)."""
    out_dir = FRAMES / source
    changed = 0
    for mp in sorted(out_dir.glob("*.meta.json")):
        m = json.loads(mp.read_text(encoding="utf-8"))
        fp = out_dir / f"{m['replay']}.parquet"
        f = pl.read_parquet(fp)
        st = f["state"].to_numpy()
        play_code = m["state_codes"][0]
        goals, phase = detect_goals(f["ball_x"].to_numpy(), f["ball_y"].to_numpy(), f["ball_z"].to_numpy(),
                                    st == play_code, st)
        if goals != m["goals"] or not np.array_equal(phase, f["phase"].to_numpy()):
            changed += 1
            f.with_columns(pl.Series("phase", phase)).write_parquet(fp)
            m["goals"] = goals
            mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    print(f"{changed} replays corrigés dans {out_dir}")


def _add_rotation_one(meta_path: str) -> bool:
    import subtr_actor as sa

    mp = Path(meta_path)
    m = json.loads(mp.read_text(encoding="utf-8"))
    fp = mp.with_name(m["replay"] + ".parquet")
    df = pl.read_parquet(fp)
    if "ball_wx" in df.columns:
        return False
    _, a = sa.get_ndarray_with_info_from_replay_filepath(m["path"], G_ADDERS, P_ADDERS, fps=FPS, dtype="f32")
    if len(a) != df.height:
        raise ValueError(f"{m['replay']} : {len(a)} images au lieu de {df.height}")
    df.with_columns(pl.Series("ball_wx", a[:, 9] / 100), pl.Series("ball_wy", a[:, 10] / 100),
                    pl.Series("ball_wz", a[:, 11] / 100)).write_parquet(fp)
    return True


def add_rotation(source: str, workers: int = 4) -> None:
    """Ajoute la rotation de la balle (ball_wx/wy/wz) aux images déjà extraites, sans toucher au reste.
    Il faut le replay d'origine (chemin `path` du meta.json)."""
    metas = sorted(str(p) for p in (FRAMES / source).glob("*.meta.json"))
    done, fails, t0 = 0, [], time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_add_rotation_one, p): p for p in metas}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                done += bool(fut.result())
            except Exception as e:  # noqa: BLE001
                fails.append(f"{Path(futs[fut]).name} : {e!r}"[:300])
            if n % 50 == 0 or n == len(metas):
                print(f"  {n}/{len(metas)} — {time.time() - t0:.0f}s, échecs {len(fails)}", flush=True)
    print(f"→ rotation ajoutée à {done} replays ({source}), échecs {len(fails)}")
    for f in fails[:10]:
        print("   ", f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--dir", nargs="+", help="un ou plusieurs dossiers de replays (sinon data/raw/<source>)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--fix-goals", action="store_true", help="recalculer buts et phases sans re-parser")
    ap.add_argument("--add-rotation", action="store_true", help="ajouter la rotation de la balle aux images extraites")
    a = ap.parse_args()
    if a.fix_goals:
        fix_goals(a.source)
        return
    if a.add_rotation:
        add_rotation(a.source, a.workers)
        return
    roots = [Path(d) for d in a.dir] if a.dir else [RAW / a.source]
    files = sorted((f for r in roots for f in r.rglob("*.replay")), key=lambda p: p.stat().st_mtime, reverse=True)
    if a.limit:
        files = files[: a.limit]
    out_dir = FRAMES / a.source
    done = {p.name.removesuffix(".meta.json") for p in out_dir.glob("*.meta.json")} if out_dir.exists() else set()
    files = [f for f in files if f.stem not in done]
    print(f"{len(files)} replays à traiter → {out_dir}", flush=True)

    infos, fails = [], []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(extract, str(f), str(out_dir)): f for f in files}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                infos.append(fut.result())
            except Exception as e:  # noqa: BLE001
                fails.append({"file": str(futs[fut]), "error": repr(e)[:300]})
            if n % 10 == 0 or n == len(files):
                print(f"  {n}/{len(files)} — {time.time() - t0:.0f}s, échecs {len(fails)}", flush=True)

    # Rapport de qualité (cumulé sur tout le dossier)
    metas = [json.loads(p.read_text(encoding="utf-8")) for p in out_dir.glob("*.meta.json")]
    q = pl.DataFrame([{k: m[k] for k in ("replay", "n_frames", "n_play_frames", "n_touches",
                                          "touch_dist_median", "n_header_goals")} | {"n_goals": len(m["goals"])}
                      for m in metas])
    q.write_parquet(out_dir.parent / f"quality_{a.source}.parquet")
    if fails:
        (out_dir.parent / f"failures_{a.source}.json").write_text(json.dumps(fails, indent=1), encoding="utf-8")
    mism = q.filter(pl.col("n_goals") != pl.col("n_header_goals")).height
    print(f"→ {q.height} replays OK, échecs {len(fails)}, buts détectés ≠ en-tête : {mism}, "
          f"distance balle-joueur médiane aux touches : {q['touch_dist_median'].median():.0f} uu")


if __name__ == "__main__":
    main()
