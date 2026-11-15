# Journal RLPI v2

## 2026-11-12 — Phase 0 : mise en place

### Fait
- Environnement virtuel `.venv` (Python 3.13.14), projet installable via `pyproject.toml`
  (`pip install -e .`, extras `model` et `app` pour plus tard).
- `src/rlpi/config.py` : chemins du projet, chargement de `.env`, client ballchasing avec
  limitation de débit proactive (`proactive_rate_limit=True`).
- `src/rlpi/check.py` : `python -m rlpi.check` → ping de l'API, versions, création des dossiers `data/`.
- Résultat : **API ballchasing OK**, compte de type `regular` (pas patron → limites de débit
  les plus basses, à prendre en compte pour la collecte en phase 1).

### Versions retenues (PyPI, vérifiées le 2026-11-12)
| Paquet | Version | Statut |
|---|---|---|
| python-ballchasing | 0.5.4 | installé |
| polars | 2.1.0 | installé |
| pyarrow | 26.0.1 | installé |
| python-dotenv | 1.2.4 | installé |
| requests | 2.34.2 | installé |
| PyYAML | 6.0.3 | installé |
| subtr-actor-py | 1.5.1 | candidat parseur (phase 2) |
| analyzerl-parser | 1.0.5 | candidat parseur (phase 2) |
| sprocket-carball | 1.2.2 | candidat parseur (phase 2) |
| scikit-learn / lightgbm | 1.9.1 / 4.7.0 | phase 4 |
| streamlit | 1.67.0 | phase 6 |

Remarque : `subtr-actor-py` (non listé dans CLAUDE.md) est un parseur image par image activement
maintenu ; il sera ajouté au comparatif de la phase 2.

### Décisions (réponses de Théo)
1. **Mode : 3v3** (playlist ballchasing `ranked-standard`, et RLCS 3v3).
2. **Speed High / Low** : liés au jeu au sol d'après Théo (« je crois »). Sens exact à préciser
   avant de définir les mesures (phase 5) ; non bloquant d'ici là.
3. **Valeurs de l'onglet Référence (ex. Kaydop 34 en Rotation dyn)** : valeurs arbitraires,
   pas une donnée de référence → ne pas s'en servir pour calibrer.
4. **Joueurs suivis et outil d'auto-upload** : pas encore répondu → à traiter en phase 1.

### Problèmes
- Le dossier n'est pas un dépôt Git. À initialiser si Théo veut versionner (`.gitignore` déjà prêt).

## 2026-11-12 — Phase 1 : collecte

### Décisions (Théo)
- Priorité aux **RLCS** et au « **top 100** ». Le top 100 est approché par les replays
  Ranked Standard (3v3) où **tous les joueurs sont SSL** (filtre ballchasing `min-rank=supersonic-legend`).
- Le suivi de joueurs (`docs/UPLOAD_JOUEURS.md`, auto-upload) est reporté à plus tard.

### État de ballchasing
- Replays officiels publiés par le compte **RLCS Referee** (steam `76561199225615730`),
  un groupe racine par saison : RLCS 2026 (7 772 replays, tous modes), RLCS 2025 (7 092),
  RLCS 2024 (7 324), RLCS 22-23 (15 443), RLCS 21-22 (5 915).
- La saison 2026-27 n'est pas encore publiée par ce compte (au 2026-11-12).
- RLCS 2026 en 3v3 (hors épreuves 1v1 / 2v2) : 1 892 groupes, **6 140 replays attendus,
  5 982 indexés** (97 %) : Split 1 Boston 2 570, Split 2 Paris 2 708, LCQ 503, Worlds 201.
- SSL ranked 3v3 : les parties à 6 joueurs SSL sont rares. Les 1 498 plus récentes couvrent
  mai 2024 → avril 2026 (saisons RL 14 à 22).
- Compte « regular » : 500 appels de liste/h, **200 téléchargements/h**, ~1,8 Mo par replay.

### Script `rlpi.collect`
- `index-rlcs` : arborescence des groupes (mise en cache dans `groups_rlcs.parquet`), puis liste
  des uploads du Referee (200 par appel) rattachés à leur groupe → `index_rlcs.parquet`.
- `index-ssl` → `index_ssl.parquet`.
- `download` : du plus récent au plus ancien, reprise automatique (fichier `.part` puis renommage),
  journal `downloads.jsonl`, contrôle de taille minimale.
- `manifest` → `data/raw/manifest.parquet` (reconstruit après chaque téléchargement).

### Problèmes rencontrés
- python-ballchasing 0.5.4 envoie `sort-by=upload-date`, refusé par l'API (400 : valeurs
  acceptées `replay-date` ou `created`). Contourné en passant `sort_by="created"`.

### Tests
- 1 replay, puis 10 RLCS et 2 SSL : 12/12 OK, en-tête `TAGame.Replay_Soccar_TA` vérifié.
- Lot lancé : 990 RLCS (les plus récents) puis 298 SSL, ~6 h 30 au débit du compte.

## 2026-11-12 — Prototype de dashboard (hors séquence, demandé par Théo)

Réalisé en parallèle de la collecte, avant la phase 2, pour tester un premier rendu sur les
replays de Théo. Ne remplace pas le comparatif de parseurs prévu en phase 2.

### Fait
- Parseur installé : **subtr-actor-py 1.5.1** (+ numpy 2.5.4). Sa fonction `get_summed_stats`
  fournit déjà ~200 stats par joueur et par match (boost, mouvement, rotation 1er/2e/3e homme,
  50/50, touches, whiffs, passes, démos, bumps…). ~11 s par replay.
- `src/rlpi/stats.py` : `python -m rlpi.stats --source theo --dir <Demos> --online-3v3` et
  `--source rlcs --limit 40` → `data/features/player_match_stats_<source>.parquet`.
- `src/rlpi/dashboard.py` + `dashboard_template.html` : `python -m rlpi.dashboard --player "Steam:76561198078330309"`
  → `reports/dashboard_prototype.html` (page autonome, en français).
- Données : 23 replays locaux de Théo (`Documents/My Games/Rocket League/TAGame/Demos`) →
  **14 parties classées en ligne 3v3** retenues (08/2023 → 09/2026). Référence : 40 matchs RLCS
  (Worlds 2026), 48 joueurs. Aucun échec de parsing.
- Théo = « Axe », identifiant `Steam:76561198078330309`.

