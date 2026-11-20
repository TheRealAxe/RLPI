// Bouton « ▶ Revoir » : affiché seulement quand la touche peut se retrouver dans le replay ; un clic ouvre la
// fenêtre avec la bonne touche ; le titre de la fenêtre.
import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Moi } from "@/api/client";
import { replayTitle } from "@/copy";
import { MINUS } from "@/lib/format";
import { canReplay, closeReplay, replay } from "@/lib/replay";
import { store } from "@/lib/store";
import ReplayButton from "./ReplayButton.vue";

const T = { match: "abc", i: 1234, action: "Dégagements", clock: 151, vb: -0.3, va: -0.6, date: "2026-11-14-21-05" };

beforeEach(() => {
  store.moi = { id: "Steam:7656", nom: "Moi", parties: 3, en_preparation: 0, version: 1 } as Moi;
});
afterEach(() => {
  closeReplay();
  replay.req = null;
  store.moi = null;
});

describe("bouton Revoir", () => {
  it("affiché pour une touche complète", () => {
    const w = mount(ReplayButton, { props: T, attachTo: document.body });
    const b = w.get("button");
    expect(b.text()).toBe("▶ Revoir");
    expect(b.attributes("aria-label")).toBe("Revoir en 3D : dégagement à 2:31");
    w.unmount();
  });

  it("absent sans partie, sans indice d'image ou sans joueur connecté", () => {
    expect(mount(ReplayButton, { props: { ...T, match: null } }).find("button").exists()).toBe(false);
    expect(mount(ReplayButton, { props: { ...T, i: undefined } }).find("button").exists()).toBe(false);
    expect(mount(ReplayButton, { props: { ...T, i: -1 } }).find("button").exists()).toBe(false);
    store.moi = null;
    expect(mount(ReplayButton, { props: T }).find("button").exists()).toBe(false);
  });

  it("un clic ouvre la fenêtre sur cette touche, sans déclencher la ligne", async () => {
    let rowClicks = 0;
    const host = document.createElement("div");
    host.addEventListener("click", () => rowClicks++);
    document.body.appendChild(host);
    const w = mount(ReplayButton, { props: T, attachTo: host });
    await w.get("button").trigger("click");
    expect(replay.open).toBe(true);
    expect(replay.req).toMatchObject({ match: "abc", i: 1234, action: "Dégagements" });
    expect(replay.opener).toBe(w.get("button").element);
    expect(rowClicks).toBe(0);
    w.unmount();
    host.remove();
  });

  it("canReplay", () => {
    expect(canReplay("abc", 0)).toBe(true);
    expect(canReplay("", 3)).toBe(false);
    expect(canReplay("abc", 1.5)).toBe(false);
  });

  it("titre de la fenêtre", () => {
    expect(replayTitle(T)).toBe(`Dégagement · 2:31 · situation ${MINUS}0,30 → ${MINUS}0,60`);
    expect(replayTitle({ action: "Tirs", clock: null })).toBe("Tir");
  });
});
