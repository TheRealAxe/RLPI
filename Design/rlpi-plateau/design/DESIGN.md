# Direction Plateau

L'interface s'habille comme une retransmission sportive : nuit de plateau, cartons blancs coupés en biais, un volt électrique pour ce qui compte. On ne lit pas un tableau de bord, on regarde un avant-match : un bandeau de score, la forme sur les dernières parties, une pesée face au coéquipier, des ralentis.

## Principes

1. **Des formats que les joueurs savent déjà lire.** Bandeau de score, forme V/D, pesée de boxe, ralenti. Pas de graphique à apprendre.
2. **Une idée par bloc, dite d'abord en mots.** Chaque bloc commence par une phrase de lecture ; le graphique la prouve.
3. **L'écart avant la valeur.** On montre où l'on se situe par rapport à 50, à la médiane SSL ou au coéquipier.
4. **Le volt est rare.** Il désigne le joueur du profil, l'action principale de l'écran, ou le focus clavier.

## Couleurs

| Jeton | Rôle |
|---|---|
| `--surface` | Fond de page, nuit de plateau. |
| `--surface-alt` | Onglets inactifs, pistes de barre sur le fond. |
| `--panel` | Cartons blancs. Tout texte dedans en `--panel-ink` / `--panel-muted`. |
| `--panel-alt` | Pistes de barre dans un carton. |
| `--ink`, `--ink-muted` | Texte sur le fond. |
| `--accent` (volt) | Une seule zone par écran, hors badge RLPI. Texte dessus en `--on-accent`. Jamais comme texte dans un carton. |
| `--good`, `--good-on-dark` | Au-dessus de 50, gain, duel gagné. `--good` en aplat ou dans un carton ; `--good-on-dark` comme texte sur le fond. |
| `--bad`, `--bad-ink` | En dessous de 50, perte. `--bad` en aplat ou comme texte sur le fond ; `--bad-ink` comme texte dans un carton. |
| `--me`, `--mate-1`, `--mate-2`, `--ref` | Joueur du profil (losange volt), coéquipiers (rond orange clair, carré vert), références (trait gris). Sur le fond uniquement. |
| `--map-0…4` | Cartes de terrain séquentielles (temps passé). |
| `--div-neg…div-pos` | Cartes divergentes (toi contre les pros). |
| `--focus` | Anneau de focus. |

`--good` et `--bad` se distinguent aussi en clarté (le bleu est plus sombre), donc sans la couleur. Les contrastes de chaque paire sont notés dans `tokens.json`.

## Typographie

- **Sofia Sans Extra Condensed**, italique 900 (`--font-display`) : noms, scores, titres de bloc. Toujours en capitales sauf pour les chiffres. Jamais pour une phrase.
- **Sofia Sans** (`--font-sans`) : tout le reste. 500 pour le courant, 800 pour les étiquettes.
- Chiffres toujours tabulaires (`font-variant-numeric: tabular-nums`).

| Style | Taille / interligne | Usage |
|---|---|---|
| score-xl | 150 / 0,85 | Le chiffre héros (indice). Un par écran. |
| score | 44 / 0,85 | Scores de bandeau, valeurs de face-à-face. |
| name | 40 / 0,85 | Noms de joueurs, titres d'écran. |
| title | 28 / 0,9 | Titres de bloc. |
| body | 15 / 22 | Texte courant, phrases de lecture. |
| small | 13 / 18 | Notes et sources. |
| tag | 12 / 16, +0,08 em, capitales | En-têtes de colonne, étiquettes de bandeau. |

## Formes

- **Tout est à angle droit.** La forme vient des coupes en biais : `.pl-cut` (parallélogramme, bandeaux, onglets, pavés de forme) et `.pl-cutr` (biais à droite, cartons de contenu).
- Coupe de 14 px pour les bandeaux, 16 px pour les cartons.
- Les bandeaux qui se suivent se chevauchent de 6 px (badge RLPI puis nom).
- Un élément coupé perd son contour de focus : placer le focus sur un parent non coupé.
- Aucune ombre, aucun arrondi.

## Espacement

Grille de 4 px : `--space-1` (4) à `--space-12` (48). Marge de page 30 px, écart entre blocs 20 à 24 px, padding de carton 18 à 22 px.

## Mouvement

Seulement en réponse à une action : changement d'onglet (le carton actif glisse de 8 px, 150 ms), ouverture du panneau Méthode. Pas d'animation d'entrée sur les blocs. Tout est coupé avec `prefers-reduced-motion`.

## Interdits

Néon, lueur, dégradé, flou, glassmorphism, ombre portée, texture carbone, faux affichage tête haute transparent, police futuriste, emoji, logos de jeu ou de compétition. Pas de radar. Pas de violet.
