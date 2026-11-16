<script setup lang="ts">
// Juger des actions à l'aveugle (swipe) : un paquet de cartes (tes actions, celles de tes coéquipiers, de tes
// lobbies, de joueurs SSL et de pros RLCS, sans dire lesquelles), fabriqué par un worker. Chaque jugement est
// enregistré en base (le dernier compte) : plus de fichier à exporter.
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import SwipeCard, { type Verdict } from "@/swipe/SwipeCard.vue";
import type { SwipeCard as Card } from "@/swipe/player";
import { ApiError, getJson, postJson } from "@/api/client";

interface Deck {
  id: number | null;
  statut: "aucun" | "en_attente" | "pret" | "erreur";
  erreur?: string | null;
  n_cartes?: number;
  cartes?: Card[];
  jugements?: Record<string, string>;
}

const deck = ref<Deck | null>(null);
const judged = ref<Record<string, string>>({});
const history = ref<string[]>([]);
const error = ref<string | null>(null);
const busy = ref(false);
const cur = ref<InstanceType<typeof SwipeCard> | null>(null);
let poll: ReturnType<typeof setTimeout> | undefined;

const cards = computed(() => deck.value?.cartes ?? []);
const rest = computed(() => cards.value.filter((c) => !judged.value[c.id]));
const done = computed(() => cards.value.length - rest.value.length);
const counts = computed(() => {
  const v = Object.values(judged.value);
  return { bien: v.filter((x) => x === "bien").length, pas_bien: v.filter((x) => x === "pas_bien").length, nsp: v.filter((x) => x === "?").length };
});

async function load() {
  clearTimeout(poll);
  try {
    const d = await getJson<Deck>("/api/swipe/deck");
    deck.value = d;
    judged.value = { ...(d.jugements ?? {}) };
    if (d.statut === "en_attente") poll = setTimeout(load, 3000); // le worker prépare le paquet (une minute environ)
  } catch {
    error.value = "Le paquet n'a pas pu être chargé. Réessaie dans un instant.";
  }
}
async function requestDeck() {
  busy.value = true;
  error.value = null;
  try {
    await postJson("/api/swipe/deck");
    history.value = [];
    await load();
  } catch {
    error.value = "Le paquet n'a pas pu être demandé. Réessaie dans un instant.";
  } finally {
    busy.value = false;
  }
}
async function vote(v: Verdict) {
  const card = rest.value[0];
  if (!card || !deck.value?.id || busy.value) return;
  busy.value = true;
  try {
    const flying = cur.value?.fly(v);
    try {
      await postJson("/api/swipe/jugements", { paquet: deck.value.id, carte: card.id, verdict: v });
    } finally {
      await flying;
    }
    judged.value = { ...judged.value, [card.id]: v };
    history.value.push(card.id);
    error.value = null;
  } catch (e) {
    cur.value?.reset();
    error.value = e instanceof ApiError && e.status === 404 ? "Carte inconnue : recharge la page." : "Le jugement n'a pas pu être enregistré. Réessaie.";
  } finally {
    busy.value = false;
  }
}
/** Revoir la carte précédente : elle revient en tête ; le nouveau jugement remplacera l'ancien. */
async function undo() {
  const id = history.value.pop();
  if (!id) return;
  const j = { ...judged.value };
  delete j[id];
  judged.value = j;
  await nextTick();
}

function onKey(e: KeyboardEvent) {
  if ((e.target as HTMLElement).tagName === "INPUT") return;
  if (e.key === "ArrowRight") vote("bien");
  else if (e.key === "ArrowLeft") vote("pas_bien");
  else if (e.key === "ArrowUp") {
    e.preventDefault();
    vote("?");
  } else if (e.code === "Space" && rest.value.length) {
    e.preventDefault();
    cur.value?.togglePlay();
  } else if (e.key === "r" || e.key === "R") cur.value?.replay();
  else if ((e.ctrlKey || e.metaKey) && e.key === "z") undo();
}
onMounted(() => {
  document.title = "Juger des actions · RLPI";
  addEventListener("keydown", onKey);
  void load();
});
onBeforeUnmount(() => {
  removeEventListener("keydown", onKey);
  clearTimeout(poll);
});
</script>

