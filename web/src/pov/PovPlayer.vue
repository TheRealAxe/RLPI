<script setup lang="ts">
// Player 3D d'une touche, comme la vue embarquée : « ta caméra » (tes réglages et ta caméra balle, lus dans le replay),
// caméra balle, caméra voiture, vue libre ; lecture ×0,25 / ×0,5 / ×1, arrêt sur la touche au premier passage.
import { onBeforeUnmount, onMounted, ref } from "vue";
import { MINUS } from "@/lib/format";
import { createPov, type CamMode, type Hud, type Pov, type PovClip } from "./scene";

const props = defineProps<{ clip: PovClip }>();
const canvas = ref<HTMLCanvasElement | null>(null);
const hud = ref<Hud | null>(null);
const t = ref(0);
const playing = ref(false);
const cam = ref<CamMode>("mine");
const speed = ref(0.5);
const failed = ref(false);
let P: Pov | null = null;

const CAMS: [CamMode, string][] = [
  ["mine", "Ta caméra"],
  ["ball", "Caméra balle"],
  ["car", "Caméra voiture"],
  ["free", "Vue libre"],
];
const LABEL: Record<CamMode, string> = { mine: "Ta caméra (comme en jeu)", ball: "Caméra balle", car: "Caméra voiture", free: "Vue libre" };
const sec = (v: number) => (Math.abs(v) < 0.05 ? "0,0 s" : `${v > 0 ? "+" : MINUS}${Math.abs(v).toFixed(1).replace(".", ",")} s`);
const phase = (h: Hud) => (h.rel < -0.02 ? "approche" : h.rel <= 0.02 ? "touche" : "après la touche");

function setCam(m: CamMode) {
  cam.value = m;
  P?.setCam(m);
}
function setSpeed(s: number) {
  speed.value = s;
  P?.setSpeed(s);
}
function onKey(e: KeyboardEvent) {
  const el = e.target as HTMLElement;
  if (e.code === "Space" && !el.matches("button, input")) {
    e.preventDefault();
    P?.toggle();
  }
}
onMounted(() => {
  if (!canvas.value) return;
  try {
    P = createPov(canvas.value, props.clip, (h) => (hud.value = h));
  } catch {
    failed.value = true; // WebGL indisponible
    return;
  }
  P.setSpeed(speed.value);
  P.onState((s) => {
    t.value = s.t;
    playing.value = s.playing;
  });
  addEventListener("keydown", onKey);
});
onBeforeUnmount(() => {
  removeEventListener("keydown", onKey);
  P?.dispose();
});
</script>

<template>
  <div class="pov">
    <div class="pov-controls">
      <button type="button" class="pov-play" @click="P?.toggle()">
        {{ playing ? "❚❚ Pause" : P && Math.abs(t - P.T0) < 0.01 ? "▶ Suite" : "▶ Lire" }}
      </button>
      <div class="pov-seg" role="radiogroup" aria-label="Caméra">
        <button v-for="[m, l] in CAMS" :key="m" type="button" role="radio" :aria-checked="cam === m" @click="setCam(m)">{{ l }}</button>
      </div>
      <div class="pov-seg" role="radiogroup" aria-label="Vitesse">
        <button v-for="s in [0.25, 0.5, 1]" :key="s" type="button" role="radio" :aria-checked="speed === s" @click="setSpeed(s)">
          ×{{ String(s).replace(".", ",") }}
        </button>
      </div>
      <button type="button" class="pov-seg-btn" title="Revoir depuis le début" @click="P?.restart()">↺ Revoir</button>
    </div>
    <div class="pov-stage">
      <canvas ref="canvas" role="img" aria-label="Vue 3D de la touche : terrain, balle et les 6 voitures"></canvas>
      <p v-if="failed" class="pov-fail">La vue 3D n'a pas pu démarrer (WebGL désactivé dans ce navigateur ?).</p>
      <div v-if="hud" class="pov-hud">
        <div class="box">
          <div class="big">{{ sec(hud.rel) }}</div>
          <div>{{ phase(hud) }}{{ cam === "mine" ? (hud.ballcam ? " · ta caméra balle" : " · ta caméra voiture") : "" }}</div>
        </div>
        <div class="box right">
          <div>
            <b>{{ hud.kmh }} km/h</b>{{ hud.kmh > 79 ? " · supersonique" : "" }} · boost <b>{{ hud.boost }}</b>
          </div>
          <div v-if="hud.move" class="big move">{{ hud.move }}</div>
          <div>{{ hud.nose }}</div>
        </div>
      </div>
      <div class="pov-lab">{{ LABEL[cam] }}</div>
    </div>
    <div class="pov-time">
      <input type="range" name="temps" min="0" :max="P ? P.tmax : 0" step="0.01" :value="t" aria-label="Position dans l'action" @input="P?.seek(+($event.target as HTMLInputElement).value)" />
      <span class="clock">{{ P ? sec((t - P.T0) / P.FPS) : "" }}</span>
    </div>
    <div class="pov-legend">
      <span><i style="background: #d4ff3a"></i>Toi</span>
      <span><i style="background: #ff9a5c"></i><i style="background: #5fd0a4"></i>Coéquipiers</span>
      <span><i style="background: #8f98a6"></i>Adversaires</span>
      <span>Phares blancs à l'avant, feux rouges à l'arrière · flamme = boost · anneau = saut · ombre et fil sous la balle = hauteur · Espace : lecture / pause</span>
    </div>
  </div>
