<script setup lang="ts">
// Le déroulé d'un match : valeur de la situation (−1 à +1, toutes les 0,5 s), zone favorable en --good, défavorable
// en --bad, buts pour (trait) et contre (pointillé), touches du joueur en losanges (pleins : gain, creux : perte).
import { computed, ref, useId } from "vue";
import type { Curve } from "@/api/client";
import { MINUS, sgn } from "@/lib/format";
import { hideTip, showTip } from "@/lib/tip";
import { useWidth } from "@/lib/width";

const props = defineProps<{ c: Curve; label: string }>();
const host = ref<HTMLElement | null>(null);
const W = useWidth(host);
const uid = useId();
const H = 200,
  L = 30,
  Rr = 8,
  T = 10,
  B = 20;

const g = computed(() => {
  const c = props.c,
    N = c.v.length,
    w = W.value;
  const X = (k: number) => L + (k / Math.max(N - 1, 1)) * (w - L - Rr);
  const Y = (v: number) => T + (1 - (v + 1) / 2) * (H - T - B);
  const segs: [number, number][][] = [];
  let cur: [number, number][] = [];
  c.v.forEach((v, k) => {
    if (v == null) {
      if (cur.length) segs.push(cur);
      cur = [];
    } else cur.push([k, v]);
  });
  if (cur.length) segs.push(cur);
  const paths = segs.map(
    (sg) => `M${X(sg[0][0])},${Y(0)} ` + sg.map(([k, v]) => `L${X(k).toFixed(1)},${Y(v).toFixed(1)}`).join(" ") + ` L${X(sg[sg.length - 1][0])},${Y(0)} Z`,
  );
  const touches = c.touches.map((t) => {
    const v = c.v[Math.min(t.k, N - 1)] ?? 0,
      x = X(t.k),
      y = Y(v),
      s = 4 + Math.min(Math.abs(t.dv ?? 0) * 10, 4);
    return { t, d: `M${x},${y - s} L${x + s},${y} L${x},${y + s} L${x - s},${y} Z`, gain: (t.dv ?? 0) >= 0 };
  });
  return { X, Y, paths, touches, goals: c.goals.map((gl) => ({ x: X(gl.k), pour: gl.pour })), w };
});
</script>

<template>
  <div ref="host">
    <svg :width="g.w" :height="H" :viewBox="`0 0 ${g.w} ${H}`" role="img" :aria-label="label">
      <defs>
        <clipPath :id="`${uid}-u`"><rect :x="L" :y="T" :width="g.w - L - Rr" :height="g.Y(0) - T" /></clipPath>
        <clipPath :id="`${uid}-d`"><rect :x="L" :y="g.Y(0)" :width="g.w - L - Rr" :height="H - B - g.Y(0)" /></clipPath>
      </defs>
      <template v-for="v in [-1, 0, 1]" :key="v">
        <line :x1="L" :x2="g.w - Rr" :y1="g.Y(v)" :y2="g.Y(v)" :stroke="v === 0 ? 'var(--ink-muted)' : 'var(--rule)'" />
        <text :x="L - 6" :y="g.Y(v) + 4" text-anchor="end">{{ v > 0 ? "+1" : v < 0 ? MINUS + "1" : "0" }}</text>
      </template>
      <template v-for="(d, i) in g.paths" :key="i">
        <path :d="d" fill="var(--good)" :clip-path="`url(#${uid}-u)`" />
        <path :d="d" fill="var(--bad)" :clip-path="`url(#${uid}-d)`" />
      </template>
      <line
        v-for="(gl, i) in g.goals"
        :key="'g' + i"
        :x1="gl.x"
        :x2="gl.x"
        :y1="T"
        :y2="H - B"
        :stroke="gl.pour ? 'var(--good-on-dark)' : 'var(--bad)'"
        stroke-width="2"
        :stroke-dasharray="gl.pour ? undefined : '4 3'"
      />
      <path
        v-for="(p, i) in g.touches"
        :key="'t' + i"
        :d="p.d"
        :fill="p.gain ? 'var(--me)' : 'var(--surface)'"
        stroke="var(--me)"
        stroke-width="1.5"
        @mousemove="showTip($event, [[{ b: p.t.a }, ` · gain ${sgn(p.t.dv)}`]])"
        @mouseleave="hideTip"
      />
      <text :x="L" :y="H - 4">début</text>
      <text :x="g.w - Rr" :y="H - 4" text-anchor="end">fin</text>
    </svg>
  </div>
</template>