<template>
  <div class="swipe">
    <header class="sw-head">
      <div class="pl-header">
        <div class="pl-cut pl-tag pl-volt">RLPI</div>
        <div class="pl-cut pl-panel"><h1 class="pl-tag">Juge l'action</h1></div>
      </div>
      <div v-if="cards.length" class="prog pl-small">
        <div class="bar"><i :style="{ width: (done / cards.length) * 100 + '%' }"></i></div>
        <span>{{ done }} / {{ cards.length }} jugées</span>
      </div>
      <div class="grow"></div>
      <button type="button" class="btn-plain" :disabled="!history.length" title="Ctrl + Z" @click="undo">↶ Revoir la précédente</button>
      <RouterLink class="pl-tag pl-muted" :to="{ name: 'ma-forme' }">◂ Tableau de bord</RouterLink>
    </header>

    <p v-if="error" class="pl-small pl-bad sw-msg" role="alert">{{ error }}</p>

    <div v-if="!deck" class="sw-msg"><p class="busy pl-small" role="status">Chargement…</p></div>
    <div v-else-if="deck.statut === 'aucun' || deck.statut === 'erreur' || (deck.statut === 'pret' && !rest.length)" class="sw-msg">
      <div class="pl-panel pl-cutr carton" style="max-width: 640px">
        <template v-if="deck.statut === 'pret'">
          <h2 class="pl-dx pl-title">Paquet terminé</h2>
          <p class="pl-body">{{ counts.bien }} bien · {{ counts.pas_bien }} pas bien · {{ counts.nsp }} je ne sais pas</p>
          <p class="pl-small pl-muted">Tes jugements sont enregistrés. Ils serviront à vérifier où les modèles se trompent.</p>
        </template>
        <template v-else-if="deck.statut === 'erreur'">
          <h2 class="pl-dx pl-title">Paquet impossible à préparer</h2>
          <p class="pl-small">{{ deck.erreur || "Le worker n'a pas pu préparer ce paquet." }}</p>
        </template>
        <template v-else>
          <h2 class="pl-dx pl-title">Juger des actions à l'aveugle</h2>
          <p class="pl-body">
            Des actions de tes parties, de tes coéquipiers, de tes lobbies, de joueurs SSL et de pros RLCS, mélangées, sans dire de qui elles viennent. Pour chacune : bonne action ou pas ?
          </p>
        </template>
        <p style="margin-top: var(--space-4)"><button type="button" class="btn pl-cut pl-volt" :disabled="busy" @click="requestDeck">{{ deck.statut === "aucun" ? "Préparer un paquet" : "Nouveau paquet" }}</button></p>
      </div>
    </div>
    <div v-else-if="deck.statut === 'en_attente'" class="sw-msg">
      <p class="busy pl-body" role="status">Paquet en préparation (une minute environ) : la page se met à jour toute seule.</p>
    </div>

    <template v-else>
      <main class="sw-main">
        <button type="button" class="vote maybe" title="Flèche du haut" :disabled="busy" @click="vote('?')"><span>?</span>Je ne sais pas <kbd>↑</kbd></button>
        <button type="button" class="vote bad" title="Flèche gauche" :disabled="busy" @click="vote('pas_bien')"><span>✕</span>Pas bien<kbd>←</kbd></button>
        <div class="deck">
          <SwipeCard v-if="rest[1]" :key="'b' + rest[1].id" :card="rest[1]" behind />
          <SwipeCard ref="cur" :key="rest[0].id" :card="rest[0]" @vote="vote" />
        </div>
        <button type="button" class="vote good" title="Flèche droite" :disabled="busy" @click="vote('bien')"><span>✓</span>Bien<kbd>→</kbd></button>
      </main>
      <div class="legend pl-small pl-muted sw-legend">
        <span><i class="sw" style="background: var(--scene-team)"></i>équipe du joueur jugé</span><span><i class="sw" style="background: var(--scene-opp)"></i>adversaires</span>
        <span><i class="sw" style="background: var(--scene-judged)"></i>joueur jugé</span><span>face blanche = avant de la voiture</span>
        <span>ombre au sol + trait = hauteur</span><span>barre orange = boost</span><span>trait jaune sur la barre de temps = l'action</span>
      </div>
    </template>
  </div>
</template>
