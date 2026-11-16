<script setup lang="ts">
// Tous les indicateurs : notés (centile face à la référence, du meilleur au moins bon), notes des modèles, style
// (position parmi les joueurs de la référence), technique (face aux SSL). Une ligne choisie montre son évolution.
import { computed, nextTick, ref, watchEffect } from "vue";
import AllRow, { type PeerMark } from "@/components/AllRow.vue";
import EvoChart, { type EvoPoint } from "@/components/EvoChart.vue";
import MI from "@/components/MI.vue";
import Scope from "@/components/Scope.vue";
import Sym from "@/components/Sym.vue";
import type { Metric, TechRow } from "@/api/client";
import { useData } from "@/lib/data";
import { NB, R, fmt, num } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { ui } from "@/lib/ui";

const dd = useData();
const { go } = useNav();
const d = computed(() => dd.value!);
const V = computed(() => d.value.V);
const L = computed(() => d.value.refLabel);
watchEffect(() => (ui.ctx = d.value ? `Tous les indicateurs · ${d.value.C.n_matches} parties · face aux ${L.value}` : ""));

interface ModelKey {
  key: "lobby_note" | "lobby_rank" | "plc_note" | "dec_note";
  label: string;
  unit: string;
  ref: number;
  lo: number;
  hi: number;
  invert?: boolean;
  refl: string;
}
const MODEL_KEYS = computed<ModelKey[]>(() =>
  V.value
    ? [
        { key: "lobby_note", label: "Résultat de tes touches", unit: "/100", ref: 50, lo: 0, hi: 100, refl: "médiane des lobbies" },
        { key: "lobby_rank", label: "Rang dans la partie", unit: "/6", ref: 3.5, lo: 1, hi: 6, invert: true, refl: "milieu (3,5)" },
        ...(V.value.plc ? [{ key: "plc_note", label: "Placement hors ballon", unit: "/100", ref: 50, lo: 0, hi: 100, refl: "pro médian" } as ModelKey] : []),
        ...(V.value.dec ? [{ key: "dec_note", label: "Choix à la touche (expérimental)", unit: "/100", ref: 50, lo: 0, hi: 100, refl: "pro médian" } as ModelKey] : []),
      ]
    : [],
);
const metrics = computed(() => d.value.D?.metrics ?? []);
const ranked = computed(() => metrics.value.filter((m) => m.sens !== 0 && m.note != null).sort((a, b) => (b.note ?? 0) - (a.note ?? 0)));
const style = computed(() => metrics.value.filter((m) => m.sens === 0));
const tech = computed(() => d.value.C.tech?.rows ?? []);
const evoKey = computed(() => ui.evo ?? MODEL_KEYS.value[0]?.key ?? ranked.value[0]?.key ?? null);

const scoredMarks = (m: Metric): PeerMark[] =>
  d.value.PEERS.flatMap((p) => {
    const pm = m.peers?.[p.id];
    return pm?.note == null ? [] : [{ slot: p.slot, v: pm.note, tip: [[{ b: p.name }, ` : ${fmt(pm.value, m.unit)} · mieux que ${R(pm.note)}${NB}%`]] }];
  });
/** Position d'une valeur de technique dans la distribution SSL (approximation par les quartiles connus). */
function pctOf(v: number, t: TechRow): number {
  const q = t.ssl_q;
  if (!q || q.length < 4 || q.some((x) => x == null)) return 50;
  const pts: [number, number][] = [
    [q[0]!, 10],
    [q[1]!, 25],
    [t.ssl ?? 0, 50],
    [q[2]!, 75],
    [q[3]!, 90],
  ];
  if (v <= pts[0][0]) return 5;
  if (v >= pts[4][0]) return 95;
  for (let i = 0; i < 4; i++) {
    const [a, pa] = pts[i],
      [b, pb] = pts[i + 1];
    if (v >= a && v <= b) return pa + ((v - a) / (b - a || 1)) * (pb - pa);
  }
  return 50;
}
const techNote = (t: TechRow) => (t.sens > 0 ? t.pct_ssl : 100 - (t.pct_ssl ?? 0));
const techMarks = (t: TechRow): PeerMark[] =>
  d.value.PEERS.flatMap((p) => {
    const v = t.peers?.[p.id];
    return v == null ? [] : [{ slot: p.slot, v: t.sens > 0 ? pctOf(v, t) : 100 - pctOf(v, t), tip: [[{ b: p.name }, ` : ${fmt(v, t.unit)}`]] }];
  });
const modelValue = (k: ModelKey) => {
  const v = V.value!;
  return k.key === "lobby_rank" ? null : k.key === "lobby_note" ? v.me_lobby_note : k.key === "plc_note" ? v.plc?.me_note : v.dec?.me_note;
};

