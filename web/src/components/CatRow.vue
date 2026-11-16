<script setup lang="ts">
// Barre 0–100 d'une note (trait à 50), avec la note de chaque coéquipier (symbole, info-bulle).
import { computed, ref } from "vue";
import SymMark from "./SymMark.vue";
import type { PeerView } from "@/lib/data";
import { R } from "@/lib/format";
import { hideTip, showTip } from "@/lib/tip";
import { useWidth } from "@/lib/width";

const props = defineProps<{ label: string; sub: string; exp?: boolean; v: number | null | undefined; peers: { p: PeerView; v: number | null | undefined }[] }>();
const host = ref<HTMLElement | null>(null);
const W = useWidth(host);
const X = (v: number) => (v / 100) * W.value;
const shown = computed(() => props.peers.filter((x) => x.v != null) as { p: PeerView; v: number }[]);
</script>

<template>
  <div class="cat">
    <span><b style="font-weight: 700">{{ label }}</b><br /><span class="pl-small" :class="exp ? 'exp' : 'pl-muted'">{{ sub }}</span></span>
    <div ref="host" class="plot">
      <svg :width="W" height="22" :viewBox="`0 0 ${W} 22`" role="img" :aria-label="`${label} : ${R(v)} sur 100`">
        <rect x="0" y="7" :width="W" height="8" fill="var(--surface-alt)" />
        <rect v-if="v != null" x="0" y="7" :width="Math.max(2, X(v))" height="8" :fill="v >= 50 ? 'var(--good)' : 'var(--bad)'" />
        <rect :x="X(50) - 1" y="2" width="2" height="18" fill="var(--ink-muted)" />
        <g v-for="x in shown" :key="x.p.id" @mousemove="showTip($event, [[{ b: x.p.name }, ` : ${R(x.v)}/100`]])" @mouseleave="hideTip">
          <SymMark :kind="x.p.slot" :x="X(x.v)" :y="11" :s="5" />
        </g>
      </svg>
    </div>
    <span class="pl-dx vl" :class="{ 'pl-bad': (v ?? 0) < 50 }">{{ R(v) }}</span>
  </div>
</template>
