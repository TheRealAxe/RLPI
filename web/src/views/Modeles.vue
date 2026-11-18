<script setup lang="ts">
// Les modèles : comment chaque modèle est construit et à quel point on peut s'y fier (rapports des modèles du volume
// de données, lus par /api/modeles). Remplace la page générée reports/modeles.html.
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import Rich from "@/components/Rich.vue";
import { api, type Modeles } from "@/api/client";

const data = ref<Modeles | null>(null);
const error = ref<string | null>(null);
onMounted(async () => {
  document.title = "Les modèles · RLPI";
  try {
    data.value = await api.modeles();
  } catch {
    error.value = "Les rapports des modèles n'ont pas pu être lus. Réessaie dans un instant.";
  }
});
const AXES = [
  ["Pertinence", "Mesure-t-il la bonne chose ? (lien avec la victoire, avec le jeu)"],
  ["Vérité", "Ce qu'il annonce est-il exact sur des données jamais vues ?"],
  ["Efficacité", "Fait-il mieux qu'une règle simple sans modèle ?"],
  ["Fiabilité", "Donne-t-il la même réponse quand on le mesure deux fois ?"],
];
</script>

<template>
  <div class="page models">
    <div class="top">
      <header class="pl-header">
        <div class="pl-cut pl-tag pl-volt">RLPI</div>
        <div class="pl-cut pl-panel"><span class="pl-tag">Les modèles</span></div>
      </header>
      <RouterLink class="pl-tag pl-muted" :to="{ name: 'ma-forme' }">◂ Tableau de bord</RouterLink>
    </div>
    <h1 class="pl-dx" style="font-size: var(--dx-56)">Ce que valent nos modèles</h1>
    <p class="pl-body read">
      Chaque note du tableau de bord vient d'un modèle ou d'une mesure. Voici comment chacun est construit et à quel point on peut s'y fier, mesuré sur des matchs qu'il n'a jamais vus.
    </p>
    <div class="axes">
      <div v-for="[t, s] in AXES" :key="t"><div class="pl-tag">{{ t }}</div><p class="pl-small pl-muted">{{ s }}</p></div>
    </div>

    <p v-if="error" class="pl-small pl-bad" role="alert" style="margin-top: var(--space-6)">{{ error }}</p>
    <p v-else-if="!data" class="busy pl-small" role="status" style="margin-top: var(--space-6)">Chargement…</p>
    <template v-else>
      <h2 class="pl-tag grph" style="margin-top: 28px">En un coup d'œil</h2>
      <div>
        <a v-for="r in data.resume" :key="r.ancre" class="pl-row sr" :href="`#${r.ancre}`">
          <span class="pl-dx nm">{{ r.titre }}</span><span class="pl-small">{{ r.chiffre }}</span><span class="pl-cut pl-tag badge" :class="r.niveau">{{ r.verdict }}</span>
        </a>
      </div>

      <section v-for="c in data.fiches" :id="c.anchor" :key="c.anchor" class="model">
        <div class="mh"><h2 class="pl-dx pl-title">{{ c.title }}</h2><span class="pl-cut pl-tag badge" :class="c.verdict.niveau">{{ c.verdict.label }}</span></div>
        <p class="pl-body read"><Rich :text="c.role" /></p>
        <p class="pl-small pl-muted">Dans la page : <Rich :text="c.where" /></p>
        <h3 class="pl-tag grph">Comment il est construit</h3>
        <ol class="pl-body"><li v-for="(x, i) in c.how" :key="i"><Rich :text="x" /></li></ol>
        <h3 class="pl-tag grph">Scores</h3>
        <div class="tw">
          <table class="sc">
            <thead><tr><th class="pl-tag">Axe</th><th class="pl-tag">Valeur</th><th class="pl-tag">Référence</th><th class="pl-tag">Ce que ça veut dire</th></tr></thead>
            <tbody>
              <tr v-for="s in c.scores" :key="s.axe">
                <th scope="row" class="pl-tag">{{ s.axe }}</th>
                <td class="pl-dx v" :class="s.niveau"><Rich :text="s.valeur" /></td>
                <td class="pl-small"><Rich :text="s.reference" /></td>
                <td class="pl-small"><Rich :text="s.lecture" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <h3 class="pl-tag grph">Limites</h3>
        <ul class="pl-body"><li v-for="(x, i) in c.limits" :key="i"><Rich :text="x" /></li></ul>
      </section>

      <section id="analyses" class="model">
        <div class="mh"><h2 class="pl-dx pl-title">Analyses</h2><span class="pl-cut pl-tag badge mid">Descriptif</span></div>
        <p class="pl-body read">
          Ce ne sont pas des modèles entraînés mais des mesures construites sur la valeur de la situation, comparées aux pros. Elles décrivent ce qui se passe ; elles ne prouvent pas une cause.
        </p>
        <div class="tw">
          <table class="sc">
            <thead><tr><th class="pl-tag">Analyse</th><th class="pl-tag">Données</th><th class="pl-tag">Ce qui la rend crédible</th><th class="pl-tag">Ce qui la limite</th></tr></thead>
            <tbody>
              <tr v-for="a in data.analyses" :key="a.analyse">
                <th scope="row" class="pl-tag"><Rich :text="a.analyse" /></th>
                <td class="pl-small"><Rich :text="a.donnees" /></td>
                <td class="pl-small"><Rich :text="a.credible" /></td>
                <td class="pl-small"><Rich :text="a.limite" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section id="avenir" class="model">
        <div class="mh"><h2 class="pl-dx pl-title">Pas encore validé</h2><span class="pl-cut pl-tag badge bad">À faire</span></div>
        <ul class="pl-body"><li v-for="(x, i) in data.a_faire" :key="i"><Rich :text="x" /></li></ul>
      </section>
      <p v-if="data.absents.length" class="pl-small pl-muted" style="margin-top: 40px">Rapports absents (fiches omises) : {{ data.absents.join(", ") }}.</p>
    </template>
  </div>
</template>
