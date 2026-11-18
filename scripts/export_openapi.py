"""Écrit la description OpenAPI de l'API (FastAPI) pour générer les types TypeScript de l'interface.

    .venv/Scripts/python scripts/export_openapi.py          # → web/src/api/openapi.json
    cd web && npm run api-types                              # → web/src/api/schema.d.ts (versionné)

Aucune connexion : l'application est seulement construite (pas démarrée). Les variables obligatoires absentes
reçoivent des valeurs factices, le temps de lire le schéma. La CI vérifie que schema.d.ts est à jour.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUMMY = {
    "RLPI_PUBLIC_URL": "http://localhost",
    "RLPI_SECRET": "openapi-seulement-0123456789",
    "DATABASE_URL": "postgresql://x@localhost/x",
    "REDIS_URL": "redis://localhost",
    "S3_ENDPOINT": "http://localhost",
    "S3_ACCESS_KEY": "x",
    "S3_SECRET_KEY": "x",
}


def main() -> None:
    for k, v in DUMMY.items():
        os.environ.setdefault(k, v)
    sys.path.insert(0, str(ROOT / "src"))
    from rlpi.web.main import create_app

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "web" / "src" / "api" / "openapi.json"
    out.write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"OpenAPI écrit dans {out}")


if __name__ == "__main__":
    main()
