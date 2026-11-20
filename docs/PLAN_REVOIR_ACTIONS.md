# Plan : revoir une action en 3D (onglets « Matchs » et « À travailler »)

Objectif : à côté de chaque touche listée (actions qui coûtent d'un match, ralentis et touches suivantes de
« À travailler »), un bouton **« ▶ Revoir »** ouvre un petit lecteur 3D isométrique : 4 s avant la touche, 2 s
après (fenêtre reprise de la version de Théo, voir le journal du 2026-11-21), à 30 images/s, avec la voiture du
joueur mise en avant.

Décidé le 2026-11-20 avec Luc :

- **Solution serveur** : l'API lit le `.replay` gardé sur Garage (`replays/<partie>.replay`, `RLPI_KEEP_REPLAYS=1`
  par défaut) et découpe le clip au clic. Pas de fichier supplémentaire stocké : la lecture complète d'un replay
  à 120 Hz prend environ 0,4 s (mesuré sur un replay de 1,6 Mo, subtr-actor-py 1.5.1).
- **On garde la porte ouverte à un parseur WebAssembly dans le navigateur** : le lecteur ne consomme qu'un clip au
  format `SwipeCard`, obtenu par une seule fonction front (`loadClip`) ; chaque touche porte de quoi se retrouver
  dans le replay (index d'image `i`, position de la balle).
- On réutilise ce qui existe : le lecteur `web/src/swipe/player.ts` et la découpe `rlpi.swipe.extract`.

Façon de travailler : comme pour la refonte web, un commit par étape, sur la branche
`feature/visualisation-actions-a-travailler` ; la fusion dans `main` (mise en production) est faite par Luc.
Suivi dans `docs/JOURNAL_REFONTE_WEB.md`. Tout réglage Coolify dans `docs/REGLAGES_COOLIFY.md`.

---

## Vue d'ensemble

```
Navigateur                         API (FastAPI)                                   Garage
──────────                         ─────────────                                   ──────
[▶ Revoir] ── loadClip(partie, i) ─► GET /api/joueurs/{id}/matchs/{partie}/clips/{i}
                                     │ 1. le joueur a-t-il joué cette partie ? (sinon 404)
                                     │ 2. clip déjà en mémoire ? → réponse immédiate
                                     │ 3. sinon : télécharge ───────────────────────► replays/<mid>.replay
                                     │            + meta.json, touch_values ────────► games/<mid>/…
                                     │ 4. lit le replay (subtr-actor, 120 Hz), cale la touche,
                                     │    rééchantillonne à 30 images/s → SwipeCard
◄──────────── SwipeCard (JSON gzip, ~30–60 Ko) ─┘
ActionReplay.vue (fenêtre par-dessus la page) → createPlayer(canvas, clip)
```

---

## Étape 1 — Découpe réutilisable côté Python (S)

`rlpi.swipe.extract` mélange aujourd'hui trois choses : lire le replay, retrouver l'instant de la touche, fabriquer
la carte. On sépare, sans changer le résultat du Swipe :

- `rlpi/clips.py` (nouveau module, sans LightGBM ni ballchasing, importable par l'API) :
  - `read_replay(path) → Track` : appel unique à subtr-actor (`BallRigidBody`, `PlayerRigidBodyBasis`,
    `PlayerBoost`, 120 Hz, float32) et index des colonnes ;
  - `locate(track, i10, ball_xy) → j` : instant exact de la touche à 120 Hz, en cherchant autour de `12 × i10` le
    moment où la balle est la plus proche de sa position notée (en x, y : `touch_values` n'a pas `ball_z`) ;
    `None` si l'écart dépasse le seuil (50 uu, comme aujourd'hui) ;
  - `cut(track, meta, j, judged_id, before=3.0, after=1.0, fps=30) → dict` : la carte `SwipeCard` (déplacement de
    `resample`, `resample_dir` et de la construction des voitures).
- `rlpi.swipe.extract` devient une boucle sur `read_replay` / `locate` / `cut`.
- Le Swipe calait la touche en x, y, z : on vérifie sur les 5 replays de `data/raw/` que le calage en x, y donne
  les mêmes instants (sinon on lit aussi `ball_z` dans le parquet à 10 Hz, voir étape 2).

**Tests** : pytest sur un replay de `data/raw/` (sauté si absent, comme les autres tests sur vrais replays) ;
le paquet Swipe produit avant et après le découpage est identique.

**Sortie** : ruff, pyright et pytest passent ; Swipe inchangé.

## Étape 2 — L'index de la touche dans les données du tableau de bord (S)

Le navigateur ne connaît aujourd'hui que l'horloge de jeu d'une touche. On ajoute :

- dans `touch_rows` (`dashboard/value.py`, pires et meilleures touches) : `i` (index d'image à 10 Hz) ;
  `x`, `y` (position de la balle) y sont déjà ;
- dans la courbe d'un match (`details["curve"]`) : `i`, `x`, `y` (aujourd'hui seulement `k = i // 5`) ;
- les schémas `Touch` et `CurveTouch` (`web/schemas.py`) ; régénération de `openapi.json` et `schema.d.ts`.

Changer le contenu des agrégats → **`aggregate.VERSION` passe de 1 à 2**. Le worker recalcule alors toutes les
parties tout seul (rattrapage existant, `rebuild-aggregates`), sans relancer l'analyse. Pendant le rattrapage,
les parties pas encore recalculées ne s'affichent pas (seuls les agrégats de la version courante sont lus) :
toute touche affichée a donc son `i`, rendu obligatoire dans les schémas.

**Tests** : instantanés du tableau de bord (`tests/snapshots`) mis à jour, et vérifiés : seuls `i`, `x`, `y`
apparaissent.

## Étape 3 — L'appel API `clips` (M)

`GET /api/joueurs/{id}/matchs/{partie}/clips/{i}` (même identifiant de partie que l'onglet Matchs), dans
`web/routes/api.py` :

1. Session obligatoire, `OwnPlayer` (soi seulement) ; la partie doit être une des siennes (même contrôle que
   `/matchs/{partie}`), sinon 404.
2. Téléchargement depuis Garage : `replays/<mid>.replay`, `games/<mid>/frames/partie/<replay>.meta.json` et
   `games/<mid>/features/touch_values_partie.parquet` (quelques Ko) dans un dossier temporaire.
3. La touche `i` est cherchée dans `touch_values` : son auteur (`player_id`) devient la voiture mise en avant
   (`judged`), sa position de balle sert au calage. Touche inconnue → 404.
4. `read_replay` → `locate` → `cut` → `SwipeCard` en JSON gzip (fonction `json_response` existante).

Protection du serveur web :

- la route est synchrone (`def`) : FastAPI l'exécute dans son pool de threads, la boucle reste libre ;
- **au plus 2 lectures de replay en même temps** (sémaphore), au-delà on attend ;
- **cache mémoire** : les clips produits (clé partie + `i`, environ 50 Ko) dans un cache LRU de quelques centaines
  d'entrées ; la dernière partie lue reste en mémoire (environ 20 Mo à 120 Hz), pour que les clics suivants sur
  le même match ne relisent pas le replay ;
- ETag immuable (partie + `i` + version de la découpe) : le navigateur garde le clip.

Erreurs, en français : replay absent (partie traitée avec `RLPI_KEEP_REPLAYS=0`) → 404 « Replay non conservé
pour cette partie » ; calage impossible → 422 « Impossible de retrouver cette touche dans le replay ».

Dépendances : `subtr-actor-py` ajouté à l'extra `server` de `pyproject.toml`, `uv.lock` mis à jour. Vérifier
que l'image du serveur se construit toujours, et noter son nouveau poids et la mémoire de l'API dans le journal.

**Tests** (`tests/test_web.py`, S3 factice déjà utilisé par les tests du worker) : 401 sans session, 403 pour un
autre joueur, 404 partie d'un autre / replay absent / touche inconnue, 200 avec la forme attendue sur un vrai
replay de `data/raw/` (sauté si absent), deuxième appel servi par le cache.

## Étape 4 — Le lecteur dans l'interface (M)

- `web/src/lib/clips.ts` : `loadClip(partie, i) → Promise<SwipeCard>`. **Seul point qui sait d'où vient le
  clip** (aujourd'hui l'API ; demain, éventuellement, le `.replay` lu dans le navigateur).
- `web/src/components/ActionReplay.vue` : fenêtre par-dessus la page (fermeture par Échap, clic à côté ou bouton),
  canvas piloté par `createPlayer` (`swipe/player.ts`, sans modification si possible) :
  lecture / pause, ralenti ×0,25 / ×1, recommencer, rotation de la caméra et vue de dessus (déjà dans le lecteur),
  repère du moment de la touche sur la barre de temps, en-tête « Démolition · 2:31 · situation −0,3 → −0,6 ».
  États : chargement, erreur (message de l'API), respect de `prefers-reduced-motion` (pas de lecture automatique).
  Utilisable au doigt sur mobile.
- Boutons **« ▶ Revoir »** :
  - **À travailler** (`ATravailler.vue`) : dans les 3 fiches (à côté de « Ouvrir le match ») et sur chaque ligne
    des touches suivantes ;
  - **Matchs** (`Matchs.vue`) : sur chaque ligne de « Les actions qui coûtent » ;
- Textes dans `web/src/copy/` ; une entrée de glossaire si besoin (« Revoir : reconstitution 3D à partir du
  replay, pas une vidéo du jeu »).

**Tests** : vitest sur `loadClip` (appel, erreurs) et sur l'affichage conditionnel du bouton ; vue-tsc.
Vérification à la main dans le navigateur sur une vraie partie (local, `docker-compose.dev.yml`).

## Étape 5 — Mise en production et suivi (S)

- CI verte, fusion dans `main` par Luc.
- `docs/REGLAGES_COOLIFY.md` : rien à régler en principe (l'API a déjà accès à Garage) ; noter si la mémoire du
  conteneur de l'API doit être relevée.
- Après déploiement : vérifier que le rattrapage des agrégats (version 2) est fini, mesurer le temps du premier
  clic et des suivants en production, noter dans le journal.

---

## Hors périmètre, pour plus tard

- **Parties sans replay** (traitées avec `RLPI_KEEP_REPLAYS=0`) : clip reconstitué à partir des images à 10 Hz
  déjà stockées, mouvements lissés. À faire seulement si de telles parties existent en nombre (à compter sur
  Garage).
- **Fantôme pro** : superposer à la touche la trajectoire d'un pro dans une situation proche (`rlpi.ghost`).
- **Lecture dans le navigateur (WebAssembly)** : remplacer l'intérieur de `loadClip` ; il faudra un parseur
  fiable (idéalement subtr-actor lui-même), porter `locate` et `cut` en TypeScript et un lien temporaire de
  téléchargement du `.replay` (URL présignée, partie du joueur seulement).

## Points à vérifier en cours de route

- Combien de parties en production n'ont plus leur `.replay` sur Garage.
- Mémoire et temps de lecture d'un replay dans le conteneur de l'API (le 0,4 s est mesuré sur le poste de Luc).
- Le calage en x, y seulement (étape 1).
