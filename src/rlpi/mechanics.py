"""Gestes techniques (resets, air dribbles, ceilings, flicks, double taps) et réponse défensive aux resets.

Source : flux d'événements de subtr-actor (`get_stats_events`), alignés sur les images 10 i/s
(index = round((temps − t0) × 10), comme les touches).

Resets : on part des « dodge resets » sur la balle (`on_ball`). Le détecteur en compte trop
(voiture posée sur la balle au sol, contacts en 50/50) : on garde un **reset aérien** seulement si
le joueur est en l'air depuis au moins 0,3 s (z > 120 sur les 3 images précédentes) et que le
contact a lieu au-dessus de 300 uu (voiture et balle). Ce filtre est à valider à l'œil (page 2D).

Réponse défensive (équipe qui subit le reset), au moment du reset, par défenseur :
  - « bas »       : à moins de 1 800 uu de sa ligne de but et sous 300 uu de hauteur ;
  - « challenge » : à moins de 1 500 uu de la balle, ou en l'air (z > 300) et à moins de 2 500 uu
                    de la balle en s'en rapprochant ;
  - « ailleurs »  : le reste.
Configuration d'équipe : « tous bas / pas de challenge », « challenge + au moins un bas »,
« challenge sans personne bas », « personne bas ni au challenge ».
Issue : but de l'équipe du joueur qui prend le reset dans les 5 s ; ΔV (valeur à +3 s − au reset).

Usage : python -m rlpi.mechanics --source rlcs --limit 10   (extraction)
        python -m rlpi.mechanics review --source rlcs        (page de vérification 2D)
        → data/features/mechanics_<source>.parquet, resets_<source>.parquet, resets_<source>_clips.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import polars as pl

from rlpi.config import FEATURES, FRAMES, MODELS
from rlpi.value import load_replay, value_series

FPS = 10
GOAL_Y = 5120.0
STREAMS = ("dodge_reset", "flip_reset", "air_dribble", "ceiling_shot", "flick", "double_tap", "wall_aerial")


def _pid(d) -> str | None:
    if not d:
        return None
    k, v = next(iter(d.items()))
    return f"{k}:{v}"


def events_of(path: str, t0: float) -> list[dict]:
    import subtr_actor as sa

    out = []
    for e in sa.get_stats_events(path)["events"]:
        st = e["meta"]["stream"]
        if st not in STREAMS:
            continue
        tm = e["meta"]["timing"]
        t_start = tm.get("start_time", tm.get("time"))
        t_end = tm.get("end_time", tm.get("time"))
        pay = (e.get("payload") or {}).get("payload") or {}
        out.append({
            "stream": st, "player_id": _pid(e["meta"].get("primary_player")),
            "team": 0 if e["meta"].get("team_is_team_0") else 1,
            "i": int(round((t_start - t0) * FPS)), "i_end": int(round((t_end - t0) * FPS)),
            "confidence": e["meta"].get("confidence", pay.get("confidence")),
            "on_ball": pay.get("on_ball"), "used": pay.get("used"), "outcome": pay.get("outcome"),
            "kind": pay.get("kind") if st != "dodge_reset" else None,
        })
    return out


def classify_defenders(f: pl.DataFrame, i: int, def_team: int, slots: list[int]) -> list[dict]:
    """Rôle de chaque défenseur à l'image i (terrain de l'équipe qui défend : son but en y = -5120)."""
    s = 1.0 if def_team == 0 else -1.0  # équipe 0 défend en y < 0
    bx, by, bz = (f[c][i] * (s if c == "ball_y" else 1) for c in ("ball_x", "ball_y", "ball_z"))
    out = []
    for k in slots:
        x, y, z = f[f"p{k}_x"][i], f[f"p{k}_y"][i] * s, f[f"p{k}_z"][i]
        vx, vy, vz = f[f"p{k}_vx"][i], f[f"p{k}_vy"][i] * s, f[f"p{k}_vz"][i]
        d = float(np.sqrt((x - bx) ** 2 + (y - by) ** 2 + (z - bz) ** 2))
        to_ball = np.array([bx - x, by - y, bz - z]) / max(d, 1.0)
        closing = float(np.dot([vx, vy, vz], to_ball))
        dist_line = y + GOAL_Y
        if d < 1500 or (z > 300 and d < 2500 and closing > 300):
            role = "challenge"
        elif dist_line < 1800 and z < 300:
            role = "bas"
        else:
            role = "ailleurs"
        out.append({"slot": k, "role": role, "d_ball": d, "dist_line": float(dist_line), "z": float(z),
                    "closing": closing})
    return out


def config_of(roles: list[str]) -> str:
    low, ch = roles.count("bas"), roles.count("challenge")
    if ch and low:
        return "challenge + au moins un bas"
    if ch:
        return "challenge sans personne bas"
    if low:
        return "tous bas / pas de challenge"
    return "personne bas ni au challenge"


def run(source: str, limit: int) -> None:
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(MODELS / "value_h5.txt"))
    metas = sorted((FRAMES / source).glob("*.meta.json"))[: limit or None]
    mech, resets, clips = [], [], []
    t_start = time.time()
    for n, mp in enumerate(metas, 1):
        m, f = load_replay(mp)
        slot_of = {p["id"]: p["slot"] for p in m["players"]}
        name_of = {p["id"]: p["name"] for p in m["players"]}
        evs = events_of(m["path"], m["t0"] or 0.0)
        for e in evs:
            e.update(replay=m["replay"], date=m["date"], player_name=name_of.get(e["player_id"]))
        mech.extend(evs)
        flips = [e for e in evs if e["stream"] == "flip_reset"]
        v = None
        z_ok = {k: f[f"p{k}_z"].to_numpy() for k in range(6)}
        bz = f["ball_z"].to_numpy()
        for e in evs:
            if e["stream"] != "dodge_reset" or not e["on_ball"]:
                continue
            i, k = e["i"], slot_of.get(e["player_id"], -1)
            if k < 0 or not (3 <= i < f.height - 1):
                continue
            pz, ballz = float(z_ok[k][i]), float(bz[i])
            airborne = bool((z_ok[k][i - 3:i] > 120).all())
            aerial = airborne and pz > 300 and ballz > 300
            team = e["team"]
            def_team = 1 - team
            slots = [p["slot"] for p in m["players"] if p["team"] == def_team]
            defs = classify_defenders(f, i, def_team, slots)
            roles = [d["role"] for d in defs]
            if v is None:
                v = value_series(booster, m, f, 5)
            j = min(i + 30, f.height - 1)
            goal5 = any(g["team"] == team and i <= g["i"] <= i + 50 for g in m["goals"])
            conceded5 = any(g["team"] == def_team and i <= g["i"] <= i + 50 for g in m["goals"])
            used = next((fl for fl in flips if fl["player_id"] == e["player_id"] and abs(fl["i"] - i) <= 2), None)
            row = {
                "replay": m["replay"], "date": m["date"], "i": i, "player_id": e["player_id"],
                "player_name": name_of.get(e["player_id"]), "team": team, "outcome": e["outcome"],
                "used": bool(e["used"]), "time_to_use": None if used is None else (used["i_end"] - used["i"]) / FPS,
                "player_z": pz, "ball_z": ballz, "airborne": airborne, "aerial_reset": aerial,
                "ball_y_att": float(f["ball_y"][i] * (1 if team == 0 else -1)),
                "defense": config_of(roles), "n_low": roles.count("bas"), "n_challenge": roles.count("challenge"),
                "goal_5s": goal5, "conceded_5s": conceded5,
                "v_reset": float(v[team][i]), "dv_3s": float(v[team][j] - v[team][i]),
                "clock": float(f["seconds_remaining"][i]) if f["seconds_remaining"][i] is not None else None,
            }
            resets.append(row)
            a, b = max(0, i - 20), min(f.height, i + 31)
            clips.append({
                "id": len(clips), "row": row, "defenders": defs,
                "players": [{"slot": p["slot"], "name": p["name"], "team": p["team"]} for p in m["players"]],
                "i0": a, "ir": i - a,
                "ball": [[round(f["ball_x"][t]), round(f["ball_y"][t]), round(f["ball_z"][t])] for t in range(a, b)],
                "cars": [[[round(f[f"p{k}_x"][t]), round(f[f"p{k}_y"][t]), round(f[f"p{k}_z"][t])]
                          for k in range(6)] for t in range(a, b)],
            })
        print(f"  {n}/{len(metas)} — {time.time() - t_start:.0f}s, gestes {len(mech)}, resets sur balle {len(resets)}",
              flush=True)
    pl.DataFrame(mech).write_parquet(FEATURES / f"mechanics_{source}.parquet")
    pl.DataFrame(resets).write_parquet(FEATURES / f"resets_{source}.parquet")
    (FEATURES / f"resets_{source}_clips.json").write_text(json.dumps(clips, ensure_ascii=False), encoding="utf-8")
    print(f"→ mechanics_{source}.parquet ({len(mech)} gestes), resets_{source}.parquet ({len(resets)} resets sur balle)")


def review(source: str, n: int = 20, seed: int = 7) -> Path:
    """Page de vérification : n resets tirés au hasard (tous les cas non aériens et expirés, puis moitié
    utilisés / moitié non utilisés)."""
    from rlpi.config import ROOT

    clips = json.loads((FEATURES / f"resets_{source}_clips.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(seed)
    pick = [c for c in clips if not c["row"]["aerial_reset"] or c["row"]["outcome"] not in ("used", "landed")]
    rest = n - len(pick)
    for oc, k in (("used", rest // 2), ("landed", rest - rest // 2)):
        pool = [c for c in clips if c["row"]["aerial_reset"] and c["row"]["outcome"] == oc]
        pick += [pool[j] for j in rng.choice(len(pool), size=min(k, len(pool)), replace=False)]
    rng.shuffle(pick)
    n_matches = len({c["row"]["replay"] for c in clips})
    data = {"batch": f"{source}-{n_matches}m-{seed}", "n_total": len(clips), "n_matches": n_matches, "clips": pick}
    tpl = (Path(__file__).with_name("resets_review_template.html")).read_text(encoding="utf-8")
    out = ROOT / "reports" / "archives" / "resets_verification.html"
    out.write_text(tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False)), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "review"])
    ap.add_argument("--source", default="rlcs")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "review":
        print(f"→ {review(a.source)}")
    else:
        run(a.source, a.limit)


if __name__ == "__main__":
    main()
