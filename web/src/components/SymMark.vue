<script setup lang="ts">
// Symbole d'un joueur placé dans un graphique SVG (centre x, y ; demi-taille s).
import type { SymKind } from "@/lib/data";
defineProps<{ kind: SymKind; x: number; y: number; s?: number }>();
</script>

<template>
  <path v-if="kind === 'me'" :d="`M${x},${y - (s ?? 6)} L${x + (s ?? 6)},${y} L${x},${y + (s ?? 6)} L${x - (s ?? 6)},${y} Z`" fill="var(--me)" />
  <circle v-else-if="kind === 'mate-1'" :cx="x" :cy="y" :r="(s ?? 6) * 0.8" fill="var(--mate-1)" />
  <rect v-else-if="kind === 'mate-2'" :x="x - (s ?? 6) * 0.75" :y="y - (s ?? 6) * 0.75" :width="(s ?? 6) * 1.5" :height="(s ?? 6) * 1.5" fill="var(--mate-2)" />
  <rect v-else :x="x - 1.5" :y="y - (s ?? 6)" width="3" :height="2 * (s ?? 6)" fill="var(--ref)" />
</template>
