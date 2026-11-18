<script setup lang="ts">
// Une carte à juger : clip qui s'arrête 1 s après l'action, lecture / ralenti / rotation / vue de dessus, carte à
// glisser (droite : bien, gauche : pas bien, haut : je ne sais pas). Le parent enregistre le jugement.
import { onBeforeUnmount, onMounted, ref } from "vue";
import { createPlayer, type Player, type SwipeCard } from "./player";
import { MINUS } from "@/lib/format";

export type Verdict = "bien" | "pas_bien" | "?";
const props = defineProps<{ card: SwipeCard; behind?: boolean }>();
const emit = defineEmits<{ vote: [v: Verdict] }>();
const ACT: Record<string, string> = { shot: "un tir", save: "un arrêt", clear: "un dégagement", pass: "une passe", boom: "une frappe forte" };

const canvas = ref<HTMLCanvasElement | null>(null);
const hud = ref<HTMLElement | null>(null);
const time = ref<HTMLElement | null>(null);
const range = ref<HTMLInputElement | null>(null);
const playing = ref(true);
const speed = ref(1);
const topView = ref(false);
const stamp = ref({ good: 0, bad: 0, maybe: 0 });
const N = props.card.ball.length;
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
  if (props.behind || !canvas.value) return;
  const p = (P = createPlayer(canvas.value, props.card));
  p.resize();
  ro = new ResizeObserver(() => p.resize());
  ro.observe(canvas.value);
  const card = props.card;
  const loop = (now: number) => {
    if (p.last == null) p.last = now;
    const d = Math.max(0, (now - p.last) / 1000);
    p.last = now;
    if (p.playing) {
      p.t += d * card.fps * p.speed;
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
      hud.value.textContent = `Joueur jugé · ${Math.round(sp)} km/h${sp >= 79 ? " (supersonique)" : ""} · boost ${Math.round(me.boost)} · hauteur ${(me.pos[2] / 100).toFixed(1).replace(".", ",")} m`;
    const sec = (p.t - card.action_frame) / card.fps;
    if (time.value) time.value.textContent = Math.abs(sec) < 0.05 ? "action" : `${sec > 0 ? "+" : MINUS}${Math.abs(sec).toFixed(1).replace(".", ",")} s`;
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
});
onBeforeUnmount(() => {
  cancelAnimationFrame(raf);
  ro?.disconnect();
});

// ------------------------------------------------ glisser la carte
let drag: { x: number; y: number } | null = null;
const tf = ref(""),
  tr = ref("");
function down(e: PointerEvent) {
  drag = { x: e.clientX, y: e.clientY };
  (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  tr.value = "none";
}
function move(e: PointerEvent) {
  if (!drag) return;
  const dx = e.clientX - drag.x,
    dy = e.clientY - drag.y;
  tf.value = `translate(${dx}px, ${Math.min(dy, 40)}px) rotate(${dx / 25}deg)`;
  stamp.value = {
    good: Math.max(0, Math.min(1, dx / 120)),
    bad: Math.max(0, Math.min(1, -dx / 120)),
    maybe: Math.max(0, Math.min(1, -dy / 120) - Math.abs(dx) / 200),
  };
}
function up(e: PointerEvent) {
  if (!drag) return;
  const dx = e.clientX - drag.x,
    dy = e.clientY - drag.y;
  drag = null;
  if (dx > 130) return emit("vote", "bien");
  if (dx < -130) return emit("vote", "pas_bien");
  if (dy < -120 && Math.abs(dx) < 120) return emit("vote", "?");
  tr.value = "transform .25s";
  tf.value = "";
  stamp.value = { good: 0, bad: 0, maybe: 0 };
}
/** Animation de sortie de la carte jugée. */
function fly(v: Verdict): Promise<void> {
  const dir = v === "bien" ? [1, 0] : v === "pas_bien" ? [-1, 0] : [0, -1];
  stamp.value = { good: v === "bien" ? 1 : 0, bad: v === "pas_bien" ? 1 : 0, maybe: v === "?" ? 1 : 0 };
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  tr.value = reduce ? "none" : "transform .35s ease-in, opacity .35s";
  tf.value = `translate(${dir[0] * 140}vw, ${dir[1] * 120}vh) rotate(${dir[0] * 25}deg)`;
  return new Promise((r) => setTimeout(r, reduce ? 0 : 300));
}
/** Carte remise en place (jugement non enregistré). */
function reset() {
  tr.value = "transform .25s";
  tf.value = "";
  stamp.value = { good: 0, bad: 0, maybe: 0 };
}
defineExpose({ fly, reset, togglePlay, replay });
</script>

<template>
  <div class="card" :class="{ behind }" :inert="behind || undefined" :aria-hidden="behind || undefined" :style="{ transform: tf || undefined, transition: tr || undefined, opacity: tf.includes('vw') || tf.includes('vh') ? 0.2 : undefined }">
    <div class="stage" @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up">
      <canvas ref="canvas"></canvas>
      <div ref="hud" class="hud pl-small"></div>
      <div class="ask pl-small">
        Le joueur en jaune joue {{ ACT[card.action ?? ""] || "la balle" }}.<br /><b>Bonne action ?</b>
        <small>Le clip s'arrête 1 s après : juge la décision, pas le résultat.</small>
      </div>
      <div class="stamp good pl-dx" :style="{ opacity: stamp.good }">Bien</div>
      <div class="stamp bad pl-dx" :style="{ opacity: stamp.bad }">Pas bien</div>
      <div class="stamp maybe pl-dx" :style="{ opacity: stamp.maybe }">?</div>
    </div>
    <div class="controls pl-small">
      <button type="button" :aria-label="playing ? 'Pause' : 'Lecture'" @click="togglePlay">{{ playing ? "❚❚" : "▶" }}</button>
      <button type="button" title="R" @click="replay">↺ Revoir</button>
      <div class="tl">
        <input ref="range" type="range" name="temps" min="0" :max="N - 1" step="0.001" aria-label="Temps" @input="seek" />
        <div class="mark" :style="{ left: `calc(${(card.action_frame / (N - 1)) * 100}% - 1px)` }"></div>
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
