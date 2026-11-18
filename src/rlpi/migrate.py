"""Migrations de la base Postgres avec Flyway (schéma « DB first » : fichiers SQL de migrations/).

    python -m rlpi.migrate            # flyway migrate, puis vérification de la version (avant le serveur)
    python -m rlpi.migrate info       # état des migrations (flyway info)
    python -m rlpi.migrate validate   # sommes de contrôle des migrations déjà passées (flyway validate)

Lancé au démarrage du conteneur du serveur, avant le serveur web (voir Dockerfile) : Flyway et Java y sont installés,
les migrations sont dans /app/migrations. Les workers ne migrent pas : ils attendent que la base soit à jour.

Flyway lit sa configuration dans des variables FLYWAY_* calculées ici à partir de DATABASE_URL (le mot de passe
n'est jamais affiché). Une base existante sans historique Flyway (la production d'avant Flyway) est marquée à la
version 1 sans rien exécuter (baselineOnMigrate) ; une base vide reçoit toutes les migrations. Flyway pose un
verrou : deux lancements simultanés ne migrent pas deux fois.

Variables : DATABASE_URL ; FLYWAY_BIN (défaut « flyway ») ; RLPI_MIGRATIONS (défaut <racine>/migrations).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from rlpi import logs, store

ROOT = Path(__file__).resolve().parents[2]


def flyway_env(database_url: str, locations: Path) -> dict[str, str]:
    """Variables FLYWAY_* pour une URL postgresql://utilisateur:mot_de_passe@hôte:port/base?options."""
    u = urlsplit(database_url)
    if u.scheme not in ("postgres", "postgresql") or not u.hostname:
        raise SystemExit("DATABASE_URL doit être de la forme postgresql://utilisateur:mot_de_passe@hôte:port/base")
    host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
    jdbc = f"jdbc:postgresql://{host}:{u.port or 5432}{u.path or '/'}" + (f"?{u.query}" if u.query else "")
    return {
        "FLYWAY_URL": jdbc,
        "FLYWAY_USER": unquote(u.username or ""),
        "FLYWAY_PASSWORD": unquote(u.password or ""),
        "FLYWAY_LOCATIONS": f"filesystem:{locations}",
        "FLYWAY_BASELINE_ON_MIGRATE": "true",
        "FLYWAY_BASELINE_VERSION": "1",
        "FLYWAY_BASELINE_DESCRIPTION": "schema de production avant Flyway",  # sans apostrophe : Flyway la colle telle quelle dans du SQL
        "FLYWAY_CONNECT_RETRIES": "12",  # Postgres pas encore prêt (redémarrage du serveur) : ~1 min d'attente
        "FLYWAY_VALIDATE_MIGRATION_NAMING": "true",
        "FLYWAY_CLEAN_DISABLED": "true",  # « flyway clean » efface tout : interdit
    }


def flyway(command: str) -> int:
    locations = Path(os.getenv("RLPI_MIGRATIONS") or ROOT / "migrations")
    if not any(locations.glob("V*__*.sql")):
        raise SystemExit(f"Aucune migration dans {locations}")
    env = os.environ | flyway_env(store.url("DATABASE_URL", ("postgres://", "postgresql://")), locations)
    args = [os.getenv("FLYWAY_BIN", "flyway"), command]
    if not logs.json_mode():
        return subprocess.call(args, env=env)
    # Journaux en JSON (image Docker) : chaque ligne de Flyway devient une ligne de rlpi.logs
    with subprocess.Popen(
        args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace"
    ) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.strip():
                logs.log(line.rstrip(), outil="flyway")
    return proc.returncode


def main() -> None:
    logs.configure(os.getenv("RLPI_SERVICE", "web"))
    cmd = sys.argv[1] if len(sys.argv) > 1 else "migrate"
    if cmd not in ("migrate", "info", "validate"):
        raise SystemExit(__doc__)
    code = flyway(cmd)
    if code != 0:
        raise SystemExit(f"flyway {cmd} a échoué (code {code})")
    if cmd == "migrate":
        with store.connect() as c:  # vérifie aussi que la base a bien la version attendue par ce code
            logs.log(f"Base de données en version {store.schema_version(c)}")


if __name__ == "__main__":
    main()
