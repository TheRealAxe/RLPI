<script setup lang="ts">
// Premier import : la page se met à jour seule (flux d'événements) et passe au tableau de bord dès le premier match.
import { computed } from "vue";
import { store } from "@/lib/store";

const st = computed(() => store.moi?.import);
const last = computed(() => {
  const s = st.value;
  if (!s) return "";
  if (s.running) return "en cours";
  if (s.last_sync) {
    const d = new Date(s.last_sync);
    const p = (n: number) => String(n).padStart(2, "0");
    return `faite le ${p(d.getDate())}/${p(d.getMonth() + 1)} à ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  return "pas encore commencée (elle démarre dès qu'un worker est libre)";
});
</script>

<template>
  <div class="pl-panel pl-cutr carton" style="max-width: 720px">
    <h2 class="pl-dx pl-title">Import de tes parties</h2>
    <p class="pl-body">
      Recherche sur ballchasing : {{ last }}.<br />
      Parties à toi déjà traitées : {{ st?.done ?? 0 }}.<br />
      <template v-if="store.moi?.en_preparation">Parties en préparation : {{ store.moi.en_preparation }}.<br /></template>
      Parties en attente de traitement (tous joueurs) : {{ st?.waiting ?? 0 }}.
    </p>
    <p class="pl-small pl-muted">
      Chaque partie est téléchargée sur ballchasing (une toutes les 18 secondes au plus) puis analysée (15 à 40
      secondes). Ton tableau de bord s'affiche ici dès ta première partie traitée, sans recharger la page. Si rien
      n'arrive, vérifie que tes replays sont publics sur ballchasing.com.
    </p>
  </div>
</template>
