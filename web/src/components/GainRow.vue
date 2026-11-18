<script setup lang="ts">
// Gain moyen d'un type de touche : toi (losange) et les pros RLCS (trait), sur une échelle commune ; trait à 0.
import { ref } from "vue";
import SymMark from "./SymMark.vue";
import type { Value } from "@/api/client";
import { pc, sgn } from "@/lib/format";
import { hideTip, showTip } from "@/lib/tip";
import { useWidth } from "@/lib/width";

const props = defineProps<{ a: Value["by_action"][number]; lo: number; hi: number; player: string }>();
const host = ref<HTMLElement | null>(null);
const W = useWidth(host);
const X = (v: number | null) => 6 + (((v ?? 0) - props.lo) / (props.hi - props.lo || 1)) * (W.value - 12);
</script>

<template>
  <div class="gainrow">
    <span><b style="font-weight: 700">{{ a.label }}</b><br /><span class="pl-small pl-muted">{{ a.n }} touches</span></span>
    <div ref="host" class="plot">
      <svg :width="W" height="20" :viewBox="`0 0 ${W} 20`" aria-hidden="true">
        <rect x="0" y="7" :width="W" height="6" fill="var(--surface-alt)" />
        <rect :x="X(0) - 1" y="0" width="2" height="20" fill="var(--ink-muted)" />
        <g @mousemove="showTip($event, [[`Pros RLCS : ${sgn(a.ref, 3)} · ${pc(a.ref_pos)} de touches positives`]])" @mouseleave="hideTip">
          <SymMark kind="ref" :x="X(a.ref)" :y="10" :s="7" />
        </g>
        <g @mousemove="showTip($event, [[`${player} : ${sgn(a.me, 3)} · ${pc(a.me_pos)} de touches positives`]])" @mouseleave="hideTip">
          <SymMark kind="me" :x="X(a.me)" :y="10" :s="7" />
        </g>
      </svg>
    </div>
    <span class="pl-dx vl" :class="(a.me ?? 0) >= 0 ? 'pl-good' : 'pl-bad'">{{ sgn(a.me, 2) }}</span>
  </div>
</template>
