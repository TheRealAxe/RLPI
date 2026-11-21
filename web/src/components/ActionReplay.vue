<script setup lang="ts">
// Fenêtre « Revoir » : une touche rejouée en 3D (4 s avant, 2 s après, 30 images/s) dans le player 3D de la vue
// embarquée (pov/PovPlayer.vue) : ta caméra (réglages et caméra balle relevés dans le replay), caméra balle,
// caméra voiture, vue libre. Fenêtre modale native (<dialog>) : focus gardé dedans, fermée par Échap, un clic à
// côté ou le bouton ; le focus revient au bouton qui l'a ouverte. Pas de lecture automatique : le player attend
// « ▶ Lire » (rien ne bouge sans action, prefers-reduced-motion compris).
import { computed, ref, shallowRef, watch } from "vue";
import { REVOIR, replayTitle } from "@/copy";
import { loadClip } from "@/lib/clips";
import { dS } from "@/lib/format";
import { closeReplay, refocusOpener, replay } from "@/lib/replay";
import PovPlayer from "@/pov/PovPlayer.vue";
import type { PovClip } from "@/pov/scene";

const dlg = ref<HTMLDialogElement | null>(null);
const clip = shallowRef<PovClip | null>(null);
const error = ref<string | null>(null);
const title = computed(() => (replay.req ? replayTitle(replay.req) : ""));
let loading = 0;

async function load() {
  const r = replay.req;
  if (!r) return;
  const seq = ++loading;
  clip.value = null;
  error.value = null;
  try {
    const c = await loadClip(r.match, r.i);
    if (seq !== loading || !replay.open) return;
    clip.value = c;
  } catch (e) {
    if (seq === loading) error.value = e instanceof Error ? e.message : String(e);
  }
}

watch(
  () => [replay.open, replay.seq] as const,
  ([open]) => {
    const d = dlg.value;
    if (!open) {
      loading++;
      clip.value = null; // démonte le player (libère WebGL)
      if (d?.open) d.close();
      refocusOpener();
      return;
    }
    if (d && !d.open) d.showModal();
    void load();
  },
);

/** Clic sur le fond (hors du contenu) : ferme. */
function onClick(e: MouseEvent) {
  if (e.target === dlg.value) closeReplay();
}
</script>

<template>
  <dialog ref="dlg" class="replay" aria-labelledby="replay-title" @close="closeReplay" @click="onClick">
    <div class="rbox">
      <div class="rh">
        <h2 id="replay-title" class="pl-dx">{{ title }}</h2>
        <span v-if="replay.req?.date" class="pl-tag pl-muted">{{ dS(replay.req.date) }}</span>
        <button type="button" class="close pl-tag" @click="closeReplay">{{ REVOIR.close }}</button>
      </div>
      <div class="rpov">
        <PovPlayer v-if="clip" :key="`${replay.req?.match}:${replay.req?.i}`" :clip="clip" />
        <div v-else-if="error" class="state pl-small" role="alert">
          <p>{{ error }}</p>
          <button type="button" class="btn-plain" @click="load">{{ REVOIR.retry }}</button>
        </div>
        <div v-else class="state pl-small" role="status">
          <p class="busy">{{ REVOIR.loading }}</p>
          <p class="note-dark">{{ REVOIR.loadingNote }}</p>
        </div>
      </div>
      <p class="note pl-small pl-muted">{{ clip && !clip.cam ? `${REVOIR.note} ${REVOIR.camDefault}` : REVOIR.note }}</p>
    </div>
  </dialog>
</template>
