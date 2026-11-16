<script setup lang="ts">
// Bandeau de période, visible sur tous les onglets : nombre de parties analysées et choix des dates.
// « début » et « aujourd'hui » retirent le filtre (le serveur prend alors toutes les parties).
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import Scope from "./Scope.vue";
import { dC } from "@/lib/format";
import { keptQuery, store } from "@/lib/store";

const props = defineProps<{ n: number; period: string }>();
const route = useRoute();
const router = useRouter();
const days = computed(() => store.profil?.jours ?? []);
const d10 = (x: unknown) => (typeof x === "string" ? x.slice(0, 10) : "");
const du = ref(""),
  au = ref("");
watch(
  () => [route.query.du, route.query.au],
  () => {
    du.value = d10(route.query.du);
    au.value = d10(route.query.au);
  },
  { immediate: true },
);
function apply() {
  const q = keptQuery(route.query);
  if (du.value) q.du = du.value;
  else delete q.du;
  if (au.value) q.au = au.value;
  else delete q.au;
  router.push({ query: q });
}
</script>

<template>
  <div class="periodbar pl-small" role="region" aria-label="Période analysée">
    <span>Période analysée : <b>{{ props.n }} partie{{ props.n > 1 ? "s" : "" }}</b> · {{ props.period }}</span>
    <span v-if="store.loading" class="busy" role="status">Calcul…</span>
    <span v-if="!days.length" class="pl-muted">
      Tous les blocs portent sur ces parties, sauf ceux marqués <Scope kind="m" /> ou <Scope kind="x" text="Ensemble" />.
    </span>
    <form v-else @submit.prevent="apply">
      <label>Du <select v-model="du" class="sel" name="du"><option value="">début</option><option v-for="x in days" :key="x.d" :value="x.d">{{ dC(x.d) }} · {{ x.n }} p.</option></select></label>
      <label>au <select v-model="au" class="sel" name="au"><option value="">aujourd'hui</option><option v-for="x in days" :key="x.d" :value="x.d">{{ dC(x.d) }} · {{ x.n }} p.</option></select></label>
      <button type="submit">Appliquer</button>
    </form>
  </div>
</template>
