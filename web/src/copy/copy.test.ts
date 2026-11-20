// Phrases de lecture et vues dérivées, sur le contenu réel du jeu d'essai (tests/snapshots/tableau_de_bord.json,
// pseudos et identifiants fictifs) : les phrases changent bien avec les données, d'un joueur à l'autre.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { Contenu } from "@/api/client";
import { derive, pickRef } from "@/lib/data";
import { MINUS, NB } from "@/lib/format";
import { act1, matchSentence, ph, synVerdict, verdict, verdictG } from ".";
import { caveats, definitions, glossary } from "./glossary";

const SNAP = JSON.parse(readFileSync(resolve(process.cwd(), "../tests/snapshots/tableau_de_bord.json"), "utf-8"));
const profiles = (k: string): Contenu[] => Object.values(SNAP[k].profiles) as Contenu[];
const base: Contenu = SNAP.defaut.profiles[SNAP.defaut.default];
const peerView: Contenu = profiles("coequipier").find((c) => c.player !== base.player) ?? base;

describe("verdicts", () => {
  it("seuils de l'indice", () => {
    expect([75, 60, 50, 35, 10].map(verdict)).toEqual(["Très bon match", "Bien joué", "Match correct", "Match en dessous", "Mauvais match"]);
    expect(verdictG(50)).toBe("Au niveau d'une performance SSL médiane");
    expect(verdictG(null)).toBe("En dessous d'une performance SSL médiane");
  });
  it("formulations par indicateur", () => {
    expect(ph("moitie_adverse", 0)).toBe("tu presses haut");
    expect(ph("inconnu", 1, "Mon Libellé")).toBe("mon libellé");
    expect(act1("Frappes fortes")).toBe("Frappe forte");
  });
  it("synergie : mieux ou moins bien seulement si toute la bande est du même côté", () => {
    expect(synVerdict({ sens: 1, lo: 12, hi: 15, ssl: 10 })[0]).toBe("mieux que les SSL");
    expect(synVerdict({ sens: 1, lo: 8, hi: 15, ssl: 10 })[0]).toBe("comme les SSL");
    expect(synVerdict({ sens: -1, lo: 12, hi: 15, ssl: 10 })[0]).toBe("moins bien que les SSL");
    expect(synVerdict({ sens: 0, lo: 0, hi: 1, ssl: 5 })[0]).toBe("style");
  });
});

describe("phrase de lecture d'un match", () => {
  const PF = base.perf!;
  it("verdict, rang et composante la plus lourde", () => {
    const m = PF.matches[PF.matches.length - 1];
    const s = matchSentence(PF, m);
    const top = [...PF.components].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0))[0];
    expect(s.startsWith(`${verdict(m.index)} : `)).toBe(true);
    expect(s).toContain(` sur ${m.n_players}.`);
    expect(s).toContain(`${Math.round((top.weight ?? 0) * 100)}${NB}% de la note`);
    expect(matchSentence(PF, m, false).startsWith(verdict(m.index))).toBe(false);
  });
  it("change d'un match à l'autre", () => {
    const all = new Set(PF.matches.map((m) => matchSentence(PF, m)));
    expect(all.size).toBeGreaterThan(PF.matches.length / 2);
  });
});

describe("vues dérivées", () => {
  it("référence choisie, sinon celle par défaut", () => {
    expect(pickRef(base, "rlcs")).toBe(base.refs.rlcs ? "rlcs" : base.default_ref);
    expect(pickRef(base, "inconnue")).toBe(base.default_ref);
    const d = derive(base, "rlcs");
    expect(d.refLabel).toBe(base.refs[d.ref].label);
    expect(Object.keys(d.M).length).toBe(base.refs[d.ref].metrics.length);
  });
  it("coéquipiers : rond puis carré, jamais la couleur du joueur", () => {
    const d = derive(base, null);
    expect(d.PEERS.map((p) => p.slot)).toEqual(["mate-1", "mate-2"].slice(0, d.PEERS.length));
    expect(d.PEERS.every((p) => p.color.startsWith("var(--mate-"))).toBe(true);
  });
  it("période en dates courtes", () => {
    expect(derive(base, null).period).toMatch(/^(du \d\d\.\d\d au )?\d\d\.\d\d\.\d\d$/);
  });
  it("les phrases dépendent du joueur affiché", () => {
    const a = derive(base, null),
      b = derive(peerView, null);
    if (base.player === peerView.player) return;
    expect(caveats(a)[0]).not.toBe(caveats(b)[0]);
  });
});

describe("panneau Méthode", () => {
  const d = derive(base, null);
  it("toutes les rubriques, avec leurs nombres", () => {
    const g = glossary(d);
    expect(g.map((r) => r.id)).toEqual(["indice", "valeur", "gain", "revoir", "resultat", "placement", "choix", "centile", "styles", "conseils", "progression", "synergie", "passes", "style", "terrain"]);
    const all = JSON.stringify(g);
    expect(all).not.toMatch(/undefined|NaN|<b>/);
  });
  it("définitions de chaque indicateur", () => {
    const def = definitions(d);
    expect(def.items.length).toBe((d.D?.metrics.length ?? 0) + (base.tech?.rows.length ?? 0));
    expect(def.source).toContain("subtr-actor");
  });
  it("pas de valeur absente dans « À lire avant d'interpréter »", () => {
    expect(caveats(d).join(" ")).not.toMatch(/undefined|NaN/);
    expect(caveats(d).join(" ")).not.toContain(`${MINUS}${MINUS}`);
  });
});
