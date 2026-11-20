// Panneau Méthode : rubriques « Comment ça marche », « À lire avant d'interpréter » et définitions des indicateurs.
// Texte écrit par nous (gras en **…**, rendu sans HTML par Rich.vue) ; les nombres viennent du contenu affiché.
// Repris de l'ancien gabarit (glossary, caveats, METRIC_DEF).
import type { Derived } from "@/lib/data";

export interface Rubric {
  id: string;
  title: string;
  what: string;
  steps: string[];
  example?: string;
  read: string[];
  limits: string[];
}

export interface Definition {
  label: string;
  meta: string;
  def: string;
}

const NB = " ";
const z = (v: number | null | undefined): number => v ?? 0;
const SRC =
  `Replays lus avec subtr-actor 1.5.1 (positions, vitesses, orientation et boost des 6 voitures et de la balle, 10 images par seconde).`;
const METRIC_DEF: Record<string, string> = {
  boost_moyen: "Moyenne du boost au cours du temps : intégrale du boost ÷ temps suivi, ramenée à 100.",
  boost_zero: "Temps passé avec 0 boost ÷ temps suivi.",
  boost_utilise: "Boost consommé, en réservoirs pleins (100), par 5 minutes de jeu.",
  boost_petits: "Boost ramassé sur les petits pads ÷ boost ramassé au total.",
  boost_vole: "Boost ramassé dans la moitié adverse, en réservoirs pleins, par 5 minutes de jeu.",
  boost_gaspille: "Boost ramassé au-delà de 100 (perdu car déjà plein) ÷ boost ramassé au total.",
  vitesse: "Vitesse moyenne de la voiture sur le temps suivi (1 uu/s = 0,036 km/h).",
  supersonique: "Temps à vitesse supersonique (seuil du jeu : 2 200 uu/s ≈ 79 km/h) ÷ temps suivi.",
  lent: "Temps sous le seuil « lent » du détecteur subtr-actor ÷ temps suivi.",
  au_sol: "Temps avec les roues au sol ÷ temps suivi.",
  air_haut: "Temps en l'air au-dessus du seuil « haut » du détecteur subtr-actor ÷ temps suivi.",
  ff_gagnes: "50/50 gagnés ÷ 50/50 tranchés (gagnés + perdus ; les neutres sont exclus). Détecteur 50/50 de subtr-actor.",
  ko_gagnes: "Kickoffs gagnés ÷ kickoffs tranchés (gagnés + perdus).",
  ff_par5: "Nombre de 50/50 disputés par 5 minutes de jeu.",
  tirs: "Tirs cadrés comptés par le jeu, par 5 minutes de jeu.",
  buts: "Buts par 5 minutes de jeu.",
  frappes_fortes: "Touches classées « frappe forte » par subtr-actor (gros changement de vitesse de la balle), par 5 minutes.",
  ratees: "Balles ratées (whiffs) détectées par subtr-actor, par 5 minutes : tu fonces vers la balle, tu passes tout près (en général à moins de 2 m) sans la toucher, et aucun adversaire ne l'a touchée avant toi. En pratique presque uniquement des ratés aériens. Non vérifié à l'œil.",
  passes: "Passes réussies détectées par le module « pass » de subtr-actor (enchaînement de touches entre coéquipiers), par 5 minutes.",
  demos: "Démolitions infligées par 5 minutes de jeu.",
  bumps: "Bumps infligés (contacts voiture contre voiture détectés par subtr-actor), par 5 minutes.",
  moitie_adverse: "Temps passé dans la moitié de terrain adverse ÷ temps suivi.",
  devant_balle: "Temps passé entre la balle et le but adverse ÷ temps suivi.",
  premier_homme: "Temps où le module rotation de subtr-actor te classe 1er homme (le plus engagé vers la balle dans ton équipe) ÷ temps de jeu actif.",
  troisieme_homme: "Temps classé 3e homme (le plus en retrait de ton équipe) ÷ temps de jeu actif.",
  derriere_balle: "Temps passé entre la balle et ton propre but ÷ temps suivi.",
};
const m_ = (uu: number | null) => `${Math.round((uu ?? 0) / 100)}${NB}m`;
export function glossary(d: Derived): Rubric[] {
  const { C, V, PF, HEAT } = d;
  const vm = V?.model, plc = V?.plc, dec = V?.dec, val = PF?.validation;
  return [
    { id: "indice", title: "Indice de performance",
      what: "Une note sur 100 par match qui répond à la question « as-tu bien joué dans cette partie ? », en regardant ce que tu as fait plutôt que le score final. Elle juge ta performance face aux joueurs que tu avais en face et à côté : **ce n'est pas une mesure de ton niveau**.",
      steps: [
        `**On mesure 7 choses** sur ton match : l'impact de tes touches, ta gestion du boost (temps à 0), tes passes réussies, ta vitesse moyenne, tes 50/50 gagnés, ton placement hors ballon et tes balles ratées.`,
        `**On les compare aux SSL.** Pour chacune, on regarde où tu te situes parmi ${val ? val.n_ref_player_matches : "les"} performances de joueurs SSL dans des parties classées 3v3 où les 6 joueurs sont SSL (écart à la médiane, divisé par la dispersion habituelle ; valeur manquante = médiane, bornée à ±4).`,
        `**On les pondère** selon ce qui fait gagner : une régression logistique régularisée a appris, sur ces parties SSL, quelles mesures sont plus fortes chez les joueurs de l'équipe qui gagne. Un poids négatif est ramené à 0.`,
        `**Un but compte comme un tir** : la touche qui marque est créditée de la valeur que le modèle donnait à l'action 0,2 s avant la ligne (≈ 0,75 en médiane), pas d'un +1 automatique. Un tir marqué et un tir arrêté de même qualité valent donc presque pareil (version 2, 14/11/2026).`,
        `**On en fait une note** : la somme pondérée est convertie en centile parmi les performances SSL. 70 = tu as fait mieux que 70 % des performances de SSL.`,
        `**Deux sous-notes**, même échelle : **Production** = centile de l'impact de tes touches seul ; **Fondamentaux** = centile des 6 autres mesures (boost, passes, vitesse, 50/50, placement, ratés), pondérées sans l'impact.`,
        `**Indice global** = moyenne de tes matchs, avec une fourchette : 80 % des moyennes obtenues en retirant au hasard tes parties (bootstrap, 2 000 tirages).`],
      example: PF ? `Poids actuels : ${[...PF.components].sort((a, b) => z(b.weight) - z(a.weight)).map(c => `${c.label.toLowerCase()} ${Math.round(z(c.weight) * 100)} %`).join(", ")}. Un match où tu as beaucoup apporté avec tes touches et rarement été à sec de boost sort vers 70–80, même perdu.` : "",
      read: ["Au-dessus de 55 : bien joué dans cette partie ; 45–55 : correct ; en dessous de 45 : tu as moins pesé que les autres.",
        PF ? `Pourquoi ce n'est pas un niveau : les autres joueurs de tes parties obtiennent ${Math.round(z(PF.lobby?.mean))} en moyenne, presque comme des SSL entre eux. L'impact de tes touches (la moitié de la note) est plus facile à obtenir face à des adversaires plus faibles. Ton niveau technique est mesuré à part (Mon jeu › Tous les indicateurs › Technique).` : "",
        "Dans l'onglet Matchs, la note décomposée montre quelle composante a fait monter ou baisser la note ce jour-là. Le classement de la partie compare ton indice à celui des 5 autres joueurs, calculé de la même façon.",
        val ? `Validité vérifiée : l'équipe dont l'indice moyen est le plus haut gagne ${Math.round(z(val.team_acc_oof) * 100)} % des parties SSL (validation croisée)${val.rlcs_team_acc ? `, ${Math.round(val.rlcs_team_acc * 100)} % de ${val.rlcs_n_matches} matchs RLCS jamais vus` : ""} et ${Math.round(z(val.perso_team_acc) * 100)} % de tes ${val.perso_n_matches} parties.` : "",
        val?.retest ? `**Fiabilité** : une note de match bouge beaucoup d'une partie à l'autre, même pour un pro. Il faut environ **${val.retest.index.matches_for_08} parties** pour que ta moyenne soit stable (fiabilité 0,8) ; pour les fondamentaux, **${val.retest.fond.matches_for_08}** suffisent, pour la production il en faudrait ${val.retest.prod.matches_for_08}. Une note de match raconte ce qui s'est passé ; pour juger ta progression, regarde des moyennes.` : ""],
      limits: ["L'impact des touches pèse environ la moitié de la note et c'est la partie la plus volatile : quelques grosses touches font la note d'un match.", "Les poids reflètent ce qui fait gagner en SSL, pas forcément ce qui fait progresser.", "Ne voit pas la communication, le mental ni les feintes : seulement ce qui se mesure dans le replay."] },
    { id: "valeur", title: "Valeur de la situation",
      what: "À chaque instant du match, un chiffre entre −1 et +1 qui dit si la situation est favorable à ton équipe : +1 = vous allez marquer, −1 = vous allez encaisser, 0 = rien de décisif.",
      steps: [
        `**Un modèle LightGBM a regardé ${vm ? vm.n_matches : "les"} matchs RLCS**, dixième de seconde par dixième de seconde, en notant à chaque fois si une équipe marquait dans les ${vm ? vm.horizon_s : 5} secondes suivantes.`,
        `**Il a appris à reconnaître les situations dangereuses** à partir de 99 informations : où est la balle et où elle va (vers un cadre ou non, dans combien de temps), où sont les 6 voitures, leur vitesse, leur boost, si elles sont démolies, si elles font face à la balle, combien de joueurs sont du bon côté de la balle, le temps restant et l'écart au score.`,
        `**Valeur** = chance que ton équipe marque − chance que l'adversaire marque, dans les ${vm ? vm.horizon_s : 5} s.`],
      example: "Ton coéquipier récupère la balle face au but adverse vide, les 3 adversaires sont derrière : la valeur monte vers +0,6. L'adversaire part seul vers votre but alors que vous êtes tous devant : elle descend vers −0,5.",
      read: ["La valeur ne juge personne : elle décrit la situation. C'est sa variation après une touche qui sert à juger la touche (voir « Gain d'une touche »).", "Dans l'onglet Matchs, « Le déroulé » trace cette valeur toutes les 0,5 s pendant le jeu.",
        vm ? `Testé sur ${vm.n_test_matches} matchs jamais vus : AUC ${z(vm.auc).toFixed(2).replace(".", ",")} (0,5 = hasard, 1 = parfait). Quand il annonce 30 % de chances, il y a bien environ 30 % de buts.` : ""],
      limits: ["Appris sur des pros : en classé, les défenses encaissent plus, donc les vraies chances de but y sont plus élevées que ce qu'il annonce.", "Ne connaît pas l'avenir au-delà de 5 s : une construction lente n'est récompensée qu'au moment où elle devient dangereuse."] },
    { id: "gain", title: "Gain d'une touche et impact",
      what: "Ce que chaque touche de balle a changé à la situation de ton équipe. L'impact d'un match = la somme de tes gains, ramenée à 5 minutes de jeu.",
      steps: ["On prend la valeur de la situation 0,2 s avant ta touche (avant que ta touche ne change quoi que ce soit).",
        "On prend la valeur juste avant la touche suivante, au plus 1 s après : c'est la conséquence directe de ta touche.",
        "Gain = valeur après − valeur avant. Si un but est marqué entre les deux, la valeur après vaut +1 (pour vous) ou −1 (contre vous).",
        "Impact = somme de tous tes gains du match ÷ temps de jeu effectif × 5 minutes."],
      example: "Tu dégages une balle qui partait au fond : la valeur passe de −0,40 à −0,05, gain +0,35. Tu fais une passe en retrait que l'adversaire intercepte face à ton but : de +0,10 à −0,30, gain −0,40.",
      read: ["Positif = ta touche a amélioré la situation ; négatif = elle l'a dégradée.", "Une touche moyenne rapporte environ +0,02 : c'est l'accumulation qui fait la différence.",
        "Les ralentis (onglet À travailler) listent tes 10 touches les plus coûteuses ; l'horloge est le temps restant au moment de la touche (5:00 → 0:00).",
        "Le gain moyen par type de touche compare tes touches à toutes celles des matchs RLCS ; en classé, les défenses encaissent environ " + (V?.ranked_goal_ratio ?? 1.5) + "× plus de buts que ne le prévoit le modèle : une touche vers le but y rapporte donc plus."],
      limits: ["Ne juge que les touches : le travail sans ballon (pression, couverture, feintes) n'y apparaît pas directement.", "Une touche correcte peut être pénalisée si un coéquipier perd la balle juste après (fenêtre d'1 s)."] },
    { id: "revoir", title: "Revoir une touche en 3D",
      what: "Le bouton **▶ Revoir**, à côté d'une touche, la rejoue dans un petit lecteur 3D : 3 s avant, 1 s après. C'est une **reconstitution à partir du replay, pas une vidéo du jeu**.",
      steps: ["Le replay de la partie, gardé après l'analyse, est relu au clic : positions, vitesses, orientation et boost des 6 voitures et de la balle, 120 images par seconde.",
        "On retrouve l'instant exact de la touche : le moment où la balle est au plus près de la position notée lors de l'analyse.",
        "On découpe 3 s avant et 1 s après, à 30 images par seconde ; le lecteur lisse le mouvement entre deux images."],
      read: ["En jaune (anneau au sol, contour, flèche au-dessus) : l'auteur de la touche. Son équipe est en bleu et attaque vers le haut ; l'autre équipe est en orange.",
        "Chaque voiture est une boîte orientée, face blanche à l'avant ; la jauge orange au-dessus est son boost, une flamme à l'arrière indique qu'elle booste. Pointillés : hauteur de la balle ou d'une voiture en l'air.",
        "Le repère jaune de la barre de temps marque la touche. Ralenti, rotation et vue de dessus aident à lire les placements.",
        "Le premier clip d'un match prend environ une seconde (le replay est relu) ; les touches suivantes du même match s'ouvrent plus vite."],
      limits: ["Voitures dessinées 1,8× plus grandes que dans le jeu pour rester lisibles ; pas de caméra du joueur ni de vue de son écran.",
        "Possible seulement pour les parties dont le replay a été gardé, et pas pour une touche collée au début ou à la fin du replay."] },
    { id: "resultat", title: "Résultat de tes touches et rang dans la partie",
      what: "Ton impact (somme des gains de tes touches) comparé à celui des autres joueurs de tes parties, pour savoir si tu as plus ou moins pesé que les joueurs qui t'entouraient.",
      steps: ["Pour chaque partie, on calcule l'impact par 5 minutes des 6 joueurs.", "**Rang** : ta place parmi les 6 (1 = le plus d'impact). Le chiffre affiché est la moyenne de tes rangs.", "**Résultat** : centile de ton impact parmi tous les impacts des autres joueurs de tes parties (une valeur par joueur et par partie)."],
      read: ["Rang moyen 3,5 = exactement dans la moyenne de tes lobbies ; plus bas = mieux.", "Résultat 50 = autant d'impact que le joueur médian de tes parties."],
      limits: ["Comparé aux joueurs de tes parties et pas aux pros : en classé, chaque tir rapporte plus car les défenses encaissent plus, la comparaison aux pros serait faussée.", "Dépend du niveau de tes lobbies."] },
    { id: "placement", title: "Placement hors ballon",
      what: "Quand tu n'es pas le joueur qui va à la balle, est-ce que tu te places là où un pro se placerait dans la même situation ?",
      steps: [`**On isole les moments où tu es 2e ou 3e homme**, c'est-à-dire pas le coéquipier le plus proche de la balle. On en prend un toutes les 0,5 s de jeu ; les moments où tu es démoli sont exclus.`,
        `**On décrit la situation sans ta position** : balle, 1er homme, ton autre coéquipier, ton boost, les 3 adversaires, le temps restant, et si tu es 2e ou 3e homme.`,
        `**Un modèle prédit où serait un pro** dans cette situation. Il a appris sur 2,7 millions de positions de 2e et 3e homme dans 1 000 matchs RLCS ; il donne la position « typique » des pros (la médiane), pas une position idéale.`,
        `**On mesure l'écart** entre ta vraie position et la position prédite, en mètres, puis on garde l'écart médian du match.`,
        `**Note** = part des performances de pros RLCS dont l'écart est plus grand que le tien${plc ? ` (${plc.n_ref} joueurs-matchs)` : ""}. 50 = aussi proche de la position « pro » qu'un pro médian.`],
      example: plc ? `Balle dans le coin adverse, ton 1er homme la conteste, tu es 2e homme : le modèle te place vers le milieu de terrain, côté balle, prêt à récupérer un dégagement. Si tu es resté collé à ton but, l'écart est grand et la note baisse. Écart médian : ${m_(plc.me_med)} pour toi, ${m_(plc.ref_med)} pour un pro médian. Sans modèle (toujours la même position moyenne), l'écart serait d'environ 33 m ; le modèle descend à 17 m sur des pros qu'il n'a jamais vus.` : "",
      read: ["Plus haut = tu te places plus comme un pro.", "Tes lobbies servent de repère : à leur niveau, un écart avec les pros est attendu ; ce qui compte, c'est d'être au-dessus d'eux et de progresser.", "Son évolution match par match est dans Mon jeu › Tous les indicateurs › Notes des modèles."],
      limits: ["Il existe souvent plusieurs bonnes positions : une position originale mais juste compte comme un écart.", "Ne juge que la position, pas le timing.", "Ne concerne pas le 1er homme, ni ce que tu fais avec la balle.", "Dans l'indice de performance, il pèse presque rien : à niveau SSL, il ne sépare pas les gagnants des perdants."] },
    { id: "choix", title: "Choix à la touche (expérimental)",
      what: "Quand tu touches la balle, as-tu choisi l'option qui, chez les pros, rapporte le plus dans cette situation ?",
      steps: ["Chaque touche (hors arrêts) est classée en 5 options selon où part la balle 0,3 s après : **tir**, **vers l'avant**, **latérale**, **en retrait**, ou **contrôle**.",
        "Un premier modèle apprend, sur les touches RLCS, quelles options les pros choisissent dans chaque situation : seules les options choisies au moins 10 % du temps par un pro sont considérées comme réalistes.",
        "Un second modèle estime le gain qu'aurait chaque option réaliste dans la situation.",
        "**Regret** = gain de la meilleure option réaliste − gain de l'option que tu as choisie. Note = 100 − centile de ton regret moyen parmi les joueurs-matchs RLCS."],
      read: ["Plus haut = tes choix ressemblent davantage aux meilleurs choix des pros.", dec ? `Tu choisis l'option la plus probable chez un pro dans ${Math.round(z(dec.me_ppro) * 100)} % des cas (pros : ${Math.round(z(dec.ref_ppro) * 100)} %).` : ""],
      limits: ["**Mesure peu fiable aujourd'hui** : le second modèle n'explique que 27 % des variations du gain, et il juge presque toujours le tir comme la meilleure option et le jeu en retrait comme la pire.", "Ne sait pas ce que tu voulais faire, seulement où la balle est partie.", "Ne compte pas dans l'indice de performance."] },
    { id: "centile", title: "Centiles, notes et références",
      what: "La plupart des notes de la page disent où tu te situes parmi un groupe de joueurs de référence.",
      steps: ["Pour chaque indicateur, on prend ta moyenne sur toutes tes parties.", "On prend la moyenne de chaque joueur de la référence sur ses propres parties.",
        "**Centile** = part de ces joueurs dont la valeur est sous la tienne (égalités comptées pour moitié).",
        "**Note** = centile si « plus haut = mieux », 100 − centile si « plus bas = mieux » (temps à 0 boost, balles ratées…). « Mieux que 80 % » = note 80.",
                "**Face-à-face** (Mon trio) : uniquement les parties jouées dans la même équipe ; moyenne par partie de chacun. La valeur gagnante est celle qui va dans le bon sens de l'indicateur."],
      read: [`**Référence SSL** : ${C.refs.ssl ? C.refs.ssl.n_ref_players + " joueurs vus dans " + C.refs.ssl.n_ref_matches : "des"} parties classées 3v3 où les 6 joueurs sont Supersonic Legend (replays publics ballchasing). La plus juste pour toi : même mode, même type de partie.`,
        `**Référence RLCS** : ${C.refs.rlcs ? C.refs.rlcs.n_ref_players + " pros ayant au moins 2 matchs parmi " + C.refs.rlcs.n_ref_matches : "des"} matchs RLCS 2026.`, "Tu changes de référence avec « Comparer à », en haut de la page."],
      limits: ["Un joueur SSL n'apparaît souvent que dans une ou deux parties : sa moyenne est bruitée ; la référence est solide dans son ensemble, pas joueur par joueur.", `Tes ${C.n_matches} parties forment un petit échantillon : les centiles bougent encore.`] },
    { id: "styles", title: "Styles de jeu",
      what: "Ton style décrit **comment** tu joues, pas si tu joues bien. Les styles ne sont pas inventés : ce sont des familles de comportements qui vont ensemble chez 401 joueurs SSL et pros RLCS.",
      steps: [
        "**30 traits par match** : rôle dans la rotation (1er, 3e homme), temps derrière la balle et dans chaque zone, jeu aérien, murs, contrôle et conduite de balle, contacts, 50/50, tirs, arrêts, dégagements, passes, gestion et vol de boost, vitesse, volume de touches, pertes et balles ratées. Le résultat (buts, victoire) n'en fait pas partie.",
        "**Comparés aux 5 autres joueurs de la partie** : chaque trait est mesuré par rapport à la moyenne du match. Sinon le niveau se confondrait avec le style (en classé, tout le monde joue plus haut que les pros).",
        "**Analyse factorielle** (ACP + rotation varimax) sur la moyenne de chaque joueur : 7 familles de traits qui varient ensemble ressortent. Chaque famille a deux pôles, et chaque pôle est nommé d'après les traits qui le portent : Voltigeur, Forteresse / Harceleur, Ancre / Fer de lance, Fusée, Fiable / Tête brûlée, Porteur, Meneur.",
        "**Ton affinité** avec un style = part des joueurs de référence moins marqués que toi dans ce style. Ton style principal est le plus marqué parmi les styles stables.",
        "**Style du trio** : quand tous les joueurs suivis partagent nettement un style (affinité ≥ 80), il décrit l'équipe ; ton style individuel est alors choisi parmi les autres familles.",
        "**Tu joues comme** : les pros RLCS (au moins 10 matchs) dont le profil sur les 7 familles est le plus proche du tien."],
      read: ["Les styles sont stables : un même pro garde le même style entre ses matchs pairs et impairs (accord de 0,69 à 0,88). Le Meneur et le Porteur le sont moins (≈ 0,3) : ils sont affichés en pâle et ne peuvent pas être ton style principal.",
        "« Ce style ressort dans N de tes parties » : nombre de parties où ce style est dans tes deux plus marqués."],
      limits: ["Un style n'est ni bon ni mauvais : les meilleurs pros se répartissent dans tous les styles.", "Avec peu de parties (moins de 10), ton style peut encore bouger.", "« Tu joues comme X » compare des styles, pas des niveaux."] },
    { id: "conseils", title: "Conseils",
      what: "Trois conseils, chacun tiré d'une mesure précise, avec la raison affichée sous le conseil.",
      steps: ["**Indice** : la composante qui te coûte le plus de points (poids × écart sous 50).",
        "**Technique** : ta mesure technique la plus en retard face aux autres joueurs de tes parties (au moins 8 % d'écart).",
        "**Style** : le piège typique de ton style principal."],
      read: ["Les conseils changent avec les filtres de la page : ils portent sur les parties affichées."],
      limits: ["Les textes de conseil sont écrits à la main pour chaque mesure : ils indiquent une piste, pas une méthode d'entraînement complète."] },
    { id: "progression", title: "Progression",
      what: "Ce qui a changé entre la seconde moitié et la première moitié de tes 20 dernières parties (ou de toutes si tu en as moins).",
      steps: ["Pour l'indice, ses deux sous-notes, ses 7 composantes et tes mesures techniques : moyenne des parties récentes moins moyenne des parties d'avant (orientée pour que ▲ = mieux).",
        "Classement par taille de l'écart rapportée à la variation habituelle de la mesure.",
        "**Net** : l'écart garde le même signe dans 80 % des tirages au sort de tes parties (1 000 tirages). Sinon : « bruit ? »."],
      read: ["La courbe montre l'indice de chaque partie (bleu : victoire, orange : défaite) et sa moyenne glissante sur 5 parties ; le trait vertical sépare les deux moitiés comparées."],
      limits: ["Une note de match est volatile : une progression « nette » sur 10 parties peut encore être en partie due au hasard.", "Ne distingue pas les progrès des changements d'adversaires ou de coéquipiers."] },
    { id: "synergie", title: "Synergie entre coéquipiers",
      what: "Ce que vous produisez **à deux**, mesuré dans les interactions entre vous plutôt qu'au taux de victoire (il faudrait des centaines de parties dans chaque configuration).",
      steps: [
        "**Connexion** : parmi vos touches à tous les deux, part de celles où la touche suivante (au plus 3 s après) est faite par l'autre.",
        "**Bonus par enchaînement** : pour chaque enchaînement A → B, gain de valeur des deux touches (modèle de valeur) moins ce que ces deux joueurs gagnent en moyenne par touche. Positif = vos enchaînements rapportent plus que vos touches isolées.",
        "**Double commit** : temps où vous êtes tous les deux à moins de 10 m de la balle avec un adversaire à moins de 15 m (images à 10 par seconde, jeu en cours).",
        "**Montés ensemble sans couverture** : temps où aucun de vous deux n'est entre la balle et votre but, le troisième étant à plus de 30 m de la balle.",
        "**Écart moyen** : distance moyenne entre vos deux voitures pendant le jeu.",
        "Comparaisons : toi avec un coéquipier inconnu (mêmes parties filtrées), et les paires de 299 parties SSL. Bande = intervalle à 80 % (tirage des parties).",
      ],
      read: ["Le verdict compare la bande de votre paire à la valeur SSL : « mieux » ou « moins bien » seulement si toute la bande est du même côté.",
        "Le sens « qui sert qui » repose sur quelques dizaines d'enchaînements par sens : à lire comme une tendance."],
      limits: ["Un double commit n'est pas toujours une erreur (défense près du but).", "Le niveau des adversaires n'est pas neutralisé.",
        "Le taux de victoire par paire n'est pas interprétable avec si peu de parties."] },
    { id: "passes", title: "Balles données et passes récupérées",
      what: "Quand tu envoies la balle vers l'avant, sur le côté ou en retrait, est-ce qu'un coéquipier la récupère, ou est-ce qu'elle part dans le vide ?",
      steps: ["On garde tes touches qui envoient la balle vers l'avant, latéralement ou en retrait (direction de la balle 0,3 s après), hors tirs, hors contrôles et hors de ton tiers défensif (pour ne pas compter les dégagements).",
        "On regarde qui touche ensuite la balle : un coéquipier = récupérée, un adversaire = perdue.",
        "On regarde si un coéquipier était en position : 1 s après ta touche, ton coéquipier le plus proche de la balle en est-il plus près que l'adversaire le plus proche ?",
        "Une passe **dans le vide** = personne en position et balle perdue. Les 10 plus coûteuses sont classées par gain à 2 s (valeur 2 s après − valeur 0,2 s avant)."],
      read: ["Beaucoup de balles « récupérées sans coéquipier placé » = tes coéquipiers lisent bien tes passes dans l'espace.", "Beaucoup de passes dans le vide dans le tiers offensif = des centres ou remises que personne n'attend."],
      limits: ["La fenêtre d'1 s est courte : une longue passe dans l'espace récupérée plus tard par un coéquipier lancé compte comme « personne en position » (mais bien comme récupérée).", "Ne distingue pas une passe voulue d'une touche ratée qui part dans la même direction."] },
    { id: "style", title: "Répartitions du temps (style de jeu)",
      what: "Comment ton temps de jeu se partage entre rôles, zones, réserves de boost, hauteurs, vitesses et types de touche.",
      steps: ["Le lecteur de replays (subtr-actor 1.5.1) classe chaque instant : rôle dans la rotation, tiers du terrain, position par rapport à la balle, tranche de boost, au sol ou en l'air, vitesse, et chaque touche selon sa force.",
        "Pour chaque joueur ou groupe, on additionne les temps de chaque catégorie sur toutes les parties et on divise par le temps total (une partie longue pèse donc plus).",
        "Mon jeu montre les 6 catégories où ta part s'écarte le plus de celle de la référence, en points de pourcentage."],
      read: ["Pas de bonne ou mauvaise valeur : ce sont des choix de style. Un écart fort avec les SSL ou les pros mérite qu'on se demande s'il est voulu."],
      limits: ["Certains seuils (vitesse « lente », hauteur « haute ») sont internes au lecteur de replays et ne sont pas publiés ; seul le seuil supersonique (2 200 uu/s) est celui du jeu."] },
    { id: "terrain", title: "Cartes du terrain",
      what: "Où tu passes ton temps, en quoi c'est différent des pros, et ce que rapportent tes touches selon l'endroit.",
      steps: [`Le terrain est retourné pour que ton équipe attaque toujours vers le haut, puis découpé en ${HEAT ? HEAT.gx + " × " + HEAT.gy : ""} cases d'environ 10 m de côté.`,
        "Temps : ta position est relevée toutes les 0,5 s pendant le jeu (pas pendant les kickoffs ni les célébrations) ; part de temps par case, en 5 paliers de la case la moins à la plus fréquentée.",
        `Toi vs les pros : ta part de temps − celle des 6 joueurs de ${HEAT ? HEAT.n_pro_replays : ""} matchs RLCS, case par case ; 5 paliers rapportés au plus gros écart.`,
        "Touches : gain moyen de tes touches par case, à la position de la balle au contact ; paliers à ±0,01 et ±0,04."],
      read: ["Une zone orange sur « Toi vs les pros » = un endroit où les pros passent plus de temps que toi.", "Sur « Touches », une zone orange = des touches qui, en moyenne, dégradent la situation."],
      limits: ["Une case avec moins de 8 touches n'est pas colorée : trop peu pour juger.", "Les pros jouent des matchs plus serrés et plus rapides : un écart n'est pas forcément une erreur."] },
  ];
}
export function caveats(d: Derived): string[] {
  const { C, V, PF } = d;
  return [
    `**Échantillon réduit** : ${C.n_matches} parties. Les centiles et les écarts entre joueurs bougent encore beaucoup.`,
    `**Référence SSL** : parties classées 3v3 où les 6 joueurs sont Supersonic Legend. Comparaison la plus juste, mais chaque joueur SSL n'apparaît que dans 1 ou 2 parties : sa moyenne est bruitée. **Référence RLCS** : tes parties sont des classées, la référence des matchs pro ; un écart de rythme ou de prise de risque est attendu.`,
    `**Résultat de tes touches** : comparé aux autres joueurs de tes parties, pas aux pros. En classé, les défenses encaissent ${V?.ranked_goal_ratio ?? 1.5}× plus de buts que ne le prévoit le modèle appris sur les pros.`,
    `**Placement hors ballon** : écart entre ta position et celle qu'aurait un pro dans la même situation. **Choix à la touche** : encore expérimental, ne pas s'y fier.`,
    ...(PF ? [`**Indice de performance** : ses poids viennent de ce qui fait gagner en SSL, donc l'impact des touches domine (${Math.round(z(PF.components.find(c => c.key === "impact")?.weight) * 100)} %). Le placement y pèse presque rien : à ce niveau il ne sépare pas gagnants et perdants, ce qui ne veut pas dire qu'il ne compte pas. Sur ${PF.me?.n ?? 0} parties, l'indice global a une marge d'environ ±${Math.round((z(PF.me?.hi) - z(PF.me?.lo)) / 2)} points.`] : []),
    `Les stats brutes viennent des détecteurs de subtr-actor 1.5.1 (50/50, ratées, rôles…), pas encore vérifiés à la main sur des extraits vidéo.`,
  ];
}

export function definitions(d: Derived): { source: string; items: Definition[] } {
  const items: Definition[] = (d.D?.metrics ?? []).map((m) => ({
    label: m.label,
    meta: `${m.unit}${m.sens === 0 ? ", style" : m.sens > 0 ? ", plus haut = mieux" : ", plus bas = mieux"}`,
    def: METRIC_DEF[m.key] || "",
  }));
  for (const t of d.C.tech?.rows ?? []) items.push({ label: t.label, meta: "technique", def: t.def });
  return { source: SRC, items };
}
