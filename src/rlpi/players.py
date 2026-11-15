"""Espace joueur (version multi-joueurs) : rassembler les parties d'un joueur et calculer son tableau de bord.

Les parties traitées par les workers sont dans le stockage S3 (Garage) :
    users/<joueur>/games/<replay>/frames/partie/…, features/…_partie.*, result.json
    users/<joueur>/profile.json      facultatif : {"player": "<identifiant en jeu>", "compare": ["…", "…"]}

Ce module, utilisé par le serveur du tableau de bord (rlpi.serve) :
    1. télécharge les parties nouvelles ou modifiées dans un cache local (<cache>/<joueur>/games/) ;
    2. les rassemble (rlpi.game merge) dans <cache>/<joueur>/data, source « perso », à côté de liens vers les
       données de référence (RLCS, SSL, rapports des modèles) du dossier de données principal ;
    3. calcule la synergie du joueur, puis le contenu du tableau de bord, dans un processus séparé où
       RLPI_DATA pointe sur ce dossier (le code du tableau de bord reste inchangé).

    python -m rlpi.players sync --user theo          # rassembler (télécharge depuis le stockage)
    python -m rlpi.players payload --user theo       # contenu du tableau de bord (JSON) — interne

Variables : S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET, S3_REGION (comme le worker),
RLPI_USERS_CACHE (défaut : <données>/users).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path

USER_SOURCE = "perso"  # nom de la source dans le dossier de données d'un joueur
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def enabled() -> bool:
    """Le mode multi-joueurs est actif si le stockage est configuré."""
    return bool(os.getenv("S3_ENDPOINT", "").strip())


def cache_root() -> Path:
    from rlpi.config import DATA

    return Path(os.getenv("RLPI_USERS_CACHE") or DATA / "users")


def safe(s: str) -> str:
    from rlpi.worker import safe as _safe

    return _safe(s)


def lock(user: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(user, threading.Lock())


# --------------------------------------------------------------------------------------------------------------
# 1. Téléchargement des parties


def list_games(cli, bucket: str, user: str) -> dict[str, dict[str, str]]:
    """{replay: {clé relative: etag}} pour toutes les parties du joueur dans le stockage."""
    prefix = f"users/{user}/games/"
    games: dict[str, dict[str, str]] = {}
    for page in cli.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            rel = o["Key"][len(prefix):]
            if "/" not in rel:
                continue
            replay, rest = rel.split("/", 1)
            games.setdefault(replay, {})[rest] = o["ETag"]
    return games


def download(user: str) -> tuple[Path, bool]:
    """Met le cache local à jour. Retourne (dossier des parties, True si quelque chose a changé)."""
    from rlpi.worker import bucket, s3

    cli, b = s3(), bucket()
    root = cache_root() / user
    gdir = root / "games"
    gdir.mkdir(parents=True, exist_ok=True)
    manifest_f = root / "manifest.json"
    old = json.loads(manifest_f.read_text(encoding="utf-8")) if manifest_f.exists() else {}
    remote = list_games(cli, b, user)
    changed = False
    for replay, files in remote.items():
        if old.get(replay) == files and (gdir / replay / "result.json").exists():
            continue
        dest = gdir / replay
        shutil.rmtree(dest, ignore_errors=True)
        for rel in files:
            f = dest / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            cli.download_file(b, f"users/{user}/games/{replay}/{rel}", str(f))
        changed = True
    for replay in set(old) - set(remote):  # partie supprimée du stockage
        shutil.rmtree(gdir / replay, ignore_errors=True)
        changed = True
    if changed or not manifest_f.exists():
        manifest_f.write_text(json.dumps(remote), encoding="utf-8")
    try:
        obj = cli.get_object(Bucket=b, Key=f"users/{user}/profile.json")
        (root / "profile.json").write_bytes(obj["Body"].read())
    except cli.exceptions.NoSuchKey:
        (root / "profile.json").unlink(missing_ok=True)
    return gdir, changed


# --------------------------------------------------------------------------------------------------------------
# 2. Dossier de données du joueur


def _link(src: Path, dst: Path) -> None:
    """Lien vers un fichier ou dossier de référence (lien symbolique ; sinon liens physiques ou copie)."""
    if dst.exists() or dst.is_symlink():
        return
    try:
        os.symlink(src, dst, target_is_directory=src.is_dir())
    except OSError:  # Windows sans droit de créer des liens symboliques
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                _link(f, dst / f.name)
        else:
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)


def link_reference(data: Path, ref: Path, own_sources: set[str]) -> None:
    """Relie les données de référence (tout ce qui n'est pas une source « joueur ») dans le dossier du joueur."""
    def own(name: str) -> bool:
        stem = name.split(".")[0]
        return any(stem.endswith(f"_{s}") for s in own_sources) or name in own_sources

    (data / "features").mkdir(parents=True, exist_ok=True)
    (data / "frames").mkdir(parents=True, exist_ok=True)
    for f in (ref / "features").iterdir():
        if not own(f.name):
            _link(f, data / "features" / f.name)
    for f in (ref / "frames").iterdir():
        if not own(f.name) and f.name not in own_sources:
            _link(f, data / "frames" / f.name)


def build(user: str, force: bool = False) -> Path | None:
    """Télécharge et rassemble les parties du joueur. Retourne son dossier de données (None : aucune partie)."""
    from rlpi import config, game

    user = safe(user)
    with lock(user):
        gdir, changed = download(user)
        data = cache_root() / user / "data"
        if not any((g / "result.json").exists() for g in gdir.iterdir()):
            return None
        if changed or force or not (data / "features" / f"player_match_stats_{USER_SOURCE}.parquet").exists():
            # On repart d'un dossier propre : les tables du joueur sont entièrement reconstruites
            shutil.rmtree(data, ignore_errors=True)
            data.mkdir(parents=True)
            game.merge(gdir, data, USER_SOURCE)
            link_reference(data, config.DATA, {USER_SOURCE, config.SOURCE, "theo", "perso", "users"})
            _run(user, data, ["synergy"])
        return data


# --------------------------------------------------------------------------------------------------------------
# 3. Tableau de bord


def _env(data: Path) -> dict:
    from rlpi.config import MODELS

    src = Path(__file__).resolve().parents[1]
    e = os.environ | {"RLPI_DATA": str(data), "RLPI_SOURCE": USER_SOURCE, "RLPI_MODELS": str(MODELS),
                      "RLPI_USERS_CACHE": str(cache_root()), "PYTHONIOENCODING": "utf-8"}
    e["PYTHONPATH"] = os.pathsep.join([str(src), e.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return e


def _run(user: str, data: Path, args: list[str]) -> str:
    p = subprocess.run([sys.executable, "-m", "rlpi.players", "_inner", "--user", user, *args], env=_env(data),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    if p.returncode != 0:
        raise RuntimeError(f"rlpi.players {args[0]} ({user}) : {(p.stderr or p.stdout)[-1500:]}")
    return p.stdout


def payload(user: str, data: Path, j: str | None, since: str | None, until: str | None,
            avec: list[str], sans: list[str]) -> dict:
    """Contenu du tableau de bord du joueur (même structure que dans rlpi.serve) ; `data` vient de build()."""
    args = ["payload"] + (["--j", j] if j else []) + (["--since", since] if since else []) \
        + (["--until", until] if until else []) + (["--avec", ",".join(avec)] if avec else []) \
        + (["--sans", ",".join(sans)] if sans else [])
    out = _run(safe(user), data, args)
    return json.loads(out.strip().splitlines()[-1])


def _profile_ids(user: str) -> tuple[list[str], dict[str, str], list[dict]]:
    """Exécuté dans le processus fils : joueur suivi (profil ou le plus présent) et ses coéquipiers fréquents."""
    import polars as pl

    from rlpi.config import FEATURES, FRAMES

    prof_f = cache_root() / user / "profile.json"
    prof = json.loads(prof_f.read_text(encoding="utf-8")) if prof_f.exists() else {}
    st = pl.read_parquet(FEATURES / f"player_match_stats_{USER_SOURCE}.parquet",
                         columns=["player_id", "player_name", "date", "replay_file", "team"])

    def resolve(q: str) -> str | None:
        d = st.filter((pl.col("player_id") == q) | (pl.col("player_name").str.to_lowercase() == q.lower()))
        return None if d.is_empty() else d["player_id"].mode()[0]

    me = resolve(prof["player"]) if prof.get("player") else None
    if me is None:  # le joueur présent dans le plus de parties
        cnt = Counter(p["id"] for f in (FRAMES / USER_SOURCE).glob("*.meta.json")
                      for p in json.loads(f.read_text(encoding="utf-8"))["players"])
        me = next((pid for pid, _ in cnt.most_common() if not st.filter(pl.col("player_id") == pid).is_empty()),
                  st["player_id"].mode()[0])
    if prof.get("compare"):
        peers = [p for p in (resolve(q) for q in prof["compare"]) if p and p != me]
    else:  # coéquipiers présents dans au moins 5 parties avec lui (2 au plus)
        mine = st.filter(pl.col("player_id") == me).select("replay_file", "team")
        mates = st.join(mine, on=["replay_file", "team"]).filter(pl.col("player_id") != me)
        top = mates.group_by("player_id").agg(pl.len().alias("n")).filter(pl.col("n") >= 5).sort("n", descending=True)
        peers = top["player_id"].head(2).to_list()
    ids = [me, *peers]
    names = {pid: st.filter(pl.col("player_id") == pid).sort("date")["player_name"][-1] for pid in ids}
    days = (st.filter(pl.col("player_id") == me).unique("replay_file")
            .with_columns(pl.col("date").str.slice(0, 10).alias("d")).group_by("d").agg(pl.len().alias("n"))
            .sort("d").to_dicts())
    return ids, names, days


def _inner(a: argparse.Namespace) -> None:
    """Exécuté dans le processus fils (RLPI_DATA = dossier du joueur)."""
    from rlpi.config import SOURCE

    assert SOURCE == USER_SOURCE
    if a.cmd2 == "synergy":
        from rlpi import synergy

        synergy.run(SOURCE, None)
        return
    from rlpi.dashboard import make_payload

    ids, names, days = _profile_ids(a.user)
    sel = a.j if a.j in ids else ids[0]
    avec = [x for x in (a.avec or "").split(",") if x in ids and x != sel]
    sans = [x for x in (a.sans or "").split(",") if x in ids and x != sel and x not in avec]
    try:
        pay, err = make_payload(sel, [i for i in ids if i != sel], a.since, a.until, avec, sans), None
    except SystemExit as e:  # aucune partie pour ce filtre
        pay, err = None, str(e)
    out = {"dynamic": True, "default": sel, "order": ids, "names": names, "days": days,
           "filters": {"j": sel, "du": a.since, "au": a.until, "avec": avec, "sans": sans},
           "profiles": {sel: pay} if pay else {}, "error": err}
    sys.stdout.flush()
    print(json.dumps(out, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description="Espace joueur")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--user", required=True)
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("payload")
    s.add_argument("--user", required=True)
    s = sub.add_parser("_inner")
    s.add_argument("--user", required=True)
    s.add_argument("cmd2", choices=["synergy", "payload"])
    for k in ("--j", "--since", "--until", "--avec", "--sans"):
        s.add_argument(k)
    a = ap.parse_args()
    if a.cmd == "_inner":
        _inner(a)
    elif a.cmd == "sync":
        print(build(a.user, a.force))
    else:
        data = build(a.user)
        if data is None:
            raise SystemExit(f"aucune partie traitée pour {a.user}")
        p = payload(a.user, data, None, None, None, [], [])
        print(json.dumps({k: v for k, v in p.items() if k != "profiles"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