### Méthode
- 26 indicateurs normalisés (par 5 min de jeu ou en % du temps), moyenne par joueur.
- Centile de Théo face aux moyennes des joueurs RLCS (≥ 2 matchs). Note de catégorie = moyenne
  des centiles des indicateurs à sens clair (orientés « plus haut = mieux ») ; les indicateurs
  de style (boost moyen, temps en 1er homme, temps en l'air…) sont affichés sans entrer dans la note.

### Problèmes
- 5 replays plantaient sur une métadonnée absente (`game_type`/`stats` à None) → corrigé.
- L'en-tête `WinningTeam` manque parfois → victoire déduite du score.
- Comparaison classée vs pro biaisée (buts / 5 min bien plus élevés en classée) : à remplacer par
  une référence SSL quand le lot SSL sera téléchargé.

### Référence SSL (même jour)
- Le dashboard accepte plusieurs références : sélecteur « vs SSL / vs RLCS » en haut de page
  (choix mémorisé dans le navigateur). SSL devient la référence par défaut dès 30 joueurs SSL.
- Moyenne par joueur : ≥ 2 matchs pour RLCS, ≥ 1 pour SSL (un joueur SSL apparaît rarement
  plusieurs fois). Les bots sont exclus, et Théo est retiré des références.
- État : seulement **4 replays SSL** téléchargés (18 joueurs), insuffisant. Le lot RLCS en cours
  (`download --source rlcs --limit 990`, 160/990 à 15 h 25) occupe le quota de 200 téléchargements/h ;
  le passage aux SSL demande de mettre ce lot en pause (arrêt du processus, puis reprise automatique).

## 2026-11-12 — Étape 1 du modèle de valeur (phases 2 et 4 en version prototype)

Demandé par Théo : aller vers « play optimal vs mon play ». Première brique = valeur d'une situation
et valeur ajoutée par touche. Le comparatif de parseurs (phase 2) et le 🛑 de la phase 3 restent à faire.

### Données image par image — `python -m rlpi.frames --source rlcs`
- subtr-actor `get_ndarray_with_info_from_replay_filepath`, **10 images/s**, ~0,2 s par replay.
  Adders retenus : `BallRigidBody`, `SecondsRemaining`, `ReplicatedGameStateTimeRemaining`,
  `ReplicatedStateName` ; joueurs `PlayerRigidBody`, `PlayerBoost`, `PlayerDemolishedBy`.
- Ordre des colonnes joueurs = `team_zero` puis `team_one` du replay (vérifié sur les buteurs).
  L'équipe 0 marque en y > 0. `rz` = cap (lacet) de la voiture.
- L'état de jeu est un **index de nom variable selon le replay** : déduit par replay
  (jeu = état le plus fréquent, attente = 1re image, but = l'état restant).
- But = la balle franchit la ligne **et** le jeu passe en état « but » dans la seconde
  (sinon arrêt sur la ligne : 8 faux buts éliminés ainsi).
- Touches : flux `touch` de `get_stats_events` (joueur, type shot/save/clear/pass/boom…),
  index = (temps − temps de l'image 0) × 10. Distance balle-joueur médiane à la touche : 212 uu.
- Résultat : 250 replays RLCS + 23 de Théo, 0 échec ; 2 replays avec un nombre de buts ≠ en-tête
  (écartés de l'apprentissage). Fichiers dans `data/frames/<source>/`, rapport `quality_<source>.parquet`.

### Modèle de valeur — `python -m rlpi.value train --horizon 5`
- Cible : l'équipe T marque dans les H secondes. Terrain retourné pour que T attaque vers y > 0,
  un seul modèle pour les deux équipes ; V_T = P_T − P_adverse.
- 99 variables : balle (position, vitesse, temps et point d'arrivée sur chaque ligne de but),
  3 coéquipiers et 3 adversaires triés par distance à la balle (position, vitesse, boost, démoli,
  vitesse de rapprochement, orientation vers la balle, du bon côté), temps restant, écart au score.
- LightGBM, séparation **par match** (200 apprentissage / 49 test), 1 situation sur 2 (5 i/s).
- **H = 10 s : AUC 0,71**, sous-estime les situations très dangereuses.
  **H = 5 s : AUC 0,87**, bien calibré (annoncé 7 % → observé 7 %, 24 % → 24 %, 38 % → 40 %) ;
  un peu prudent au-delà de 70 % (82 % → 95 %). **H = 5 s retenu.**
- Remarque : subtr-actor propose un modèle de menace intégré (`ThreatModelValues`) ; non utilisé
  (le plan demande un modèle appris sur RLCS), à garder comme point de comparaison.

### Valeur des touches — `python -m rlpi.value touches --source rlcs|theo --horizon 5`
- ΔV = V(juste avant la touche suivante, 1 s max) − V(0,2 s avant la touche) ; ±1 si but entre les deux.
- RLCS (60 723 touches) : tirs +0,147, arrêts +0,103, dégagements +0,024, frappes fortes +0,013,
  passes +0,002, contrôles +0,004.
- Note par match = centile de la somme des ΔV par 5 min de jeu face aux 1 500 matchs-joueurs RLCS.
- Théo (14 parties) : note moyenne 66/100, +1,62 / 5 min (médiane RLCS +0,89). L'écart vient
  surtout des tirs (+0,35 contre +0,15) : effet probable du niveau des défenses en classée.

### Limites connues
- Ne mesure que les touches : rien sur le placement sans ballon ni sur le choix entre options.
- ΔV mélange décision et exécution ; biais positif moyen (+0,027 par touche).
- Référence pro vs parties classées : à recalibrer avec une référence SSL.

## 2026-11-12 — Correction du biais « niveau RLCS » (Théo : « on dirait que j'ai le niveau RLCS »)

### Diagnostic
- Note de valeur ajoutée 66/100 vs RLCS trompeuse. Deux causes mesurées :
  1. En classé, **1,5× plus de buts** que prévu par le modèle RLCS (taux à 5 s : 4,9 % vs 3,3 %) ;
     un tir y vaut +0,25 en moyenne contre +0,15 en RLCS → le résultat des touches est gonflé par
     la faiblesse des défenses adverses.
  2. La note mesurait le **résultat** des touches, pas la **décision**. Théo est au-dessus de ses
     lobbies (66 vs 44) : c'est un niveau relatif à son lobby.

### Nouvelles mesures — `src/rlpi/decisions.py`
- **Résultat des touches** : désormais comparé aux autres joueurs des mêmes parties (lobby).
- **Choix à la touche** (`python -m rlpi.decisions touches`) : actions définies par l'intention
  (direction donnée à la balle : tir vers le but cadré ou non, avant, latéral, arrière, contrôle),
  pas par la réussite. Policy P(a|s) (57 % de bonnes prédictions vs 36 % classe majoritaire) et
  Q(s,a) (R² hors échantillon 0,256 vs 0,113 avec la seule moyenne par action), validation croisée
  5 plis par match. Regret = Q(meilleure option réaliste) − Q(jouée).
  Essais ΔV à 2 s / 3 s : R² 0,08 / 0,06 → abandonnés, on garde ΔV jusqu'à la touche suivante (1 s max).
  Limite : le tir sort toujours « meilleure option » et le jeu arrière « pire » (la valeur à 5 s ne
  récompense pas la conservation du ballon). Mesure marquée **expérimentale**.
- **Placement hors ballon** (`python -m rlpi.decisions placement`) : pour le 2e et le 3e homme, un
  modèle RLCS prédit la position (x, y) d'un pro dans la même situation. Écart médian 17,3 m pour
  les pros hors échantillon (34,1 m sans modèle).

### Résultats (14 parties de Théo)
| Mesure | Pros RLCS | Théo | Autres joueurs de ses parties |
|---|---|---|---|
| Écart de placement (médiane) | 17,3 m | 18,6 m | 18,9 m |
| Regret moyen au choix | 0,024 | 0,035 | 0,030 |
| Note placement / 100 (50 = pro médian) | 50 | 30 | 28 |
| Note choix / 100 | 50 | 29 | 42 |
| Résultat des touches vs lobby | — | 70 (rang moyen 2,9/6) | 50 |

- Les deux mesures « vs pros » classent bien pros > lobbies, mais les écarts sont faibles par
  rapport au bruit d'un match : une note 30 ne veut pas dire « meilleur que 30 % des pros ».
  Il faut une échelle intermédiaire (référence SSL) pour lire ces notes en niveau.

## 2026-11-12 — Ajout des replays récents de Théo (`setTest2026/`)
- 10 parties classées 3v3 d'avril 2026 (fichiers ballchasing), Théo présent dans toutes.
- `rlpi.stats` et `rlpi.frames` acceptent plusieurs dossiers (`--dir A B`) ; doublons écartés par
  `MatchGUID`. Nouvelle commande `python -m rlpi.decisions placement-theo` : note le placement
  avec les modèles déjà entraînés (sans réentraîner).
- Commande complète pour Théo :
  `--dir "<Documents>/My Games/Rocket League/TAGame/Demos" setTest2026` pour stats et frames, puis
  `rlpi.value touches --source theo --horizon 5`, `rlpi.decisions placement-theo`,
  `rlpi.decisions touches`, `rlpi.dashboard`.
- Total : 24 parties (16 victoires). Placement 32/100 vs pros (lobbies 28), choix 27 (lobbies 43),
  résultat des touches vs lobby 56 (rang moyen 3,5/6).
- Écart entre les deux lots : anciens replays (14) résultat/lobby 70, rang 2,9 ; avril 2026 (10)
  résultat/lobby 37, rang 4,4. Hypothèse : les replays sauvegardés à la main sont des parties
  « mémorables » (biais de sélection), alors que le lot d'avril est une session complète.

## 2026-11-12 — Comparaison avec les coéquipiers LAinox et Rileq
- `python -m rlpi.dashboard --player "Steam:76561198078330309" --compare LAinox Rileq`
  (pseudos ou identifiants). LAinox = `Steam:76561198102768137` (16 parties, toutes avec Théo),
  Rileq = `Steam:76561198185727581` (8 parties, 2026). Toujours coéquipiers de Théo.
- Dashboard : polygones sur le radar, marqueurs sur chaque indicateur et sur les jauges des modèles,
  tableau face-à-face sur les parties communes (mêmes adversaires). Couleurs : Théo bleu (losange),
  LAinox orange (rond), Rileq vert (carré) ; palette validée (CVD toutes paires ΔE ≥ 9,2 ; le vert
  < 3:1 en clair → formes distinctes + valeurs écrites dans le tableau).
- Sur les parties communes :
  - vs LAinox (16) : Théo meilleur placement (32 vs 19) et résultat comparable (47 vs 46) ;
    LAinox meilleurs choix à la touche (40 vs 24), plus rapide (56 vs 54 km/h, 17 % vs 10 % supersonique).
  - vs Rileq (8) : Rileq meilleur résultat (60 vs 32, rang 2,8 vs 4,4) et 50/50 (56 % vs 46 %) ;
    Théo meilleurs choix (31 vs 22), plus de passes, moins de temps à 0 boost.

## 2026-11-12 — Passes tentées vs récupérées (`python -m rlpi.passes`)
- Question de Théo : il fait beaucoup de passes, parfois « dans le vide » (bonne passe au milieu,
  aucun coéquipier pour la récupérer). Avant : seules les passes RÉUSSIES étaient comptées
  (module pass de subtr-actor) ; une passe non récupérée était invisible en tant que passe.
- « Balle donnée » = touche vers l'avant / le côté / l'arrière (intention par la direction), hors
  tirs, conduites et tiers défensif. Issue = premier autre joueur à toucher. « Coéquipier en position »
  = 1 s après, le coéquipier le plus proche de la balle est plus près que l'adversaire le plus proche.

| Joueur | Balles données / 5 min | Récupérées par un coéquipier | Coéquipier en position | ΔV 2 s si personne en position |
|---|---|---|---|---|
| Pros RLCS | 12,6 | 29 % | 20 % | −0,002 |
| Théo | 13,7 | 41 % | 32 % | −0,006 |
| LAinox | 13,4 | 42 % | 36 % | +0,003 |
| Rileq | 16,9 | 29 % | 23 % | −0,007 |
| Autres joueurs de ses parties | 11,6 | 30 % | 26 % | −0,008 |

- Lecture : Théo donne la balle un peu plus que les autres et elle arrive plus souvent à un
  coéquipier (41 % vs 30 % dans ses lobbies). 2/3 de ses balles partent sans coéquipier en position
  à 1 s ; 30 % d'entre elles sont quand même récupérées, et leur coût moyen est faible (−0,006).
- Les pros « réussissent » moins (29 %) : ils jouent beaucoup dans l'espace et sous pression ; ce
  taux n'est donc pas un objectif en soi. La fenêtre de 1 s est grossière (une passe longue
  peut être récupérée plus tard). Non encore affiché dans le dashboard.
- Section « Passes » ajoutée au dashboard (tableau par groupe, taux de récupération par partie,
  10 passes dans le vide les plus coûteuses avec horloge et position). Observation : ces passes
  dans le vide sont presque toutes jouées dans le tiers offensif (centres / remises sans preneur).

## 2026-11-12 (soir) — 1 000 matchs RLCS, détection des buts corrigée, gestes techniques (test 10 matchs)
- Import RLCS terminé : 1 004 replays, 0 échec ; 1 000 analysés image par image (`rlpi.frames`).
- **Bug corrigé — détection des buts** : 176 replays récents avaient 0 but détecté (le code d'état qui suit
  un but diffère selon la version du jeu). Nouvelle règle : la balle franchit la ligne ET le jeu s'arrête
  dans les 1,5 s ; phase « but » = premier bloc hors jeu qui suit. Résultat : 996/1 000 replays RLCS et
  33/33 de Théo ont le même nombre de buts que l'en-tête (avant : 824/1 000). Recalcul sans re-parser :
  `python -m rlpi.frames --source rlcs --fix-goals`.
- Modèle de valeur (H = 5 s) réentraîné sur 996 matchs : AUC 0,866 → **0,884** (test sur 199 matchs au
  lieu de 49), calibration bonne de 0 à 100 %.
- **Gestes techniques** (`src/rlpi/mechanics.py`) : subtr-actor fournit des détecteurs de dodge/flip reset,
  air dribble, ceiling shot, flick, double tap, wall aerial. Test sur 10 matchs RLCS : 64 resets sur la
  balle, dont 62 « aériens » (joueur en l'air depuis 0,3 s, contact au-dessus de 300 uu) ; 27 utilisés,
  33 non utilisés. Point suspect : la moitié des resets « utilisés » sont suivis d'un flip en ≤ 0,1 s
  (vrai reset ou flip dans la balle ?).
- Réponse défensive classée au moment du reset (bas / challenge / ailleurs). Sur 10 matchs, 62 cas :
  **aucune conclusion possible** à cette taille, c'est un test du pipeline.
- 🛑 Page de vérification : `reports/resets_verification.html` (20 resets en vue 2D dessus + côté, Théo juge
  « vrai reset ? » et « défense bien classée ? »). L'étude sur 1 000 matchs attend son retour.

## 2026-11-12 (nuit) — Refonte de la page de stats
- Gestes techniques mis de côté à la demande de Théo (code conservé dans `src/rlpi/mechanics.py`).
- `reports/dashboard_prototype.html` refait (gabarit `src/rlpi/dashboard_template.html`, ancien gabarit
  non conservé dans le dépôt). Une forme de visuel par type de donnée :
  - Synthèse : 5 tuiles (victoires + forme, rang dans la partie, placement, résultat des touches,
    passes récupérées) avec mini-courbe par match et valeurs des coéquipiers.
  - Points forts : catégories en « dot plot » 0–100 (remplace le radar) + notes des modèles ;
    barres divergentes de chaque indicateur autour de la médiane de la référence.
  - Style de jeu : 7 barres empilées à 100 % (rôle, zone, position / balle, boost, hauteur, vitesse,
    type de touche) — toi, coéquipiers, lobbies, référence.
  - Terrain : 3 cartes de chaleur 8×10 (présence, écart avec les pros, touches : taille = nombre,
    couleur = gain moyen) sur 200 matchs RLCS.
  - Match par match : courbe avec moyenne glissante sur 5 parties et bande interquartile de la
    référence ; gain moyen par type de touche (points toi / pros) ; déroulé d'un match en aire ±.
  - Coéquipiers : barres face-à-face vers celui qui a l'avantage. Passes : issues en barres empilées.
- Couleurs : identité (toi bleu, LAinox orange, Rileq aqua) ; échelle ordonnée violette pour les
  répartitions et la présence ; divergente bleu ↔ rouge pour les écarts. Rampes vérifiées avec
  `validate_palette.js` (clair et sombre, `--ordinal`).
- Vérifié : aucune erreur console, mode clair et sombre, mobile 375 px sans défilement horizontal.
- Aperçu local : `python -m http.server 8765 --directory reports`.

## 2026-11-12 — Auto-upload sans BakkesMod

- BakkesMod n'est plus autorisé → nouveau module `src/rlpi/autoupload.py` : surveille le dossier
  `Documents/My Games/Rocket League/TAGame/Demos` (lecture de fichiers seulement, aucun lien avec le jeu)
  et envoie chaque nouveau replay via `POST https://ballchasing.com/api/v2/upload`.
- 409 (doublon) traité comme succès ; 429 / 5xx → pause exponentielle (10 s à 10 min) ; 3 essais max sur les autres erreurs.
- Premier lancement : replays existants ignorés (sauf `--backlog`). État : `data/autoupload_state.json`, journal : `data/autoupload.log`.
- Lanceur sans fenêtre : `autoupload.cmd`. Testé en `--dry-run` sur les 23 replays locaux ; aucun envoi réel fait.

### Résultat (2026-11-12, 21 h 18)
- **1 302 replays téléchargés, 0 échec** : 1 000 RLCS 2026 (Worlds 201, LCQ 501, Split 2 Paris 298)
  et 302 SSL. 2,4 Go dans `data/raw/`.
- Manifeste `data/raw/manifest.parquet` : 1 302 lignes uniques, tous les fichiers ont un en-tête valide.
- Critère de sortie de la phase 1 atteint (≥ 1 000 matchs).
- Limite : l'échantillon RLCS est concentré sur la fin de saison (LCQ, Worlds, Split 2). Compléter
  plus tard avec Split 1 si besoin de diversité (`download --source rlcs` reprend où il s'est arrêté).

## 2026-11-12 (nuit, suite) — Indice de performance, référence SSL complète, info-bulles
- SSL : 302 replays téléchargés ; stats recalculées (723 joueurs, 301 parties) ; images 10 i/s (299 OK,
  3 échecs), valeur des touches (61 936 touches) et placement notés (`decisions placement-score --source ssl`).
- **Indice de performance** (`src/rlpi/perf.py`) : 7 composantes par joueur-match (impact ΔV/5 min,
  placement, 50/50, temps à 0 boost, vitesse, ratés, passes), centrées-réduites sur 1 758 joueurs-matchs SSL ;
  poids = régression logistique (victoire) régularisée, poids négatifs à 0 ; indice = centile du score
  pondéré parmi les SSL (50 = SSL médian). Poids : impact 56 %, boost 18 %, passes 12 %, vitesse 10 %,
  50/50 3 %, placement 1 %, ratés 0 %.
  Validation : l'équipe au meilleur indice moyen gagne 85 % des parties SSL (hors échantillon) et 78 % des
  23 parties de Théo ; AUC joueur 0,70.
  Théo : **55/100** (fourchette bootstrap 80 % : 48–62) ; LAinox 55, Rileq 47, lobbies 43.
- Page : bloc indice en tête (global, match par match, détail du match cliqué) ; toutes les descriptions
  passées en info-bulles « ? » décrivant la méthode exacte ; définition de chaque indicateur au survol.
- Section « Comment ça marche » ajoutée à la page : 10 fiches (indice de performance, valeur de la
  situation, gain d'une touche / impact, résultat et rang, placement hors ballon, choix à la touche,
  centiles et références, passes, répartitions du temps, cartes du terrain), chacune avec : ce que ça
  mesure, calcul pas à pas, exemple, lecture, limites. Les noms de valeurs dans la page renvoient à leur fiche.
- Retour de Théo : l'indice le place « niveau SSL » alors qu'il est GC1, lent et en difficulté dans le jeu
  aérien à plusieurs touches. Constat : l'indice mesure la performance **relative à la partie** (ses lobbies
  GC obtiennent 45, presque comme des SSL entre eux) ; l'impact des touches (56 %) dépend du niveau adverse.
  → Libellés corrigés (« par rapport aux joueurs de ta partie », « ce n'est pas un niveau »).
- Nouvelle section « Technique » : vitesse, supersonique, temps lent, temps en l'air haut, touches
  aériennes (hautes / toutes), touches au mur, aériens ratés, battu sur la balle ; toi vs lobbies GC, SSL
  (bande 25–75 %), pros. Théo est sous ses propres lobbies GC en supersonique (10,5 % vs 14,5 %), vitesse,
  temps lent, aériens ratés et battu sur la balle ; 6e centile SSL en supersonique, 24e en touches aériennes hautes.
- À faire pour un vrai indice de niveau : replays publics de plusieurs rangs (Champion → SSL) et mesures du
  jeu aérien à plusieurs touches (air dribbles, enchaînements), à vérifier à l'œil avant affichage.

## 2026-11-12 (nuit, fin) — Jeu de jugement « swipe » (indice humain, séparé du modèle)
- Idée de Théo : juger des actions comme sur Tinder (droite = bien, gauche = pas bien, haut = je ne sais pas),
  pour construire un indice humain indépendant des modèles.
- Lecteur : 3D libre écartée (moins lisible), vue tactique de dessus testée, puis **vue isométrique** retenue :
  voitures en volume orientées avec les vecteurs avant / haut du replay (`PlayerRigidBodyBasis`), face avant
  blanche + flèche sur le toit, ombres au sol + trait vertical pour la hauteur, jauge de boost, flamme quand il
  boost, caméra qui suit l'action (rotation de la vue, vue de dessus). Le replay est enregistré à 30 i/s
  (`RecordFPS`) : rendu fluide à la fréquence de l'écran par interpolation d'Hermite avec les vitesses.
  Indicateurs de saut / flip de subtr-actor (`PlayerJump`) inutilisables (toujours à 1) : non affichés.
- `src/rlpi/swipe.py` : paquet de cartes à l'aveugle, 3 s avant / 1 s après la touche (on juge la décision, pas
  le résultat), tirage stratifié : Théo 40 %, coéquipiers 15 %, lobbies 15 %, SSL 15 %, RLCS 15 %.
  `python -m rlpi.swipe --n 40` → `reports/swipe/deck.json` (40 cartes, 4,9 Mo).
- Page `reports/swipe/index.html` (servie par `python -m http.server 8765 --directory reports`) : grande carte,
  boutons à gauche / en haut / à droite, glisser la carte, flèches du clavier, annuler, export JSON des votes
  (gardés dans le navigateur). À faire : cartes répétées pour mesurer la cohérence, calcul de l'indice humain.
- Saccades corrigées : dans les replays, les voitures ne sont mises à jour qu'environ une image sur deux
  (≈ 15 Hz, réplication réseau) → positions figées puis sauts, aggravés par l'interpolation. Lecture du replay
  à 120 i/s, détection des vraies mises à jour, trajectoire reconstruite entre elles (Hermite avec les vitesses),
  puis clip livré à 30 i/s. Résultat : 0 image figée ; rendu mesuré à ~160 i/s dans le navigateur sans à-coup.

## 2026-11-13 — Nettoyage des pages

- `reports/` réorganisé :
  - `index.html` : nouvelle page d'accueil (tableau de bord, jugement d'actions, archives).
  - `tableau_de_bord.html` : ancien `dashboard_prototype.html`, renommé (sortie par défaut de `rlpi.dashboard` mise à jour).
  - `swipe/` : inchangé.
  - `archives/` : `prototype_3d.html` (abandonné), `prototype_tactique.html` (remplacé par la vue isométrique),
    `clip_demo.json` (données de ces deux prototypes), `resets_verification.html` (fonctionnalité en pause ;
    `rlpi.mechanics` écrit désormais là).
- Rien supprimé : tout est déplacé, réversible. `data/` et `setTest2026/` non touchés.
- Modèle `value_h10` (horizon 10 s, remplacé par 5 s) laissé dans `data/models/`, inutilisé.

## 2026-11-13 — Défense en infériorité : reculer ou rush ?

- Question de Théo : en 1v1 / 1v2 avec les coéquipiers en train de revenir, vaut-il mieux défendre de dos
  (reculer) ou sauter au ballon ?
- `src/rlpi/defense.py` : détection des situations (définition en tête de fichier) et du choix du défenseur sur
  la seconde suivante (rush / recul / autre). Testé sur 10 matchs RLCS (90 épisodes, vérifiés à la main : un
  défenseur « téléporté » après démolition → filtre ajouté), puis lot complet :
  RLCS 8 407 épisodes, SSL 2 209, parties de Théo 270 (dont 39 de Théo).
  Sorties : `data/features/defense_{rlcs,ssl,theo}.parquet`.
- Comparaison rush − recul à danger égal : pondération par score de propension (V de départ, P(encaisser),
  distance au ballon, profondeur de la balle, boost, 1v1/1v2), intervalles 80 % par bootstrap sur les matchs.
- Résultats (RLCS+SSL) :
  - balle près de notre but (y < −3 000), 1v1 : rush −4,2 pts de buts encaissés à 5 s [−6,9 ; −0,9], ΔV +5,6.
  - milieu de notre moitié : rush +2,3 (1v1) et +2,6 pts (1v2) de buts encaissés ; en 1v2 il fait aussi marquer
    +1,5 pt de plus → bilan de valeur ≈ 0.
  - rush de loin (> 2 100 uu) en 1v2 : +2,5 pts encaissés.
  - Les pros rushent ~2 fois plus souvent qu'ils ne reculent dans ces situations.
- Limite : étude observationnelle, contrôle partiel (on ne voit pas la qualité de contrôle de l'attaquant ni la
  vitesse de retour des coéquipiers). Théo : 39 épisodes, trop peu pour conclure sur lui.

## 2026-11-14 — Session du 14/11 (12 parties)

- 12 replays classés 3v3 (Demos, 00h22 → 01h47), Théo + LAinox dans toutes, Rileq dans 5. 7 V / 5 D.
  Frames et stats : 0 échec, buts = en-tête partout. Total Théo : 45 parties.
- Nouvelle commande `python -m rlpi.decisions touches-theo` : note les touches de Théo avec les modèles
  enregistrés, sans réentraîner sur RLCS.
- Chaîne relancée : value touches (h5), touches-theo, placement-score, passes, perf, defense theo, dashboard.
  Poids de l'indice inchangés (référence SSL identique). Équipe au meilleur indice = gagnante : 79,5 % (44 parties).
- Session : indice moyen 47 (anciennes parties 54 ; écart −6,8, IC 80 % [−18,7 ; +4,9] → pas significatif).
  Très irrégulier : 92 et 79 (01h20, 01h27) puis 18 et 9 (01h40, 01h47). Passes réussies 4,1 / 5 min (7,3 avant).
  Technique stable : supersonique 10 % (lobbies 17 % ce soir), whiffs aériens 1,9 / 5 min, touches aériennes
  hautes 5,7 / 5 min (4,7 avant).
- Défense rush/recul : 52 épisodes de Théo au total (13 nouveaux), encore trop peu pour juger ses choix.

## 2026-11-14 — Tableau de bord : parties récentes et sélecteur de joueur

- `rlpi.dashboard --since 2026-11-14` : seules les parties à partir de cette date sont affichées (12 parties).
  Les anciennes ne sont pas supprimées du disque (`setTest2026/` = seule copie), juste exclues de la page.
  Les modèles et références (RLCS, SSL) ne changent pas.
- Sélecteur « Joueur » en tête de page : Axe / LAinox / Rileq. Un profil complet par joueur, chacun comparé
  aux deux autres (`?j=<identifiant>` dans l'adresse). Page ≈ 3,9 Mo. « Tes lobbies » → « Lobbies ».
- Commande : `python -m rlpi.dashboard --player "Steam:76561198078330309" --compare LAinox Rileq --since 2026-11-14`
- Indice de perf vs score affiché en jeu (Spearman) : 0,51 sur 1 758 joueurs-matchs SSL, 0,53 sur les parties
  de Théo ; porté presque entièrement par la composante impact (0,53–0,56), les autres ≈ 0. Le meilleur indice
  du match = meilleur score 48 % (SSL). Victoire : indice 0,35, score 0,31.

## 2026-11-14 — Analyse du boost de Rileq (13 parties, dont 5 du 14/11)

- Stats subtr-actor par joueur-match + frames (rôle 1er/2e/3e homme, zone, boost au moment des touches) ;
  référence SSL (1 801 joueurs-matchs ; 120 matchs pour l'analyse image par image). Scripts dans le scratchpad.
- Rileq ne dépense pas trop (23 réservoirs / 5 min, SSL 25) : il ramasse trop peu. Gros pads 13,8 / 5 min
  (centile SSL 8), 46 % de son boost vient des petits pads sur le 14/11. Boost moyen 39 (centile 11),
  17,6 % du temps à 0 (centile 80). 60 % de son boost brûlé en l'air (SSL 54 %), peu de gaspillage (8 %).
- À 0 boost dans son tiers défensif 15,5 % du temps (SSL 9,3, Axe 6,4) ; touche la balle à 0 boost 22 % du
  temps (SSL 15 %).
- Attention : le boost pèse peu sur la victoire (corrélation 0,1 en SSL). Échantillon de 13 parties.
- Erreur corrigée en cours de route : le boost des frames est déjà sur 0–100 (pas 0–255).

## 2026-11-14 — Analyse de l'équipe (12 parties du 14/11) et conseils

- Comparaison : notre équipe vs nos adversaires (mêmes parties) vs 150 matchs SSL ; joueurs vs SSL.
  Scripts `team_analysis.py`, `players_analysis.py` (scratchpad, non versionnés).
- Équipe : structure proche du SSL (double commit 8,3 % vs 8,1 ; personne derrière la balle 4,8 % vs 3,8).
  Différence nette : 3 joueurs en moitié adverse 21,5 % du temps (adversaires 15, SSL 15,6) ; balle en moitié
  adverse 51 %. Rien de tout ça ne sépare nos victoires de nos défaites (12 parties : trop peu).
- Joueurs : Axe tirs de qualité SSL (ΔV +17,8) mais arrêts sans suite (ΔV +1,4 vs SSL 9,4) et 18 % de booms
  qui coûtent (SSL 10 %), vitesse centile 21, 54 % d'hésitation en défense seul (n=13). LAinox meilleur passeur
  (42 % récupérées) et meilleur indice (54), kickoffs 46 %. Rileq : booms et arrêts de qualité, tirs faibles
  (conversion 14 %), whiffs 3,8 / 5 min, boost bas. Passes récupérées 35–42 % vs RLCS 29 %.

## 2026-11-14 — Définition d'un kickoff gagné (subtr-actor) et correction

- Source : `src/stats/calculators/fifty_fifty*.rs` et `accumulators/fifty_fifty.rs` du dépôt rlrml/subtr-actor
  (version HEAD lue en ligne, nous utilisons la 1.5.1 : peut différer légèrement).
  Un 50/50 = une touche de chaque équipe à ≤ 0,2 s d'écart ; « kickoff » s'il a lieu dans la phase de kickoff.
  Tranché ≥ 0,35 s après la dernière touche : balle à ≥ 180 uu du milieu des deux voitures, côté adverse
  → gagné ; sinon vitesse ≥ 220 uu/s vers l'adversaire → gagné ; sinon neutre (abandon à 1,25 s).
  La possession après le kickoff est comptée à part et n'entre pas dans gagné/perdu.
- Contrôle sur 150 matchs SSL : corrélation 0,32 avec « la balle est chez l'adversaire 2,5 s après » →
  sens correct, mais mesure très locale (qui sort la balle du duel, pas qui profite du kickoff).
- Correction de l'analyse d'équipe : Rileq « 75 % » = 3 gagnés / 1 perdu / 6 neutres sur 10 kickoffs ;
  Axe 13 / 9 / 0 sur 22 ; LAinox 6 / 7 / 4 sur 17. Trop peu pour conseiller qui doit prendre les kickoffs.

## 2026-11-14 — Kickoffs : où part la balle et ce que ça donne (`src/rlpi/kickoffs.py`)

- Zone de la balle 1,5 s après la première touche (grille 3 × 3, x = ±1 300, y = ±2 000), 1re équipe à toucher
  après le duel (> 0,5 s), V (h5) à 3 et 5 s, buts à 10 s. RLCS 4 866 kickoffs, SSL 1 593, parties de Théo 270.
  Sorties `data/features/kickoffs_{rlcs,ssl,theo}.parquet`.
- RLCS, vu de l'équipe concernée : balle dans notre coin arrière 11 % des kickoffs → nous touchons ensuite 87 %,
  V ≈ −1 pt, buts 4,2 % pour / 3,1 % contre (différence non significative, p = 0,21) ⇒ issue neutre, pas une
  défaite, alors que subtr-actor la compte « perdue ». Balle devant notre but (5 %) : V −13,6, 17 % de buts
  contre. Balle reste au centre (17 %) : la plus ouverte (5,5 % de buts de chaque côté). Coin arrière : si
  l'adversaire touche en premier (13 %), 25 % de buts contre.
- Nous (14/11, 78 kickoffs) : balle dans leur coin arrière 18 % (pros 11 %), récupérée par eux 71 %.

## 2026-11-14 — Filtres globaux du tableau de bord (partie serveur)

- `rlpi.dashboard` : `filter_games()` (plage de dates jours inclus, parties avec / sans tel joueur) ;
  `make_payload(..., since, until, with_ids, without_ids)`. Génération d'un profil 5 s → 2 s (centile vectorisé,
  durées de jeu et stats mises en cache).
- `src/rlpi/serve.py` : serveur local (127.0.0.1) qui sert `reports/` et génère `/tableau_de_bord.html` à la
  demande : `?j=<id>&du=AAAA-MM-JJ&au=AAAA-MM-JJ&avec=<id>,<id>&sans=<id>`. Données passées au gabarit :
  `{dynamic, default, order, names, days[{d,n}], filters, profiles{sel: payload}, error}`.
- Pas encore branché : barre de filtres dans `dashboard_template.html`, en cours de refonte par une autre
  session (UX/UI). `launch.json` toujours sur `http.server`.

## 2026-11-14 — Synergie entre coéquipiers (`src/rlpi/synergy.py`, premier essai)

- Mesures par paire et par partie (définitions en tête du fichier) : enchaînements A → B (≤ 3 s) et leur
  « bonus » de valeur au-delà du ΔV moyen de chacun, double commit, montés ensemble, écart moyen.
  Toutes les parties de Théo (45, pour avoir de quoi mesurer) et 299 SSL. IC 80 % par bootstrap sur les parties.
- Connexion (part des touches suivies par le coéquipier) : Axe–LAinox 10,2 % [9,5–11,0] vs Axe avec un
  inconnu 8,7 [8,0–9,4], lobbies 7,7, SSL 7,4 → vrai effet duo sur la connexion.
- Mais bonus par enchaînement Axe–LAinox +0,2 pt [−1,8 ; +2,2] vs SSL +1,6 : plus de liaisons, pas plus de valeur.
- Double commit plus fréquent dans les paires avec Rileq : 11,6 s / 5 min [10,3–12,8] (Axe–Rileq) et 11,0
  (LAinox–Rileq) vs 9,3 Axe–LAinox, 9,2 SSL. Axe–LAinox montent ensemble 11,5 s / 5 min vs SSL 8,9.
  Écart entre coéquipiers plus faible que SSL pour les 3 paires (3 250–3 390 vs 3 610 uu).
- Victoires par paire non interprétables (anciens replays « mémorables » biaisés, petits effectifs).

## 2026-11-14 — Synergie dans l'onglet « Mon trio »

- `dashboard.synergy_section()` : métriques de `synergy_theo.parquet` restreintes aux parties retenues par les
  filtres, IC 80 % (200 tirages), références « toi + inconnu » et paires SSL, sens « qui sert qui ».
- Gabarit : bloc « Notre synergie » sous le face-à-face (bande 80 %, symbole du coéquipier, trait SSL, rond
  toi + inconnu, verdict seulement si toute la bande est d'un côté), tableau « qui sert qui », fiche méthode
  « Synergie entre coéquipiers ». Vérifié dans le navigateur pour LAinox et Rileq, aucune erreur console.
- Sur les 12 parties du 14/11 : Axe–LAinox connexion 8,9 % (mieux que SSL), montés ensemble 11,4 s / 5 min
  (moins bien) ; Axe–Rileq (5 parties) double commit 12,6 s et montés ensemble 10,5 s (moins bien).

## 2026-11-14 — Fantôme pro (prototype, `src/rlpi/ghost.py` + `reports/fantome.html`)

- Idée : rejouer une action de Théo vue de dessus avec, par-dessus, ce qu'un pro RLCS a fait dans la situation
  la plus proche. Cible = touche d'Axe du 14/11 au plus gros regret (choix ≠ meilleur choix du modèle Q).
- Recherche : touches RLCS dont la balle est à < 900 uu (repère du toucheur, + version retournée gauche/droite),
  puis distance pondérée sur la situation 0,2 s avant : balle (pos., vit.), toucheur (pos., vit., boost),
  2 coéquipiers et 3 adversaires triés par distance à la balle. Un exemple par match, 3 retenus.
- Premier exemple : 14/11 01-06-55, 23,6 s — Axe joue latéral devant le but adverse (47 % des pros tirent).
  8 179 touches RLCS présélectionnées (996 matchs). Plus proches : T7LM (tir, but, +0,48), risk. (tir, −0,16),
  Nwpo (latéral, −0,19). Ressemblance 86–88 %. Balles alignées à 30 uu près au moment de la touche.
- Page : superposé / côte à côte, ralenti, zoom action, barres « ce que font les pros ». Jetons ajoutés hors
  kit : `--ghost`, `--opp`, `--pitch`, `--pitch-line`. Serveur d'aperçu `rapports-fantome` (port 8767).
- À faire : choisir le moment depuis « Ce match », bouton RLCS/SSL, index de recherche pré-calculé, 3D plus tard.

## 2026-11-14 — Indice de performance v2 et page « Les modèles »

### Diagnostic de l'indice v1
- Impact (56 % du poids) : un tiers de sa variance venait des seules touches de but (+1 forcé) ; corrélation
  impact ~ buts 0,56. Fiabilité d'un match (test-retest, 207 pros RLCS, 27 matchs chacun) : indice 0,07,
  impact 0,02 ; placement 0,21, boost 0,36, vitesse 0,41. Il fallait 51 matchs pour une moyenne fiable (0,8).
- Moitiés d'un même match (minutes paires / impaires) : indice 0,22, impact 0,16-0,20 → la note d'un match
  dépend de quelques grosses touches. Plafonner les touches (±0,05 à ±0,20) n'y change rien.
- Variantes testées (poids appris sur SSL, évaluées sur RLCS jamais vu) : v1 85 % d'équipes gagnantes ;
  sans les buts 73 % (mais un tir marqué ne vaut plus rien alors qu'un tir arrêté rapporte → écarté) ;
  « xV » 79 % ; fondamentaux seuls 58 % mais 18 matchs suffisent.

### Changements (`src/rlpi/perf.py` v2, `rlpi.value goals`)
- Touche de but créditée de la valeur du modèle 0,2 s avant la ligne (médiane 0,75) au lieu de +1
  (`data/features/goal_xv_{source}.parquet`). Poids : impact 49 %, boost 19 %, passes 13 %, vitesse 12 %,
  50/50 5 %, placement 2 %, ratés 0 %.
- Sous-notes Production (centile de l'impact) et Fondamentaux (6 autres composantes, poids appris sans
  l'impact). Rapport : validation RLCS, test-retest, moitiés de match (`python -m rlpi.perf fiabilite`).
- Résultats : équipe gagnante SSL 82 % (cv), RLCS 79 %, Théo 82 % (44) ; moitiés de match indice 0,26,
  fondamentaux 0,49, production 0,16 ; parties pour une moyenne fiable : indice 50, fondamentaux 18,
  production 208. Théo (12 parties du 14/11) : 45 (v1 : 47) · production 46 · fondamentaux 43.
- Tableau de bord : sous-notes et « moyenne fiable vers N parties » (Ma forme, Ce match), fiche méthode mise à jour.

### Page « Les modèles » (`python -m rlpi.models_page` → `reports/modeles.html`)
- Générée depuis les rapports : lecture des replays, valeur, placement, choix à la touche, indice ; axes
  pertinence / vérité / efficacité / fiabilité ; analyses descriptives ; ce qui reste à valider. Liée depuis l'accueil.

## 2026-11-14 — Meilleur jeu calculé (`src/rlpi/bestplay.py` + `reports/meilleur_jeu.html`)

- Retour de Théo sur le fantôme pro : superposer l'action d'un autre joueur n'est pas clair. Il veut voir le
  meilleur jeu calculé pour SA situation. → nouvelle page qui ne montre que la scène de Théo.
- Modèles appris sur 226 339 touches RLCS (1 000 matchs, 20 % des matchs tenus à part pour la validation) :
  - P(direction | situation), 16 secteurs + contrôle : le secteur joué est « faisable » (≥ 3 %) dans 92 % des cas ;
  - Q(situation, direction) avec couloir (adversaire le plus proche de la trajectoire), cadrage et coéquipier sur
    la trajectoire : R² hors échantillon 0,37 (modèle à 5 actions de `decisions` : 0,27).
- Piège corrigé : la direction lue 0,3 s après la touche et la force de la balle dépendent de l'issue (un tir
  contré sort lentement / dévié). La 1re version recommandait « tir très fort » dans 3 défenseurs (Q = 0,73).
  → direction lue à 0,1 s, force retirée de Q (on ne recommande qu'une direction).
- Exemple (14/11 01-06-55, 23,6 s, même moment que le fantôme) : Théo envoie la balle vers la gauche (Q −0,47 ;
  réel −0,85) ; meilleur jeu = droit au but, cadré (Q +0,13) ; écart 0,61.
- Page : arrêt sur image à la décision, éventail coloré (mieux / moins bien que ton jeu), flèches « ton jeu » /
  « meilleur jeu », balle bleue simulée (ligne droite + rebonds), positions idéales des coéquipiers (modèle de
  placement), bascule « Meilleur jeu » / « Ce que tu as fait ». Le fantôme pro (`fantome.html`) reste en archive.
- Limites : trajectoire simulée sans hauteur, voitures figées après la touche, pas de force recommandée,
  pas encore de choix du moment depuis « Ce match » (`--rank N` en ligne de commande).
- Question de Théo : « tirer, c'est peut-être impossible dans ma position ? » → oui. Au moment de la touche il est
  entre la balle et le but adverse, orienté vers son camp (−148°) ; balle vers le but chez les pros dans cette
  situation : 4 % (modèle), 7 % sur 399 situations RLCS semblables. Le seuil « faisable » à 3 % était trop bas.
- Corrections : seuil 10 % (comme `decisions`), options 3–10 % affichées hachurées « rares », jamais recommandées ;
  recommandation par grand secteur (22,5°, valeur moyenne du secteur) car l'argmax d'un angle exact tombe toujours
  à la frontière de la zone faisable (130–135°, juste à côté du tir rare). Option `--at "date@t_s"`.
- Nouveau verdict pour le moment 23,6 s : meilleur jeu réaliste = diagonale avant-gauche (20 % des pros, Q −0,21)
  contre −0,46 pour Théo, écart 0,24 (et non 0,6). Toutes les options réalistes sont négatives : l'erreur est
  surtout AVANT la touche (mauvais côté de la balle). Piste : « meilleure position d'approche » avant la touche.

## 2026-11-14 — Meilleur jeu sur l'action entière (`src/rlpi/approach.py`, approche dans `bestplay.export`)

- Demande de Théo : juger l'action entière, pas seulement la touche.
- Modèle d'approche : position du FUTUR toucheur relative à la balle, 3,0 → 0,3 s avant la touche, à partir de la
  balle, du temps restant, du boost, de 2 coéquipiers et 3 adversaires. 1,11 M approches RLCS (1 000 matchs,
  20 % tenus à part). Écart médian 721 uu (base « décalage médian par instant » : 1 084) ; 249 uu à 0,3 s,
  896 à 1,8 s, 1 368 à 3,0 s → approche montrée seulement de −1,8 s à −0,3 s.
- Coût du placement : valeur (modèle `value_h5`) réelle vs « toi à la position idéale », le reste de la scène
  identique ; vitesse et orientation rendues cohérentes avec le chemin idéal (sinon voiture placée devant la balle
  mais filant vers son but → comparaison faussée).
- Exemple 23,6 s : jusqu'à −0,9 s la position de Théo vaut autant ou plus que celle d'un pro (collé à la balle) ;
  à −0,4 s un pro arrivant face au but vaudrait +0,12. Courbe de valeur : +0,84 juste avant la touche, ~0 après.
  CORRECTION de l'entrée précédente : la situation n'était PAS mal engagée — c'était une grosse occasion ; toutes
  les options ont un ΔV négatif parce qu'on part de très haut, et la touche de Théo en perd le plus.
- Page : lecture depuis −4 s avec arrêt sur la touche, losange vide « où un pro serait » relié à Théo, courbe de
  valeur synchronisée (orange = placement qui coûte, bleu = qui rapporte), cartes « 1 · L'approche » / « 2 · La touche ».

## 2026-11-14 — Catégories RLPI masquées dans le tableau de bord

- Constat : les catégories affichées (Boost mana, Speed, 50's, Précision, Agressivité, Placement) ne
  correspondent ni à la grille 2020 (`config/criteres_rlpi.yaml`) ni aux modèles v2 ; Placement n'apparaissait
  jamais (indicateurs tous « style ») ; notes = moyennes de centiles non reliées à la victoire.
- Décision de Théo : ne plus les afficher en attendant une nouvelle grille. Interrupteur `SHOW_RLPI_CATS = false`
  dans `dashboard_template.html` : le bloc de « Mon jeu » devient « Notes des modèles », le nom de catégorie
  disparaît des lignes de « Tous les indicateurs » et de la fiche méthode. Calcul (`radar`) inchangé.
- Piste de refonte : catégories par phase (Attaque, Collectif, Défense, Duels, Placement, Technique) + style non
  noté. Pour juger des pros : référence par rôle, correction par l'adversaire, modèles de valeur plutôt que de
  conformité ; à valider sur RLCS (stabilité entre moitiés de saison, lien avec la victoire, bon sens).

## 2026-11-14 — Meilleur jeu : 4 actions + bug des tirs arrêtés

- Bug trouvé en testant 3 autres actions : les 3 « pires » étaient des TIRS ARRÊTÉS 0,1 s plus tard. La liste des
  touches suivantes excluait les arrêts (`touch_values` filtré sur action ≠ save) et la direction lue à i+1
  incluait déjà la déviation du gardien → tir lu comme « balle jouée vers l'arrière ».
- Correctif (`exit_dir`) : touche suivante cherchée parmi TOUTES les touches ; si elle arrive dès l'image suivante,
  direction lue à l'image de la touche si la balle y a changé de vitesse (> 300 uu/s), sinon touche écartée
  (Théo 208 / 8 509, RLCS 5 581 / 226 339). Modèles réentraînés : R² Q 0,34 ; secteur joué ≥ 10 % dans 69 % des cas.
- Page : sélecteur d'actions (`meilleur_jeu.html?m=0..3`, `bestplay_data_N.js`, `bestplay_index.js`) et nature de la
  touche : « duel » (adversaire < 250 uu de la balle), « touche probablement manquée » (direction jouée par < 5 %
  des pros ici), sinon vrai choix.
- Actions retenues : 01h06 23,6 s (occasion perdue, +0,25), 01h20 27,1 s (choix : arrière-gauche au lieu
  d'avant-gauche, +0,27), 01h47 36,8 s (balle partie dans une direction jouée par 1 % des pros → exécution),
  01h40 286,2 s (duel, adversaire à 214 uu, indicatif).

## 2026-11-14 — Styles de jeu, conseils et progression (« Mon jeu »)

- `src/rlpi/styles.py` : 30 traits par joueur-match (rôle, zones, aérien, murs, contrôle, contacts, 50/50, tirs,
  arrêts, dégagements, passes, boost, vitesse, volume, pertes, ratés), **centrés sur la moyenne des 6 joueurs du
  match** (sinon le niveau classé se confond avec le style). Moyenne par joueur : 207 pros RLCS (≥ 10 matchs) +
  194 SSL (≥ 3). ACP + varimax, 7 facteurs. Pôles nommés par signature : Voltigeur, Forteresse / Harceleur,
  Ancre / Fer de lance, Fusée, Fiable / Tête brûlée, Porteur, Meneur. Stabilité d'un pro entre matchs pairs et
  impairs : 0,69 à 0,88 ; Porteur 0,30 et Meneur 0,35 → jamais style principal. `python -m rlpi.styles fit`
  → `data/models/styles.json`. Premier essai sans centrage : les trois du trio sortaient « Harceleur » (effet du
  classé) ; avec centrage, toujours Harceleur → c'est un style d'équipe : règle « style du trio » si tous ≥ 80.
- Résultat (toutes parties) : trio Harceleur ; Axe Ancre + Fiable (comme Rezears, chaaneel.) ; LAinox Fer de lance
  + Fusée ; Rileq Fer de lance + Fiable. Depuis le 14/11 : Rileq < 5 parties → pas de style.
- `dashboard.style_section / advice_section / progress_section` + gabarit : hero « Ton style de jeu » (style,
  teinte, signature en mots, pro le plus proche, affinités, styles du trio), 3 conseils (composante qui coûte le
  plus d'indice, retard technique face aux lobbies, piège du style), progression (20 dernières parties : courbe,
  moyenne glissante, plus fortes progressions et reculs, « net » si l'IC 80 % exclut 0). Fiches méthode ajoutées.
  Vérifié dans le navigateur (Axe, LAinox, mobile 375 px), aucune erreur console.

## 2026-11-14 — Formation à trois (`src/rlpi/formation.py`) à la place de l'approche joueur par joueur

- Remarque de Théo (capture, action 1 à −0,6 s) : la position « idéale » de Théo tombait à 235 uu de LAinox. Les
  positions idéales étaient calculées séparément (approche pour le toucheur, placement pour les autres) → trois
  joueurs « idéaux » collés, pas une rotation.
- Nouveau modèle : positions des 3 rôles d'une équipe RLCS (sur la balle / 2e / 3e = rangs de distance à la balle),
  relatives à la balle, à partir de la balle et des adversaires seulement. 1,34 M situations (1 000 matchs, 20 %
  tenus à part). Écart médian : 580 uu sur la balle (base 713), 1 696 pour le 2e (2 146), 2 521 pour le 3e (3 939).
  Prédictions trop resserrées (écart minimal médian 1 200 uu contre 2 025 réel) → écart minimal imposé de 1 000 uu.
- Attribution des rôles : déplacement minimal, rôle « sur la balle » pondéré ×3 (sinon le joueur le plus loin était
  envoyé sur la balle — Rileq à 4 400 uu au fond du but adverse dans l'action 4), pénalité de changement de rôle
  (Viterbi). Balle « disputée » si les deux mieux placés sont à < 300 uu d'écart.
- Valeur : les 3 joueurs déplacés (vitesse et orientation cohérentes) vs réel.
- Résultats : action 1 → balle pour Zernica (le plus proche), Théo 2e, LAinox 3e, formation +0,16 à −1,0 s ;
  action 2 → balle pour Théo, +0,31 à −3,1 s ; actions 3 et 4 → balle disputée (Rileq / Théo, LAinox / Théo).
- `approach.py` n'est plus utilisé par la page (gardé pour mémoire).
- Retour de Théo : « le premier joueur est marqué balle déjà » + voir la trajectoire pro dès le début. Diagnostic :
  au début de l'action 1, Théo conduit la balle le long du mur (450 uu) → rôle « sur la balle » juste, mais le
  contour + l'étiquette « BALLE » collés sur sa voiture donnaient l'impression d'un rôle décidé d'avance.
  Page : trajectoires pro de chaque joueur tracées dès −4 s (pointillé de sa couleur, lissées sur 0,5 s, coupées
  aux changements de rôle) ; contour, lien et étiquette affichés seulement si le joueur est à > 350 uu de sa
  position pro ; cadre élargi aux trajectoires entières.

## 2026-11-14 — Meilleur jeu limité aux 5 pires actions des 10 dernières parties

- Décision de Théo : la visualisation n'est proposée que pour les 5 pires actions des 10 dernières parties.
- `python -m rlpi.bestplay worst --games 10 --k 5` : pire = plus grand écart touche jouée ↔ meilleur jeu réaliste ;
  duels écartés (adversaire < 250 uu de la balle), une seule touche par action (< 3 s dans la même partie).
  Écrit `reports/bestplay_data_0..4.js` + `bestplay_index.js` (liste + méta) ; la page affiche la phrase de sélection.
- Résultat (10 parties du 14/11, 00h36 → 01h47 ; 1 duel écarté) : 01h47 36,8 s (+0,35, touche manquée ?),
  00h50 151,6 s (+0,34, touche manquée ?), 01h20 27,1 s (+0,27, choix), 01h06 23,6 s (+0,25, balle d'un coéquipier),
  00h36 174,2 s (+0,24, balle d'un coéquipier).
- À chaque nouvelle session : `bestplay extract --source theo` (après `decisions touches-theo`) puis `bestplay worst`.

## 2026-11-15 — Mise en ligne chez Lainox (Coolify)

- Même circuit que Football PVP : push sur `main` → GitHub Action `.github/workflows/deploy.yml` construit l'image
  `ghcr.io/therealaxe/rlpi` (`:latest` et `:sha-…`) → appel de l'API Coolify pour redéployer (port 3001).
- Secrets GitHub à créer (fournis par Luc) : `COOLIFY_TOKEN` (permission « deploy ») et `COOLIFY_APP_UUID`.
- L'image ne contient que le serveur (`python -m rlpi.serve`), pas les données. Les données vivent dans un volume
  persistant monté sur `/app/data` (pages statiques dans `/app/data/reports`), envoyées à Luc à part.
- `serve.py` : hôte, port et dossier des rapports réglables par variables d'environnement (`RLPI_HOST`, `PORT`,
  `RLPI_REPORTS`, `RLPI_SINCE`) ; route `/health` ajoutée. Sans variables, comportement local inchangé.
- Fichiers lus par le tableau de bord (≈ 294 Mo) : `data/features/*` utilisés, `data/models/{perf_report,styles,
  value_h5_report}.json`, `data/frames/theo/`, et dans `data/frames/rlcs/` tous les `.meta.json` + 200 parquets
  (échantillon des heatmaps).

## 2026-11-15 — Mode opératoire Coolify (version multi-joueurs)

- `docs/DEPLOIEMENT_COOLIFY.md` : partie A (tableau de bord actuel : image ghcr, volume `/app/data`, variables,
  déploiement GitHub) et partie B (Postgres, Redis, MinIO, sauvegardes R2/B2, workers ×3 limités à 1 Go / 1,5 CPU).
- Serveur : M920q de Luc, i5-9400T 6 cœurs, 16 Go, NVMe 476 Go. Budget RLPI ≈ 5 Go de RAM (mesures : modèles 195 Mo, parsing d'un replay 5,7 s et 310 Mo en pic).
- Estimation de stockage : ≈ 0,9 Mo par partie extraite (frames 0,69 + features 0,22), ≈ 2,5 Mo avec le replay brut.
- Reste à faire côté code avant les workers : pipeline découpé partie par partie, `Dockerfile.worker`,
  mesure du temps de traitement d'une partie.
- Infra en place sur Coolify (projet `RLPI`, environnement `production`) : `rlpi-db` (Postgres), `rlpi-queue`
  (redis:8, privé), `rlpi-storage` (Garage v2.3.0 : nœud déjà configuré par Coolify, bucket `rlpi`, clé `rlpi-app`
  en lecture/écriture, quota 100 GiB). Tout est en *Running*. Secrets gardés par Théo, hors Git.
- Reste côté serveur : retrait des URL publiques de Garage, rattachement au réseau partagé, sauvegardes externes.

## 2026-11-15 — Traitement partie par partie (préparation des workers)

- Généralisation reprise de la copie « partage » (hors Git) : `config.SOURCE` (`RLPI_SOURCE`, « theo » par défaut),
  `config.PLAYER` / `config.COMPARE` (profil de Théo par défaut quand la source est « theo »), `app.py`,
  console UTF-8. Les rapports gardent les clés `perso_team_acc` / `perso_n_matches` ; repli sur les anciennes
  clés `theo_*` dans le tableau de bord et la page des modèles. `decisions touches-theo` reste accepté.
- `config` : `RLPI_DATA` et `RLPI_MODELS` permettent de travailler dans un autre dossier (une partie = un dossier).
- `perf` : la référence SSL (médianes, écarts, poids, distributions triées) est enregistrée dans
  `data/models/perf_reference.npz` à chaque `python -m rlpi.perf` ; `python -m rlpi.perf score --source X` note
  une source sans réapprendre. Vérifié : perf_ssl et perf_theo identiques à l'ancienne version (écarts du rapport
  ≤ 1e-16 sur le test-retest).
- `rlpi.game` : `run <replay> --out <dossier>` traite une partie seule dans un processus séparé (frames, stats,
  valeur, buts, décisions, placement, passes, perf, défense, engagements, meilleur jeu) et écrit `result.json`
  (statut ok / partiel / rejetee, durée par étape, erreurs). `merge <parties> --into <data> --source X`
  reconstruit les tables d'un joueur (doublons MatchGUID écartés comme dans `rlpi.stats`).
- Équivalence vérifiée sur 11 parties (10 du dossier Demos + 1 de setTest2026) : lot classique vs partie par
  partie + merge → toutes les tables, types compris, le meilleur jeu (X + lignes), les courbes de valeur et les
  33 fichiers d'images sont identiques.
- Mesures (PC de Théo) : 9 à 26 s par partie ; l'étape stats (subtr-actor `get_summed_stats`) prend ~60 % du
  temps, frames ~30 %. Pic mémoire 410 Mo sur la plus longue partie → limite de 1 Go par worker confirmée.
- Pas encore fait : synergie, actions à revoir et tableau de bord restent au niveau du joueur (après merge) ;
  `Dockerfile.worker`, file Redis et stockage Garage. `perf_reference.npz` devra être embarqué avec les modèles.
- Piste d'optimisation : le replay est lu 3 fois (frames, événements, stats) ; une seule lecture ferait gagner
  plusieurs secondes par partie.

## 2026-11-15 — Worker (file Redis → Garage → Postgres)

- `src/rlpi/worker.py` : `run` (boucle : BLMOVE de `rlpi:queue` vers `rlpi:processing:<worker>`, téléchargement du
  replay, `rlpi.game run`, envoi du dossier de la partie dans `users/<joueur>/games/<replay>/`, statut dans la table
  `games`), `enqueue --user X fichiers…`, `status`, `check`. Reprise des tâches interrompues au démarrage,
  3 essais en cas d'erreur, arrêt propre sur SIGTERM, fichier de vie pour le contrôle de santé Docker.
- `Dockerfile.worker` (python:3.13-slim + libgomp1) ; paquets Linux vérifiés : subtr-actor-py 1.5.1,
  lightgbm 4.7.0, psycopg-binary 3.3.9, redis 8.1.0, boto3 1.44.3. Modèles dans un volume `/app/models`
  (archive `rlpi-models-worker.zip`, 24 Mo, 6 fichiers) : `data/` n'étant pas versionné, la GitHub Action ne peut
  pas les embarquer.
- GitHub Action : deuxième image `ghcr.io/<repo>-worker`, redéploiement des workers listés dans le secret
  `COOLIFY_WORKER_UUIDS`.
- Pas testé localement contre Redis / Postgres / Garage (choix de Théo) : à valider sur le serveur avec
  `python -m rlpi.worker check` puis le test de charge B6.
- Décision (Théo n'a que l'interface Coolify, pas de SSH) : les 6 modèles du worker sont versionnés dans `models/`
  (61 Mo, exception à la règle « data/ non versionné », voir `models/README.md`) et copiés dans l'image ; plus de
  volume `rlpi-models` à préparer. `.gitattributes` : `models/** binary`.
- `worker enqueue --ballchasing N` / `--ballchasing-id ID…` : met en file des parties téléchargées depuis
  ballchasing (pour tester sans SSH). L'API refuse `sort-by=upload-date` : tri `created`. Constat : l'auto-upload
  n'a jamais tourné qu'en `--dry-run`, le compte ballchasing de la clé ne contient que des parties 2019-2020.
- Mise en service sur le M920q (2026-11-15) : `rlpi-worker-1` créé dans Coolify, `worker check` tout OK
  (modèles, Redis, Postgres, Garage), 3 parties de Théo traitées de bout en bout via `enqueue --ballchasing 3`
  (confirmé par Théo). Pièges rencontrés : URL Redis copiée masquée, `S3_ENDPOINT` collé avec la syntaxe d'un lien
  Markdown ; Garage rattaché au réseau partagé de Coolify. Temps par partie sur le serveur : pas encore relevé.

## 2026-11-15 — Pages joueurs (agrégation + tableau de bord multi-joueurs)

- `rlpi.players` : télécharge les parties d'un joueur depuis Garage (`users/<joueur>/games/`, manifeste des ETag :
  seules les parties nouvelles ou modifiées sont rapatriées), les rassemble (`game.merge`, source « perso ») dans
  `<données>/users/<joueur>/data` avec des liens vers les données de référence (RLCS, SSL, rapports des modèles),
  calcule la synergie, puis le contenu du tableau de bord dans un processus séparé (`RLPI_DATA` = dossier du
  joueur ; `dashboard.py` inchangé).
- Joueur suivi détecté (le plus présent), coéquipiers comparés = les 2 plus fréquents avec ≥ 5 parties ensemble ;
  surcharge possible par `users/<joueur>/profile.json`.
- `serve.py` : route `/joueur/<joueur>` (mêmes filtres que `/tableau_de_bord.html`, mise en cache tant que les
  données ne changent pas). Image du tableau de bord : + boto3.
- Test local (stockage simulé par les 11 parties du test d'équivalence) : regroupement 1,8 s, calcul 3,3 s, page
  1,4 Mo avec toutes les sections ; Axe détecté, LAinox et Rileq comparés ; 2e affichage sans recalcul ; joueur
  inconnu → 404. Lecture S3 réelle non testée en local.
- Limites : pas de connexion (page visible par qui connaît l'adresse) ; actions à revoir (bestplay worst) et pages
  annexes (swipe, fantôme, modèles) restent celles de Théo ; la phrase de validité de l'indice cite les chiffres
  des parties de Théo (perf_report.json).
