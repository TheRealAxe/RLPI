<script setup lang="ts">
// Évolution d'un indicateur match par match : un losange par match (V/D dessous s'il y en a 30 au plus), moyenne
// glissante sur 5 parties, trait de référence. Courbe retournée quand « plus bas = mieux ».
import { computed, ref } from "vue";
import SymMark from "./SymMark.vue";
import { R, dL, num } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { hideTip, showTip } from "@/lib/tip";
import { useWidth } from "@/lib/width";

export interface EvoPoint {
  d: string;
  v: number | null;
  w?: boolean;
  replay?: string;
}
const props = defineProps<{ pts: EvoPoint[]; lo: number; hi: number; refv: number | null; invert: boolean; label: string; summary: string; fv: (v: number | null) => string }>();
const { openMatch } = useNav();
const host = ref<HTMLElement | null>(null);
const W = useWidth(host);
const H = 220,
  Lp = 40,
  Rp = 12,
  T = 12,
  B = 30;

const g = computed(() => {
  const n = props.pts.length,
    w = W.value,
    { lo, hi } = props;
  const X = (i: number) => Lp + (n < 2 ? (w - Lp - Rp) / 2 : (i * (w - Lp - Rp)) / (n - 1));
  const Y = (v: number) => {
    const t = (v - lo) / (hi - lo || 1);
    return T + (props.invert ? t : 1 - t) * (H - T - B);
  };
  const grid = [0, 1, 2, 3, 4].map((k) => {
    const v = lo + (k * (hi - lo)) / 4;
    return { y: Y(v), t: Math.abs(hi - lo) >= 20 ? R(v) : num(v, 1) };
  });
  const roll = props.pts.map((_p, i) => {
    const win = props.pts
      .slice(Math.max(0, i - 4), i + 1)
      .map((x) => x.v)
      .filter((v) => v != null) as number[];
    return win.length ? win.reduce((a, b) => a + b) / win.length : null;
  });
  const line = roll.flatMap((v, i) => (v == null ? [] : [`${X(i)},${Y(v)}`])).join(" ");
  const pts = props.pts.flatMap((p, i) => (p.v == null ? [] : [{ p, x: X(i), y: Y(p.v) }]));
  return { w, X, Y, grid, line, pts, n };
});
</script>

<template>
  <div ref="host">
    <svg :width="g.w" :height="H" :viewBox="`0 0 ${g.w} ${H}`" role="img" :aria-label="`${label}, match par match. ${summary}`">
      <template v-for="(l, k) in g.grid" :key="k">
        <line :x1="Lp" :x2="g.w - Rp" :y1="l.y" :y2="l.y" stroke="var(--rule)" />
        <text :x="Lp - 8" :y="l.y + 4" text-anchor="end">{{ l.t }}</text>
      </template>
      <line v-if="refv != null" :x1="Lp" :x2="g.w - Rp" :y1="g.Y(refv)" :y2="g.Y(refv)" stroke="var(--ref)" stroke-width="2" />
      <polyline :points="g.line" fill="none" stroke="var(--me)" stroke-width="3" stroke-linejoin="round" />
      <template v-for="(q, i) in g.pts" :key="i">
        <g
          :style="q.p.replay ? { cursor: 'pointer' } : undefined"
          @mousemove="
            showTip($event, [
              [{ b: dL(q.p.d) }, q.p.w == null ? '' : ' · ' + (q.p.w ? 'victoire' : 'défaite')],
              [`${label} : `, { b: fv(q.p.v) }],
              ...(q.p.replay ? [[{ m: 'clic : ouvrir le match' }]] : []),
            ])
          "
          @mouseleave="hideTip"
          @click="openMatch(q.p.replay)"
        >
          <SymMark kind="me" :x="q.x" :y="q.y" :s="5" />
        </g>
        <text v-if="q.p.w != null && g.n <= 30" :x="q.x" :y="H - B + 16" text-anchor="middle" :style="{ fill: q.p.w ? 'var(--ink)' : 'var(--ink-muted)' }">{{ q.p.w ? "V" : "D" }}</text>
      </template>
    </svg>
  </div>
</template>
