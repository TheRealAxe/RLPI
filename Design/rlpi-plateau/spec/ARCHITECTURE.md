# Architecture : quatre onglets et un panneau Méthode

La page actuelle empile onze sections de même poids. Elle devient quatre onglets, chacun répondant à une seule question. L'onglet par défaut est **Ma forme**.

## Coquille commune

- **Barre d'onglets** (en haut à gauche) : Ce match · Ma forme · Mon jeu · Mon trio. Onglet actif en carton blanc, inactifs sur `--surface-alt`. Navigation clavier avec les flèches (rôle `tablist`). Chaque onglet a sa propre URL ou ancre.
- **Sélecteurs** (en haut à droite) : Joueur (Axe, LAinox, Rileq) et Comparer à (SSL, RLCS). Lien « Méthode ⓘ ».
- **En-tête** : badge volt « RLPI » + carton au nom du joueur + ligne de contexte en étiquette (période, mode, référence).
- **Panneau Méthode** : panneau latéral à droite qui reprend tout « Comment ça marche » et « À lire avant d'interpréter ». Chaque valeur de la page porte un lien discret qui ouvre le panneau à la bonne rubrique.

## Répartition des sections actuelles

| Section actuelle | Nouvel emplacement | Composant Plateau | Référence |
|---|---|---|---|
| Indice de performance | Ma forme | Bandeau de score | `ma-forme.html` |
| Bien joué ou pas, match par match | Ma forme | Forme (pavés V/D) | `ma-forme.html` |
| Victoires, rang, placement, résultat des touches, passes récupérées | Ma forme | Bande de chiffres clés (sous la forme) | à construire, voir COMPONENTS |
| Résultat de tes touches (courbe par partie) | Ma forme | Courbe de forme, en option | à construire |
| Match du jour : composantes pondérées | Ce match | Note décomposée | `ce-match.html` |
| Dans cette partie (indices des 6 joueurs) | Ce match | Classement de la partie | `ce-match.html` |
| Tes 10 touches les plus coûteuses | Ce match | Moments clés + fiches ralenti | `ce-match-moments.html` |
| Déroulé d'un match | Ce match | Courbe de situation | à construire |
| Gain moyen par type de touche | Ce match (sous les ralentis) | Liste de gains | à construire |
| Technique | Mon jeu | Top 3 / Flop 3 + vue complète | `mon-jeu.html` |
| Points forts et points faibles | Mon jeu | Top 3 / Flop 3 | `mon-jeu.html` |
| Notes par catégorie RLPI, notes des modèles | Mon jeu | Barres de catégorie | à construire |
| Ton style de jeu (7 répartitions) | Mon jeu | Écarts de style (6 plus gros écarts) | `mon-jeu.html` |
| Sur le terrain (3 cartes) | Mon jeu | Carte terrain (une à la fois, sélecteur) | `mon-jeu.html` |
| Tes passes | Mon jeu | Barre empilée « Que deviennent tes balles » + liste | à construire |
| Toi face à tes coéquipiers | Mon trio | Face-à-face | `mon-trio.html` |
| Tous les indicateurs | Vue dédiée, ouverte depuis Mon jeu | Liste complète triée par centile | à construire |
| Comment ça marche, À lire avant d'interpréter | Panneau Méthode | Texte | — |

## Hiérarchie dans un onglet

1. Phrase de lecture de l'onglet (une ou deux lignes).
2. Le bloc principal, en carton.
3. Les blocs secondaires, sur le fond.
4. Un lien vers le détail (ralentis, tous les indicateurs, méthode).

Un onglet ne dépasse pas deux hauteurs d'écran sur ordinateur ; au-delà, le détail part dans une vue dédiée.
