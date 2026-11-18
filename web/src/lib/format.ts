// Formats de nombres et de dates (spec Plateau, COPY.md) : virgule décimale, espace fine insécable avant les
// unités, vrai signe moins (U+2212). Repris à l'identique de l'ancien gabarit.

export const NB = " ";
export const MINUS = "−";

type N = number | null | undefined;

/** Nombre à d décimales, virgule, signe moins typographique. */
export const num = (v: number, d = 1): string => (v < 0 ? MINUS : "") + Math.abs(v).toFixed(d).replace(".", ",");
/** Valeur signée (+0,35 / −0,92) ; « — » si absente. */
export const sgn = (v: N, d = 2): string =>
  v == null ? "—" : (v >= 0 ? "+" : MINUS) + Math.abs(v).toFixed(d).replace(".", ",");
/** Entier signé (+8 / −5). */
export const sgnI = (v: number): string => (Math.round(v) >= 0 ? "+" : MINUS) + Math.abs(Math.round(v));
/** Entier arrondi ; « — » si absent. */
export const R = (v: N): string => (v == null ? "—" : String(Math.round(v)));
/** Part (0–1) en pourcentage entier. */
export const pc = (v: N): string => (v == null ? "—" : Math.round(v * 100) + NB + "%");

/** Valeur d'un indicateur avec son unité. */
export function fmt(v: N, unit = ""): string {
  if (v == null) return "—";
  const a = Math.abs(v),
    d = a >= 100 ? 0 : a < 1 && a !== 0 ? 2 : 1;
  const s = num(v, d);
  if (unit.startsWith("%")) return s + NB + "%";
  if (unit === "km/h") return s + NB + "km/h";
  if (unit.includes("/ 5 min")) return s + NB + "/ 5 min";
  if (unit === "/100") return R(v);
  if (unit === "/6") return num(v, 1) + NB + "/ 6";
  return s;
}

const dParts = (d: string) => {
  const [y, m, j] = d.slice(0, 10).split("-");
  return { y, m, j, h: d.slice(11, 16).replace("-", ":") };
};
/** Heure « 21:05 » d'une date de replay. */
export const dH = (d: string): string => dParts(d).h;
/** Date courte de bandeau : 14.11 */
export const dS = (d: string): string => {
  const p = dParts(d);
  return `${p.j}.${p.m}`;
};
/** Date compacte : 14.11.26 */
export const dC = (d: string): string => {
  const p = dParts(d);
  return `${p.j}.${p.m}.${p.y.slice(2)}`;
};
/** Date longue de texte : 14/11/2026 */
export const dL = (d: string): string => {
  const p = dParts(d);
  return `${p.j}/${p.m}/${p.y}`;
};
/** Horloge de jeu (secondes restantes) : 4:07 */
export const clock = (s: N): string =>
  s == null ? "—" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
/** Rang ordinal : 1er, 2e… */
export const ord = (r: number): string => (r === 1 ? "1er" : r + "e");
/** « a, b et c » */
export const joinFr = (a: string[]): string =>
  a.length <= 1 ? (a[0] ?? "") : a.slice(0, -1).join(", ") + " et " + a[a.length - 1];
export const cap = (s: string): string => (s ? s[0].toUpperCase() + s.slice(1) : s);
/** Score « 3-2 » → « 3–2 » */
export const scoreTxt = (s: string | null | undefined): string => (s ? s.replace("-", "–") : "");
