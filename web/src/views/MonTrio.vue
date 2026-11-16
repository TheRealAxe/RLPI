<script setup lang="ts">
// Mon trio : face-à-face avec un coéquipier (parties jouées ensemble), bilan des duels, synergie de la paire.
import { computed, nextTick, ref, watchEffect } from "vue";
import MI from "@/components/MI.vue";
import Scope from "@/components/Scope.vue";
import Sym from "@/components/Sym.vue";
import SynRow from "@/components/SynRow.vue";
import { ph, synVerdict } from "@/copy";
import { useData } from "@/lib/data";
import { NB, R, fmt, joinFr, num, sgn } from "@/lib/format";
import { ui } from "@/lib/ui";

const dd = useData();
const d = computed(() => dd.value!);
const PEERS = computed(() => d.value.PEERS);
const p = computed(() => PEERS.value[ui.peer] ?? PEERS.value[0]);
watchEffect(() => (ui.ctx = p.value ? `Face à face · ${p.value.n_shared} parties ensemble · ${p.value.wins_shared} V` : "Mon trio"));

const fv = (v: number | null, u: string) => (v == null ? "—" : u === "/100" ? R(v) : u === "/6" ? num(v, 1) : fmt(v, u));
const tape = computed(() => {
  const rows = p.value.h2h.map((r) => {
    let win: "me" | "peer" | null = null;
    if (r.sens !== 0 && r.me != null && r.peer != null && r.me !== r.peer) win = r.sens > 0 === r.me > r.peer ? "me" : "peer";
    const rel = r.me != null && r.peer != null ? Math.abs(r.me - r.peer) / (Math.max(Math.abs(r.me), Math.abs(r.peer)) || 1) : 0;
    return { ...r, win, rel };
  });
  // Intertitre « Notes des modèles » avant la première ligne issue du modèle de valeur
  let grp = false;
  const out = rows.map((r) => {
    const head = r.value && !grp;
    if (r.value) grp = true;
    return { ...r, head };
  });
  const duels = rows.filter((r) => r.sens !== 0 && r.me != null && r.peer != null);
  const mine = duels.filter((r) => r.win === "me").sort((a, b) => b.rel - a.rel),
    his = duels.filter((r) => r.win === "peer").sort((a, b) => b.rel - a.rel);
  const list = (a: typeof duels, n: number) => joinFr(a.slice(0, n).map((r) => ph(r.key, 2, r.label)));
  const sentence =
    (mine.length
      ? `Tu gagnes ${mine.length} duel${mine.length > 1 ? "s" : ""} sur ${duels.length}${mine.length > 4 ? ", dont" : " :"} ${list(mine, 4)}.`
      : `Tu ne gagnes aucun des ${duels.length} duels.`) + (his.length ? ` ${p.value.name} prend le dessus sur ${list(his, 3)}.` : "");
  return { rows: out, sentence };
});
const meI = computed(() => d.value.PF?.me?.mean);
const peI = computed(() => d.value.PF?.peers?.[p.value.id]?.mean);

const S = computed(() => d.value.C.synergy?.pairs?.[p.value.id] ?? null);
const syn = computed(() => {
  const s = S.value!;
  const good = s.rows.filter((r) => synVerdict(r)[1] === "pl-good").map((r) => r.label.toLowerCase());
  const bad = s.rows.filter((r) => synVerdict(r)[1] === "pl-bad").map((r) => r.label.toLowerCase());
  let t = `${s.n} parties ensemble, ${s.n_chains} enchaînements entre vous.`;
  if (good.length) t += ` Point fort : ${joinFr(good)}.`;
  if (bad.length) t += ` À travailler : ${joinFr(bad)}.`;
  if (!good.length && !bad.length) t += " Rien ne se détache nettement des paires SSL.";
  const me = d.value.C.player;
  return {
    text: t,
    dirs: [
      { a: me, b: p.value.name, x: s.me_to },
      { a: p.value.name, b: me, x: s.to_me },
    ],
  };
});

const seg = ref<HTMLElement | null>(null);
async function pick(i: number) {
  ui.peer = i;
  await nextTick();
  seg.value?.querySelector<HTMLElement>(`[data-i="${i}"]`)?.focus();
}
</script>

