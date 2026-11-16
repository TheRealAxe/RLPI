<script setup lang="ts">
// Texte avec du gras, rendu sans v-html : chaque morceau reste du texte.
import { computed } from "vue";
const props = defineProps<{ text: string }>();
// Gras : **…** (nos textes) ou <b>…</b> (textes des rapports de modèles, écrits côté serveur). Toute autre balise
// reste du texte.
const parts = computed(() =>
  props.text
    .split(/(\*\*[^*]+\*\*|<b>.*?<\/b>)/)
    .filter(Boolean)
    .map((s) => (s.startsWith("**") ? { b: true, t: s.slice(2, -2) } : s.startsWith("<b>") ? { b: true, t: s.slice(3, -4) } : { b: false, t: s })),
);
</script>

<template><template v-for="(p, i) in parts" :key="i"><b v-if="p.b">{{ p.t }}</b><template v-else>{{ p.t }}</template></template></template>
