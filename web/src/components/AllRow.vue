<script setup lang="ts">
// Une ligne de « Tous les indicateurs » : barre de centile (trait à 50) avec les coéquipiers, ou, pour un indicateur
// de style, la position parmi les joueurs de la référence (trait : médiane). Cliquable pour suivre son évolution.
import { computed, ref } from "vue";
import SymMark from "./SymMark.vue";
import type { Metric } from "@/api/client";
import type { PeerView, SymKind } from "@/lib/data";
import { R } from "@/lib/format";
import { hideTip, showTip, type TipLine } from "@/lib/tip";
import { useWidth } from "@/lib/width";

export interface PeerMark {
  slot: SymKind;
  v: number;
  tip?: TipLine[];
}
const props = defineProps<{
  label: string;
  sub: string;
  note: number | null | undefined;
  val: string;
  /** Indicateur de style : bande des joueurs de la référence au lieu d'une barre de centile. */
  styleMetric?: Metric | null;
  peers: PeerView[];
  marks?: PeerMark[];
  pressed?: boolean | null;
}>();
defineEmits<{ pick: [] }>();
const host = ref<HTMLElement | null>(null);
const W = useWidth(host);
const H = 22;

const band = computed(() => {
  const m = props.styleMetric;
  if (!m) return null;
  const vals = [...m.ref.map((x) => x.v), m.value].filter((v) => v != null) as number[];
  const lo = Math.min(...vals),
    hi = Math.max(...vals);
  const X = (v: number) => 6 + ((v - lo) / (hi - lo || 1)) * (W.value - 12);
  return {
    refs: m.ref.filter((x) => x.v != null).map((x) => X(x.v!)),
    med: X(m.ref_med ?? 0),
    me: X(m.value ?? 0),
    peers: props.peers.flatMap((p) => {
      const v = m.peers?.[p.id]?.value;
      return v == null ? [] : [{ slot: p.slot, x: X(v) }];
    }),
  };
});
const X = (v: number) => (v / 100) * W.value;
</script>

<template>
  <button type="button" class="all" :aria-pressed="pressed ?? undefined" :disabled="pressed == null" :style="pressed == null ? { cursor: 'default' } : undefined" @click="$emit('pick')">
    <span><b style="font-weight: 700">{{ label }}</b><br /><span class="pl-small pl-muted">{{ sub }}</span></span>
    <div ref="host" class="plot">
      <svg :width="W" :height="H" :viewBox="`0 0 ${W} ${H}`" aria-hidden="true">
        <template v-if="band">
          <rect x="0" y="8" :width="W" height="6" fill="var(--surface-alt)" />
          <rect v-for="(x, i) in band.refs" :key="i" :x="x - 0.5" y="6" width="1" height="10" fill="var(--ref)" />
          <rect :x="band.med - 1" y="1" width="2" height="20" fill="var(--ink)" />
          <SymMark v-for="p in band.peers" :key="p.slot" :kind="p.slot" :x="p.x" :y="11" :s="5" />
          <SymMark kind="me" :x="band.me" :y="11" :s="7" />
        </template>
        <template v-else>
          <rect x="0" y="7" :width="W" height="8" fill="var(--surface-alt)" />
          <rect v-if="note != null" x="0" y="7" :width="Math.max(2, X(note))" height="8" :fill="note >= 50 ? 'var(--good)' : 'var(--bad)'" />
          <rect :x="X(50) - 1" y="2" width="2" height="18" fill="var(--ink-muted)" />
          <g v-for="(mk, i) in marks ?? []" :key="i" @mousemove="mk.tip && showTip($event, mk.tip)" @mouseleave="hideTip">
            <SymMark :kind="mk.slot" :x="X(mk.v)" :y="11" :s="5" />
          </g>
        </template>
      </svg>
    </div>
    <span class="vl"><span class="pl-dx">{{ note == null ? "" : R(note) }}</span><br /><span class="pl-small pl-muted">{{ val }}</span></span>
  </button>
</template>
