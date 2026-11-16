<script setup lang="ts">
// Carte du terrain, une à la fois : temps passé, toi contre les pros, gain des touches par zone. Ton équipe attaque
// vers le haut ; aucun texte sur les cases.
import { computed, nextTick, ref } from "vue";
import MI from "../MI.vue";
import Scope from "../Scope.vue";
import type { Derived } from "@/lib/data";
import { NB, pc, sgn, sgnI } from "@/lib/format";
import { hideTip, showTip, type TipLine } from "@/lib/tip";
import { ui } from "@/lib/ui";

const props = defineProps<{ d: Derived }>();
const MAP = ["--map-0", "--map-1", "--map-2", "--map-3", "--map-4"],
  DIV = ["--div-neg", "--div-neg-soft", "--div-mid", "--div-pos-soft", "--div-pos"];
const modes = { temps: "Temps", pros: "Toi vs les pros", touches: "Touches" } as const;
type Mode = keyof typeof modes;
const cw = 24,
  ch = 20,
  gp = 2;

const v = computed(() => {
  const H = props.d.HEAT!;
  const n = H.gx * H.gy,
    half = (k: number) => Math.floor(k / H.gx) >= H.gy / 2;
  const occ = H.occ_me.map((x) => x ?? 0),
    pro = H.occ_pro.map((x) => x ?? 0);
  const zone = (k: number) => {
    const j = Math.floor(k / H.gx),
      i = k % H.gx;
    const t = j < H.gy / 3 ? "ton tiers défensif" : j < (2 * H.gy) / 3 ? "le tiers central" : "le tiers offensif";
    const s = i < (H.gx * 3) / 8 ? "à gauche" : i >= (H.gx * 5) / 8 ? "à droite" : "au centre";
    return `${t}, ${s}`;
  };
  let color: (k: number) => string, phrase: string, ramp: string[], rl: [string, string];
  if (ui.terrain === "temps") {
    const mn = Math.min(...occ),
      mx = Math.max(...occ);
    color = (k) => `var(${MAP[Math.min(4, Math.floor(((occ[k] - mn) / (mx - mn || 1)) * 5))]})`;
    const off = occ.reduce((s, x, k) => s + (half(k) ? x : 0), 0);
    phrase = `Tu passes ${pc(off)} de ton temps dans la moitié adverse. Ta zone la plus fréquentée : ${zone(occ.indexOf(mx))}.`;
    ramp = MAP;
    rl = ["rare", "fréquent"];
  } else if (ui.terrain === "pros") {
    const dd = occ.map((x, k) => x - pro[k]),
      dm = Math.max(...dd.map(Math.abs)) || 1;
    color = (k) => {
      const t = dd[k] / dm;
      return `var(${DIV[t < -0.5 ? 0 : t < -0.15 ? 1 : t <= 0.15 ? 2 : t <= 0.5 ? 3 : 4]})`;
    };
    const off = dd.reduce((s, x, k) => s + (half(k) ? x : 0), 0);
    phrase =
      off >= 0
        ? `Plus présent que les pros dans la moitié adverse (${sgnI(off * 100)} points de ton temps), moins dans ta moitié : tu remontes tôt.`
        : `Moins présent que les pros dans la moitié adverse (${sgnI(off * 100)} points de ton temps), plus dans ta moitié : tu restes bas.`;
    ramp = DIV;
    rl = ["moins que les pros", "plus"];
  } else {
    const ok = (k: number) => H.touch_n[k] >= 8,
      dv = (k: number) => H.touch_dv[k] ?? 0;
    color = (k) => {
      if (!ok(k)) return "var(--surface-alt)";
      const x = dv(k);
      return `var(${DIV[x < -0.04 ? 0 : x < -0.01 ? 1 : x <= 0.01 ? 2 : x <= 0.04 ? 3 : 4]})`;
    };
    const ks = [...Array(n).keys()].filter(ok);
    const b = ks.reduce((a, k) => (dv(k) > dv(a) ? k : a), ks[0]),
      w = ks.reduce((a, k) => (dv(k) < dv(a) ? k : a), ks[0]);
    phrase = ks.length
      ? `Tes touches rapportent le plus dans ${zone(b)} (${sgn(dv(b), 3)} en moyenne) et coûtent le plus dans ${zone(w)} (${sgn(dv(w), 3)}).`
      : "Pas assez de touches par zone.";
    ramp = DIV;
    rl = ["perd de la valeur", "en gagne"];
  }
  const cells = [];
  for (let j = 0; j < H.gy; j++)
    for (let i = 0; i < H.gx; i++) {
      const k = j * H.gx + i;
      cells.push({ k, x: i * (cw + gp), y: (H.gy - 1 - j) * (ch + gp), fill: color(k) });
    }
  const p = (x: number | null) => ((x ?? 0) * 100).toFixed(1).replace(".", ",") + NB + "%";
  const tipOf = (k: number): TipLine[] =>
    ui.terrain === "touches"
      ? [[{ b: zone(k) }], [`${H.touch_n[k]} touches · gain moyen ${sgn(H.touch_dv[k], 3)}`, ...(H.touch_n[k] < 8 ? [" ", { m: "(trop peu pour juger)" }] : [])]]
      : [[{ b: zone(k) }], [`Toi : ${p(H.occ_me[k])} du temps`], [{ m: `pros : ${p(H.occ_pro[k])} · lobbies : ${p(H.occ_lobby[k])}` }]];
  return { H, cells, phrase, ramp, rl, Wm: H.gx * (cw + gp) - gp, Hm: H.gy * (ch + gp) - gp, tipOf };
});

