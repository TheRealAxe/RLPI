<script setup lang="ts">
// Compte : parties prêtes, recherche de nouvelles parties (au plus une fois toutes les 5 minutes), déconnexion.
import { ref } from "vue";
import { api } from "@/api/client";
import { store, toast } from "@/lib/store";

const busy = ref(false);
async function refresh() {
  busy.value = true;
  try {
    const r = await api.actualiser();
    toast(r?.message ?? "Recherche lancée.");
  } catch {
    toast("La recherche n'a pas pu être lancée. Réessaie dans un instant.");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="account pl-small">
    <span v-if="store.moi" class="pl-muted">
      {{ store.moi.parties }} partie{{ store.moi.parties > 1 ? "s" : "" }}<template v-if="store.moi.en_preparation"> · {{ store.moi.en_preparation }} en préparation</template>
    </span>
    <button type="button" class="linkbtn" :disabled="busy" @click="refresh">Chercher mes nouvelles parties</button>
    <form method="post" action="/auth/deconnexion"><button class="linkbtn">Se déconnecter</button></form>
  </div>
</template>
