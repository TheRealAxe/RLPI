<script setup lang="ts">
// Notes des modèles : placement hors ballon, résultat des touches, choix à la touche (expérimental).
// Les catégories RLPI restent masquées (grille en cours de refonte, masquées le 2026-11-14 : docs/JOURNAL.md).
import { computed } from "vue";
import CatRow from "../CatRow.vue";
import MI from "../MI.vue";
import Scope from "../Scope.vue";
import Sym from "../Sym.vue";
import type { Derived } from "@/lib/data";

const props = defineProps<{ d: Derived }>();
const rows = computed(() => {
  const V = props.d.V;
  if (!V) return [];
  const peers = (f: (pv: NonNullable<Derived["PEERS"][number]["value"]>) => number | null) =>
    props.d.PEERS.map((p) => ({ p, v: p.value ? f(p.value) : null }));
  return [
    ...(V.plc ? [{ label: "Placement hors ballon", sub: "face aux pros RLCS", v: V.plc.me_note, peers: peers((x) => x.plc_note) }] : []),
    { label: "Résultat des touches", sub: "face à tes lobbies", v: V.me_lobby_note, peers: peers((x) => x.lobby_note) },
    ...(V.dec ? [{ label: "Choix à la touche", sub: "expérimental · peu fiable", exp: true, v: V.dec.me_note, peers: peers((x) => x.dec_note) }] : []),
  ];
});
</script>

<template>
  <div v-if="d.V">
    <div class="bt"><h2 class="pl-dx pl-title">Notes des modèles</h2><MI id="centile" label="Notes des modèles" /><Scope kind="p" /></div>
    <CatRow v-for="r in rows" :key="r.label" v-bind="r" />
    <div class="legend pl-small pl-muted">
      <span v-for="p in d.PEERS" :key="p.id"><Sym :kind="p.slot" />{{ p.name }}</span><span>Trait : 50, la médiane de la référence.</span>
    </div>
  </div>
</template>
