<script setup lang="ts">
// Lecteur d'un ralenti (même scène que le swipe, sans vote) : tout le clip se lit, la touche est marquée sur la
// barre de temps ; lecture / ralenti / rotation / vue de dessus.
import { onBeforeUnmount, onMounted, ref } from "vue";
import { createPlayer, type Player, type SwipeCard } from "./player";
import { MINUS } from "@/lib/format";

const props = defineProps<{ clip: SwipeCard }>();
const canvas = ref<HTMLCanvasElement | null>(null);
const hud = ref<HTMLElement | null>(null);
const time = ref<HTMLElement | null>(null);
const range = ref<HTMLInputElement | null>(null);
const playing = ref(true);
const speed = ref(0.5);
const topView = ref(false);
const N = props.clip.ball.length;
let P: Player | null = null,
  raf = 0,
  ro: ResizeObserver | null = null;

function setPlay(p: boolean) {
  playing.value = p;
  if (P) P.playing = p;
}
function togglePlay() {
  if (!P) return;
  if (!P.playing && P.t >= P.stopAt - 0.01) P.t = 0;
  setPlay(!P.playing);
}
function replay() {
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
function seek() {
  if (!P || !range.value) return;
  P.t = Math.min(+range.value.value, P.stopAt);
  setPlay(false);
}

onMounted(() => {
  if (!canvas.value) return;
  const p = (P = createPlayer(canvas.value, props.clip));
  p.stopAt = N - 1; // tout le ralenti, pas seulement 1 s après la touche comme au swipe
  p.speed = speed.value;
  p.resize();
  ro = new ResizeObserver(() => p.resize());
  ro.observe(canvas.value);
  const clip = props.clip;
  const loop = (now: number) => {
    if (p.last == null) p.last = now;
    const d = Math.max(0, (now - p.last) / 1000);
    p.last = now;
    if (p.playing) {
      p.t += d * clip.fps * p.speed;
      if (p.t >= p.stopAt) {
        p.t = p.stopAt;
        setPlay(false);
      }
      if (range.value) range.value.value = String(p.t);
    }
    const s = p.draw(),
      me = s.cars.find((c) => c.judged)!,
      sp = Math.hypot(...me.vel) * 0.036;
    if (hud.value)
      hud.value.textContent = `Toi · ${Math.round(sp)} km/h${sp >= 79 ? " (supersonique)" : ""} · boost ${Math.round(me.boost)} · hauteur ${(me.pos[2] / 100).toFixed(1).replace(".", ",")} m`;
    const sec = (p.t - clip.action_frame) / clip.fps;
    if (time.value) time.value.textContent = Math.abs(sec) < 0.05 ? "touche" : `${sec > 0 ? "+" : MINUS}${Math.abs(sec).toFixed(1).replace(".", ",")} s`;
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
});
onBeforeUnmount(() => {
  cancelAnimationFrame(raf);
  ro?.disconnect();
});
defineExpose({ togglePlay, replay });
</script>

<template>
  <div class="card clip">
    <div class="stage">
      <canvas ref="canvas" role="img" aria-label="Ralenti de la touche : terrain, balle et les 6 voitures"></canvas>
      <div ref="hud" class="hud pl-small"></div>
    </div>
    <div class="controls pl-small">
      <button type="button" :aria-label="playing ? 'Pause' : 'Lecture'" @click="togglePlay">{{ playing ? "❚❚" : "▶" }}</button>
      <button type="button" title="R" @click="replay">↺ Revoir</button>
      <div class="tl">
        <input ref="range" type="range" name="temps" min="0" :max="N - 1" step="0.001" aria-label="Temps" @input="seek" />
        <div class="mark" :style="{ left: `calc(${(clip.action_frame / (N - 1)) * 100}% - 1px)` }"></div>
      </div>
      <span ref="time" class="time"></span>
      <span class="sep"></span>
      <button v-for="s in [1, 0.5, 0.25]" :key="s" type="button" :aria-pressed="speed === s" @click="setSpeed(s)">×{{ String(s).replace(".", ",") }}</button>
      <span class="sep"></span>
      <button type="button" title="Tourner la vue" @click="P?.rotate(-1)">⟲</button>
      <button type="button" title="Tourner la vue" @click="P?.rotate(1)">⟳</button>
      <button type="button" :aria-pressed="topView" @click="toggleTop">Dessus</button>
    </div>
  </div>
</template>

<style scoped>
.clip { position: relative; inset: auto; height: min(68vh, 620px); touch-action: auto; user-select: auto; }
.clip .stage { cursor: default; }
</style>
