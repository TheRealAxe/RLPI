<script setup lang="ts">
// Badge de portée : sur quelles parties porte un bloc (période choisie, match affiché, parties ensemble…).
defineProps<{ kind: "p" | "m" | "e" | "x"; n?: number; text?: string; title?: string }>();
</script>

<template>
  <span v-if="kind === 'p'" class="scope scope--p" title="Toutes les parties de la période choisie en haut de page">Période</span>
  <span v-else-if="kind === 'm'" class="scope scope--m" title="Uniquement le match affiché">Ce match</span>
  <span v-else-if="kind === 'e'" class="scope scope--e" title="Uniquement les parties jouées dans la même équipe">Ensemble · {{ n }} parties</span>
  <span v-else class="scope scope--e" :title="title">{{ text }}</span>
</template>
