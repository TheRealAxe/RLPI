"""Traitement partie par partie (version multi-joueurs, workers Coolify).

Chaque partie est traitée seule, dans un dossier autonome, avec les modèles déjà entraînés :

    python -m rlpi.game run <fichier.replay> --out <dossier_partie>

    <dossier_partie>/frames/partie/<replay>.parquet, .touches.parquet, .meta.json, .cameras.json
    <dossier_partie>/features/<table>_partie.parquet   (+ value_curves_partie.json, bestplay_X_partie.npy)
    <dossier_partie>/result.json                       statut, durée de chaque étape, erreurs

Les étapes, dans l'ordre : frames, stats, valeur des touches,
buts (xV), décisions à la touche, placement, passes, indice de performance, défense, engagements, meilleur jeu.
Toutes ne dépendent que de la partie elle-même ; l'indice de performance utilise la référence SSL figée
(data/models/perf_reference.npz, voir rlpi.perf).

Puis on rassemble les parties d'un joueur dans un dossier de données classique, lisible par le tableau de bord :

    python -m rlpi.game merge <dossier_des_parties> --into <dossier_data> [--source perso]

Ce qui reste au niveau du joueur (toutes ses parties ensemble) n'est pas fait ici : synergie (rlpi.synergy),
actions à revoir (bestplay worst), tableau de bord.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

GAME_SOURCE = "partie"  # nom de la source à l'intérieur d'un dossier de partie
HORIZON = 5             # horizon du modèle de valeur, comme dans l'application
# Version de l'analyse (code + modèles) : à augmenter quand le résultat d'une partie change (nouveaux modèles,
# correction d'un calcul). `python -m rlpi.worker reanalyze` relance les parties analysées avec une version plus
# ancienne. 2 : corrections de l'audit de l'impact (F1, F2, F3) et trajectoire simulée de la balle (25/11/2026).
ANALYSIS_VERSION = 2


# --------------------------------------------------------------------------------------------------------------
# Une partie


def run(replay: str | Path, out: str | Path, models: str | Path | None = None, timeout: float = 900) -> dict:
    """Traite une partie dans un processus séparé (mémoire libérée à la fin) et renvoie son result.json."""
    from rlpi.config import MODELS

    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ | {"RLPI_DATA": str(out), "RLPI_MODELS": str(Path(models or MODELS).resolve()),
                        "RLPI_SOURCE": GAME_SOURCE, "PYTHONIOENCODING": "utf-8"}
    src = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join([str(src), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    t0 = time.time()
    p = subprocess.run([sys.executable, "-m", "rlpi.game", "_steps", str(Path(replay).resolve())],
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    res_file = out / "result.json"
    if res_file.exists():
        res = json.loads(res_file.read_text(encoding="utf-8"))
    else:
        res = {"status": "erreur", "error": (p.stderr or p.stdout)[-2000:], "replay": Path(replay).stem}
        res_file.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    res["wall_s"] = round(time.time() - t0, 2)
    return res


def cameras(replay: str | Path, dest: str | Path, timeout: float = 300) -> None:
    """Caméras des joueurs (`clips.read_cameras`) écrites dans `dest`, lues dans un processus séparé : la lecture
    prend environ 250 Mo, rendus au système à la fin. Pour le rattrapage des parties traitées avant le
    `cameras.json` (python -m rlpi.worker backfill-cameras). RuntimeError si la lecture échoue."""
    dest = Path(dest).resolve()
    src = Path(__file__).resolve().parents[1]
    env = os.environ | {"PYTHONIOENCODING": "utf-8"}
    env["PYTHONPATH"] = os.pathsep.join([str(src), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    p = subprocess.run([sys.executable, "-m", "rlpi.game", "_cameras", str(Path(replay).resolve()), str(dest)],
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if p.returncode != 0 or not dest.exists():
        dest.unlink(missing_ok=True)
        raise RuntimeError((p.stderr or p.stdout or f"code {p.returncode}").strip()[-500:])


def _cameras(replay: str, dest: str) -> None:
    from rlpi import clips

    cams = clips.read_cameras(replay)
    tmp = Path(dest).with_suffix(".tmp")
    tmp.write_text(json.dumps(cams), encoding="utf-8")
    tmp.replace(dest)


def _steps(replay: str) -> None:
    """Exécuté dans le processus fils : RLPI_DATA, RLPI_MODELS et RLPI_SOURCE sont déjà réglés."""
    import polars as pl

    from rlpi import bestplay, clips, decisions, defense, frames, kickoffs, passes, perf, stats, value
    from rlpi.config import DATA, FEATURES, FRAMES, SOURCE

    assert SOURCE == GAME_SOURCE, "lancer via rlpi.game run"
    FEATURES.mkdir(parents=True, exist_ok=True)
    res = {"replay": Path(replay).stem, "file": Path(replay).name, "status": "ok", "steps": {}, "errors": {},
           "analysis_version": ANALYSIS_VERSION}

    def step(name, fn):
        t = time.time()
        try:
            fn()
            res["steps"][name] = round(time.time() - t, 2)
        except Exception as e:  # noqa: BLE001 — on note l'erreur et on continue avec les étapes suivantes
            res["steps"][name] = round(time.time() - t, 2)
            res["errors"][name] = f"{type(e).__name__}: {e}"[:500]
            res["traceback_" + name] = traceback.format_exc()[-1500:]

    def save():
        (DATA / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    # 1. Lecture du replay : seules les parties 3v3 complètes passent
    t = time.time()
    try:
        info = frames.extract(replay, str(FRAMES / SOURCE))
    except Exception as e:  # noqa: BLE001
        res.update(status="rejetee", reason=f"{type(e).__name__}: {e}"[:500])
        res["steps"]["frames"] = round(time.time() - t, 2)
        save()
        return
    res["steps"]["frames"] = round(time.time() - t, 2)
    res |= {"date": info["date"], "match_type": info["match_type"], "n_frames": info["n_frames"],
            "n_touches": info["n_touches"], "players": info["players"],
            "score": [info["team0_score"], info["team1_score"]]}

    # 2. Stats de base (subtr-actor) : gardées seulement pour une partie en ligne 3v3, comme --online-3v3
    def do_stats():
        df = pl.DataFrame(stats.extract(replay), infer_schema_length=None)
        df = df.filter((pl.col("match_type") == "Online") & (pl.col("team_size") == 3))
        res["online_3v3"] = not df.is_empty()
        guids = [g for g in df["match_guid"].unique().to_list() if g] if "match_guid" in df.columns else []
        res["match_guid"] = guids[0] if guids else None  # même match envoyé deux fois → même GUID
        if not df.is_empty():
            df.write_parquet(FEATURES / f"player_match_stats_{SOURCE}.parquet")
    step("stats", do_stats)

    # Caméras des joueurs (vue joueur du bouton « ▶ Revoir ») : lecture lourde, faite une fois ici. Facultatif :
    # un échec est noté en avertissement sans rendre la partie « partiel » (le clip part alors sans caméra).
    t = time.time()
    try:
        cams = clips.read_cameras(replay)
        (FRAMES / SOURCE / f"{info['replay']}.cameras.json").write_text(json.dumps(cams), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        res.setdefault("warnings", {})["cameras"] = f"{type(e).__name__}: {e}"[:500]
    res["steps"]["cameras"] = round(time.time() - t, 2)

    step("valeur", lambda: value.touches(SOURCE, HORIZON))
    step("buts", lambda: value.goal_values(SOURCE, HORIZON))
    step("decisions", lambda: decisions.touches(retrain=False))
    step("placement", lambda: decisions.placement_score(SOURCE))
    step("passes", lambda: passes.build(SOURCE).write_parquet(FEATURES / f"passes_{SOURCE}.parquet"))
    if res.get("online_3v3"):
        step("perf", lambda: perf.score_source(SOURCE))
    step("defense", lambda: defense.run(SOURCE, None))
    step("engagements", lambda: kickoffs.run(SOURCE, None))
    step("meilleur_jeu", lambda: bestplay.extract(SOURCE))

    if res["errors"]:
        res["status"] = "partiel"
    save()


# --------------------------------------------------------------------------------------------------------------
# Rassembler les parties d'un joueur


def merge(games_dir, into: str | Path, source: str) -> dict:
    """Rassemble les dossiers de parties (sortie de `run`) en un dossier de données `into` pour la source donnée.

    `games_dir` : un dossier contenant les dossiers de parties, ou directement une liste de dossiers de parties.

    Les tables sont reconstruites entièrement à partir des parties (on peut relancer sans risque de doublon).
    """
    import numpy as np
    import polars as pl

    into = Path(into)
    dirs = sorted(p for p in Path(games_dir).iterdir()) if isinstance(games_dir, (str, Path)) else list(games_dir)
    games = []
    for d in (p for p in dirs if (p / "result.json").exists()):
        r = json.loads((d / "result.json").read_text(encoding="utf-8"))
        if r.get("status") in ("ok", "partiel"):
            games.append(d)

    # Images par image : simple copie
    fr_out = into / "frames" / source
    fr_out.mkdir(parents=True, exist_ok=True)
    metas = []
    for g in games:
        for f in (g / "frames" / GAME_SOURCE).iterdir():
            shutil.copy2(f, fr_out / f.name)
            if f.name.endswith(".meta.json"):
                metas.append(json.loads(f.read_text(encoding="utf-8")))
    if metas:
        pl.DataFrame([{k: m[k] for k in ("replay", "n_frames", "n_play_frames", "n_touches", "touch_dist_median",
                                          "n_header_goals")} | {"n_goals": len(m["goals"])} for m in metas]
                     ).write_parquet(into / "frames" / f"quality_{source}.parquet")

    # Tables Parquet : concaténation partie par partie
    feat_out = into / "features"
    feat_out.mkdir(parents=True, exist_ok=True)
    suffix = f"_{GAME_SOURCE}.parquet"
    names = sorted({f.name.removesuffix(suffix) for g in games for f in (g / "features").glob(f"*{suffix}")}
                   - {"bestplay_rows"})
    counts = {}
    tables = {}
    for name in names:
        parts = [pl.read_parquet(f) for g in games if (f := g / "features" / f"{name}{suffix}").exists()]
        parts = [p for p in parts if p.height]
        if not parts:
            continue
        df = pl.concat(parts, how="diagonal_relaxed")
        if "source" in df.columns:
            df = df.with_columns(pl.lit(source).alias("source"))
        tables[name] = df

    # Doublons : un même match présent deux fois (même MatchGUID) → on garde un seul fichier, comme rlpi.stats
    if "player_match_stats" in tables:
        st = tables["player_match_stats"]
        keep = st.group_by("match_guid").agg(pl.col("replay_file").min())["replay_file"]
        st2 = st.filter(pl.col("replay_file").is_in(keep.implode()) | pl.col("match_guid").is_null())
        dropped = set(st["replay_file"].unique()) - set(st2["replay_file"].unique())
        tables["player_match_stats"] = st2
        if dropped and "perf" in tables:
            stems = {Path(f).stem for f in dropped}
            tables["perf"] = tables["perf"].filter(~pl.col("replay").is_in(list(stems)))
    for name, df in tables.items():
        df.write_parquet(feat_out / f"{name}_{source}.parquet")
        counts[name] = df.height

    # Meilleur jeu : matrice X et lignes, dans le même ordre
    xs, rows = [], []
    for g in games:
        fx, fr = g / "features" / f"bestplay_X_{GAME_SOURCE}.npy", g / "features" / f"bestplay_rows{suffix}"
        if fx.exists() and fr.exists():
            r = pl.read_parquet(fr)
            if r.height:
                xs.append(np.load(fx))
                rows.append(r)
    if rows:
        np.save(feat_out / f"bestplay_X_{source}.npy", np.vstack(xs))
        pl.concat(rows, how="diagonal_relaxed").write_parquet(feat_out / f"bestplay_rows_{source}.parquet")
        counts["bestplay_rows"] = sum(r.height for r in rows)

    # Courbes de valeur (JSON)
    curves = []
    for g in games:
        f = g / "features" / f"value_curves_{GAME_SOURCE}.json"
        if f.exists():
            curves += json.loads(f.read_text(encoding="utf-8"))
    (feat_out / f"value_curves_{source}.json").write_text(json.dumps(curves), encoding="utf-8")

    return {"games": len(games), "tables": counts}


# --------------------------------------------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Traitement partie par partie")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("run", help="traiter une partie")
    s.add_argument("replay")
    s.add_argument("--out", required=True, help="dossier de sortie de la partie")
    s.add_argument("--models", help="dossier des modèles (défaut : data/models)")
    s = sub.add_parser("merge", help="rassembler les parties d'un joueur")
    s.add_argument("games_dir")
    s.add_argument("--into", required=True)
    s.add_argument("--source", default=None, help="nom de la source (défaut : RLPI_SOURCE, sinon perso)")
    s = sub.add_parser("_steps")
    s.add_argument("replay")
    s = sub.add_parser("_cameras")
    s.add_argument("replay")
    s.add_argument("dest")
    a = ap.parse_args()
    if a.cmd == "_steps":
        _steps(a.replay)
    elif a.cmd == "_cameras":
        _cameras(a.replay, a.dest)
    elif a.cmd == "run":
        r = run(a.replay, a.out, a.models)
        err = f" — erreurs : {', '.join(r['errors'])}" if r.get("errors") else ""
        print(f"{r.get('replay')} : {r['status']} en {r['wall_s']} s{err}" + (f" ({r['reason']})" if r.get("reason") else ""))
    else:
        from rlpi.config import SOURCE
        print(json.dumps(merge(a.games_dir, a.into, a.source or SOURCE), ensure_ascii=False))


if __name__ == "__main__":
    main()
