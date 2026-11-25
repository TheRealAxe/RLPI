# Audit du calcul de l'impact — 24/11/2026

**Objet** : repérer les erreurs du calcul de la valeur des touches (« impact », 49 % de l'indice) pour améliorer le
modèle. Point de départ : deux défauts vus à la main sur les parties d'Axe (but de loin crédité +0,01, arrêts tentés
sur des ballons qui rentraient comptés comme buts contre son camp).

**Échantillon** : les 43 parties classées 3v3 d'Axe du 15.11 au 23.11.26, ré-analysées en local avec `rlpi.game run`
(mêmes modèles que la production, `value_h5.txt` et `perf_reference.npz` identiques à `models/`). Les notes
recalculées sont identiques à celles de l'application (Axe 44,5 et LAinox 58,9 sur la période). 258 joueurs-matchs,
8 350 touches, 217 buts.

**Scripts** : `notebooks/audit_impact/` — `audit.py` (détecteurs), `resume.py` (tableaux), `corrections.py`
(corrections F1 à F3 et nouvelle note). Argument : un dossier contenant `games/<partie>/` produits par `rlpi.game run`.
La physique de la balle (`balle.py`) est simplifiée : gravité et rebonds, sans effet ni voitures.

## Résumé

| # | Erreur | Fréquence | Valeur mal comptée | Correction |
|---|---|---|---|---|
| F1 | But marqué plus d'1 s après le tir : le but n'est crédité à personne | 38 buts sur 176 (22 %) | +10,8 manquants | simple |
| F2 | Arrêt tenté sur un ballon qui rentrait déjà : compté comme une erreur | 42 touches | −7,1 en trop | moyenne (prédiction de balle) |
| F3 | Même joueur, même image : touche comptée deux fois | 86 lignes | +1,0 en double | triviale |
| F4 | Touche non détectée par subtr-actor | ≈ 24 cas (0,3 %) | quelques buts mal attribués | moyenne |
| L1 | Trajectoire de la balle en ligne droite sans gravité dans les variables du modèle | — | valeur près du but sous-estimée | ré-entraînement |
| L2 | Fenêtre d'1 s après la touche | tirs surtout | valeur des tirs sous-estimée | à étudier |

