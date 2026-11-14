# Plan RLPI v2

Chaque phase a un livrable et des critères de sortie. 🛑 = point de contrôle avec Théo.

---

## Phase 0 — Mise en place

**Objectif** : un projet qui s'installe et se lance proprement.

- Créer l'environnement virtuel, `pyproject.toml`, `.gitignore`, structure `src/rlpi/`.
- Charger `.env` (token ballchasing) et vérifier que l'API répond (ping).
- Vérifier les versions actuelles des librairies candidates (client ballchasing, parseurs).
- Créer `docs/JOURNAL.md`.

**Sortie** : `python -m rlpi.check` affiche « API ballchasing OK » et les versions installées.
🛑 Poser à Théo les questions ouvertes listées dans `CLAUDE.md`.

---

## Phase 1 — Collecte

**Objectif** : constituer le jeu de données d'entraînement et celui des joueurs suivis.

1. **Vérifier l'état de ballchasing** : les groupes RLCS de la saison en cours sont-ils alimentés ?
   Lister les saisons disponibles et le nombre de replays par saison dans le mode choisi.
2. **Script de téléchargement** `rlpi.collect` :
   - RLCS : téléchargement par groupe, en conservant la structure (saison / événement / série).
   - Complément SSL : replays récents du mode choisi, rang minimum Supersonic Legend.
   - Reprise sur incident (ne pas retélécharger ce qui existe), journal des téléchargements.
3. **Joueurs suivis** : documenter dans `docs/UPLOAD_JOUEURS.md` comment chaque joueur envoie ses
   replays sur ballchasing (outils compatibles Easy Anti-Cheat : envoi de l'historique de matchs
   après session, ou surveillance du dossier de replays). Un groupe ballchasing par joueur.

**Sortie** : un manifeste `data/raw/manifest.parquet` (id, source, saison, mode, date, joueurs).
Viser au moins 1 000 matchs RLCS + SSL pour commencer.

---

## Phase 2 — Parsing

**Objectif** : transformer chaque replay en données exploitables.

- Comparer 2 parseurs sur 5 replays : complétude (positions, rotations, vitesses, boost de chaque
  voiture, balle), cadence, vitesse de traitement, robustesse aux versions récentes du jeu.
- Choisir, puis parser tout le lot en Parquet : une table par replay, une ligne par frame.
- Normaliser : coordonnées orientées du point de vue de l'équipe qui attaque, temps en secondes.

**Sortie** : `data/frames/` complet + rapport de qualité (replays en échec, frames manquantes).

---

## Phase 3 — Moments de décision et actions

**Objectif** : savoir *quand* un joueur décide et *ce qu'il a fait*.

1. **Moments de décision** : partir d'une règle simple et la raffiner. Candidats : changement de
   possession, touche adverse, fin de rotation, intervalle fixe (ex. toutes les 0,5 s pour le
   joueur le plus proche de la balle). Documenter le choix.
2. **Classes d'action** (première version) : challenge, tir, passe / centre, dribble,
   shadow défense, rotation arrière, prise de boost, démo / bump, attente (positionnement).
3. **Étiquetage automatique** : déduire l'action des 1 à 2 secondes qui suivent (trajectoire,
   touche, boost ramassé, démo…).

🛑 **Contrôle** : générer 50 exemples aléatoires (vue 2D du terrain + action détectée) dans un
rapport HTML. Théo valide ou corrige. Viser ≥ 85 % d'accord avant de continuer.

---

## Phase 4 — Modèle de valeur

**Objectif** : estimer la valeur de chaque action dans chaque situation.

1. **Valeur d'une situation** V(s) : probabilité de marquer moins probabilité d'encaisser dans les
   N secondes suivantes (tester N = 5 et 10). Variables : positions / vitesses / boost des 4 ou 6
   voitures et de la balle, score, temps restant.
2. **Valeur d'une action** Q(s, a) : variation de V obtenue après l'action a, apprise sur les
   matchs RLCS / SSL.
3. **Validation** : calibration (les probabilités prédites correspondent-elles aux fréquences
   réelles ?), séparation par matchs (jamais les mêmes matchs en entraînement et en test).

🛑 **Contrôle** : sortir les 30 situations où le modèle contredit le plus nettement le choix du
pro. Théo juge : le modèle se trompe-t-il, ou a-t-il vu quelque chose ?

---

## Phase 5 — Score d'adéquation

**Formule de départ** :

```
adéquation = (Q(s, action jouée) − min Q) / (max Q − min Q) × 100
```

- Ne noter que les moments où l'écart entre meilleure et pire action est significatif
  (sinon tout se vaut et le score n'a pas de sens).
- Agréger par joueur et par match, puis sur une période : notes **Décision**, **Lecture**,
  **Rotation dyn** sur 100.
- Calculer aussi les critères mesurables directement (voir `config/criteres_rlpi.yaml`) et les
  ramener sur 100 par rapport à la distribution des joueurs RLCS (centiles).

**Sortie** : une table de notes par joueur au format du RLPI 2020 (6 catégories, 20 critères),
avec pour chaque critère sa source : automatique, modèle, ou manuel.

🛑 **Contrôle** : comparer avec la notation manuelle de Théo sur quelques joueurs.

---

## Phase 6 — Restitution

Application locale (Streamlit ou équivalent), en français :

- Fiche joueur : radar des 6 catégories (comme en 2020), évolution dans le temps, objectif.
- Liste des plays les moins bien notés, avec reconstitution 2D/3D de la situation et l'action
  que le modèle jugeait meilleure.
- Saisie manuelle des critères non automatisables (Calls, Mental, Mindgame…).
- Mise à jour : un bouton qui récupère les nouveaux replays des joueurs suivis et recalcule.

---

## Hors périmètre (pour plus tard)

- Simulation des alternatives avec un simulateur physique (RocketSim / RLGym) pour affiner
  l'évaluation des plays rares.
- Modèles séparés par niveau de jeu.
- Utilisation en direct pendant les matchs via la Stats API officielle.
