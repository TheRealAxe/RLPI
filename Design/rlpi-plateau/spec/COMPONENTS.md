# Composants

Chaque composant : rôle, données, anatomie, règles. Les noms de champs renvoient à `data/sample-axe.json`.

## Coquille

### TabBar
- **Rôle** : naviguer entre les quatre onglets.
- **Anatomie** : onglets en `.pl-cut`, texte `tag`. Actif : `--panel` / `--panel-ink`. Inactif : `--surface-alt` / `--ink-muted`.
- **Règles** : rôle `tablist`, flèches gauche/droite, focus visible sur le parent.

### Header
- **Données** : `player.name`, `scope`.
- **Anatomie** : badge `.pl-volt` « RLPI » (coupe 14 px) chevauché de 6 px par un carton au nom (`name`), puis la ligne de contexte en `tag` `--ink-muted`.

### MethodPanel
- **Rôle** : expliquer une valeur sans quitter l'écran. Reprend le texte actuel de « Comment ça marche », rubrique par rubrique (Indice de performance, Valeur de la situation, Gain d'une touche, etc.).
- **Règles** : panneau latéral de 420 px sur `--panel`, fermeture par Échap, focus piégé tant qu'il est ouvert.

## Ma forme

### ScoreBug (bandeau de score)
- **Données** : `index.value`, `low`, `high`, `last5`, `verdict`.
- **Anatomie** : carton `.pl-cutr`, étiquette « Indice de performance », chiffre `score-xl`, « /100 » en `title` `--panel-muted`, puis verdict + fourchette en `body`.

### TrioList
- **Données** : `index.teammates`, `index.lobbies`.
- **Anatomie** : lignes `.pl-row` : symbole (rond `--mate-1`, carré `--mate-2`, trait `--ref`), nom en `.pl-dx` 26 px, valeur en `.pl-dx` 34 px alignée à droite.

### FormGuide (forme)
- **Données** : `matches[]` (`result`, `index`).
- **Anatomie** : grille de 6 colonnes × 2 rangées de pavés `.pl-form` coupés en biais. Lettre V/D en `tag`, indice en `.pl-dx` 34 px. Pavé `--good` (texte blanc) si indice ≥ 50, `--bad` (texte `--panel-ink`) sinon. Dernier match : `.pl-form--current`.
- **Règles** : ordre chronologique, le plus ancien en premier. Résumé en tête : « 7 V · 5 D · 5 au-dessus de 50 ». Chaque pavé est un lien vers Ce match pour cette partie. Mobile : 4 colonnes.

### KeyFigures (bande de chiffres clés) — à construire
- **Données** : `kpis[]`.
- **Anatomie** : cinq cartons `.pl-cutr` côte à côte : étiquette, valeur en `score`, comparaison coéquipiers en `small` avec leurs symboles. Pas de mini-courbe.

### ReviewBar (« À revoir »)
- **Données** : `lastMatch`.
- **Anatomie** : badge volt « À revoir » + carton : date et résultat en `.pl-dx` 30 px, indice en `score` (`--bad-ink` si < 50, `--good` sinon), phrase de lecture, lien « Voir le replay ». C'est la zone volt de l'écran Ma forme.

## Ce match

### MatchResultBar
- **Anatomie** : badge `--bad` (défaite) ou `--good` (victoire) avec résultat en `tag` et indice en `.pl-dx` 56 px, carton avec la phrase de lecture du match.

### ScoreBreakdown (note décomposée)
- **Données** : `lastMatch.components[]` (`label`, `weight`, `score`).
- **Anatomie** : carton `.pl-cutr`. Une ligne par composante, triée par poids décroissant : libellé, poids en `tag`, barre 0–100 sur `--panel-alt` avec trait vertical à 50, note en `.pl-dx` 30 px (`--good` ou `--bad-ink`).
- **Règles** : une composante de poids 0 n'a pas de ligne ; elle est citée en note sous le carton.