**Effet des corrections F1 + F2 + F3** sur les 258 joueurs-matchs : 31 notes changent de plus de 5 points, 16 de
plus de 15 points (jusqu'à +51). Moyennes de la période : Axe 44,5 → 47,3, LAinox 58,9 → 60,6. Les classements
moyens bougent peu, mais des notes de match individuelles sont fausses de 20 à 50 points.

⚠ Après correction, la référence SSL (`perf_reference.npz` : moyennes, écarts-types, poids, centiles) doit être
recalculée avec le même calcul (`python -m rlpi.perf`), sinon les centiles sont décalés.

## F1 — Les buts de loin ne sont crédités à personne

**Constat** : `value.touches` mesure une touche entre `i − 2` et `after = min(i + 1 s, touche suivante − 1)`.
`perf.xv` ne remplace le résultat par la valeur du but (xV) que si `v_after ≥ 0,999`, c'est-à-dire si le but tombe
dans la seconde. Quand le ballon met plus d'1 s à rentrer sans autre touche, le tireur est crédité de la valeur
1 s après sa frappe (ballon encore en vol), et la montée à +1 au moment du but n'est attribuée à personne.

**Mesure** : 55 buts sur 176 (hors contre son camp) arrivent plus d'1 s après la dernière touche ; 38 sont
sous-crédités, pour 10,8 de valeur au total (0,28 par but en moyenne).

**Exemples**
- Axe, `A00FB16D…`, tir du milieu de terrain à 3:01, but à 2:59 (1,9 s) : +0,01 au lieu de +0,82. Note du match
  9 → 45.
- LAinox, `CC3ACB45…`, but à 4:12 : −0,03 au lieu de +0,71 (voir aussi F4).
- Rileq, `A00FB16D…`, but à 4:07 : +0,03 au lieu de +0,72.

**Correction proposée** (`value.touches` ou `perf.xv`) : si l'événement qui suit une touche est un but de son équipe,
sans autre touche entre les deux, prendre `v_after = 1` quel que soit le délai (donc `dv_xv = xV − v_before`).
Garder une limite raisonnable (par exemple 4 s) pour ne pas créditer un dégagement qui finit au fond par hasard.

## F2 — Les arrêts sur un ballon qui rentrait déjà sont punis

**Constat** : le coût d'une touche compare la situation juste avant et juste après, sans jamais se demander ce qui
serait arrivé sans la touche. Quand un défenseur touche un ballon déjà parti pour rentrer et qu'il rentre quand
même (ou après une déviation), la touche est notée comme si elle avait créé le but. Le modèle compte en plus sur
la présence du défenseur pour estimer le danger « avant » assez bas, d'où des coûts de −0,5 à −0,8.

**Mesure** : sur les touches négatives dans le tiers défensif, on simule la balle sans la touche (depuis `i − 2`,
3 s) : 42 touches concernent un ballon qui rentrait, pour −7,1 au total ; 15 sont suivies d'un but encaissé dans la
seconde (−4,8, soit −0,32 par touche). Plus largement, 41 buts sur 217 (19 %) ont pour dernière touche un joueur de
l'équipe qui encaisse.

**Exemples**
- Axe, `45F1EFE0…`, 4:44 : LAinox perd le ballon, tir adverse cadré, Axe dévie, le ballon rentre de l'autre côté :
  −0,81. Sans la touche, but 0,8 s plus tard.
- Axe, `B0BE2318…`, 4:45 : lob de 4 s, touche sur la ligne 0,2 s avant le but : −0,48.
- n7md351ɥ, `776DE544…`, 4:18 : −0,78. Note du match 3,5 → 54,6.

**Correction proposée** : si la balle libre (sans la touche) entre dans le but du joueur dans les ~3 s, le coût de la
touche est ramené à 0 (`dv = max(dv, 0)`). Une touche qui sauve garde son crédit. Pour la production, remplacer la
physique simplifiée par une vraie prédiction de balle (effet, rebonds sur les arêtes, voitures adverses qui peuvent
finir l'action).

## F3 — Touches comptées deux fois

**Constat** : `frames.extract` arrondit les événements « touch » de subtr-actor à 10 images par seconde. Deux
événements du même joueur à moins de 0,1 s (typiquement un contrôle puis un tir) tombent sur la même image, et
`value.touches` les valorise tous les deux avec la même fenêtre : la valeur est comptée deux fois.

**Mesure** : 86 lignes en double (même joueur, même image), 1,0 de valeur comptée deux fois. En plus, 54 images où
deux coéquipiers différents touchent en même temps : les deux reçoivent la totalité du crédit.

**Exemple** : LAinox, `9D113475…`, image 4707 : contrôle + tir sur la même image, +0,55 compté deux fois. Note du
match 72 → 54 après correction.

**Correction proposée** : fusionner les touches par `(i, slot)` dans `frames.extract` ou `value.touches` en gardant
l'action la plus forte (tir > passe > dégagement > …) et la somme des `ball_speed_change`. Pour deux coéquipiers sur
la même image, partager le crédit.

## F4 — Touches non détectées

**Constat** : 246 sauts brusques de la vitesse de la balle (> 900 uu/s d'une image à l'autre, loin du sol et des
murs) sans touche enregistrée. La plupart n'ont aucun joueur à moins de 300 uu (artefacts d'échantillonnage
probables), mais 24 ont un joueur tout près, dont 6 qui changent la valeur de plus de 0,1.

**Exemple** : `CC3ACB45…`, 4:13, LAinox à 260 uu, la balle prend 3 900 uu/s, valeur +0,93, but 0,6 s plus tard :
le but est rattaché au tir précédent, 3 s plus tôt (−0,03).

**Correction proposée** : détecter ces touches manquantes dans `frames.extract` (saut de vitesse + joueur à moins
de ~300 uu) et les ajouter au joueur le plus proche, avec un marqueur « déduite ».

## Limites du modèle (pas des erreurs de code)

**L1 — Trajectoire sans gravité.** Les variables `ball_t_*`, `ball_on_target_*`, `ball_x_at_*_line` de
`value.features` prolongent la balle en ligne droite, sans gravité ni rebond. 0,5 s avant un but que la physique
simple donne rentrant, la valeur médiane n'est que de 0,64, et 18 buts sur 140 sont sous 0,3 (lobs et rebonds
surtout). Piste : calculer ces variables avec la trajectoire de `balle.py` (gravité + rebonds) et ré-entraîner
`value_h5`.

**L2 — Fenêtre d'1 s.** Pour les tirs, la valeur à 3 s dépasse en moyenne de +0,075 celle à 1 s (écart absolu
moyen 0,24) : la fenêtre d'1 s sous-estime ce que produit un tir. F1 règle le cas des tirs qui rentrent ; pour les
autres, une fenêtre « jusqu'à la touche suivante, au plus 2 s » serait à tester.

**L3 — Jeu sans ballon.** 31 % des variations de la valeur tombent hors des fenêtres de touche (placement,
pression, mouvements des adversaires) et ne sont attribuées à personne. C'est voulu (le placement a sa propre
composante, 2 % du poids), mais l'impact ne voit que ce qui se passe au contact du ballon.

