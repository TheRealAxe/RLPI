<script setup lang="ts">
// Racine : connexion requise (chacun ne voit que le sien), puis l'application. Info-bulle, panneau Méthode et
// messages sont communs à toutes les pages.
import { onMounted } from "vue";
import Connexion from "./views/Connexion.vue";
import MethodPanel from "./components/MethodPanel.vue";
import Tip from "./components/Tip.vue";
import { loadMe, store } from "./lib/store";

onMounted(loadMe);
</script>

<template>
  <div v-if="store.status === 'loading'" class="gate"><p class="busy pl-small">Chargement…</p></div>
  <Connexion v-else-if="store.status === 'anon'" />
  <div v-else-if="store.status === 'error' && !store.moi" class="gate">
    <div class="pl-panel pl-cutr carton">
      <h1 class="pl-dx pl-title">RLPI indisponible</h1>
      <p class="pl-small">{{ store.error }}</p>
    </div>
  </div>
  <RouterView v-else />
  <MethodPanel />
  <Tip />
  <div v-if="store.toast" class="toast pl-cut pl-panel pl-small" role="status" aria-live="polite">{{ store.toast }}</div>
</template>