### MatchLeaderboard
- **Données** : `lastMatch.others`, `lastMatch.rank`.
- **Anatomie** : lignes `.pl-row` : rang, symbole, nom, indice. Le joueur du profil en `--me`. Sous la liste, le bouton volt « Voir les ralentis » (zone volt de l'écran).

### KeyMoments (moments clés)
- **Données** : `costlyTouches[]`.
- **Anatomie** : horloge de jeu horizontale (5:00 → 0:00), une barre `--bad` par touche, hauteur proportionnelle au coût ; les trois premières numérotées en volt. Puis trois fiches ralenti `.pl-cutr` : horloge, type en `title`, coût en `score` `--bad-ink`, barre de situation −1 → +1 avec point avant (creux) et après (plein).

### SituationTimeline — à construire
- **Rôle** : le « Déroulé d'un match » actuel.
- **Anatomie** : courbe de la valeur de la situation (−1 à +1) ; zone au-dessus de 0 en `--good`, en dessous en `--bad` ; buts pour en trait `--good-on-dark`, buts contre en pointillé `--bad` ; touches du joueur en losanges `--me`. Sélecteur de match en carton.

## Mon jeu

### TopFlop
- **Données** : `strengths[]`, `weaknesses[]`.
- **Anatomie** : étiquette coupée « Top 3 » sur `--good`, « Flop 3 » sur `--bad`. Chaque ligne : libellé, valeur brute en `small`, barre de centile 0–100 avec trait à 50, centile en `.pl-dx` 34 px.
- **Règles** : lien « Les 17 indicateurs » vers la vue complète.

### StyleGaps (écarts de style)
- **Données** : `style[]` (part du joueur, part de référence).
- **Anatomie** : les six plus gros écarts en valeur absolue. Libellé, « 59 % contre 51 % (SSL) », barre divergente centrée en `--ink-muted` (le style n'a pas de bon sens), écart en `.pl-dx`.

### TerrainMap
- **Données** : `terrain.time` ou `terrain.vsPros` (grilles 8 × 10, ligne 0 = but adverse).
- **Anatomie** : une carte à la fois, sélecteur Temps / Toi vs les pros / Touches. Cases sur la rampe `--map-*` ou `--div-*`, ligne médiane, « but adverse » et « ton but » écrits. Légende sous la carte. Phrase de lecture à côté.
- **Règles** : aucun texte sur les cases.

### CategoryBars — à construire
- **Données** : `categories[]`, `models[]`.
- **Anatomie** : barres 0–100 avec trait à la médiane, la valeur en `.pl-dx`. Les notes des modèles dans un second groupe titré, « expérimental » signalé.

### PassOutcomes — à construire
- **Rôle** : « Que deviennent tes balles données ? ».
- **Anatomie** : une barre empilée par joueur et référence, quatre segments : récupérée avec coéquipier placé (`--good`), récupérée sans (`--good` à 60 % d'opacité), perdue avec coéquipier placé (`--bad` à 60 %), perdue dans le vide (`--bad`). Libellés dans les segments de plus de 10 %.

## Mon trio

### TaleOfTheTape (face-à-face)
- **Données** : `headToHead.rows[]` (`better` : `higher`, `lower` ou `null` pour une mesure de style).
- **Anatomie** : en-tête avec les deux noms en `.pl-dx` 64 px et leurs indices (joueur en `--me`, coéquipier en `--mate-1` ou `--mate-2`), « vs » au centre. Lignes `.pl-tape` : valeur à gauche, libellé centré en `tag`, valeur à droite. Le gagnant de la ligne prend la couleur de son joueur ; une ligne de style reste blanche et porte « · style ».
- **Règles** : phrase de bilan sous le tableau (« Tu gagnes 4 duels sur 12… »). Sélecteur pour changer de coéquipier.

## Mobile (base)

Sous 720 px : une colonne ; barre d'onglets défilante horizontalement ; `score-xl` à 104 px ; forme en 4 colonnes ; face-à-face avec libellé au-dessus des deux valeurs.
