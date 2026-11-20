<script setup lang="ts">
// Fenêtre « Revoir » : une touche rejouée en 3D (4 s avant, 2 s après, 30 images/s), par le lecteur du Swipe
// (swipe/player.ts). Fenêtre modale native (<dialog>) : focus gardé dedans, fermée par Échap, un clic à côté ou
// le bouton ; le focus revient au bouton qui l'a ouverte. Pas de lecture automatique si l'utilisateur demande
// moins d'animations (prefers-reduced-motion) : le clip s'ouvre alors arrêté sur la touche.
// « Vue joueur » : la caméra du jeu derrière l'auteur de la touche (caméra balle ou voiture, ses réglages relevés
// dans le replay) ; le choix est gardé d'un clip à l'autre.
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import { REVOIR, replayTitle } from "@/copy";
import { loadClip } from "@/lib/clips";
import { MINUS, dS } from "@/lib/format";
import { closeReplay, refocusOpener, replay } from "@/lib/replay";
import { createPlayer, type Player, type SwipeCard } from "@/swipe/player";

const dlg = ref<HTMLDialogElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const hud = ref<HTMLElement | null>(null);
const time = ref<HTMLElement | null>(null);
const range = ref<HTMLInputElement | null>(null);
const card = shallowRef<SwipeCard | null>(null);
const error = ref<string | null>(null);
const playing = ref(false);
const speed = ref(1);
const topView = ref(false);
const povView = ref(false);
const N = computed(() => card.value?.ball.length ?? 1);
const title = computed(() => (replay.req ? replayTitle(replay.req) : ""));
let P: Player | null = null,
  raf = 0,
  ro: ResizeObserver | null = null,
  loading = 0;

const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

function stop() {
  cancelAnimationFrame(raf);
  ro?.disconnect();
  ro = null;
  P = null;
}

function setPlay(p: boolean) {
  playing.value = p;
  if (P) P.playing = p;
}
function togglePlay() {
  if (!P) return;
  if (!P.playing && P.t >= P.stopAt - 0.01) P.t = 0;
  setPlay(!P.playing);
}
function restart() {
  if (!P) return;
  P.t = 0;
  setPlay(true);
}
function setSpeed(s: number) {
  speed.value = s;
  if (P) P.speed = s;
}
function toggleTop() {
  topView.value = !topView.value;
  P?.top(topView.value);
}
function togglePov() {
  povView.value = !povView.value;
  P?.pov(povView.value);
}
function seek() {
  if (!P || !range.value) return;
  P.t = Math.min(+range.value.value, P.stopAt);
  setPlay(false);
}

