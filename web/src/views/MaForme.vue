<script setup lang="ts">
// Ma forme : indice de performance (bandeau de score), indice du trio et des lobbies, forme match par match,
// repères, et le dernier match à revoir.
import { computed, watchEffect } from "vue";
import MI from "@/components/MI.vue";
import Scope from "@/components/Scope.vue";
import Sym from "@/components/Sym.vue";
import { matchSentence, verdictG } from "@/copy";
import { useData, type SymKind } from "@/lib/data";
import { NB, R, dL, dS, num, pc } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { ui } from "@/lib/ui";

const dd = useData();
const { openMatch } = useNav();
const d = computed(() => dd.value!);

watchEffect(() => (ui.ctx = d.value ? `Profil · ${d.value.C.n_matches} parties classées 3v3 · ${d.value.period}` : ""));

const PF = computed(() => d.value.PF);
const me = computed(() => PF.value?.me ?? null);
const matches = computed(() => PF.value?.matches ?? []);
const wins = computed(() => matches.value.filter((m) => m.won).length);
const n50 = computed(() => matches.value.filter((m) => (m.index ?? 0) >= 50).length);
const last = computed(() => matches.value[matches.value.length - 1]);
const trio = computed(() => {
  const pf = PF.value;
  if (!pf) return [];
  const rows: { name: string; kind: SymKind; v: number | null | undefined }[] = [
    ...d.value.PEERS.map((p) => ({ name: p.name, kind: p.slot as SymKind, v: pf.peers[p.id]?.mean })),
    { name: "Lobbies", kind: "ref", v: pf.lobby?.mean },
  ];
  return rows.filter((r) => r.v != null);
});
const retest = computed(() => PF.value?.validation?.retest);

// Repères : cinq cartons, comparaison aux coéquipiers avec leurs symboles
interface PeerLine {
  slot: SymKind;
  name: string;
  v: string;
}
interface Kpi {
  k: string;
  m: string;
  v: string;
  u: string;
  s: string;
  c: PeerLine[];
}
const kpis = computed<Kpi[]>(() => {
  const { C, V, PS, PEERS } = d.value;
  const T: Kpi[] = [];
  const peerLine = (f: (p: (typeof PEERS)[number]) => string | null): PeerLine[] =>
    PEERS.flatMap((p) => {
      const x = f(p);
      return x == null ? [] : [{ slot: p.slot, name: p.name, v: x }];
    });
  T.push({ k: "Victoires", m: "centile", v: String(Math.round((C.wins / C.n_matches) * 100)), u: `${NB}%`, s: `${C.wins} V · ${C.n_matches - C.wins} D`, c: [] });
  if (V) {
    T.push({
      k: "Rang dans la partie",
      m: "resultat",
      v: V.me_lobby_rank == null ? "—" : num(V.me_lobby_rank, 1),
      u: `${NB}/ 6`,
      s: "face à tes lobbies · 1 = meilleur des 6",
      c: peerLine((p) => (p.value?.lobby_rank == null ? null : num(p.value.lobby_rank, 1))),
    });
    if (V.plc)
      T.push({
        k: "Placement hors ballon",
        m: "placement",
        v: R(V.plc.me_note),
        u: "/100",
        s: `face aux pros RLCS · lobbies ${R(V.plc.lobby_note)}`,
        c: peerLine((p) => (p.value?.plc_note == null ? null : R(p.value.plc_note))),
      });
    T.push({
      k: "Résultat de tes touches",
      m: "resultat",
      v: R(V.me_lobby_note),
      u: "/100",
      s: "face à tes lobbies · 50 = médian",
      c: peerLine((p) => (p.value?.lobby_note == null ? null : R(p.value.lobby_note))),
    });
  }
  if (PS) {
    const g = PS.groups,
      mine = g.find((x) => x.key === "me"),
      lob = g.find((x) => x.key === "lobby");
    if (mine)
      T.push({
        k: "Passes récupérées",
        m: "passes",
        v: String(Math.round((mine.recovered ?? 0) * 100)),
        u: `${NB}%`,
        s: `lobbies ${pc(lob?.recovered)}`,
        c: peerLine((p) => {
          const x = g.find((y) => y.key === p.id);
          return x ? pc(x.recovered) : null;
        }),
      });
  }
  return T;
});
</script>

