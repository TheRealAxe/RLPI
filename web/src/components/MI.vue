<script setup lang="ts">
// Lien discret vers la rubrique du panneau Méthode qui explique la valeur.
import { openMethod } from "@/lib/method";
defineProps<{ id: string; label: string }>();
</script>

<template>
  <button class="mi" type="button" :aria-label="`Méthode : ${label}`" title="Comment c'est calculé" aria-haspopup="dialog" @click.stop="openMethod(id, $event.currentTarget)">ⓘ</button>
</template>
