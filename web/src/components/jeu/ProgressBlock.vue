<script setup lang="ts">
// Progression : parties récentes de la période face aux précédentes ; courbe de l'indice (moyenne sur 5).
import { computed, ref } from "vue";
import MI from "../MI.vue";
import Scope from "../Scope.vue";
import type { Derived } from "@/lib/data";
import { R, dS, fmt } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { hideTip, showTip } from "@/lib/tip";
import { useWidth } from "@/lib/width";

const props = defineProps<{ d: Derived }>();
const { openMatch } = useNav();
const G = computed(() => props.d.C.progress);
type Change = NonNullable<typeof G.value>["changes"][number];
const lists = computed(() => {
  const g = G.value!;
  const ch = g.changes.filter((c) => !c.headline);
  const head = Object.fromEntries(g.changes.filter((c) => c.headline).map((c) => [c.key, c]));
  const e = (c: Change) => c.effect ?? 0;
  const up = ch.filter((c) => e(c) > 0).sort((a, b) => +b.clear - +a.clear || e(b) - e(a)).slice(0, 3);
  const down = ch.filter((c) => e(c) < 0).sort((a, b) => +b.clear - +a.clear || e(a) - e(b)).slice(0, 2);
  return { up, down, ix: head.index, fond: head.fond };
});
const val = (c: Change, x: number | null) => (c.unit === "/100" ? R(x) : fmt(x, c.unit));

const host = ref<HTMLElement | null>(null);
const W = useWidth(host);
const H = 120,
  pad = 8;
const plot = computed(() => {
  const g = G.value!,
    n = g.index.length,
    w = W.value;
  const X = (i: number) => pad + (i / Math.max(1, n - 1)) * (w - 2 * pad);
  const Y = (y: number) => H - 6 - (y / 100) * (H - 12);
  return {
    w,
    X,
    Y,
    line: g.roll5.map((y, i) => `${i ? "L" : "M"}${X(i)},${Y(y ?? 0)}`).join(" "),
    pts: g.index.map((y, i) => ({ x: X(i), y: Y(y ?? 0), v: y, won: g.won[i], date: g.dates[i], roll: g.roll5[i], replay: props.d.replayOfDate(g.dates[i]) })),
  };
});
</script>

<template>
  <p v-if="!G" class="empty">Pas encore assez de parties pour suivre une progression (6 minimum).</p>
  <div v-else class="prog">
    <div class="bt" style="margin-bottom: 8px"><h2 class="pl-dx h44">Progression</h2><MI id="progression" label="Progression" /><Scope kind="p" /></div>
    <p class="pl-body read">
      Les {{ G.n - G.half }} parties les plus récentes de la période face aux {{ G.half }} d'avant.<template v-if="lists.ix">
        Indice {{ R(lists.ix.before) }} → <b>{{ R(lists.ix.after) }}</b>{{ lists.ix.clear ? "" : " (écart dans le bruit)" }}</template
      ><template v-if="lists.fond"> · fondamentaux {{ R(lists.fond.before) }} → <b>{{ R(lists.fond.after) }}</b></template>.
    </p>
    <div ref="host" class="plot" style="margin: 8px 0 14px">
      <svg :width="plot.w" :height="H" :viewBox="`0 0 ${plot.w} ${H}`" role="img" :aria-label="`Indice des ${G.index.length} dernières parties`">
        <rect x="0" :y="plot.Y(50) - 0.5" :width="plot.w" height="1" fill="var(--ink-muted)" opacity=".6" />
        <rect :x="plot.X(G.half - 0.5) - 0.5" y="0" width="1" :height="H" fill="var(--rule)" />
        <path :d="plot.line" fill="none" stroke="var(--accent)" stroke-width="2.5" />
        <circle
          v-for="(p, i) in plot.pts"
          :key="i"
          :cx="p.x"
          :cy="p.y"
          r="4"
          :fill="p.won ? 'var(--good-on-dark)' : 'var(--bad)'"
          stroke="var(--surface)"
          stroke-width="1.5"
          :style="p.replay ? { cursor: 'pointer' } : undefined"
          @mousemove="showTip($event, [[`${dS(p.date)} · ${p.won ? 'victoire' : 'défaite'}`], ['Indice ', { b: R(p.v) }, ` · moyenne sur 5 : ${R(p.roll)}`], [{ m: 'clic : ouvrir le match' }]])"
          @mouseleave="hideTip"
          @click="openMatch(p.replay)"
        />
      </svg>
    </div>
    <h3 class="grph pl-tag"><span>Plus fortes progressions</span></h3>
    <div v-for="c in lists.up" :key="c.key" class="chg">
      <span><b>{{ c.label }}</b><br /><span class="pl-small pl-muted">{{ val(c, c.before) }} → {{ val(c, c.after) }}{{ c.clear ? "" : " · à confirmer" }}</span></span>
      <span class="pl-dx d pl-good">▲</span><span class="pl-tag" :class="{ 'pl-muted': !c.clear }">{{ c.clear ? "net" : "bruit ?" }}</span>
    </div>
    <p v-if="!lists.up.length" class="pl-small pl-muted">Aucune.</p>
    <h3 class="grph pl-tag"><span>En recul</span></h3>
    <div v-for="c in lists.down" :key="c.key" class="chg">
      <span><b>{{ c.label }}</b><br /><span class="pl-small pl-muted">{{ val(c, c.before) }} → {{ val(c, c.after) }}{{ c.clear ? "" : " · à confirmer" }}</span></span>
      <span class="pl-dx d pl-bad">▼</span><span class="pl-tag" :class="{ 'pl-muted': !c.clear }">{{ c.clear ? "net" : "bruit ?" }}</span>
    </div>
    <p v-if="!lists.down.length" class="pl-small pl-muted">Aucun.</p>
    <p class="pl-small pl-muted" style="margin-top: 6px">« Net » : l'écart tient dans 80 % des tirages au sort de tes parties. Sinon, il peut venir du hasard de quelques matchs.</p>
  </div>
</template>
