# RLPI v2 — Rocket League Player Index

## Contexte

Théo a créé en 2020 le **Rocket League Player Index (RLPI)** : une notation manuelle de joueurs
Rocket League, faite en regardant des replays, sur 6 catégories et 20 sous-critères notés sur 100
(voir `config/criteres_rlpi.yaml` et le fichier d'origine `docs/historique/RLPI_2020.xlsx`).

Le RLPI v2 a deux objectifs :

1. **Automatiser** les critères mesurables (boost, vitesse, précision, 50/50, agressivité…).
2. **Évaluer les décisions** : pour chaque moment de décision d'un joueur, estimer le move le plus
   adapté et attribuer au move réellement joué un **score d'adéquation sur 100**.

Le « meilleur move » est appris à partir de **matchs de haut niveau joués par des humains**
(RLCS en priorité, complétés par des replays Supersonic Legend), et non par simulation de bots :
l'optimum recherché est ce qui fonctionne face à des humains.

Le plan détaillé, phase par phase, est dans `docs/PLAN.md`. Lis-le avant toute chose.

## Règles de travail

- **Langue** : tout ce que Théo lit (messages, rapports, tableau de bord, commentaires de commits)
  est en français. Le code et les noms de variables peuvent être en anglais.
- **Avance phase par phase.** Ne commence pas une phase tant que les critères de sortie de la
  précédente ne sont pas remplis. Tiens `docs/JOURNAL.md` à jour (date, ce qui est fait, décisions,
  problèmes).
- **Points de contrôle** : les étapes marquées 🛑 dans le plan exigent l'avis de Théo. Arrête-toi,
  prépare ce qu'il doit vérifier (échantillon, visualisation, résumé court) et attends sa réponse.
- **Vérifie avant de supposer.** Les librairies Rocket League évoluent vite (parseurs de replays,
  API ballchasing, Stats API du jeu). Vérifie la doc et les versions actuelles avant de les utiliser,
  et note dans le journal les versions retenues.
- **Commence petit** : chaque traitement est d'abord testé sur 1 replay, puis 10, puis le lot complet.
- **Données** : `data/` n'est jamais versionné. Les replays bruts vont dans `data/raw/`, les données
  image par image dans `data/frames/` (Parquet), les variables dérivées dans `data/features/`,
  les modèles dans `data/models/`.

## Secrets et usage des API

- Le token ballchasing est dans `.env` (`BALLCHASING_TOKEN`), jamais dans le code ni dans Git.
- Respecte les limites de débit de l'API ballchasing (utilise la limitation automatique de la
  librairie cliente, ou des pauses explicites). Pas de téléchargement massif en parallèle.
- Ne télécharge que des replays publics, et n'uploade rien au nom de Théo sans qu'il l'ait demandé.

## Stack technique (à confirmer en phase 0)

- Python 3.11+, environnement virtuel dédié.
- Polars ou pandas + PyArrow pour les tables, Parquet pour le stockage.
- Collecte : client Python de l'API ballchasing (ex. `python-ballchasing`).
- Parsing : un parseur donnant les positions image par image (ex. `analyzerl-parser`,
  `sprocket-rl-parser`/carball). Comparer et choisir en phase 2.
- Modèles : scikit-learn / LightGBM pour commencer ; réseau de neurones seulement si nécessaire.
- Restitution : petite application web locale (Streamlit ou équivalent).

## Questions ouvertes à poser à Théo dès la première session

1. Mode de jeu à cibler en premier : 2v2 ou 3v3 ?
2. Dans la catégorie Speed, que désignaient « High » et « Low » : vitesse de jeu (accélérer /
   ralentir) ou jeu aérien / jeu au sol ?
3. Dans l'onglet Référence du fichier 2020, Kaydop a 34 en Rotation dyn (91 dans l'onglet
   précédent) : faute de frappe ?
4. Quels joueurs suivre en v2, et comment récupérer leurs replays (outil d'auto-upload choisi) ?
