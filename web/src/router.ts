// Adresses des onglets en chemins (décidé le 2026-11-16), filtres en paramètres (?du=&au=&j=&ref=).
// Mode historique : FastAPI renvoie index.html pour tout chemin de l'application (rlpi.web.spa).
import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import Connexion from "./views/Connexion.vue";
import Profil from "./views/Profil.vue";

export const TABS = [
  { name: "ma-forme", label: "Ma forme" },
  { name: "matchs", label: "Matchs" },
  { name: "mon-jeu", label: "Mon jeu" },
  { name: "a-travailler", label: "À travailler" },
  { name: "mon-trio", label: "Mon trio" },
] as const;

const routes: RouteRecordRaw[] = [
  {
    path: "/",
    component: Profil,
    children: [
      { path: "", redirect: (to) => ({ name: "ma-forme", query: to.query }) },
      { path: "ma-forme", name: "ma-forme", component: () => import("./views/MaForme.vue") },
      { path: "matchs/:match?", name: "matchs", component: () => import("./views/Matchs.vue") },
      { path: "mon-jeu", name: "mon-jeu", component: () => import("./views/MonJeu.vue") },
      { path: "a-travailler", name: "a-travailler", component: () => import("./views/ATravailler.vue") },
      { path: "mon-trio", name: "mon-trio", component: () => import("./views/MonTrio.vue") },
      { path: "indicateurs", name: "indicateurs", component: () => import("./views/Indicateurs.vue") },
    ],
  },
  // Page d'accueil, rouverte depuis le tableau de bord (les visiteurs non connectés la voient sur toute adresse).
  { path: "/accueil", name: "accueil", component: Connexion }, // déjà dans le paquet principal (App.vue)
  { path: "/modeles", name: "modeles", component: () => import("./views/Modeles.vue") },
  { path: "/swipe", name: "swipe", component: () => import("./views/Swipe.vue") },
  { path: "/:rest(.*)*", redirect: { name: "ma-forme" } },
];

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: (to, from) => (to.name !== from.name || to.params.match !== from.params.match ? { top: 0 } : false),
});
