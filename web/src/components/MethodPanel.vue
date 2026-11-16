<script setup lang="ts">
// Panneau Méthode : panneau latéral de 420 px, fermé par Échap ou un clic à côté, focus piégé tant qu'il est ouvert ;
// à la fermeture, le focus revient au bouton qui l'a ouvert.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import Rich from "./Rich.vue";
import { caveats, definitions, glossary } from "@/copy/glossary";
import { useData } from "@/lib/data";
import { closeMethod, method } from "@/lib/method";

const dd = useData();
const panel = ref<HTMLElement | null>(null);
const G = computed(() => (dd.value ? glossary(dd.value) : []));
const A = computed(() => (dd.value ? caveats(dd.value) : []));
const DEF = computed(() => (dd.value ? definitions(dd.value) : { source: "", items: [] }));
const toc = computed(() => [
  ...G.value.map((g) => ({ id: g.id, title: g.title })),
  { id: "alire", title: "À lire avant d'interpréter" },
  { id: "defs", title: "Définitions des indicateurs" },
]);
const hit = ref("");

async function focusRubric(id: string) {
  await nextTick();
  const s = panel.value?.querySelector<HTMLElement>(`#g-${id}`);
  if (!s) return;
  hit.value = id;
  s.scrollIntoView({ block: "start" });
  s.focus({ preventScroll: true });
}
watch(
  () => [method.open, method.rubric, method.seq] as const,
  ([open]) => {
    if (open) void focusRubric(method.rubric);
  },
);

function onKey(e: KeyboardEvent) {
  const p = panel.value;
  if (!method.open || !p) return;
  if (e.key === "Escape") {
    e.preventDefault();
    closeMethod();
    return;
  }
  if (e.key === "Tab") {
    const f = [...p.querySelectorAll<HTMLElement>("button, a[href], [tabindex]:not([tabindex='-1'])")].filter((x) => !(x as HTMLButtonElement).disabled && x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0],
      last = f[f.length - 1];
    if (!p.contains(document.activeElement)) {
      e.preventDefault();
      first.focus();
    } else if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
}
function onClick(e: MouseEvent) {
  const t = e.target as Node;
  if (method.open && panel.value && !panel.value.contains(t) && !(t as HTMLElement).closest?.(".mi, [aria-haspopup='dialog']")) closeMethod();
}
onMounted(() => {
  document.addEventListener("keydown", onKey);
  document.addEventListener("click", onClick);
});
onBeforeUnmount(() => {
  document.removeEventListener("keydown", onKey);
  document.removeEventListener("click", onClick);
});
</script>

<template>
  <aside v-if="method.open" ref="panel" class="method pl-panel enter" role="dialog" aria-modal="true" aria-labelledby="method-title">
    <div class="mh">
      <h2 id="method-title" class="pl-dx pl-name">Méthode</h2>
      <button type="button" class="close pl-tag" @click="closeMethod">Fermer ✕</button>
    </div>
    <p class="pl-small" style="margin-bottom: var(--space-3)">
      Chaque valeur de la page, expliquée : ce qu'elle mesure, comment elle est calculée, comment la lire et ce qu'elle ne dit pas.
    </p>
    <nav class="toc pl-small" aria-label="Rubriques">
      <a v-for="t in toc" :key="t.id" :href="`#g-${t.id}`" @click.prevent="focusRubric(t.id)">{{ t.title }}</a>
    </nav>
    <section v-for="g in G" :id="`g-${g.id}`" :key="g.id" tabindex="-1" :class="{ hit: hit === g.id }">
      <h3 class="pl-dx">{{ g.title }}</h3>
      <p class="pl-body"><Rich :text="g.what" /></p>
      <h4 class="pl-tag">Comment c'est calculé</h4>
      <ol><li v-for="(s, i) in g.steps.filter(Boolean)" :key="i"><Rich :text="s" /></li></ol>
      <template v-if="g.example"><h4 class="pl-tag">Exemple</h4><p class="ex"><Rich :text="g.example" /></p></template>
      <h4 class="pl-tag">Comment le lire</h4>
      <ul><li v-for="(s, i) in g.read.filter(Boolean)" :key="i"><Rich :text="s" /></li></ul>
      <h4 class="pl-tag">Ce que ça ne dit pas</h4>
      <ul><li v-for="(s, i) in g.limits.filter(Boolean)" :key="i"><Rich :text="s" /></li></ul>
    </section>
    <section id="g-alire" tabindex="-1" :class="{ hit: hit === 'alire' }">
      <h3 class="pl-dx">À lire avant d'interpréter</h3>
      <ul><li v-for="(s, i) in A" :key="i"><Rich :text="s" /></li></ul>
    </section>
    <section id="g-defs" tabindex="-1" :class="{ hit: hit === 'defs' }">
      <h3 class="pl-dx">Définitions des indicateurs</h3>
      <p>{{ DEF.source }}</p>
      <ul><li v-for="(m, i) in DEF.items" :key="i"><b>{{ m.label }}</b> ({{ m.meta }}) : {{ m.def }}</li></ul>
    </section>
  </aside>
</template>
