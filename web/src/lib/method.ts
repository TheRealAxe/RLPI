// Panneau Méthode : ouvert depuis n'importe quel bouton ⓘ, à la bonne rubrique ; le focus revient au bouton à la
// fermeture.
import { reactive } from "vue";

export const method = reactive({ open: false, rubric: "indice", seq: 0, opener: null as HTMLElement | null });

export function openMethod(rubric: string, opener?: EventTarget | null): void {
  method.opener = opener instanceof HTMLElement ? opener : (document.activeElement as HTMLElement | null);
  method.rubric = rubric;
  method.seq++; // même rubrique demandée deux fois : on y retourne quand même
  method.open = true;
}

export function closeMethod(): void {
  method.open = false;
  const o = method.opener;
  if (o && document.contains(o)) o.focus();
}
