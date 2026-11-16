<script setup lang="ts">
// Symbole d'un joueur : toi = losange volt, coéquipier 1 = rond, coéquipier 2 = carré, référence = trait.
// inPanel : contour sombre pour rester lisible sur un carton.
import type { SymKind } from "@/lib/data";
defineProps<{ kind: SymKind; inPanel?: boolean }>();
</script>

<template>
  <svg class="sym" viewBox="0 0 14 14" aria-hidden="true">
    <path v-if="kind === 'me'" d="M7,1 L13,7 L7,13 L1,7 Z" fill="var(--me)" v-bind="inPanel ? { stroke: 'var(--panel-ink)', 'stroke-width': 1.5 } : {}" />
    <circle v-else-if="kind === 'mate-1'" cx="7" cy="7" r="6" fill="var(--mate-1)" v-bind="inPanel ? { stroke: 'var(--panel-ink)', 'stroke-width': 1.5 } : {}" />
    <rect v-else-if="kind === 'mate-2'" x="1" y="1" width="12" height="12" fill="var(--mate-2)" v-bind="inPanel ? { stroke: 'var(--panel-ink)', 'stroke-width': 1.5 } : {}" />
    <rect v-else-if="kind === 'ref'" x="1" y="5" width="12" height="4" :fill="inPanel ? 'var(--panel-muted)' : 'var(--ref)'" />
    <circle v-else-if="kind === 'other'" cx="7" cy="7" r="5" fill="none" stroke="var(--ink-muted)" stroke-width="1.5" />
  </svg>
</template>
