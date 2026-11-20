<script setup lang="ts">
// Fenêtre « Revoir » d'une touche coûteuse : demande le ralenti (fabriqué par un worker à partir du replay, environ
// 30 s la première fois), attend qu'il soit prêt, puis le lit dans le player 3D (vue embarquée). Échap ou ✕ pour fermer.
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { api, ApiError, type Ralenti, type Touch } from "@/api/client";
import { act1 } from "@/copy";
import { clock, dS, sgn } from "@/lib/format";
import PovPlayer from "@/pov/PovPlayer.vue";
import type { PovClip } from "@/pov/scene";

const props = defineProps<{ t: Touch }>();
const emit = defineEmits<{ close: [] }>();
const state = ref<"chargement" | "attente" | "pret" | "erreur">("chargement");
const err = ref("");
const clip = ref<PovClip | null>(null);
const box = ref<HTMLElement | null>(null);
const POLL_MS = 2000,
  MAX_WAIT_MS = 3 * 60 * 1000;
let timer = 0,
  started = 0,
  alive = true;

function show(r: Ralenti): boolean {
  if (r.statut === "pret" && r.clip) {
    clip.value = r.clip as unknown as PovClip;
    state.value = "pret";
    return true;
  }
  if (r.statut === "erreur") {
    state.value = "erreur";
    err.value = r.erreur || "Le ralenti n'a pas pu être fabriqué.";
    return true;
  }
  return false;
}
async function poll() {
  if (!alive) return;
  try {
    const r = await api.ralenti(props.t.match!, props.t.i!);
    if (show(r)) return;
    if (Date.now() - started > MAX_WAIT_MS) {
      state.value = "erreur";
      err.value = "Le ralenti met trop de temps à venir. Réessaie dans quelques minutes.";
      return;
    }
    timer = window.setTimeout(poll, POLL_MS);
  } catch (e) {
    state.value = "erreur";
    err.value = e instanceof ApiError ? e.message : "Serveur injoignable.";
  }
}
async function load() {
  state.value = "chargement";
  started = Date.now();
  try {
    const r = await api.ralenti(props.t.match!, props.t.i!);
    if (r.statut === "pret" && show(r)) return;
    await api.demanderRalenti(props.t.match!, props.t.i!);
    state.value = "attente";
    timer = window.setTimeout(poll, POLL_MS);
  } catch (e) {
    state.value = "erreur";
    err.value = e instanceof ApiError ? e.message : "Serveur injoignable.";
  }
}
function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") emit("close");
}
onMounted(async () => {
  addEventListener("keydown", onKey);
  await nextTick();
  box.value?.focus();
  load();
});
onBeforeUnmount(() => {
  alive = false;
  clearTimeout(timer);
  removeEventListener("keydown", onKey);
});
</script>

<template>
  <div class="rl-back" @click.self="emit('close')">
    <section ref="box" class="rl-box pl-panel" role="dialog" aria-modal="true" aria-labelledby="rl-title" tabindex="-1">
      <header class="rl-head">
        <div>
          <h2 id="rl-title" class="pl-dx pl-title">{{ act1(t.action) }} · {{ clock(t.clock) }}</h2>
          <div class="pl-small pl-muted">Partie du {{ dS(t.date) }} · cette touche a coûté {{ sgn(t.dv) }} · toi en jaune</div>
        </div>
        <button type="button" class="pl-tag" aria-label="Fermer" @click="emit('close')">✕</button>
      </header>
      <PovPlayer v-if="state === 'pret' && clip" :clip="clip" />
      <div v-else class="rl-wait pl-body" role="status" aria-live="polite">
        <template v-if="state === 'erreur'">
          <p>{{ err }}</p>
          <button type="button" class="pl-tag" @click="load">Réessayer</button>
        </template>
        <p v-else-if="state === 'attente'">Préparation du ralenti à partir du replay… (environ 30 s la première fois)</p>
        <p v-else>Chargement…</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.rl-back { position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, .55); display: flex; align-items: center; justify-content: center; padding: 16px; }
.rl-box { width: min(1240px, 100%); max-height: 100%; overflow: auto; display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-5, 20px); outline: none; background: #0b0d11; color: #f3f3ee; }
.rl-box .pl-muted { color: #9aa1ab; }
.rl-box .pl-tag { color: #f3f3ee; }
.rl-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-4); }
.rl-wait { min-height: 240px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-4); text-align: center; }
</style>
