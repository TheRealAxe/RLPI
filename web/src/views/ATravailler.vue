<script setup lang="ts">
// À travailler : les touches les plus coûteuses de la période (horloge de jeu, fiches ralenti, suivantes) et le
// gain moyen par type de touche face aux pros.
import { computed, watchEffect } from "vue";
import ClockLine from "@/components/ClockLine.vue";
import GainRow from "@/components/GainRow.vue";
import MI from "@/components/MI.vue";
import Scope from "@/components/Scope.vue";
import Sym from "@/components/Sym.vue";
import { act1 } from "@/copy";
import { useData } from "@/lib/data";
import { MINUS, clock, dS, sgn } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { ui } from "@/lib/ui";

const dd = useData();
const { openMatch } = useNav();
const d = computed(() => dd.value!);
watchEffect(() => (ui.ctx = d.value ? `À travailler · ${d.value.C.n_matches} parties` : ""));

const V = computed(() => d.value.V);
const worst = computed(() => V.value?.worst ?? []);
const top = computed(() => worst.value.slice(0, 3));
const rest = computed(() => worst.value.slice(3));
const sx = (v: number | null) => (((v ?? 0) + 1) / 2) * 220;

const gains = computed(() => {
  const A = V.value?.by_action ?? [];
  if (!A.length) return null;
  const gap = (a: (typeof A)[number]) => (a.me ?? 0) - (a.ref ?? 0);
  const best = [...A].sort((a, b) => gap(b) - gap(a))[0],
    worstA = [...A].sort((a, b) => gap(a) - gap(b))[0];
  const vals = A.flatMap((a) => [a.me ?? 0, a.ref ?? 0]);
  return { A, best, worst: worstA, lo: Math.min(0, ...vals) * 1.1, hi: Math.max(0, ...vals) * 1.1 };
});
</script>

<template>
  <section>
    <p v-if="!V" class="empty">Modèle de valeur indisponible.</p>
    <template v-else>
      <div class="bt"><h2 class="pl-dx h44">Les actions qui coûtent</h2><MI id="gain" label="Les actions qui coûtent" /><Scope kind="p" /></div>
      <p class="pl-body pl-muted read">
        Tes {{ worst.length }} touches les plus coûteuses, placées sur l'horloge de jeu (5:00 → 0:00, temps restant). Plus la barre est haute, plus la touche a coûté.
      </p>
      <ClockLine v-if="worst.length" :touches="worst" />
      <div class="fiches">
        <div v-for="(t, k) in top" :key="k" class="pl-panel pl-cutr fiche">
          <div class="top2"><span class="pl-tag pl-muted">Ralenti #{{ k + 1 }} · {{ dS(t.date) }}</span><span class="pl-dx clk">{{ clock(t.clock) }}</span></div>
          <div class="pl-dx kind">{{ act1(t.action) }}</div>
          <div class="pl-dx cost">{{ sgn(t.dv) }}</div>
          <svg width="100%" height="36" viewBox="0 0 220 36" style="margin-top: 6px; max-width: 220px" role="img" :aria-label="`Situation avant ${sgn(t.vb)}, après ${sgn(t.va)}`">
            <rect x="0" y="12" width="220" height="10" fill="var(--panel-alt)" />
            <line x1="110" x2="110" y1="6" y2="28" stroke="var(--panel-ink)" />
            <rect :x="Math.min(sx(t.vb), sx(t.va))" y="12" :width="Math.abs(sx(t.va) - sx(t.vb))" height="10" fill="var(--bad)" />
            <circle :cx="sx(t.vb)" cy="17" r="5" fill="var(--panel)" stroke="var(--panel-ink)" stroke-width="2" />
            <circle :cx="sx(t.va)" cy="17" r="5" fill="var(--panel-ink)" />
            <text x="0" y="36">{{ MINUS }}1</text><text x="220" y="36" text-anchor="end">+1</text>
          </svg>
          <div class="pl-small pl-muted">Situation {{ sgn(t.vb) }} → {{ sgn(t.va) }}</div>
          <button type="button" class="pl-tag open" @click="openMatch(t.replay)">Ouvrir le match ▸</button>
        </div>
      </div>
      <div v-if="rest.length" class="block others">
        <h3 class="pl-tag pl-muted" style="margin-bottom: 4px">Les {{ rest.length }} suivantes</h3>
        <button v-for="(t, k) in rest" :key="k" type="button" class="pl-row pl-small" @click="openMatch(t.replay)">
          <span class="pl-dx" style="font-size: var(--dx-22)">#{{ k + 4 }}</span><span>{{ dS(t.date) }}</span>
          <span class="hide-s">{{ clock(t.clock) }}</span><span>{{ act1(t.action) }}</span>
          <span class="hide-s pl-muted">{{ sgn(t.vb) }} → {{ sgn(t.va) }}</span>
          <span class="pl-bad" style="text-align: right; font-weight: 800">{{ sgn(t.dv) }}</span>
        </button>
      </div>

      <div v-if="gains" class="block">
        <div class="bt"><h2 class="pl-dx pl-title">Gain moyen par type de touche</h2><MI id="gain" label="Gain moyen par type de touche" /><Scope kind="p" /></div>
        <p class="pl-body read">
          Tes {{ gains.best.label.toLowerCase() }} rapportent plus que chez les pros ({{ sgn(gains.best.me, 3) }} contre {{ sgn(gains.best.ref, 3) }}) ; tes
          {{ gains.worst.label.toLowerCase() }} rapportent moins ({{ sgn(gains.worst.me, 3) }} contre {{ sgn(gains.worst.ref, 3) }}).
        </p>
        <GainRow v-for="a in gains.A" :key="a.label" :a="a" :lo="gains.lo" :hi="gains.hi" :player="d.C.player" />
        <div class="legend pl-small pl-muted">
          <span><Sym kind="me" />toi</span><span><Sym kind="ref" />pros RLCS</span>
          <span>Trait : 0. En classé les tirs rapportent plus (défenses plus faibles) : l'écart avec les pros n'est pas une note.</span>
        </div>
      </div>
    </template>
  </section>
</template>
