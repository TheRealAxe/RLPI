<script setup lang="ts">
// Mon jeu : style de jeu, conseils, progression, Top 3 / Flop 3 face à la référence, écarts de style, carte du
// terrain, notes des modèles, balles données. Lien vers « Tous les indicateurs ».
import { computed, watchEffect } from "vue";
import MI from "@/components/MI.vue";
import Scope from "@/components/Scope.vue";
import Advice from "@/components/jeu/Advice.vue";
import ModelScores from "@/components/jeu/ModelScores.vue";
import PassOutcomes from "@/components/jeu/PassOutcomes.vue";
import ProgressBlock from "@/components/jeu/ProgressBlock.vue";
import StyleGaps from "@/components/jeu/StyleGaps.vue";
import StyleHero from "@/components/jeu/StyleHero.vue";
import TerrainMap from "@/components/jeu/TerrainMap.vue";
import { cap, ph } from "@/copy";
import { useData } from "@/lib/data";
import { NB, R, fmt } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { ui } from "@/lib/ui";

const dd = useData();
const { go } = useNav();
const d = computed(() => dd.value!);
watchEffect(() => (ui.ctx = d.value ? `Mon jeu · ${d.value.C.n_matches} parties · face aux ${d.value.refLabel}` : ""));

/** Indicateurs notés (hors style), du meilleur au moins bon. */
const ranked = computed(() => (d.value.D?.metrics ?? []).filter((m) => m.sens !== 0 && m.note != null).sort((a, b) => (b.note ?? 0) - (a.note ?? 0)));
const top = computed(() => ranked.value.slice(0, 3));
const flop = computed(() => ranked.value.slice(-3).reverse());
const lead = computed(() => {
  const t = top.value,
    w = flop.value[0],
    L = d.value.refLabel;
  if (t.length < 2 || !w) return "";
  return `${cap(ph(t[0].key, 0, t[0].label))} et ${ph(t[1].key, 0, t[1].label)}. Ton chantier : ${ph(w.key, 1, w.label)}${(w.note ?? 0) < 25 ? `, dans le dernier quart des ${L}` : ""}.`;
});
</script>

<template>
  <section>
    <StyleHero :d="d" />
    <div class="g-2" style="margin-bottom: var(--space-8)">
      <Advice :d="d" />
      <ProgressBlock :d="d" />
    </div>
    <p v-if="lead" class="lead">{{ lead }}</p>
    <div class="g-2">
      <div>
        <div class="bt" style="margin-bottom: 6px"><h2 class="pl-tag pl-muted">Face aux {{ d.refLabel }}</h2><Scope kind="p" /></div>
        <template v-for="(grp, gi) in [{ name: 'Top 3', cls: 'bg-good', rows: top }, { name: 'Flop 3', cls: 'bg-bad', rows: flop }]" :key="grp.name">
          <div class="pl-cut pl-tag chip" :class="grp.cls" :style="gi ? { marginTop: '18px' } : undefined">{{ grp.name }}</div>
          <div v-for="m in grp.rows" :key="m.key" class="tf">
            <div>
              <div class="l"><b>{{ m.label }}</b><span class="pl-small pl-muted">{{ fmt(m.value, m.unit) }}</span></div>
              <svg width="100%" height="12" viewBox="0 0 300 12" preserveAspectRatio="none" style="margin-top: 5px" role="img" :aria-label="`${m.label} : mieux que ${R(m.note)} % des ${d.refLabel}`">
                <rect width="300" height="8" y="2" fill="var(--surface-alt)" />
                <rect :width="Math.max(2, (m.note ?? 0) * 3)" height="8" y="2" :fill="(m.note ?? 0) >= 50 ? 'var(--good)' : 'var(--bad)'" />
                <rect x="149" width="2" height="12" fill="var(--ink-muted)" />
              </svg>
            </div>
            <span class="pl-dx vl" :class="{ 'pl-bad': (m.note ?? 0) < 50 }">{{ R(m.note) }}</span>
          </div>
        </template>
        <p class="pl-small pl-muted note">
          Centile face aux {{ d.refLabel }} (mieux que x{{ NB }}%) ; trait : 50. <MI id="centile" label="Centiles" />
          <button type="button" class="linkbtn" @click="go('indicateurs')">Les {{ ranked.length }} indicateurs ▸</button>
        </p>
      </div>
      <div>
        <StyleGaps :d="d" />
        <TerrainMap :d="d" />
      </div>
    </div>
    <div class="g-2 block">
      <ModelScores :d="d" />
      <PassOutcomes :d="d" />
    </div>
  </section>
</template>
