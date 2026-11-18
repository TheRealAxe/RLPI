<script setup lang="ts">
// Écarts de style : les six catégories où ta part du temps s'écarte le plus de la référence. Barre divergente
// neutre (--ink-muted) : le style n'a pas de bon sens.
import { computed } from "vue";
import MI from "../MI.vue";
import Scope from "../Scope.vue";
import type { Derived } from "@/lib/data";
import { NB, sgnI } from "@/lib/format";

const props = defineProps<{ d: Derived }>();
const gaps = computed(() => {
  const all: { lab: string; me: number; ref: number; d: number; title: string }[] = [];
  for (const c of props.d.C.compo) {
    const me = c.rows.find((r) => r.key === "me"),
      ref = c.rows.find((r) => r.key === props.d.ref);
    if (!me || !ref) continue;
    c.labels.forEach((lab, i) => {
      const a = me.parts[i],
        b = ref.parts[i];
      if (a == null || b == null) return;
      all.push({ lab, me: a, ref: b, d: (a - b) * 100, title: c.title });
    });
  }
  const g = all.sort((a, b) => Math.abs(b.d) - Math.abs(a.d)).slice(0, 6);
  const mx = Math.max(10, ...g.map((x) => Math.abs(x.d)));
  return g.map((x) => ({ ...x, w: (Math.abs(x.d) / mx) * 118 }));
});
</script>

<template>
  <div v-if="gaps.length">
    <div class="bt" style="margin-bottom: 4px">
      <h2 class="pl-tag pl-muted">Ton style · les 6 plus gros écarts aux {{ d.refLabel }} (points)</h2><MI id="style" label="Style de jeu" /><Scope kind="p" />
    </div>
    <p class="pl-small read">
      Ton plus gros écart : {{ gaps[0].lab }} ({{ gaps[0].title.toLowerCase() }}), {{ sgnI(gaps[0].d) }} points. Le style n'a pas de bon sens : la barre ne dit ni bien ni mal.
    </p>
    <div v-for="x in gaps" :key="x.title + x.lab" class="gap">
      <span><b>{{ x.lab }}</b><span class="pl-small pl-muted">{{ Math.round(x.me * 100) }}{{ NB }}% contre {{ Math.round(x.ref * 100) }}{{ NB }}% ({{ d.refLabel }})</span></span>
      <svg width="100%" height="14" viewBox="0 0 240 14" preserveAspectRatio="none" role="img" :aria-label="`${x.lab} : ${sgnI(x.d)} points`">
        <rect :x="x.d >= 0 ? 120 : 120 - x.w" y="2" :width="x.w" height="10" fill="var(--ink-muted)" />
        <rect x="119" y="0" width="2" height="14" fill="var(--ink)" />
      </svg>
      <span class="pl-dx vl">{{ sgnI(x.d) }}</span>
    </div>
  </div>
</template>
