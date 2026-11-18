<script setup lang="ts">
// Une mesure de synergie de la paire : bande = intervalle 80 %, symbole du coéquipier = valeur de la paire,
// trait = paires SSL, rond vide = toi avec un coéquipier inconnu.
import { computed, ref } from "vue";
import SymMark from "./SymMark.vue";
import { synVerdict } from "@/copy";
import type { SynergyPair } from "@/api/client";
import type { PeerView } from "@/lib/data";
import { NB, num, sgn } from "@/lib/format";
import { hideTip, showTip } from "@/lib/tip";
import { useWidth } from "@/lib/width";

type Row = SynergyPair["rows"][number];
const props = defineProps<{ r: Row; peer: PeerView; player: string }>();
const host = ref<HTMLElement | null>(null);
const W = useWidth(host);
const H = 22;

const u = (r: Row) => (r.key === "bonus" ? "pts" : r.key === "connexion" ? "%" : r.key === "ecart" ? "m" : "s");
const f = (v: number | null | undefined, r: Row) => (v == null ? "—" : r.key === "bonus" ? sgn(v, 1) : num(v, r.key === "ecart" ? 0 : 1));
const verdict = computed(() => synVerdict(props.r));
const g = computed(() => {
  const r = props.r;
  const vals = [r.lo, r.hi, r.v, r.ssl, r.random].filter((v) => v != null) as number[];
  let lo = Math.min(...vals),
    hi = Math.max(...vals);
  const pad = (hi - lo) * 0.25 || 1;
  lo -= pad;
  hi += pad;
  const X = (v: number | null | undefined) => 6 + (((v ?? 0) - lo) / (hi - lo)) * (W.value - 12);
  return { X };
});
</script>

<template>
  <div class="all" style="cursor: default">
    <span><b style="font-weight: 700">{{ r.label }}</b><br /><span class="pl-small pl-muted">{{ r.unit }}{{ r.sens === 0 ? "" : r.sens > 0 ? " · plus haut = mieux" : " · plus bas = mieux" }}</span></span>
    <div ref="host" class="plot">
      <svg :width="W" :height="H" :viewBox="`0 0 ${W} ${H}`" aria-hidden="true">
        <rect x="0" y="8" :width="W" height="6" fill="var(--surface-alt)" />
        <rect v-if="r.key === 'bonus'" :x="g.X(0) - 0.5" y="4" width="1" height="14" fill="var(--ink-muted)" />
        <rect :x="g.X(r.lo)" y="7" :width="Math.max(2, g.X(r.hi) - g.X(r.lo))" height="8" :fill="peer.color" opacity=".35" />
        <rect :x="g.X(r.ssl) - 1.5" y="1" width="3" height="20" fill="var(--ref)" @mousemove="showTip($event, [['Paires SSL : ', { b: `${f(r.ssl, r)}${NB}${u(r)}` }]])" @mouseleave="hideTip" />
        <circle
          v-if="r.random != null"
          :cx="g.X(r.random)"
          cy="11"
          r="5"
          fill="none"
          stroke="var(--ink-muted)"
          stroke-width="1.5"
          @mousemove="showTip($event, [['Toi + inconnu : ', { b: `${f(r.random, r)}${NB}${u(r)}` }]])"
          @mouseleave="hideTip"
        />
        <g
          @mousemove="showTip($event, [[{ b: `${player} + ${peer.name}` }, ` : ${f(r.v, r)}${NB}${u(r)}`], [{ m: `intervalle 80${NB}% : ${f(r.lo, r)} à ${f(r.hi, r)}` }]])"
          @mouseleave="hideTip"
        >
          <SymMark :kind="peer.slot" :x="g.X(r.v)" :y="11" :s="7" />
        </g>
      </svg>
    </div>
    <span class="vl"><span class="pl-dx">{{ f(r.v, r) }}</span><br /><span class="pl-small" :class="verdict[1]">{{ verdict[0] }}</span></span>
  </div>
</template>
