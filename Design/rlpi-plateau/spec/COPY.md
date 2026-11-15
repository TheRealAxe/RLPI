# Textes

## Ton

Tutoiement, phrases courtes, vocabulaire de joueur (« pressing », « tu remontes tôt »). On constate, on ne juge pas : « Ton chantier : la vitesse », pas « Tu es lent ». Pas de point d'exclamation.

## Nombres

- Virgule décimale et espace fine avant les unités : `52,6 %`, `53,5 km/h`, `7,0 / 5 min`.
- Indices et centiles entiers : `47`, `88`. Gains de touche à deux décimales signées : `−0,92` (vrai signe moins U+2212).
- Écarts signés : `+8`, `−5`. Rang : `3,6 / 6`.
- Dates courtes dans les bandeaux : `14.11` ; longues dans les textes : `14/11/2026`.

## Phrases de lecture

Chaque bloc commence par une phrase calculée. Modèles de départ (à affiner avec les données réelles) :

| Bloc | Modèle | Exemple |
|---|---|---|
| Indice | « {verdict}. Fourchette {low}–{high} · 5 dernières : {last5}. » | « Dans la moyenne de tes parties. Fourchette 37–57 · 5 dernières : 49. » |
| Forme | « {v} V · {d} D · {n50} au-dessus de 50 » | « 7 V · 5 D · 5 au-dessus de 50 » |
| Match | « {verdict} : {rank}e sur {of}. {composante la plus lourde} pèse {poids} % de la note et tombe à {note}/100. » | « Mauvais match : 6e sur 6. L'impact de tes touches pèse 56 % de la note et tombe à 8/100. » |
| Mon jeu | « Tu {force 1} et tu {force 2}. Ton chantier : {faiblesse 1}. » | « Tu presses haut et tu voles le boost adverse. Ton chantier : la vitesse. » |
| Face-à-face | « Tu gagnes {n} duels sur {total} : {liste}. {Coéquipier} {ses points forts}. » | « Tu gagnes 4 duels sur 12 : les 50/50, le boost volé, la propreté et le choix à la touche. LAinox va plus vite et finit plus. » |

Pour les forces et faiblesses, prévoir une formulation par indicateur (par exemple Temps en moitié adverse → « tu presses haut », Boost volé → « tu voles le boost adverse », Temps supersonique → « la vitesse »).

## Mots

| Interne / actuel | Dans l'interface |
|---|---|
| Comment ça marche | Méthode |
| Lobbies, GC | Les joueurs de tes parties (« lobbies » en étiquette courte) |
| ΔV | Gain de la touche |
| Whiffs | Balles ratées |
