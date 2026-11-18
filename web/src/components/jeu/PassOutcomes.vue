<script setup lang="ts">
// Que deviennent tes balles données ? Une barre empilée par joueur et référence (récupérée ou perdue, avec ou sans
// coéquipier placé), et les passes dans le vide les plus coûteuses.
import { computed } from "vue";
import MI from "../MI.vue";
import Scope from "../Scope.vue";
import Sym from "../Sym.vue";
import type { Derived, SymKind } from "@/lib/data";
import { NB, clock, dS, num, pc, sgn } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { hideTip, showTip } from "@/lib/tip";

const props = defineProps<{ d: Derived }>();
const { openMatch } = useNav();
const labs = ["récupérée, coéquipier placé", "récupérée sans coéquipier placé", "perdue, coéquipier placé", "perdue dans le vide"];
const fills = ["var(--good)", "var(--good)", "var(--bad)", "var(--bad)"],
  ops = [1, 0.6, 0.6, 1],
  ink = ["var(--on-good)", "var(--ink)", "var(--ink)", "var(--panel-ink)"];

const v = computed(() => {
  const PS = props.d.PS!,
    PEERS = props.d.PEERS;
  const order = ["me", ...PEERS.map((p) => p.id), "lobby", "rlcs"];
  const G = PS.groups.filter((g) => order.includes(g.key)).sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
  const rows = G.map((g) => {
    const peer = PEERS.find((p) => p.id === g.key);
    return {
      g,
      name: g.key === "me" ? props.d.C.player : peer ? peer.name : g.label,
      kind: (g.key === "me" ? "me" : peer ? peer.slot : "ref") as SymKind,
      segs: (g.split ?? []).map((x, i) => ({ x: x ?? 0, i })).filter((s) => s.x > 0),
    };
  });
  const voids = PS.void.map((t) => ({ t, replay: props.d.replayOfDate(t.date) })).map((x) => ({ ...x, ok: !!(x.replay && props.d.PFM[x.replay]) }));
  return { me: G.find((g) => g.key === "me"), lob: G.find((g) => g.key === "lobby"), rows, voids, n: PS.void.length };
});
</script>

<template>
  <div v-if="d.PS">
    <div class="bt"><h2 class="pl-dx pl-title">Que deviennent tes balles données ?</h2><MI id="passes" label="Balles données" /><Scope kind="p" /></div>
    <p class="pl-body read">
      {{ pc(v.me?.recovered) }} de tes balles données sont reprises par un coéquipier (lobbies : {{ pc(v.lob?.recovered) }}). {{ pc(v.me?.split?.[3]) }} partent dans le vide.
    </p>
    <div v-for="r in v.rows" :key="r.g.key" class="stack">
      <span class="who pl-small"><Sym :kind="r.kind" /><b style="font-weight: 800; overflow: hidden; text-overflow: ellipsis">{{ r.name }}</b></span>
      <div class="bar" role="img" :aria-label="`${r.name} : ${(r.g.split ?? []).map((x, i) => `${labs[i]} ${pc(x)}`).join(', ')}`">
        <i
          v-for="s in r.segs"
          :key="s.i"
          :style="{ flex: `${s.x} 1 0`, background: fills[s.i], opacity: ops[s.i], color: ink[s.i] }"
          @mousemove="showTip($event, [[`${labs[s.i]} : `, { b: pc(s.x) }], [{ m: `${r.g.n.toLocaleString('fr-FR')} balles données` }]])"
          @mouseleave="hideTip"
          >{{ s.x >= 0.1 ? Math.round(s.x * 100) + NB + "%" : "" }}</i
        >
      </div>
      <span class="p5 pl-small pl-muted">{{ r.g.per5 == null ? "—" : num(r.g.per5, 1) }}</span>
    </div>
    <div class="legend pl-small pl-muted">
      <span v-for="(l, i) in labs" :key="l"><i class="sw" :style="{ background: fills[i], opacity: ops[i] }"></i>{{ l }}</span><span>À droite : balles données / 5 min.</span>
    </div>
    <details v-if="v.n" class="more">
      <summary class="pl-small">Tes {{ v.n }} passes dans le vide les plus coûteuses</summary>
      <table class="t pl-small">
        <thead>
          <tr><th>Partie</th><th class="n">Horloge</th><th>Passe</th><th class="n">Coéq. / adv.</th><th class="n">Gain 2 s</th></tr>
        </thead>
        <tbody>
          <tr
            v-for="(x, i) in v.voids"
            :key="i"
            :class="{ go: x.ok }"
            :tabindex="x.ok ? 0 : undefined"
            :title="x.ok ? 'Ouvrir le match' : undefined"
            @click="x.ok && openMatch(x.replay)"
            @keydown.enter="x.ok && openMatch(x.replay)"
          >
            <td>{{ dS(x.t.date) }} ▸</td>
            <td class="n">{{ clock(x.t.clock) }}</td>
            <td>{{ x.t.act }}</td>
            <td class="n">{{ Math.round(x.t.d_mate ?? 0) }}{{ NB }}m / {{ Math.round(x.t.d_opp ?? 0) }}{{ NB }}m</td>
            <td class="n pl-bad">{{ sgn(x.t.dv) }}</td>
          </tr>
        </tbody>
      </table>
    </details>
  </div>
</template>
