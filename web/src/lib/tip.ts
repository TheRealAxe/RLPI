// Info-bulle commune (une seule à l'écran). Contenu structuré, jamais de HTML : les pseudos restent du texte.
import { reactive } from "vue";

/** Un morceau de ligne : texte simple, gras ({ b }) ou discret ({ m }). */
export type TipPart = string | { b: string } | { m: string };
export type TipLine = TipPart[];

export const tip = reactive({ show: false, x: 0, y: 0, lines: [] as TipLine[] });

export function showTip(ev: MouseEvent, lines: TipLine[]): void {
  tip.lines = lines;
  tip.x = ev.clientX;
  tip.y = ev.clientY;
  tip.show = true;
}

export function hideTip(): void {
  tip.show = false;
}