const seg = ref<HTMLElement | null>(null);
async function setMode(m: Mode) {
  ui.terrain = m;
  await nextTick();
  seg.value?.querySelector<HTMLElement>(`[data-mode="${m}"]`)?.focus();
}
</script>

<template>
  <div v-if="d.HEAT" class="terrain">
    <div>
      <svg :width="v.Wm" :height="v.Hm + 30" :viewBox="`0 -14 ${v.Wm} ${v.Hm + 30}`" role="img" :aria-label="v.phrase">
        <text :x="v.Wm / 2" y="-4" text-anchor="middle">BUT ADVERSE</text>
        <rect v-for="c in v.cells" :key="c.k" :x="c.x" :y="c.y" :width="cw" :height="ch" :fill="c.fill" @mousemove="showTip($event, v.tipOf(c.k))" @mouseleave="hideTip" />
        <line x1="0" :x2="v.Wm" :y1="v.Hm / 2" :y2="v.Hm / 2" stroke="var(--ink-muted)" />
        <text :x="v.Wm / 2" :y="v.Hm + 14" text-anchor="middle">TON BUT</text>
      </svg>
      <div class="ramp"><span v-for="c in v.ramp" :key="c" :style="{ background: `var(${c})` }"></span></div>
      <div class="ramp-l pl-small pl-muted"><span>{{ v.rl[0] }}</span><span>{{ v.rl[1] }}</span></div>
      <div v-if="ui.terrain === 'touches'" class="pl-small pl-muted" style="display: flex; gap: 6px; align-items: center; margin-top: 4px">
        <i class="sw" style="background: var(--surface-alt)"></i>moins de 8 touches
      </div>
    </div>
    <div>
      <div ref="seg" class="seg pl-tag" role="group" aria-label="Carte affichée">
        <button v-for="(l, k) in modes" :key="k" type="button" :data-mode="k" :aria-pressed="k === ui.terrain" @click="setMode(k)">{{ l }}</button>
      </div>
      <div class="bt" style="margin-top: 12px"><h3 class="pl-dx" style="font-size: var(--dx-24)">{{ modes[ui.terrain] }}</h3><MI id="terrain" label="Cartes du terrain" /><Scope kind="p" /></div>
      <p class="pl-small" style="margin-top: 6px">{{ v.phrase }}</p>
      <p class="pl-small pl-muted note">Ton équipe attaque vers le haut. {{ v.H.n_pro_replays }} matchs RLCS en référence.</p>
    </div>
  </div>
</template>
