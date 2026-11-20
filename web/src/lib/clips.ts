// Clips 3D d'une touche (« Revoir »). Seul endroit qui sait d'où vient le clip : aujourd'hui l'API, qui le découpe
// dans le replay gardé sur Garage ; demain, peut-être, le .replay lu dans le navigateur. Le lecteur
// (swipe/player.ts) ne voit qu'une carte au format SwipeCard.
import { api, ApiError } from "@/api/client";
import type { SwipeCard } from "@/swipe/player";
import { store } from "./store";

const KEEP = 40; // clips gardés en mémoire (environ 60 Ko chacun une fois lus)
const memo = new Map<string, Promise<SwipeCard>>();

/** Message lisible d'un échec : celui de l'API quand il explique (replay non conservé, touche introuvable…). */
function message(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return "Ta session a expiré : reconnecte-toi.";
    if ((e.status === 404 || e.status === 422) && !/^Erreur \d+$/.test(e.message)) return e.message;
    return "Le clip n'a pas pu être préparé. Réessaie dans un instant.";
  }
  return "Le serveur ne répond pas. Réessaie dans un instant.";
}

/** Clip de la touche `i` (indice d'image à 10 images/s) de la partie `partie`. Rejette avec un message en français. */
export function loadClip(partie: string, i: number): Promise<SwipeCard> {
  const me = store.moi?.id;
  if (!me) return Promise.reject(new Error("Ta session a expiré : reconnecte-toi."));
  const key = `${me}|${partie}|${i}`;
  const hit = memo.get(key);
  if (hit) {
    memo.delete(key); // remis en dernier : le plus récemment demandé
    memo.set(key, hit);
    return hit;
  }
  const p = api.clip(me, partie, i).then(
    (c): SwipeCard => c,
    (e: unknown) => {
      memo.delete(key); // un échec n'est pas gardé : le clic suivant réessaie
      throw new Error(message(e));
    },
  );
  memo.set(key, p);
  while (memo.size > KEEP) memo.delete(memo.keys().next().value!);
  return p;
}

/** Vide la mémoire des clips (tests, changement de joueur). */
export function forgetClips(): void {
  memo.clear();
}
