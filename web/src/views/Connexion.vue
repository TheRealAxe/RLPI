<script setup lang="ts">
// Page de connexion : Steam obligatoire (plus aucun tableau de bord public).
// Un retour de Steam refusé arrive ici avec ?connexion=echec. En développement (RLPI_DEV_LOGIN=1), /dev/joueurs
// répond et la page propose d'ouvrir une session pour un joueur connu, sans Steam ; ailleurs, cette route est une 404.
import { onMounted, ref } from "vue";

type DevPlayer = { id: string; pseudo: string | null; parties: number };

const failed = new URLSearchParams(location.search).get("connexion") === "echec";
const devPlayers = ref<DevPlayer[] | null>(null);

const devHref = (id: string) => `/dev/connexion?${new URLSearchParams({ joueur: id })}`;

onMounted(async () => {
  document.title = "RLPI · connexion";
  try {
    const r = await fetch("/dev/joueurs", { credentials: "same-origin" });
    if (r.ok) devPlayers.value = (await r.json()) as DevPlayer[];
  } catch {
    // pas de connexion de développement
  }
});
</script>

<template>
  <main class="gate">
    <header class="pl-header" style="margin-bottom: var(--space-5)">
      <div class="pl-cut pl-tag pl-volt">RLPI</div>
      <div class="pl-cut pl-panel"><h1 class="pl-dx pl-name">Rocket League Player Index</h1></div>
    </header>
    <div class="pl-panel pl-cutr carton">
      <p v-if="failed" class="pl-body" role="alert">La connexion Steam n'a pas abouti. Tu peux réessayer.</p>
      <p class="pl-body">Connecte-toi avec ton compte Steam pour voir les statistiques de tes parties 3v3.</p>
      <p class="pl-small pl-muted">
        Tes parties sont récupérées automatiquement sur ballchasing.com : il faut qu'elles y soient envoyées (par toi
        ou un coéquipier, avec l'envoi automatique de BakkesMod par exemple).
      </p>
      <p><a class="btn pl-cut pl-volt" href="/auth/steam">Se connecter avec Steam</a></p>
    </div>
    <div v-if="devPlayers" class="pl-panel pl-cutr carton" style="margin-top: var(--space-5)">
      <p class="pl-tag">Connexion de développement</p>
      <p class="pl-small pl-muted">Sans Steam (RLPI_DEV_LOGIN=1, jamais en production).</p>
      <ul class="pl-small">
        <li v-for="p in devPlayers" :key="p.id">
          <a :href="devHref(p.id)">{{ p.pseudo || p.id }}</a>
          <span class="pl-muted"> · {{ p.id }} · {{ p.parties }} partie(s)</span>
        </li>
        <li v-if="!devPlayers.length">Aucune partie traitée.</li>
      </ul>
      <form method="get" action="/dev/connexion">
        <input name="joueur" placeholder="Steam:7656119800000000x" aria-label="Identifiant du joueur" />
        <button class="btn pl-cut pl-volt" type="submit">Se connecter</button>
      </form>
    </div>
  </main>
</template>