<template>
  <section>
    <p v-if="!PF || !me" class="empty">Indice de performance indisponible pour ce profil.</p>
    <template v-else>
      <div class="g-side">
        <div class="pl-panel pl-cutr scorebug">
          <div class="bt"><h2 class="pl-tag pl-muted">Indice de performance</h2><MI id="indice" label="Indice de performance" /><Scope kind="p" /></div>
          <div class="big"><span class="pl-dx pl-score-xl">{{ R(me.mean) }}</span><span class="pl-dx of">/100</span></div>
          <p class="pl-body" style="margin-top: 6px">
            {{ verdictG(me.mean) }} (50).<br />Moyenne de tes matchs · fourchette {{ R(me.lo) }}–{{ R(me.hi) }} · 5 dernières : {{ R(me.last5) }}.
          </p>
          <p v-if="me.prod != null" class="pl-body" style="margin-top: 6px">Production <b>{{ R(me.prod) }}</b> · Fondamentaux <b>{{ R(me.fond) }}</b></p>
          <p v-if="retest?.index && retest?.fond" class="pl-small pl-muted" style="margin-top: 4px">
            Moyenne fiable vers {{ retest.index.matches_for_08 }} parties (fondamentaux : {{ retest.fond.matches_for_08 }}). Tu en as {{ me.n }}.
          </p>
        </div>
        <div>
          <div class="trio">
            <div class="bt" style="margin-bottom: 6px"><h2 class="pl-tag pl-muted">Indice de ton trio et de tes lobbies</h2><Scope kind="p" /></div>
            <div v-for="r in trio" :key="r.name + r.kind" class="pl-row"><Sym :kind="r.kind" /><span class="pl-dx nm">{{ r.name }}</span><span class="pl-dx vl">{{ R(r.v) }}</span></div>
          </div>
          <div class="formhead">
            <div class="bt"><h2 class="pl-tag pl-muted">Forme · match par match</h2><Scope kind="p" /></div>
            <span class="pl-tag">{{ wins }} V · {{ matches.length - wins }} D · <span class="pl-good">{{ n50 }} au-dessus de 50</span></span>
          </div>
          <div class="formgrid" role="list" aria-label="Indice match par match, du plus ancien au plus récent">
            <button
              v-for="(m, i) in matches"
              :key="m.replay"
              type="button"
              class="formcell"
              role="listitem"
              :aria-label="`${dL(m.date)}, ${m.won ? 'victoire' : 'défaite'}, indice ${R(m.index)}. Ouvrir ce match.`"
              @click="openMatch(m.replay)"
            >
              <span class="pl-cut pl-form" :class="[(m.index ?? 0) >= 50 ? 'pl-form--up' : 'pl-form--down', { 'pl-form--current': i === matches.length - 1 }]">
                <span class="pl-tag" style="display: block">{{ m.won ? "V" : "D" }}</span><span class="pl-dx" style="display: block">{{ R(m.index) }}</span>
              </span>
            </button>
          </div>
          <p class="pl-small pl-muted note">Bleu : indice d'au moins 50 · orange : en dessous. Du plus ancien au plus récent, le cadre marque le dernier match. Clique sur une case pour ouvrir le match.</p>
        </div>
      </div>

      <div class="bt block" style="margin-bottom: var(--space-2)"><h2 class="pl-tag pl-muted">Repères</h2><Scope kind="p" /></div>
      <div class="kpis">
        <div v-for="t in kpis" :key="t.k" class="pl-panel pl-cutr kpi">
          <div class="bt"><h3 class="pl-tag pl-muted">{{ t.k }}</h3><MI :id="t.m" :label="t.k" /></div>
          <div class="pl-dx pl-score v">{{ t.v }}<small>{{ t.u }}</small></div>
          <div class="pl-small pl-muted">{{ t.s }}</div>
          <div v-if="t.c.length" class="cmp">
            <span v-for="c in t.c" :key="c.name" class="pl-small"><Sym :kind="c.slot" in-panel />{{ c.name }} {{ c.v }}</span>
          </div>
        </div>
      </div>

      <div v-if="last" class="review">
        <div class="pl-cut pl-tag pl-volt">À revoir</div>
        <div class="pl-cut pl-panel">
          <span class="pl-dx when">Dernier match · {{ dS(last.date) }} · {{ last.won ? "Victoire" : "Défaite" }}</span>
          <span class="pl-dx pl-score" :style="{ color: (last.index ?? 0) >= 50 ? 'var(--good)' : 'var(--bad-ink)' }">{{ R(last.index) }}</span>
          <span class="pl-body txt">{{ matchSentence(PF, last, false) }}</span>
          <button type="button" class="pl-tag go" @click="openMatch(last.replay)">Voir le match ▸</button>
        </div>
      </div>
    </template>
  </section>
</template>