</template>

<style scoped>
.pov { display: flex; flex-direction: column; gap: 10px; color: #f3f3ee; }
.pov-controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.pov button { font: 800 13px/16px var(--font-sans, "Sofia Sans", Arial, sans-serif); letter-spacing: 0.04em; text-transform: uppercase; color: #f3f3ee; background: #171a21; border: 0; padding: 9px 12px; cursor: pointer; }
.pov button:focus-visible, .pov input:focus-visible { outline: 3px solid #d4ff3a; outline-offset: 2px; }
.pov .pov-play { background: #d4ff3a; color: #0b0d11; min-width: 110px; }
.pov-seg { display: inline-flex; gap: 2px; }
.pov-seg button[aria-checked="true"] { background: #f3f3ee; color: #0b0d11; }
.pov-stage { position: relative; background: #000; }
.pov-stage canvas { width: 100%; height: min(58vh, 600px); display: block; }
.pov-fail { position: absolute; inset: 0; margin: 0; display: flex; align-items: center; justify-content: center; text-align: center; padding: 20px; }
.pov-hud { position: absolute; left: 0; right: 0; top: 0; display: flex; justify-content: space-between; gap: 8px; pointer-events: none; padding: 10px 12px; }
.pov-hud .box { background: rgba(11, 13, 17, 0.82); padding: 6px 12px; font-size: 13px; line-height: 18px; }
.pov-hud .right { text-align: right; }
.pov-hud .big { font-family: var(--font-display, "Sofia Sans Extra Condensed", sans-serif); font-style: italic; font-weight: 900; font-size: 26px; line-height: 1; }
.pov-hud .move { color: #d4ff3a; font-size: 20px; }
.pov-lab { position: absolute; left: 10px; bottom: 10px; font: 800 12px/16px var(--font-sans, Arial, sans-serif); letter-spacing: 0.08em; text-transform: uppercase; background: rgba(11, 13, 17, 0.82); padding: 4px 10px; pointer-events: none; }
.pov-time { display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: center; }
.pov-time input { width: 100%; accent-color: #f3f3ee; }
.pov-time .clock { font-family: var(--font-display, sans-serif); font-style: italic; font-weight: 900; font-size: 26px; min-width: 70px; text-align: right; }
.pov-legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 13px; color: #9aa1ab; }
.pov-legend i { display: inline-block; width: 12px; height: 12px; vertical-align: -1px; margin-right: 6px; }
@media (max-width: 700px) { .pov-stage canvas { height: 46vh; } .pov-hud .box { font-size: 12px; } .pov-hud .big { font-size: 20px; } }
</style>