## Ordre conseillé

1. F3 (fusion des touches en double) : quelques lignes, aucun risque.
2. F1 (buts crédités quel que soit le délai) : quelques lignes dans `value.touches` / `perf.xv`.
3. Recalcul de la référence SSL (`python -m rlpi.perf`) et des agrégats (`aggregate.VERSION` + 1).
4. F2 avec une prédiction de balle fiable.
5. L1 (variables de trajectoire avec gravité) puis ré-entraînement du modèle de valeur.
6. F4 si le volume le justifie sur plus de parties.

## Corrections appliquées — 25/11/2026

Demande de Théo : F3, F1, référence SSL, F2 avec une vraie prédiction de balle, puis ré-entraînement avec une
trajectoire qui tient compte de la gravité. F4 et L2 restent à faire.

**Simulateur de balle** (`rlpi.ballsim`) : gravité, frottement de l'air, rebonds avec effet (modèle « chip »), terrain
standard avec raccords arrondis, cages, poteaux et barre ; vectorisé (8 000 balles sur 4 s en 0,6 s). Les replays
donnent aussi la rotation de la balle (`ball_wx/wy/wz`, ajoutée par `frames.extract`). Validation sur 563 trajets
libres de 3 s tirés de vrais replays : erreur médiane de position à 3 s **48 uu** (p90 332 uu), contre 3 594 uu pour
la ligne droite et 106 uu sans la rotation. Le simulateur annonce 179 des 190 buts depuis la dernière touche (94 %).

| # | Correction | Où |
|---|---|---|
| F3 | une ligne par (image, joueur), action la plus forte, `ball_speed_change` sommés ; crédit partagé (`share`) entre coéquipiers qui touchent sur la même image | `value.merge_same_frame` |
| F1 | si le prochain événement est un but de l'équipe du joueur, sans autre touche et dans les 4 s, la fenêtre va jusqu'au but (donc `dv_xv = xV − v_before`) ; seulement pour l'équipe qui marque | `value.touch_window` |
| F2 | balle simulée sans la touche (depuis `i − 1`, 3 s) : si elle entrait dans le but du joueur, coût ramené à 0 (`going_in_own`) ; une touche qui sauve garde son crédit | `value.touches`, `perf.xv` |
| L1 | les 6 variables de trajectoire du modèle de valeur (`ball_t_*`, `ball_on_target_*`, `ball_x_at_*_line`) viennent du simulateur (4 s) au lieu de la ligne droite ; mêmes noms, 99 variables | `value.trajectory` |
| Réf. | modèle de valeur ré-entraîné (996 matchs RLCS), touches et buts revalorisés (SSL, RLCS, perso), modèles de décision et référence de l'indice recalculés | `data/models`, `models/` |

**Modèle de valeur** : AUC 0,884 → 0,885, log-loss 0,0920 → 0,0914, toujours bien calibré. Gain modeste : le
modèle apprend surtout de la position des joueurs ; la trajectoire en ligne droite n'était grossièrement fausse que
pour les lobs et rebonds. Sur les 43 parties, la valeur des touches bouge peu avec le nouveau modèle seul
(corrélation 0,96, écart moyen 0,024).

**Indice** : équipe gagnante RLCS (jamais vue) 79,1 % → 79,8 % ; fiabilité test-retest d'un match 0,075 → 0,07 ;
poids quasi identiques (impact 0,489).

**Effet sur les 43 parties d'Axe** (avant → toutes corrections + nouveaux modèles et référence) :
- 123 notes de match sur 258 bougent de plus de 5 points, 43 de plus de 15 ;
- moyennes : Axe 44,5 → 47,8, LAinox 58,9 → 56,1, Rileq 42,3 → 43,8 ;
- LAinox baisse surtout par la nouvelle référence : son impact brut ne bouge presque pas (0,82 → 0,87), mais celui
  des SSL monte davantage (buts de loin enfin crédités) ;
- 341 touches sur des ballons qui rentraient : plus aucune n'est punie ; les arrêts restent peu payés (+0,16 en
  moyenne), car le modèle juge le danger « avant » à travers la position du défenseur.

**Limites** : terrains non standard (géométrie différente), aucune voiture dans la simulation (un adversaire peut
finir l'action), parties sans replay conservé impossibles à réanalyser, votes du swipe faits sur les cartes de
l'ancien modèle.

**Mise en production** (voir `docs/JOURNAL.md` du 25/11) : pousser le code et `models/`, mettre à jour le volume
`rlpi-data` (références), puis `python -m rlpi.worker reanalyze` sur le serveur.
