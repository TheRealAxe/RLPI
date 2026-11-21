// Fenêtre « Revoir » : ouverte depuis n'importe quel bouton ▶ Revoir (À travailler, Matchs), une seule pour toute
// l'application (components/ActionReplay.vue). Le focus revient au bouton à la fermeture.
import { reactive } from "vue";

/** Touche à revoir : où la retrouver (partie, indice d'image) et de quoi titrer la fenêtre. */
export interface ReplayReq {
  match: string;
  i: number;
  /** Type de touche, tel que donné par les données (« Tirs », « Dégagements »…). */
  action: string;
  clock?: number | null;
  vb?: number | null;
  va?: number | null;
  date?: string | null;
}

export const replay = reactive({ open: false, req: null as ReplayReq | null, seq: 0, opener: null as HTMLElement | null });

/** Une touche se revoit si l'on connaît sa partie et son indice d'image. */
export const canReplay = (match: string | null | undefined, i: number | null | undefined): boolean =>
  !!match && typeof i === "number" && Number.isInteger(i) && i >= 0;

export function openReplay(req: ReplayReq, opener?: EventTarget | null): void {
  replay.opener = opener instanceof HTMLElement ? opener : (document.activeElement as HTMLElement | null);
  replay.req = req;
  replay.seq++;
  replay.open = true;
}

/** Ferme la fenêtre ; ActionReplay rend ensuite le focus au bouton (après la fermeture du <dialog>, qui sinon
 * rendrait le focus à l'élément actif avant son ouverture). */
export function closeReplay(): void {
  replay.open = false;
}

export function refocusOpener(): void {
  const o = replay.opener;
  if (o && document.contains(o)) o.focus();
}
