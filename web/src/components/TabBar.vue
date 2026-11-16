<script setup lang="ts">
// Barre d'onglets : rôle tablist, flèches gauche/droite, Début/Fin ; l'onglet actif est le seul dans l'ordre de
// tabulation. « Tous les indicateurs » dépend de Mon jeu.
import { computed, nextTick, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { TABS } from "@/router";
import { keptQuery } from "@/lib/store";
import { ui } from "@/lib/ui";

const props = defineProps<{ trio: boolean }>();
const route = useRoute();
const router = useRouter();
const tabs = computed(() => TABS.filter((t) => t.name !== "mon-trio" || props.trio));
const active = computed(() => (route.name === "indicateurs" ? "mon-jeu" : String(route.name)));
const btns = ref<HTMLButtonElement[]>([]);

function go(name: string) {
  const query = keptQuery(route.query);
  if (name === "matchs" && ui.match) router.push({ name, params: { match: ui.match }, query });
  else router.push({ name, query });
}
async function key(e: KeyboardEvent, i: number) {
  const n = tabs.value.length;
  const j = e.key === "ArrowRight" ? (i + 1) % n : e.key === "ArrowLeft" ? (i - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : null;
  if (j == null) return;
  e.preventDefault();
  go(tabs.value[j].name);
  await nextTick();
  btns.value[j]?.focus();
}
</script>

<template>
  <div class="tabs" role="tablist" aria-label="Sections du profil">
    <button
      v-for="(t, i) in tabs"
      :key="t.name"
      ref="btns"
      class="tab"
      role="tab"
      type="button"
      :aria-selected="active === t.name"
      :tabindex="active === t.name ? 0 : -1"
      @click="go(t.name)"
      @keydown="key($event, i)"
    >
      <span class="pl-cut pl-tag">{{ t.label }}</span>
    </button>
  </div>
</template>
