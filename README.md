# RLPI v2 — kit de lancement

## Démarrer

1. Crée un compte sur ballchasing.com, puis une clé API (onglet Upload).
2. Copie `.env.example` en `.env` et colle la clé après `BALLCHASING_TOKEN=`.
3. Installe Python 3.11+ et Claude Code (application de bureau).
4. Ouvre ce dossier dans Claude Code et envoie :

> Lis CLAUDE.md et docs/PLAN.md, pose-moi les questions ouvertes, puis lance la phase 0.

Claude Code avance ensuite phase par phase et s'arrête aux points de contrôle 🛑
pour te demander ton avis. Le suivi est dans `docs/JOURNAL.md`.

## Contenu

- `CLAUDE.md` : contexte et règles de travail pour Claude Code
- `docs/PLAN.md` : plan en 6 phases
- `config/criteres_rlpi.yaml` : les 20 critères et leur source en v2
- `docs/historique/RLPI_2020.xlsx` : ton fichier d'origine
