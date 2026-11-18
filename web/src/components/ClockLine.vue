<script setup lang="ts">
// Moments clés : les touches les plus coûteuses sur l'horloge de jeu (5:00 → 0:00, temps restant). Hauteur
// proportionnelle au coût ; les trois premières numérotées en volt.
import { computed, ref } from "vue";
import type { Touch } from "@/api/client";
import { clock, dL, sgn } from "@/lib/format";
import { hideTip, showTip } from "@/lib/tip";
import { useWidth } from "@/lib/width";

const props = defineProps<{ touches: Touch[] }>();
const host = ref<HTMLElement | null>(null);
const W = useWidth(host);
const H = 92,
  L = 14,
  Rr = 14,
  base = 60;
const g = computed(() => {
  const w = W.value;
  const X = (s: number) => L + ((300 - Math.min(300, Math.max(0, s))) / 300) * (w - L - Rr);
  const mx = Math.max(...props.touches.map((t) => Math.abs(t.dv ?? 0))) || 1;
  const bars = props.touches
    .map((t, k) => ({ t, k, h: (Math.abs(t.dv ?? 0) / mx) * 46, x: X(t.clock ?? 0) }))
    .reverse();
  const label = "Horloge des touches coûteuses : " + props.touches.map((t, k) => `#${k + 1} à ${clock(t.clock)}, ${sgn(t.dv)}`).join(" ; ");
  return { w, X, bars, label };
});
</script>

<template>
  <div ref="host">
    <svg :width="g.w" :height="H" :viewBox="`0 0 ${g.w} ${H}`" role="img" :aria-label="g.label">
      <line :x1="L" :x2="g.w - Rr" :y1="base" :y2="base" stroke="var(--ink)" stroke-width="2" />
      <template v-for="s in [300, 240, 180, 120, 60, 0]" :key="s">
        <line :x1="g.X(s)" :x2="g.X(s)" :y1="base - 6" :y2="base + 6" stroke="var(--ink)" stroke-width="2" />
        <text :x="g.X(s)" :y="base + 24" text-anchor="middle">{{ clock(s) }}</text>
      </template>
      <template v-for="b in g.bars" :key="b.k">
        <rect
          :x="b.x - 5"
          :y="base - b.h"
          width="10"
          :height="b.h"
          fill="var(--bad)"
          @mousemove="showTip($event, [[{ b: `#${b.k + 1} · ${b.t.action}` }, ` à ${clock(b.t.clock)}`], [`${dL(b.t.date)} · gain ${sgn(b.t.dv)}`]])"
          @mouseleave="hideTip"
        />
        <text v-if="b.k < 3" :x="b.x" :y="base - b.h - 6" text-anchor="middle" style="fill: var(--accent-ink); font-size: var(--fs-small)">#{{ b.k + 1 }}</text>
      </template>
    </svg>
  </div>
</template>
