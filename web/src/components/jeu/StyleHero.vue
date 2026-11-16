<script setup lang="ts">
// Ton style de jeu : familles de comportements trouvées chez 401 joueurs SSL et RLCS. Style principal, signature,
// pros au style le plus proche, affinité avec chaque style, styles des coéquipiers.
import { computed } from "vue";
import MI from "../MI.vue";
import Scope from "../Scope.vue";
import Sym from "../Sym.vue";
import type { Derived } from "@/lib/data";
import { R, cap } from "@/lib/format";

const props = defineProps<{ d: Derived }>();
const S = computed(() => props.d.C.style);
const P = computed(() => S.value?.me ?? null);
const v = computed(() => {
  const s = S.value!,
    p = P.value!;
  const st = s.styles,
    main = st[p.main],
    sec = p.second != null ? st[p.second] : null,
    team = s.team.map((j) => st[j]);
  const order = st.map((x, j) => ({ ...x, j, p: p.pct[j] ?? 0 })).sort((a, b) => b.p - a.p);
  const peers = props.d.PEERS.map((pe) => ({ pe, pr: s.peers?.[pe.id] ?? null }));
  let tag = p.polyvalent ? "Aucune famille ne ressort nettement : tu t'adaptes à la partie." : main.tagline;
  if (team.length) tag += ` Comme tout ton trio, tu joues ${team[0].name === "Harceleur" ? "haut, dans le camp adverse" : team[0].tagline.toLowerCase()}.`;
  return { st, main, sec, team, order, peers, tag };
});
const words = (p: number | null) => {
  const x = p ?? 50;
  const k = Math.min(9, Math.max(5, Math.round(Math.max(x, 100 - x) / 10)));
  return `plus marqué que ${k} joueurs sur 10`;
};
</script>

<template>
  <template v-if="S">
    <p v-if="!P" class="empty">Il faut au moins 5 parties pour définir ton style de jeu.</p>
    <div v-else class="hero">
      <div class="pl-panel pl-cutr id">
        <div class="kick">
          <span class="pl-tag pl-muted">Ton style de jeu</span><MI id="styles" label="Styles de jeu" /><Scope kind="p" />
          <span v-if="v.team.length" class="pl-cut pl-tag pl-volt" style="padding: 3px 14px">Trio · {{ v.team.map((t) => t.name).join(" · ") }}</span>
        </div>
        <div class="pl-dx nm">{{ P.polyvalent ? "Polyvalent" : v.main.name }}</div>
        <div v-if="v.sec" class="pl-dx sub">{{ P.polyvalent ? `penchant ${v.main.name}` : `teinté ${v.sec.name}` }}</div>
        <p class="pl-body tag">{{ v.tag }}</p>
        <ul>
          <li v-for="(x, i) in P.signature" :key="i"><span class="pl-body">{{ cap(x.txt) }}</span><span class="pl-small q">{{ words(x.pct) }}</span></li>
        </ul>
        <p class="pl-small pl-muted" style="margin-top: 10px">Ce style ressort dans {{ P.regular }} de tes {{ P.n }} parties. Comparé aux autres joueurs de chaque partie, pas à leur niveau.</p>
      </div>
      <div class="side">
        <h2 class="pl-tag pl-muted">Tu joues comme</h2>
        <div class="like">
          <template v-for="(x, i) in P.like.slice(0, 2)" :key="x.name"><span v-if="i" class="pl-muted"> · </span><b>{{ x.name }}</b></template>
        </div>
        <p class="pl-small pl-muted">Pros RLCS au style le plus proche du tien (pas au niveau).</p>
        <div class="spec" role="list" aria-label="Affinité avec chaque style">
          <div v-for="x in v.order" :key="x.j" class="r" :class="{ main: x.j === P.main, team: S.team.includes(x.j), dim: (x.retest ?? 1) < 0.5 }" role="listitem">
            <span class="pl-tag">{{ x.name }}</span><span class="bar"><i :style="{ width: Math.max(2, x.p) + '%' }"></i></span><span class="pl-small">{{ R(x.p) }}</span>
          </div>
        </div>
        <p class="pl-small pl-muted" style="margin-top: 6px">Affinité : part des joueurs de référence moins marqués que toi dans ce style. Pâle : style peu stable d'un match à l'autre.</p>
        <div v-if="v.peers.length" class="trio-st">
          <div v-for="{ pe, pr } in v.peers" :key="pe.id" class="pl-row" style="padding: 4px 0">
            <Sym :kind="pe.slot" /><span class="pl-tag">{{ pe.name }}</span>
            <span class="pl-small">{{ pr ? v.st[pr.main].name + (pr.second != null ? ` · ${v.st[pr.second].name}` : "") : "pas assez de parties" }}</span>
          </div>
        </div>
      </div>
    </div>
  </template>
</template>
