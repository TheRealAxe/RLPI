// Vue dérivée du contenu affiché : sections, coéquipiers (couleur et symbole), référence choisie, index par match.
// Mêmes règles que l'ancien gabarit (variables BASE, PF, V, PS, HEAT, PEERS, D, M).
import { computed } from "vue";
import { useRoute } from "vue-router";
import type { Contenu, Metric, Peer, Reference } from "@/api/client";
import { dC, dS } from "./format";
import { store } from "./store";

export type Slot = "mate-1" | "mate-2";
export type SymKind = "me" | Slot | "ref" | "none" | "other";
export interface PeerView extends Peer {
  slot: Slot;
  color: string;
  win: "win-m1" | "win-m2";
}

const SLOTS: Slot[] = ["mate-1", "mate-2"];
const REF_KEY = "rlpi-ref";

export function storedRef(): string | null {
  try {
    return localStorage.getItem(REF_KEY);
  } catch {
    return null;
  }
}
export function storeRef(r: string): void {
  try {
    localStorage.setItem(REF_KEY, r);
  } catch {
    /* navigation privée : sans conséquence */
  }
}

export function peersOf(c: Contenu): PeerView[] {
  return (c.peers ?? []).map((p, i) => {
    const slot = SLOTS[i] ?? "mate-2";
    return { ...p, slot, color: `var(--${slot})`, win: i === 0 ? "win-m1" : "win-m2" };
  });
}

export function pickRef(c: Contenu, wanted: string | null | undefined): string {
  if (wanted && c.refs[wanted]) return wanted;
  if (c.refs[c.default_ref]) return c.default_ref;
  return Object.keys(c.refs)[0];
}

/** Toutes les vues dérivées d'un contenu et d'une référence (fonction pure : testée sans navigateur). */
export function derive(C: Contenu, wantedRef: string | null | undefined) {
  const ref = pickRef(C, wantedRef);
  const R: Reference = C.refs[ref];
  const PF = C.perf,
    V = C.value;
  const PEERS = peersOf(C);
  const metrics: Metric[] = R?.metrics ?? [];
  return {
    C,
    PF,
    V,
    PS: C.passes,
    HEAT: C.heat,
    PEERS,
    ref,
    refs: (["ssl", "rlcs"] as const).filter((k) => C.refs[k]),
    D: R,
    refLabel: R?.label ?? "",
    M: Object.fromEntries(metrics.map((m) => [m.key, m])) as Record<string, Metric>,
    PFM: Object.fromEntries((PF?.matches ?? []).map((m) => [m.replay, m])),
    REC: Object.fromEntries((C.record ?? []).map((r) => [r.d, r])),
    peerByName: (n: string) => PEERS.find((p) => p.name === n),
    replayOfDate: (d: string) => PF?.matches.find((m) => m.date === d)?.replay,
    /** Phrase de période : « du 02.11 au 14.11.26 » */
    period: C.first === C.last ? dC(C.first) : `du ${dS(C.first)} au ${dC(C.last)}`,
  };
}
export type Derived = ReturnType<typeof derive>;

/** Contenu affiché et ses vues dérivées, recalculés quand le contenu ou la référence changent. */
export function useData() {
  const route = useRoute();
  return computed<Derived | null>(() => {
    const C = store.tableau?.contenu;
    if (!C) return null;
    const q = route.query.ref;
    return derive(C, (typeof q === "string" ? q : null) ?? storedRef());
  });
}
