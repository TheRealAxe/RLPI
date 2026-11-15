# Contrat de données

`data/sample-axe.json` contient un profil complet relevé sur la capture actuelle de l'application. La forme est une **proposition** : adapte-la au modèle existant plutôt que l'inverse, mais vérifie que chaque champ ci-dessous est disponible.

| Champ | Utilisé par | Remarque |
|---|---|---|
| `player`, `teammates[].slot` | Partout | `slot` décide de la couleur et du symbole (`mate-1` rond, `mate-2` carré). |
| `scope` | Header | Période, mode, référence et effectif. |
| `index` | ScoreBug, TrioList | `low`/`high` = fourchette affichée. |
| `matches[]` | FormGuide | Ordre chronologique. |
| `kpis[]` | KeyFigures, TaleOfTheTape | `lowerIsBetter` pour le rang. |
| `lastMatch` | MatchResultBar, ScoreBreakdown, MatchLeaderboard, ReviewBar | Composantes avec `weight` (%) et `score` (/100). |
| `costlyTouches[]` | KeyMoments | `clock` au format de l'horloge de jeu. |
| `indicators[]`, `strengths[]`, `weaknesses[]` | TopFlop, vue complète | Centiles face à la référence choisie. |
| `categories[]`, `models[]` | CategoryBars | |
| `style[]` | StyleGaps | Parts du temps, joueur contre référence. |
| `terrain` | TerrainMap | Grilles 8 × 10, ligne 0 = but adverse. Les valeurs de l'exemple sont relevées à l'œil. |
| `headToHead` | TaleOfTheTape | `better` : `higher`, `lower` ou `null` (style). |

Les sections « Déroulé d'un match », « Gain moyen par type de touche » et « Tes passes » utilisent des données déjà présentes dans l'app ; elles ne sont pas reprises dans l'exemple.