function start(c: SwipeCard) {
  if (!canvas.value) return;
  const p = (P = createPlayer(canvas.value, c));
  p.resize();
  p.speed = speed.value;
  p.top(topView.value);
  p.pov(povView.value);
  const still = reducedMotion();
  if (still) p.t = c.action_frame; // arrêté sur la touche
  setPlay(!still);
  ro = new ResizeObserver(() => p.resize());
  ro.observe(canvas.value);
  const loop = (now: number) => {
    if (P !== p) return;
    if (p.last == null) p.last = now;
    const d = Math.max(0, (now - p.last) / 1000);
    p.last = now;
    if (p.playing) {
      p.t += d * c.fps * p.speed;
      if (p.t >= p.stopAt) {
        p.t = p.stopAt;
        setPlay(false);
      }
    }
    if (range.value) range.value.value = String(p.t);
    const s = p.draw(),
      me = s.cars.find((x) => x.judged)!,
      sp = Math.hypot(...me.vel) * 0.036;
    const view = s.ballCam == null ? "" : ` · ${s.ballCam ? REVOIR.ballCam : REVOIR.carCam}`;
    if (hud.value)
      hud.value.textContent = `${REVOIR.author} · ${Math.round(sp)} km/h${sp >= 79 ? " (supersonique)" : ""} · boost ${Math.round(me.boost)} · hauteur ${(me.pos[2] / 100).toFixed(1).replace(".", ",")} m${view}`;
    const sec = (p.t - c.action_frame) / c.fps;
    if (time.value) time.value.textContent = Math.abs(sec) < 0.05 ? "touche" : `${sec > 0 ? "+" : MINUS}${Math.abs(sec).toFixed(1).replace(".", ",")} s`;
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
}

async function load() {
  const r = replay.req;
  if (!r) return;
  const seq = ++loading;
  stop();
  card.value = null;
  error.value = null;
  if (hud.value) hud.value.textContent = "";
  if (time.value) time.value.textContent = "";
  try {
    const c = await loadClip(r.match, r.i);
    if (seq !== loading || !replay.open) return;
    card.value = c;
    await nextTick();
    start(c);
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
      stop();
      card.value = null;
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
onBeforeUnmount(stop);
</script>

<template>
  <dialog ref="dlg" class="replay" aria-labelledby="replay-title" @close="closeReplay" @click="onClick">
    <div class="rbox">
      <div class="rh">
        <h2 id="replay-title" class="pl-dx">{{ title }}</h2>
        <span v-if="replay.req?.date" class="pl-tag pl-muted">{{ dS(replay.req.date) }}</span>
        <button type="button" class="close pl-tag" @click="closeReplay">{{ REVOIR.close }}</button>
      </div>
      <div class="stage">
        <canvas ref="canvas" role="img" :aria-label="`Reconstitution 3D : ${title}`"></canvas>
        <div v-show="card" ref="hud" class="hud pl-small"></div>
        <div v-if="!card && !error" class="state pl-small" role="status">
          <p class="busy">{{ REVOIR.loading }}</p>
          <p class="pl-muted">{{ REVOIR.loadingNote }}</p>
        </div>
        <div v-else-if="error" class="state pl-small" role="alert">
          <p>{{ error }}</p>
          <button type="button" class="btn-plain" @click="load">{{ REVOIR.retry }}</button>
        </div>
      </div>
      <div class="controls pl-small">
        <button type="button" :disabled="!card" :aria-label="playing ? 'Pause' : 'Lecture'" @click="togglePlay">{{ playing ? "❚❚" : "▶" }}</button>
        <button type="button" :disabled="!card" @click="restart">↺ Recommencer</button>
        <div class="tl">
          <input ref="range" type="range" name="temps" min="0" :max="N - 1" step="0.001" value="0" aria-label="Temps" :disabled="!card" @input="seek" />
          <div v-if="card" class="mark" :style="{ left: `calc(${(card.action_frame / (N - 1)) * 100}% - 1px)` }" title="Moment de la touche"></div>
        </div>
        <span ref="time" class="time"></span>
        <span class="sep"></span>
        <button v-for="s in [1, 0.5, 0.25]" :key="s" type="button" :aria-pressed="speed === s" :aria-label="`Vitesse ×${String(s).replace('.', ',')}`" @click="setSpeed(s)">×{{ String(s).replace(".", ",") }}</button>
        <span class="sep"></span>
        <button type="button" :aria-pressed="povView" :title="REVOIR.povTitle" @click="togglePov">{{ REVOIR.pov }}</button>
        <button type="button" title="Tourner la vue" aria-label="Tourner la vue à gauche" :disabled="!card || povView" @click="P?.rotate(-1)">⟲</button>
        <button type="button" title="Tourner la vue" aria-label="Tourner la vue à droite" :disabled="!card || povView" @click="P?.rotate(1)">⟳</button>
        <button type="button" :aria-pressed="topView" :disabled="povView" @click="toggleTop">Dessus</button>
      </div>
      <p class="note pl-small pl-muted">{{ REVOIR.note }}<template v-if="povView"> {{ card?.cam?.known ? REVOIR.povNote : REVOIR.povDefault }}</template></p>
    </div>
  </dialog>
</template>