// Évolution de l'indicateur choisi
const evo = computed(() => {
  const key = evoKey.value;
  if (!key) return null;
  const model = MODEL_KEYS.value.find((k) => k.key === key);
  let pts: EvoPoint[], unit: string, lo: number, hi: number, refv: number | null, refl: string, invert: boolean, label: string;
  if (model) {
    pts = V.value!.matches.map((m) => ({ d: m.date, v: m[model.key] ?? null }));
    ({ unit, label, lo, hi, refl } = model);
    refv = model.ref;
    invert = !!model.invert;
  } else {
    const m = d.value.M[key];
    if (!m) return null;
    label = m.label;
    unit = m.unit;
    pts = m.matches.map((x) => ({ d: x.d, v: x.v }));
    refv = m.ref_med;
    refl = `médiane ${L.value}`;
    const vals = [...pts.map((p) => p.v), refv].filter((v) => v != null) as number[];
    lo = Math.min(...vals);
    hi = Math.max(...vals);
    const pad = (hi - lo) * 0.12 || 1;
    lo -= pad;
    hi += pad;
    if (unit.startsWith("%")) lo = Math.max(0, lo);
    invert = m.sens < 0;
  }
  pts = pts.map((p) => ({ ...p, w: d.value.REC[p.d]?.w, replay: d.value.replayOfDate(p.d) }));
  const ok = pts.filter((p) => p.v != null) as (EvoPoint & { v: number })[];
  const half = Math.ceil(ok.length / 2);
  const avg = (a: { v: number }[]) => a.reduce((s, p) => s + p.v, 0) / (a.length || 1);
  const fv = (v: number | null) => (model ? (unit === "/6" ? (v == null ? "—" : num(v, 1)) : R(v)) : fmt(v, unit));
  const trend = ok.length >= 4 ? `Moyenne de ta première moitié de parties : ${fv(avg(ok.slice(0, half)))} ; de la seconde : ${fv(avg(ok.slice(half)))}.` : "";
  return { pts, lo, hi, refv, refl, invert, label, fv, trend };
});

const evoBlock = ref<HTMLElement | null>(null);
async function pick(key: string) {
  ui.evo = key;
  await nextTick();
  evoBlock.value?.scrollIntoView({ block: "nearest" });
}
</script>

<template>
  <section>
    <button type="button" class="back pl-tag" @click="go('mon-jeu')">◂ Mon jeu</button>
    <div class="bt"><h2 class="pl-dx h44">Tous les indicateurs</h2><MI id="centile" label="Tous les indicateurs" /><Scope kind="p" /></div>
    <p class="pl-body read">
      {{ ranked.length }} indicateurs notés face aux {{ L }}, du meilleur au moins bon : {{ ranked.filter((m) => (m.note ?? 0) >= 50).length }} au-dessus de la médiane. Choisis une ligne pour voir son évolution match par match.
    </p>
    <div ref="evoBlock" class="block">
      <template v-if="evo">
        <div class="bh">
          <h3 class="pl-dx pl-title">{{ evo.label }} · match par match</h3><Scope kind="p" />
          <span class="pl-tag pl-muted">{{ evo.invert ? "plus bas = mieux · courbe retournée" : "" }}</span>
        </div>
        <p class="pl-body read">{{ evo.trend }} Trait gris : {{ evo.refl }} ({{ evo.fv(evo.refv) }}).</p>
        <EvoChart :pts="evo.pts" :lo="evo.lo" :hi="evo.hi" :refv="evo.refv" :invert="evo.invert" :label="evo.label" :summary="evo.trend" :fv="evo.fv" />
        <div class="legend pl-small pl-muted">
          <span><Sym kind="me" />un match (V/D sous le point)</span>
          <span><svg width="22" height="10" aria-hidden="true"><line x1="1" x2="21" y1="5" y2="5" stroke="var(--me)" stroke-width="3" /></svg>moyenne sur 5 parties</span>
          <span><Sym kind="ref" />{{ evo.refl }}</span>
        </div>
      </template>
    </div>

    <h3 class="grph pl-tag"><span>Notés · centile face aux {{ L }}</span><span>note · valeur</span></h3>
    <AllRow
      v-for="m in ranked"
      :key="m.key"
      :label="m.label"
      :sub="m.sens > 0 ? 'plus haut = mieux' : 'plus bas = mieux'"
      :note="m.note"
      :val="fmt(m.value, m.unit)"
      :peers="d.PEERS"
      :marks="scoredMarks(m)"
      :pressed="m.key === evoKey"
      @pick="pick(m.key)"
    />
    <template v-if="MODEL_KEYS.length">
      <h3 class="grph pl-tag"><span>Notes des modèles</span><span>note</span></h3>
      <AllRow
        v-for="k in MODEL_KEYS"
        :key="k.key"
        :label="k.label"
        :sub="k.key === 'lobby_rank' ? '1 = meilleur des 6' : k.key === 'lobby_note' ? 'face à tes lobbies' : 'face aux pros RLCS'"
        :note="modelValue(k)"
        :val="k.key === 'lobby_rank' ? fmt(V!.me_lobby_rank, '/6') : ''"
        :peers="d.PEERS"
        :pressed="k.key === evoKey"
        @pick="pick(k.key)"
      />
    </template>
    <h3 class="grph pl-tag"><span>Style · pas de bon sens</span><span>toi · médiane {{ L }}</span></h3>
    <AllRow
      v-for="m in style"
      :key="m.key"
      :label="m.label"
      :sub="m.unit"
      :note="null"
      :val="`${fmt(m.value, m.unit)} · ${fmt(m.ref_med, m.unit)}`"
      :style-metric="m"
      :peers="d.PEERS"
      :pressed="m.key === evoKey"
      @pick="pick(m.key)"
    />
    <template v-if="tech.length">
      <h3 class="grph pl-tag"><span>Technique · face aux SSL</span><span>note · valeur</span></h3>
      <AllRow v-for="t in tech" :key="t.key" :label="t.label" :sub="t.def" :note="techNote(t)" :val="fmt(t.me, t.unit)" :peers="d.PEERS" :marks="techMarks(t)" :pressed="null" />
    </template>
    <div class="legend pl-small pl-muted">
      <Sym kind="me" /><span>toi</span>
      <span v-for="p in d.PEERS" :key="p.id"><Sym :kind="p.slot" />{{ p.name }}</span>
      <span>Barre : centile (trait à 50). Ligne de style : position entre les joueurs {{ L }} (trait : médiane).</span>
    </div>
  </section>
</template>
