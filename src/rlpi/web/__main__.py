"""Serveur de développement : python -m rlpi.web [--host 127.0.0.1] [--port 8765] [--workers 1]

En production (image Docker) : uvicorn --factory rlpi.web.main:create_app (voir Dockerfile).
"""

from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.getenv("RLPI_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8765")))
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    print(f"Site sur http://{a.host}:{a.port}/ (documentation de l'API : /docs, Ctrl+C pour arrêter)", flush=True)
    uvicorn.run(
        "rlpi.web.main:create_app",
        factory=True,
        host=a.host,
        port=a.port,
        workers=a.workers,
        access_log=False,
    )


if __name__ == "__main__":
    main()
