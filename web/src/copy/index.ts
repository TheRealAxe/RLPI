// Textes de l'interface (spec Plateau, COPY.md) : verdicts, formulations par indicateur, phrases de lecture.
// Ton : tutoiement, phrases courtes, on constate sans juger. Repris de l'ancien gabarit.
import type { Perf, PerfMatch } from "@/api/client";
import { NB, R, cap, clock, ord, sgn } from "@/lib/format";

type N = number | null | undefined;

/** Verdict d'un match d'après son indice. */
export const verdict = (v: N): string => {
  const x = v ?? 0;
  return x >= 70 ? "Très bon match" : x >= 55 ? "Bien joué" : x >= 45 ? "Match correct" : x >= 30 ? "Match en dessous" : "Mauvais match";
};

/** Verdict de l'indice global (moyenne des matchs) face à la performance SSL médiane (50). */
export const verdictG = (v: N): string => {
  const x = v ?? 0;
  return x >= 65
    ? "Nettement au-dessus d'une performance SSL médiane"
    : x >= 55
      ? "Au-dessus d'une performance SSL médiane"
      : x >= 45
        ? "Au niveau d'une performance SSL médiane"
        : x >= 35
          ? "Un peu en dessous d'une performance SSL médiane"
          : "En dessous d'une performance SSL médiane";
};

/** Formulations par indicateur : [force (« tu … »), chantier (nom), duel (nom court)]. */
export const PH: Record<string, [string, string, string]> = {
  boost_zero: ["tu es rarement à sec de boost", "le temps à 0 boost", "le boost à sec"],
  boost_petits: ["tu vis sur les petits pads", "les petits pads", "les petits pads"],
  boost_vole: ["tu voles le boost adverse", "le vol de boost", "le boost volé"],
  boost_gaspille: ["tu gaspilles peu de boost", "le boost gaspillé", "le boost gaspillé"],
  vitesse: ["tu joues vite", "la vitesse", "la vitesse"],
  supersonique: ["tu restes supersonique", "le temps supersonique", "le supersonique"],
  lent: ["tu ralentis rarement", "le temps passé lent", "le temps lent"],
  ff_gagnes: ["tu gagnes tes 50/50", "les 50/50", "les 50/50"],
  ko_gagnes: ["tu gagnes tes kickoffs", "les kickoffs", "les kickoffs"],
  tirs: ["tu tires souvent", "le volume de tirs", "les tirs"],
  buts: ["tu finis tes actions", "la finition", "les buts"],
  frappes_fortes: ["tu frappes fort", "les frappes fortes", "les frappes fortes"],
  ratees: ["tu rates peu de balles", "les balles ratées", "la propreté"],
  passes: ["tu fais jouer tes coéquipiers", "les passes", "les passes"],
  demos: ["tu démolis souvent", "les démos", "les démos"],
  bumps: ["tu bouscules beaucoup", "les bumps", "les bumps"],
  moitie_adverse: ["tu presses haut", "la présence chez l'adversaire", "le pressing"],
  plc_note: ["tu te places comme un pro", "le placement", "le placement"],
  dec_note: ["tu choisis bien à la touche", "le choix à la touche", "le choix à la touche"],
  lobby_note: ["tes touches rapportent", "le résultat des touches", "le résultat des touches"],
  lobby_rank: ["tu pèses dans tes parties", "le rang dans la partie", "le rang dans la partie"],
};
export { cap } from "@/lib/format";
export const ph = (key: string, i: 0 | 1 | 2, label?: string): string => PH[key]?.[i] ?? (label || key).toLowerCase();

/** Types de touche au singulier (les données les donnent au pluriel). */
const ACT1: Record<string, string> = {
  Tirs: "Tir",
  Arrêts: "Arrêt",
  Dégagements: "Dégagement",
  Passes: "Passe",
  "Frappes fortes": "Frappe forte",
  "Contrôles / autres": "Contrôle",
};
export const act1 = (a: string): string => ACT1[a] ?? a;

