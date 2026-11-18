import { describe, expect, it } from "vitest";
import { MINUS, NB, R, cap, clock, dC, dL, dS, fmt, joinFr, num, ord, pc, scoreTxt, sgn, sgnI } from "./format";

describe("nombres", () => {
  it("virgule décimale et vrai signe moins", () => {
    expect(num(52.64, 1)).toBe("52,6");
    expect(num(-0.92, 2)).toBe(`${MINUS}0,92`);
  });
  it("valeurs signées", () => {
    expect(sgn(0.354)).toBe("+0,35");
    expect(sgn(-0.92)).toBe(`${MINUS}0,92`);
    expect(sgn(0)).toBe("+0,00");
    expect(sgn(null)).toBe("—");
    expect(sgnI(7.6)).toBe("+8");
    expect(sgnI(-4.6)).toBe(`${MINUS}5`);
  });
  it("entiers et pourcentages", () => {
    expect(R(47.5)).toBe("48");
    expect(R(undefined)).toBe("—");
    expect(pc(0.526)).toBe(`53${NB}%`);
    expect(pc(null)).toBe("—");
  });
  it("unités des indicateurs", () => {
    expect(fmt(52.6, "% du temps")).toBe(`52,6${NB}%`);
    expect(fmt(53.46, "km/h")).toBe(`53,5${NB}km/h`);
    expect(fmt(7, "par / 5 min")).toBe(`7,0${NB}/ 5 min`);
    expect(fmt(61.4, "/100")).toBe("61");
    expect(fmt(3.62, "/6")).toBe(`3,6${NB}/ 6`);
    expect(fmt(0.123)).toBe("0,12");
    expect(fmt(1234)).toBe("1234");
    expect(fmt(0)).toBe("0,0");
    expect(fmt(null, "km/h")).toBe("—");
  });
});

describe("dates et textes", () => {
  const d = "2026-11-14-21-05-33";
  it("formats de date", () => {
    expect(dS(d)).toBe("14.11");
    expect(dC(d)).toBe("14.11.26");
    expect(dL(d)).toBe("14/11/2026");
  });
  it("horloge de jeu", () => {
    expect(clock(247)).toBe("4:07");
    expect(clock(0)).toBe("0:00");
    expect(clock(null)).toBe("—");
  });
  it("ordinaux, listes, score", () => {
    expect(ord(1)).toBe("1er");
    expect(ord(6)).toBe("6e");
    expect(joinFr([])).toBe("");
    expect(joinFr(["a"])).toBe("a");
    expect(joinFr(["a", "b", "c"])).toBe("a, b et c");
    expect(cap("tir")).toBe("Tir");
    expect(scoreTxt("3-2")).toBe("3–2");
  });
});
