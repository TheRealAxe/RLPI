// loadClip : appel de l'API (joueur connecté, partie, indice), mémoire des clips et messages d'erreur en français.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Moi } from "@/api/client";
import { forgetClips, loadClip } from "./clips";
import { store } from "./store";

const CLIP = { id: "abc:120", fps: 30, action_frame: 90, ball: [[0, 0, 93]], ball_v: [[0, 0, 0]], cars: [] };

function respond(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

beforeEach(() => {
  forgetClips();
  store.moi = { id: "Steam:7656", nom: "Moi", parties: 3, en_preparation: 0, version: 1 } as Moi;
});
afterEach(() => {
  vi.unstubAllGlobals();
  store.moi = null;
});

describe("loadClip", () => {
  it("appelle la route du joueur connecté et rend la carte", async () => {
    const f = respond(200, CLIP);
    vi.stubGlobal("fetch", f);
    const c = await loadClip("partie/1", 120);
    expect(c.action_frame).toBe(90);
    expect(f).toHaveBeenCalledOnce();
    expect(String((f.mock.calls[0] as unknown[])[0])).toBe("/api/joueurs/Steam%3A7656/matchs/partie%2F1/clips/120");
  });

  it("garde le clip en mémoire : un second clic ne rappelle pas l'API", async () => {
    const f = respond(200, CLIP);
    vi.stubGlobal("fetch", f);
    await loadClip("abc", 120);
    await loadClip("abc", 120);
    await loadClip("abc", 121);
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("rend le message de l'API (replay non conservé, touche introuvable)", async () => {
    vi.stubGlobal("fetch", respond(404, { detail: "Replay non conservé pour cette partie." }));
    await expect(loadClip("abc", 1)).rejects.toThrow("Replay non conservé pour cette partie.");
    vi.stubGlobal("fetch", respond(422, { detail: "Impossible de retrouver cette touche dans le replay." }));
    await expect(loadClip("abc", 2)).rejects.toThrow("Impossible de retrouver cette touche dans le replay.");
  });

  it("un échec n'est pas gardé : le clic suivant réessaie", async () => {
    vi.stubGlobal("fetch", respond(500, {}));
    await expect(loadClip("abc", 3)).rejects.toThrow("Le clip n'a pas pu être préparé. Réessaie dans un instant.");
    const ok = respond(200, CLIP);
    vi.stubGlobal("fetch", ok);
    await expect(loadClip("abc", 3)).resolves.toMatchObject({ id: "abc:120" });
    expect(ok).toHaveBeenCalledOnce();
  });

  it("session expirée, serveur muet, pas de joueur connecté", async () => {
    vi.stubGlobal("fetch", respond(401, { detail: "Non connecté" }));
    await expect(loadClip("abc", 4)).rejects.toThrow("Ta session a expiré : reconnecte-toi.");
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(loadClip("abc", 5)).rejects.toThrow("Le serveur ne répond pas. Réessaie dans un instant.");
    store.moi = null;
    await expect(loadClip("abc", 6)).rejects.toThrow("Ta session a expiré : reconnecte-toi.");
  });
});
