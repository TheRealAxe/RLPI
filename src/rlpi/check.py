"""Vérification de l'installation : `python -m rlpi.check`."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version

from rlpi import config

PACKAGES = [
    "python-ballchasing",
    "polars",
    "pyarrow",
    "python-dotenv",
    "requests",
    "PyYAML",
    # installés aux phases suivantes
    "subtr-actor-py",
    "analyzerl-parser",
    "sprocket-carball",
    "scikit-learn",
    "lightgbm",
    "streamlit",
]


def check_versions() -> None:
    print(f"Python {sys.version.split()[0]}")
    for pkg in PACKAGES:
        try:
            v = version(pkg)
        except PackageNotFoundError:
            v = "non installé"
        print(f"  {pkg:<20} {v}")


def check_api() -> bool:
    try:
        api = config.ballchasing_api()
        info = api.ping()
    except Exception as exc:  # noqa: BLE001 — message lisible pour Théo
        print(f"API ballchasing : ÉCHEC ({exc})")
        return False
    print(f"API ballchasing OK (compte : {info.get('name', '?')}, "
          f"type : {info.get('type', '?')})")
    return True


def check_dirs() -> None:
    for d in (config.RAW, config.FRAMES, config.FEATURES, config.MODELS):
        d.mkdir(parents=True, exist_ok=True)
    print(f"Dossiers de données prêts : {config.DATA}")


def main() -> int:
    ok = check_api()
    check_versions()
    check_dirs()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
