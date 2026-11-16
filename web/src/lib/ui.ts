// État d'affichage partagé entre la coquille et les onglets.
import { reactive } from "vue";

export const ui = reactive({
  /** Ligne de contexte sous le nom (période, match, référence), donnée par l'onglet affiché. */
  ctx: "",
  /** Dernier match ouvert dans l'onglet Matchs (l'onglet y revient). */
  match: null as string | null,
  /** Carte de terrain affichée (Mon jeu). */
  terrain: "pros" as "temps" | "pros" | "touches",
  /** Coéquipier du face-à-face (Mon trio). */
  peer: 0,
  /** Indicateur dont on suit l'évolution (Tous les indicateurs). */
  evo: null as string | null,
});