<template>
  <section>
    <p v-if="!PEERS.length" class="empty">Aucun coéquipier suivi.</p>
    <template v-else>
      <div v-if="PEERS.length > 1" ref="seg" class="seg pl-tag" role="group" aria-label="Coéquipier" style="margin-bottom: var(--space-4)">
        <button v-for="(x, i) in PEERS" :key="x.id" type="button" :data-i="i" :aria-pressed="x.id === p.id" @click="pick(i)"><Sym :kind="x.slot" /> {{ x.name }}</button>
      </div>
      <div class="bt" style="margin-bottom: var(--space-2)"><h2 class="pl-tag pl-muted">Face-à-face</h2><Scope kind="e" :n="p.n_shared" /></div>
      <div class="tape-head">
        <div class="l"><div class="pl-tag win-me">◆ Toi</div><div class="pl-dx big">{{ d.C.player }} <span class="win-me">{{ R(meI) }}</span></div></div>
        <div class="pl-dx vs">vs</div>
        <div class="r"><div class="pl-tag" :class="p.win">{{ p.slot === "mate-1" ? "●" : "■" }} Coéquipier</div><div class="pl-dx big"><span :class="p.win">{{ R(peI) }}</span> {{ p.name }}</div></div>
      </div>
      <div class="tape" role="table" :aria-label="`Face-à-face ${d.C.player} contre ${p.name}`">
        <template v-for="r in tape.rows" :key="r.key">
          <div v-if="r.head" class="grp pl-tag" role="row"><span role="cell">Notes des modèles</span></div>
          <div class="row" role="row">
            <div class="a" role="cell"><span class="pl-dx" :class="{ 'win-me': r.win === 'me' }">{{ fv(r.me, r.unit) }}</span></div>
            <div class="lab pl-tag" role="rowheader" :style="{ color: r.sens === 0 ? 'var(--ink-muted)' : 'var(--ink)' }">{{ r.label.replace(/\s*\(.*\)$/, "") }}{{ r.sens === 0 ? " · style" : "" }}</div>
            <div class="b" role="cell"><span class="pl-dx" :class="r.win === 'peer' ? p.win : ''">{{ fv(r.peer, r.unit) }}</span></div>
          </div>
        </template>
      </div>
      <p class="pl-body read" style="margin-top: var(--space-4)">{{ tape.sentence }}</p>
      <p class="pl-small pl-muted">
        Uniquement les {{ p.n_shared }} parties jouées dans la même équipe : mêmes adversaires, mêmes conditions. La valeur gagnante prend la couleur de son joueur ; une ligne « style » n'a pas de gagnant.
        <MI id="centile" label="Face-à-face" />
      </p>

      <div v-if="S" class="block">
        <div class="bt"><h2 class="pl-dx h44">Notre synergie</h2><MI id="synergie" label="Synergie" /><Scope kind="e" :n="S.n" /></div>
        <p class="pl-body read">{{ syn.text }}</p>
        <h3 class="grph pl-tag"><span>Votre paire · bande 80{{ NB }}% · trait = SSL · rond = toi + inconnu</span><span>valeur · verdict</span></h3>
        <SynRow v-for="r in S.rows" :key="r.key" :r="r" :peer="p" :player="d.C.player" />
        <h3 class="grph pl-tag"><span>Qui sert qui</span><span>touches reprises · bonus</span></h3>
        <div class="syn-dir" role="table" aria-label="Qui sert qui">
          <div v-for="x in syn.dirs" :key="x.a" class="row" role="row">
            <div class="lab pl-tag" role="rowheader">{{ x.a }} → {{ x.b }}</div>
            <div role="cell" class="pl-dx">{{ num(x.x.sert ?? 0, 1) }}{{ NB }}%</div>
            <div role="cell" class="pl-dx" :class="{ 'pl-bad': (x.x.bonus ?? 0) < 0 }">{{ sgn(x.x.bonus, 1) }}</div>
            <div role="cell" class="pl-small pl-muted">{{ x.x.n }} enchaînements</div>
          </div>
        </div>
        <p class="pl-small pl-muted">
          <template v-if="d.C.synergy?.n_random">« Toi + inconnu » : tes {{ d.C.synergy.n_random }} parties retenues avec un coéquipier non suivi. </template>Le sens « qui sert qui » repose sur peu d'enchaînements : c'est une tendance.
        </p>
      </div>
    </template>
  </section>
</template>
