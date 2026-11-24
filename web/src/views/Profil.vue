<script setup lang="ts">
// Coquille du profil : barre d'onglets, sélecteurs (joueur affiché, référence), lien Méthode, en-tête, bandeau de
// période. Les filtres viennent de l'adresse et sont appliqués par fetch : le contenu précédent reste affiché (en
// grisé) pendant le calcul du suivant.
import { computed, onBeforeUnmount, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import Account from "@/components/Account.vue";
import PeriodBar from "@/components/PeriodBar.vue";
import TabBar from "@/components/TabBar.vue";
import ImportGate from "./ImportGate.vue";
import { storeRef, useData } from "@/lib/data";
import { openMethod } from "@/lib/method";
import { keptQuery, loadDashboard, stopEvents, store, watchEvents } from "@/lib/store";
import { ui } from "@/lib/ui";

const route = useRoute();
const router = useRouter();
const dd = useData();

watch(
  () => [store.status, route.query] as const,
  () => {
    if (store.status === "ready") void loadDashboard(route.query);
  },
  { immediate: true, deep: true },
);
// Nouveau match traité : le contenu est relu sans recharger la page ni perdre les filtres.
watchEvents(() => {
  if (store.status === "ready") void loadDashboard(route.query, true);
});
onBeforeUnmount(stopEvents);

const contenu = computed(() => store.tableau?.contenu ?? null);
const who = computed(() => store.profil?.joueurs ?? []);
const shown = computed(() => store.tableau?.joueur ?? store.moi?.id ?? "");
const showRef = computed(() => route.name === "mon-jeu" || route.name === "indicateurs");
const name = (id: string) => store.profil?.noms?.[id] ?? id;

watch(
  () => contenu.value?.player,
  (p) => (document.title = p ? `${p} · RLPI` : "RLPI"),
  { immediate: true },
);

function setWho(e: Event) {
  const v = (e.target as HTMLSelectElement).value;
  const q = keptQuery(route.query);
  if (v && v !== store.moi?.id) q.j = v;
  else delete q.j;
  ui.match = null;
  router.push({ query: q });
}
function setRef(e: Event) {
  const v = (e.target as HTMLSelectElement).value;
  storeRef(v);
  router.replace({ query: { ...keptQuery(route.query), ref: v } });
}
function resetFilters() {
  const q = keptQuery(route.query);
  for (const k of ["du", "au", "avec", "sans"]) delete q[k];
  router.push({ query: q });
}
</script>

<template>
  <a class="skip" href="#main">Aller au contenu</a>
  <div class="page">
    <nav class="top" aria-label="Profil">
      <TabBar v-if="store.status === 'ready'" :trio="!!dd?.PEERS.length" />
      <div class="controls pl-small">
        <label v-if="who.length > 1">Joueur
          <select class="sel" name="j" :value="shown" @change="setWho">
            <option v-for="id in who" :key="id" :value="id">{{ name(id) }}</option>
          </select>
        </label>
        <label v-if="showRef && dd" title="Référence des centiles de Mon jeu">Mon jeu face aux
          <select class="sel" name="ref" :value="dd.ref" @change="setRef">
            <option v-for="k in dd.refs" :key="k" :value="k">{{ contenu?.refs[k]?.label }}</option>
          </select>
        </label>
        <button type="button" class="linkbtn" aria-haspopup="dialog" @click="openMethod('indice', $event.currentTarget)">Méthode ⓘ</button>
        <RouterLink class="linkbtn" :to="{ name: 'accueil' }">Accueil</RouterLink>
      </div>
    </nav>
    <header class="pl-header">
      <RouterLink class="pl-cut pl-tag pl-volt" :to="{ name: 'accueil' }" title="Page d'accueil" style="text-decoration: none">RLPI</RouterLink>
      <div class="pl-cut pl-panel"><h1 class="pl-dx pl-name">{{ contenu?.player ?? store.moi?.nom ?? "Ton profil" }}</h1></div>
      <div class="ctx pl-tag pl-muted">{{ store.status === "ready" && contenu ? ui.ctx : "" }}</div>
    </header>

    <main v-if="store.status === 'import'" id="main"><ImportGate /></main>
    <template v-else>
      <PeriodBar v-if="contenu && dd" :n="contenu.n_matches" :period="dd.period" />
      <main id="main" :class="{ loading: store.loading && !!store.tableau }" :aria-busy="store.loading">
        <p v-if="!store.tableau && store.loading" class="busy pl-small" role="status">Chargement du tableau de bord…</p>
        <div v-else-if="!store.tableau && store.error" class="pl-panel pl-cutr carton">
          <h2 class="pl-dx pl-title">Tableau de bord indisponible</h2>
          <p class="pl-small" style="margin-top: 8px">{{ store.error }}</p>
        </div>
        <div v-else-if="store.tableau && !contenu" class="pl-panel pl-cutr carton">
          <h2 class="pl-dx pl-title">Aucune partie pour ces filtres</h2>
          <p class="pl-small" style="margin-top: 8px">{{ store.tableau.erreur || "Change la période ou les coéquipiers." }}</p>
          <p style="margin-top: 12px"><button type="button" class="linkbtn" @click="resetFilters">Revenir à toutes mes parties</button></p>
        </div>
        <RouterView v-else-if="dd" v-slot="{ Component }">
          <component :is="Component" :key="String(route.name)" class="view enter" />
        </RouterView>
        <p v-if="store.error && store.tableau" class="pl-small pl-bad" role="alert" style="margin-top: var(--space-4)">{{ store.error }}</p>
      </main>
    </template>
    <footer class="pl-small pl-muted">
      <Account />
      <p v-if="contenu" style="margin-top: var(--space-2)">
        Calculé le {{ contenu.generated }}. Données : {{ contenu.n_matches }} parties classées 3v3.
        <RouterLink :to="{ name: 'modeles' }">Les modèles</RouterLink> ·
        <RouterLink :to="{ name: 'swipe' }">Juger des actions à l'aveugle</RouterLink>
      </p>
    </footer>
  </div>
</template>
