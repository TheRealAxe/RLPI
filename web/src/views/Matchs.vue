<script setup lang="ts">
// Matchs : un match de la période (sélecteur, précédent / suivant). Résultat et phrase de lecture, note décomposée,
// classement de la partie, actions qui coûtent, déroulé.
import { computed, watchEffect } from "vue";
import { useRoute, useRouter } from "vue-router";
import MI from "@/components/MI.vue";
import Scope from "@/components/Scope.vue";
import Sym from "@/components/Sym.vue";
import Timeline from "@/components/Timeline.vue";
import { act1, matchSentence } from "@/copy";
import { useData, type SymKind } from "@/lib/data";
import { NB, R, clock, dC, dH, dS, pc, scoreTxt, sgn } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { keptQuery } from "@/lib/store";
import { ui } from "@/lib/ui";

const dd = useData();
const route = useRoute();
const router = useRouter();
const { go } = useNav();
const d = computed(() => dd.value!);
const PF = computed(() => d.value.PF);
const list = computed(() => PF.value?.matches ?? []);
const idx = computed(() => {
  const want = typeof route.params.match === "string" ? route.params.match : ui.match;
  const i = list.value.findIndex((x) => x.replay === want);
  return i >= 0 ? i : list.value.length - 1;
});
const m = computed(() => list.value[idx.value]);
watchEffect(() => {
  if (m.value) ui.match = m.value.replay;
  ui.ctx = m.value ? `Match du ${dC(m.value.date)} · ${dH(m.value.date)} · 3v3 classé` : "Ce match";
});

function show(replay: string) {
  router.replace({ name: "matchs", params: { match: replay }, query: keptQuery(route.query) });
}
const scoreOf = (replay: string, date: string) => d.value.V?.curves?.[replay]?.score || d.value.REC[date]?.s || "";
const curve = computed(() => (m.value ? d.value.V?.curves?.[m.value.replay] : undefined));
const score = computed(() => (m.value ? scoreOf(m.value.replay, m.value.date) : ""));

// Note décomposée : composantes par poids décroissant ; celles de poids 0 sont citées en note
const comps = computed(() => [...(PF.value?.components ?? [])].sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)));
const shownC = computed(() => comps.value.filter((c) => Math.round((c.weight ?? 0) * 100) > 0));
const zero = computed(() => comps.value.filter((c) => Math.round((c.weight ?? 0) * 100) === 0));

// Classement de la partie
const board = computed(() => {
  const x = m.value;
  if (!x) return { rows: [], full: false };
  type Row = { name: string; v: number | null | undefined; kind: SymKind; cls: string; norank?: boolean };
  const rows: Row[] = [
    { name: d.value.C.player, v: x.index, kind: "me", cls: "me" },
    ...x.mates.map((o) => ({ name: o.name, v: o.index, kind: (d.value.peerByName(o.name)?.slot ?? "other") as SymKind, cls: "mate" })),
  ];
  if (x.opps?.length) rows.push(...x.opps.map((o) => ({ name: o.name, v: o.index, kind: "none" as SymKind, cls: "opp" })));
  rows.sort((a, b) => (b.v ?? -1) - (a.v ?? -1));
  const full = !!x.opps?.length;
  if (!full) rows.push({ name: "Adv. (moy.)", v: x.opp_mean, kind: "ref", cls: "opp", norank: true });
  return { rows: rows.map((r, k) => ({ ...r, rk: r.norank ? "–" : r.kind === "me" ? String(x.rank) : full ? String(k + 1) : "–" })), full };
});

// Les actions qui coûtent dans ce match
const costly = computed(() => (curve.value ? curve.value.touches.filter((t) => (t.dv ?? 0) < 0).sort((a, b) => (a.dv ?? 0) - (b.dv ?? 0)).slice(0, 5) : []));

