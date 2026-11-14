"""Auto-upload des replays Rocket League vers ballchasing.com, sans BakkesMod.

Principe : le jeu enregistre chaque replay sauvegardé dans
`Documents/My Games/Rocket League/TAGame/Demos`. Ce script surveille ce dossier
(simple lecture de fichiers, aucune interaction avec le processus du jeu) et
envoie chaque nouveau replay via l'API ballchasing (`POST /api/v2/upload`).

Usage :
    python -m rlpi.autoupload                 # surveille en continu
    python -m rlpi.autoupload --once          # traite ce qui est en attente puis quitte
    python -m rlpi.autoupload --dry-run       # montre ce qui serait envoyé, n'envoie rien
    python -m rlpi.autoupload --backlog       # envoie aussi les replays déjà présents

Au premier lancement, les replays déjà présents sont marqués comme « vus » sans
être envoyés (sauf --backlog). L'état est gardé dans data/autoupload_state.json.

Astuce : dans le jeu, Réglages > Gameplay > « Sauvegarde auto des replays »
(Auto Save Replays) doit être activé pour que chaque match soit enregistré.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from rlpi import config

UPLOAD_URL = "https://ballchasing.com/api/v2/upload"
STATE_FILE = config.DATA / "autoupload_state.json"
LOG_FILE = config.DATA / "autoupload.log"


def default_demos_dir() -> Path:
    env = os.getenv("RL_DEMOS_DIR", "").strip()
    if env:
        return Path(env)
    docs = Path.home() / "Documents"
    # OneDrive redirige parfois « Documents »
    onedrive = os.getenv("OneDrive")
    candidates = [docs]
    if onedrive:
        candidates.insert(0, Path(onedrive) / "Documents")
    for d in candidates:
        p = d / "My Games" / "Rocket League" / "TAGame" / "Demos"
        if p.is_dir():
            return p
    return docs / "My Games" / "Rocket League" / "TAGame" / "Demos"


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def is_stable(path: Path, wait: float = 2.0) -> bool:
    """Le jeu a fini d'écrire le fichier : taille identique après `wait` s et fichier lisible."""
    try:
        s1 = path.stat().st_size
        time.sleep(wait)
        s2 = path.stat().st_size
        if s1 != s2 or s2 == 0:
            return False
        with path.open("rb"):
            return True
    except OSError:
        return False


def upload(session: requests.Session, path: Path, visibility: str, group: str | None) -> tuple[str, dict]:
    """Retourne (statut, payload). statut ∈ ok | duplicate | retry | error."""
    params = {"visibility": visibility}
    if group:
        params["group"] = group
    with path.open("rb") as f:
        r = session.post(UPLOAD_URL, params=params,
                         files={"file": (path.name, f, "application/octet-stream")}, timeout=120)
    try:
        payload = r.json()
    except ValueError:
        payload = {"raw": r.text[:300]}
    if r.status_code in (200, 201):
        return "ok", payload
    if r.status_code == 409:  # déjà sur ballchasing (envoyé par toi ou un autre joueur)
        return "duplicate", payload
    if r.status_code == 429 or r.status_code >= 500:
        return "retry", payload
    return "error", {"status": r.status_code, **payload}


def run(args: argparse.Namespace) -> int:
    demos = Path(args.demos_dir) if args.demos_dir else default_demos_dir()
    if not demos.is_dir():
        log(f"Dossier de replays introuvable : {demos} (option --demos-dir ou variable RL_DEMOS_DIR)")
        return 1

    state = load_state()
    if state is None:
        state = {"done": {}, "failed": {}}
        if not args.backlog:
            for p in demos.glob("*.replay"):
                state["done"][p.name] = {"status": "preexisting"}
            if not args.dry_run:
                save_state(state)
            log(f"Premier lancement : {len(state['done'])} replays existants ignorés (--backlog pour les envoyer).")
    elif args.backlog:
        # --backlog sur un état existant : on réessaie aussi les « preexisting »
        state["done"] = {k: v for k, v in state["done"].items() if v.get("status") != "preexisting"}

    session = requests.Session()
    if not args.dry_run:
        session.headers["Authorization"] = config.ballchasing_token()

    log(f"Surveillance de {demos} — visibilité « {args.visibility} »"
        + (f", groupe {args.group}" if args.group else "") + (" — DRY-RUN" if args.dry_run else ""))
    backoff = 0.0

    while True:
        pending = sorted(
            (p for p in demos.glob("*.replay") if p.name not in state["done"]),
            key=lambda p: p.stat().st_mtime,
        )
        for p in pending:
            if state["failed"].get(p.name, {}).get("attempts", 0) >= 3:
                continue
            if not is_stable(p):
                continue
            if args.dry_run:
                log(f"[dry-run] serait envoyé : {p.name} ({p.stat().st_size // 1024} Ko)")
                state["done"][p.name] = {"status": "dry-run"}
                continue
            try:
                status, payload = upload(session, p, args.visibility, args.group)
            except requests.RequestException as e:
                status, payload = "retry", {"error": str(e)}

            if status in ("ok", "duplicate"):
                state["done"][p.name] = {"status": status, "id": payload.get("id"),
                                         "url": payload.get("location"),
                                         "at": datetime.now().isoformat(timespec="seconds")}
                state["failed"].pop(p.name, None)
                log(f"{'Envoyé' if status == 'ok' else 'Déjà présent'} : {p.name} → {payload.get('location')}")
                backoff = 0.0
            elif status == "retry":
                backoff = min(max(backoff * 2, 10.0), 600.0)
                log(f"Limite de débit / erreur réseau sur {p.name} ({payload}) — pause {backoff:.0f} s")
                save_state(state)
                time.sleep(backoff)
                break
            else:
                f = state["failed"].setdefault(p.name, {"attempts": 0})
                f["attempts"] += 1
                f["last_error"] = payload
                log(f"Échec {p.name} (tentative {f['attempts']}/3) : {payload}")
                if payload.get("status") in (401, 403):
                    save_state(state)
                    log("Token ballchasing refusé : vérifie BALLCHASING_TOKEN dans .env.")
                    return 2
            save_state(state)

        if args.once:
            return 0
        time.sleep(args.interval)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Auto-upload des replays Rocket League vers ballchasing.com")
    ap.add_argument("--demos-dir", help="dossier des replays (défaut : Documents/My Games/Rocket League/TAGame/Demos)")
    ap.add_argument("--visibility", choices=["public", "unlisted", "private"], default="public")
    ap.add_argument("--group", help="ID d'un groupe ballchasing où ranger les replays")
    ap.add_argument("--interval", type=float, default=15.0, help="secondes entre deux scans (défaut 15)")
    ap.add_argument("--once", action="store_true", help="un seul passage puis quitte")
    ap.add_argument("--backlog", action="store_true", help="envoyer aussi les replays déjà présents")
    ap.add_argument("--dry-run", action="store_true", help="n'envoie rien, n'écrit pas l'état")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        log("Arrêt.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