/** Composantes de l'indice : [forme longue avec article, forme courte, pluriel]. */
const COMP_PH: Record<string, [string, string, boolean]> = {
  impact: ["l'impact de tes touches", "ton impact", false],
  placement: ["ton placement hors ballon", "ton placement", false],
  duels: ["tes 50/50", "tes 50/50", true],
  boost: ["ta gestion du boost", "ton boost", false],
  vitesse: ["ta vitesse", "ta vitesse", false],
  fiabilite: ["ta fiabilité (peu de ratés)", "ta fiabilité", false],
  collectif: ["ton jeu collectif", "ton jeu collectif", false],
};
type Comp = Perf["components"][number];
const cph = (c: Comp, i: 0 | 1): string => COMP_PH[c.key]?.[i] ?? c.label.toLowerCase();
const plural = (c: Comp): boolean => COMP_PH[c.key]?.[2] ?? false;

/** Phrase de lecture d'un match : verdict, rang, composante la plus lourde, et ce qui compense ou reste en retrait. */
export function matchSentence(PF: Perf, m: PerfMatch, withVerdict = true): string {
  const comps = [...PF.components].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0));
  const top = comps[0];
  const s = m.comps[top.key] ?? 0;
  let out = (withVerdict ? `${verdict(m.index)} : ` : "") + `${ord(m.rank)} sur ${m.n_players}. `;
  out += `${cap(cph(top, 0))} ${plural(top) ? "pèsent" : "pèse"} ${Math.round((top.weight ?? 0) * 100)}${NB}% de la note et ${s >= 50 ? "monte" : "tombe"}${plural(top) ? "nt" : ""} à ${R(s)}/100.`;
  const rest = comps.slice(1).filter((c) => (c.weight ?? 0) >= 0.05);
  const v = (c: Comp) => m.comps[c.key] ?? 0;
  if ((m.index ?? 0) < 50) {
    const c = rest.filter((c) => v(c) >= 55).sort((a, b) => v(b) - v(a))[0];
    if (c) out += ` ${cap(cph(c, 1))} (${R(v(c))}) ne ${plural(c) ? "compensent" : "compense"} pas.`;
  } else {
    const c = rest.filter((c) => v(c) < 45).sort((a, b) => v(a) - v(b))[0];
    if (c) out += ` ${cap(cph(c, 1))} ${plural(c) ? "restent" : "reste"} en retrait (${R(v(c))}).`;
  }
  return out;
}

/** Verdict d'une mesure de synergie : « mieux » ou « moins bien » que les paires SSL seulement si toute la bande
 *  à 80 % est du même côté. [texte, classe de couleur] */
export function synVerdict(r: { sens: number; lo: number | null; hi: number | null; ssl: number | null }): [string, string] {
  if (r.sens === 0) return ["style", "pl-muted"];
  const lo = r.lo ?? 0,
    hi = r.hi ?? 0,
    ssl = r.ssl ?? 0;
  const better = r.sens > 0 ? lo > ssl : hi < ssl,
    worse = r.sens > 0 ? hi < ssl : lo > ssl;
  return better ? ["mieux que les SSL", "pl-good"] : worse ? ["moins bien que les SSL", "pl-bad"] : ["comme les SSL", "pl-muted"];
}

// ------------------------------------------------------------------ Revoir une touche en 3D

/** Textes de la fenêtre « Revoir » et de ses boutons. */
export const REVOIR = {
  button: "▶ Revoir",
  loading: "Préparation du clip…",
  loadingNote: "Le premier clip d'un match prend environ une seconde : le replay est relu.",
  note: "Reconstitution 3D à partir du replay, pas une vidéo du jeu. « Ta caméra » reprend tes réglages et ta caméra balle enregistrés dans le replay ; le stick droit n'y est pas enregistré.",
  camDefault: "Tes réglages caméra n'ont pas été relevés pour cette partie : réglages par défaut du jeu.",
  retry: "Réessayer",
  close: "Fermer ✕",
};

/** En-tête de la fenêtre : « Dégagement · 2:31 · situation −0,30 → −0,60 ». */
export function replayTitle(t: { action: string; clock?: number | null; vb?: number | null; va?: number | null }): string {
  const parts = [act1(t.action)];
  if (t.clock != null) parts.push(clock(t.clock));
  if (t.vb != null && t.va != null) parts.push(`situation ${sgn(t.vb)} → ${sgn(t.va)}`);
  return parts.join(" · ");
}

/** Nom accessible d'un bouton « Revoir » : « Revoir en 3D : tir à 2:31 ». */
export const replayLabel = (t: { action: string; clock?: number | null }): string =>
  `Revoir en 3D : ${act1(t.action).toLowerCase()}${t.clock != null ? ` à ${clock(t.clock)}` : ""}`;