// Déroulé : phrase de lecture
const flow = computed(() => {
  const c = curve.value;
  if (!c) return "";
  const vals = c.v.filter((v) => v != null) as number[];
  const up = vals.filter((v) => v > 0).length / (vals.length || 1);
  const pos = c.touches.filter((t) => (t.dv ?? 0) >= 0).length,
    neg = c.touches.length - pos;
  const big = [...c.touches].sort((a, b) => (a.dv ?? 0) - (b.dv ?? 0))[0];
  return (
    `La situation a penché pour ton équipe ${pc(up)} du temps. Tes ${c.touches.length} touches : ${pos} l'ont améliorée, ${neg} l'ont dégradée` +
    (big && (big.dv ?? 0) < -0.2 ? ` (la pire : ${act1(big.a).toLowerCase()}, ${sgn(big.dv)})` : "") +
    "."
  );
});
</script>

<template>
  <section>
    <p v-if="!PF || !m" class="empty">Indice de performance indisponible pour ce profil.</p>
    <template v-else>
      <div class="picker pl-small">
        <Scope kind="m" /><span class="pl-muted" style="margin-right: auto">Parties de la période, de la plus ancienne à la plus récente.</span>
        <button type="button" class="step" aria-label="Match précédent" :disabled="idx === 0" @click="show(list[idx - 1].replay)">◂</button>
        <label>Partie
          <select class="sel" name="match" :value="m.replay" @change="show(($event.target as HTMLSelectElement).value)">
            <option v-for="x in list" :key="x.replay" :value="x.replay">
              {{ dS(x.date) }} · {{ dH(x.date) }} · {{ x.won ? "V" : "D" }} {{ scoreTxt(scoreOf(x.replay, x.date)) }} · indice {{ R(x.index) }}
            </option>
          </select>
        </label>
        <button type="button" class="step" aria-label="Match suivant" :disabled="idx === list.length - 1" @click="show(list[idx + 1].replay)">▸</button>
      </div>

      <div class="resultbar">
        <div class="pl-cut badge" :class="m.won ? 'bg-good' : 'bg-bad'">
          <span class="pl-tag">{{ m.won ? "Victoire" : "Défaite" }}{{ score ? " · " + scoreTxt(score) : "" }}</span><span class="pl-dx">{{ R(m.index) }}</span>
        </div>
        <div class="pl-cut pl-panel">
          <p class="pl-body">{{ matchSentence(PF, m) }}</p>
          <p v-if="m.prod != null" class="pl-small pl-muted" style="margin-top: 4px">Production {{ R(m.prod) }} · Fondamentaux {{ R(m.fond) }} · une note de match est volatile, surtout la production.</p>
        </div>
      </div>

      <div class="g-side-r">
        <div class="pl-panel pl-cutr carton">
          <div class="bh">
            <div class="bt"><h2 class="pl-dx pl-title">La note décomposée</h2><MI id="indice" label="La note décomposée" /><Scope kind="m" /></div>
            <span class="pl-tag pl-muted">poids · note /100</span>
          </div>
          <div v-for="c in shownC" :key="c.key" class="brow">
            <span class="lab">{{ c.label }}</span>
            <span class="pl-tag pl-muted w">{{ Math.round((c.weight ?? 0) * 100) }}{{ NB }}%</span>
            <svg width="100%" height="18" viewBox="0 0 300 18" preserveAspectRatio="none" role="img" :aria-label="`${c.label} : ${R(m.comps[c.key])} sur 100, ta moyenne ${R(PF.me?.comps[c.key])}`">
              <rect x="0" y="4" width="300" height="10" fill="var(--panel-alt)" />
              <rect x="0" y="4" :width="Math.max(1, (m.comps[c.key] ?? 0) * 3)" height="10" :fill="(m.comps[c.key] ?? 0) >= 50 ? 'var(--good)' : 'var(--bad)'" />
              <rect x="149" y="0" width="2" height="18" fill="var(--panel-ink)" />
              <template v-if="PF.me?.comps[c.key] != null">
                <path :d="`M${PF.me.comps[c.key]! * 3 - 5},0 L${PF.me.comps[c.key]! * 3 + 5},0 L${PF.me.comps[c.key]! * 3},6 Z`" fill="var(--panel-ink)" />
                <rect :x="PF.me.comps[c.key]! * 3 - 1" y="4" width="2" height="10" fill="var(--panel-ink)" opacity=".55" />
              </template>
            </svg>
            <span class="pl-dx n" :class="(m.comps[c.key] ?? 0) >= 50 ? 'pl-good' : 'pl-bad'">{{ R(m.comps[c.key]) }}</span>
          </div>
          <p class="pl-small pl-muted note">
            <template v-for="c in zero" :key="c.key">{{ c.label }} : {{ R(m.comps[c.key]) }}, poids 0{{ NB }}%. </template>
            Trait vertical : 50, la performance SSL médiane. Triangle : ta moyenne sur la période.
          </p>
        </div>
        <div>
          <div class="bt" style="margin-bottom: 4px"><h2 class="pl-tag pl-muted">Classement de la partie</h2><MI id="indice" label="Classement de la partie" /><Scope kind="m" /></div>
          <div class="board">
            <div v-for="(r, k) in board.rows" :key="k" class="pl-row" :class="r.cls">
              <span class="pl-dx rk">{{ r.rk }}</span>
              <span v-if="r.kind === 'none'" class="sym"></span><Sym v-else :kind="r.kind" />
              <span class="pl-dx nm">{{ r.name }}</span><span class="pl-dx vl">{{ R(r.v) }}</span>
            </div>
            <p v-if="board.full" class="pl-small pl-muted note">En gris : les adversaires.</p>
          </div>
          <div v-if="curve" class="costs block">
            <div class="bt" style="margin-bottom: 4px"><h2 class="pl-tag pl-muted">Les actions qui coûtent</h2><MI id="gain" label="Les actions qui coûtent" /><Scope kind="m" /></div>
            <template v-if="costly.length">
              <div v-for="(t, k) in costly" :key="k" class="pl-row pl-small">
                <span class="pl-dx">#{{ k + 1 }}</span><span>{{ t.clock != null ? clock(t.clock) : "" }}</span><span>{{ act1(t.a) }}</span>
                <span class="pl-bad" style="font-weight: 800; text-align: right">{{ sgn(t.dv) }}</span>
              </div>
            </template>
            <p v-else class="pl-small pl-muted">Aucune touche n'a dégradé la situation.</p>
            <p class="pl-small pl-muted note">Sur toute la période : onglet <button type="button" class="linkbtn" @click="go('a-travailler')">À travailler ▸</button></p>
          </div>
        </div>
      </div>

      <div v-if="curve" class="block">
        <div class="bh"><div class="bt"><h2 class="pl-dx pl-title">Le déroulé</h2><MI id="valeur" label="Le déroulé" /><Scope kind="m" /></div></div>
        <p class="pl-body read">{{ flow }}</p>
        <Timeline :c="curve" :label="flow" />
        <div class="legend pl-small pl-muted">
          <span><i class="sw" style="background: var(--good)"></i>favorable</span>
          <span><i class="sw" style="background: var(--bad)"></i>défavorable</span>
          <span><svg width="16" height="12" aria-hidden="true"><line x1="8" x2="8" y1="0" y2="12" stroke="var(--good-on-dark)" stroke-width="2" /></svg>but pour</span>
          <span><svg width="16" height="12" aria-hidden="true"><line x1="8" x2="8" y1="0" y2="12" stroke="var(--bad)" stroke-width="2" stroke-dasharray="3 2" /></svg>but contre</span>
          <span><Sym kind="me" />ta touche (pleine : gain, creuse : perte)</span>
        </div>
      </div>
    </template>
  </section>
</template>
