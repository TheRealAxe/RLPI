<script setup lang="ts">
// Conseils : trois pistes tirées chacune d'une mesure, avec leur raison.
import MI from "../MI.vue";
import Scope from "../Scope.vue";
import type { Derived } from "@/lib/data";
defineProps<{ d: Derived }>();
</script>

<template>
  <div v-if="d.C.advice.length">
    <div class="bt" style="margin-bottom: 8px"><h2 class="pl-dx h44">Conseils</h2><MI id="conseils" label="Conseils" /><Scope kind="p" /></div>
    <div class="advice">
      <div v-for="(a, i) in d.C.advice" :key="i" class="a">
        <span class="pl-tag pl-muted">{{ a.kind }}</span>
        <h3 class="pl-dx">{{ a.title }}</h3>
        <p class="pl-body">{{ a.text }}</p>
        <p class="pl-small pl-muted" style="margin-top: 4px">{{ a.why }}</p>
      </div>
    </div>
  </div>
</template>
