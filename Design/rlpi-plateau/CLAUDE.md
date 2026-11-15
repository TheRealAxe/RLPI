# RLPI · Direction « Plateau » — brief pour Claude Code

Tu vas refondre l'interface de l'application RLPI (Rocket League Player Index) dans la direction visuelle **Plateau** : l'habillage d'une retransmission sportive. Ce dossier contient tout ce qu'il faut : jetons, règles, architecture, spécifications de composants, contrat de données et écrans de référence en HTML.

## À lire avant d'écrire du code, dans cet ordre

1. `design/DESIGN.md` — la direction visuelle, les règles de lecture, ce qui est interdit.
2. `spec/ARCHITECTURE.md` — la nouvelle navigation en quatre onglets et où va chaque section actuelle.
3. `spec/COMPONENTS.md` — chaque composant : rôle, données, anatomie, règles.
4. `spec/COPY.md` — ton, formats de nombres, phrases de lecture.
5. `spec/DATA.md` et `data/sample-axe.json` — les champs dont l'interface a besoin.
6. `reference/*.html` — la vérité visuelle. Ouvre `reference/index.html` dans un navigateur.

`design/tokens.css` et `design/plateau.css` sont la source des valeurs : couleurs, polices, espacements, coupes en biais.

## Ce qui ne se négocie pas

- **Les valeurs viennent des jetons.** Aucune couleur, police ou taille codée en dur hors de `tokens.css`. Si un besoin n'est pas couvert, ajoute un jeton et signale-le.
- **Une seule zone volt (`--accent`) par écran**, en dehors du badge RLPI de l'en-tête.
- **Le joueur du profil est toujours `--me` en losange ; les coéquipiers `--mate-1` en rond et `--mate-2` en carré.** Jamais la couleur « bien joué » pour désigner un joueur.
- **Bien ou mal = `--good` / `--bad`, toujours par rapport à une ligne 50 visible**, et toujours doublé par un signe, une position ou une lettre (V/D).
- **Chaque bloc commence par une phrase de lecture** calculée à partir des données (`spec/COPY.md`). Le graphique prouve la phrase.
- **Pas de néon, de lueur, de dégradé, de flou, d'ombre portée, de glassmorphism, d'emoji.** Les surfaces sont pleines ; l'énergie vient des coupes en biais et de la typographie.
- **Accessibilité** : contrastes déjà vérifiés dans `tokens.json` (respecte les paires indiquées), focus clavier visible (`--focus`), navigation au clavier des onglets, `prefers-reduced-motion` respecté, textes alternatifs pour chaque graphique (la phrase de lecture sert de résumé).

## Méthode de travail

1. **Commence par explorer le dépôt** : stack, système de style, composants existants, source des données. Ne suppose rien. Adapte les jetons et les classes au système en place (variables CSS, Tailwind, CSS modules…), sans changer leurs valeurs.
2. **Propose un plan court avant de coder** : où vivent les jetons, comment tu découpes les composants, ce qui manque côté données. Attends une validation si un choix structurant est ambigu.
3. **Ordre de construction** : jetons et polices → coquille (barre d'onglets, en-tête, sélecteurs Joueur / Comparer à, panneau Méthode) → Ma forme → Ce match → Mon trio → Mon jeu → vue « Tous les indicateurs ».
4. **Compare chaque écran à sa référence** (`reference/`), idéalement en capture d'écran côte à côte, avant de passer au suivant.
5. **Ne supprime pas la méthode** : le contenu actuel de « Comment ça marche » est conservé et déplacé dans le panneau Méthode (`spec/ARCHITECTURE.md`).

## Ce qui reste ouvert (à me demander plutôt qu'à inventer)

- Les seuils et formulations des phrases de lecture au-delà des modèles fournis.
- Le comportement mobile détaillé (une base est donnée dans `spec/COMPONENTS.md`).
- L'orientation de l'horloge des moments clés : la référence suppose le décompte du jeu (5:00 → 0:00). À confirmer d'après les données réelles.

## Fini, c'est quand

- Les quatre onglets et le panneau Méthode fonctionnent avec les vraies données.
- Chaque écran correspond à sa référence (mise en page, hiérarchie, couleurs, typographie).
- Aucune valeur de style en dur hors des jetons.
- Contrastes, focus clavier et réduction des animations vérifiés.
- Les phrases de lecture changent bien avec les données (teste au moins deux joueurs).
