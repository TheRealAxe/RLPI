// Navigation entre onglets en gardant les filtres de l'adresse.
import { useRoute, useRouter } from "vue-router";
import { keptQuery } from "./store";
import { ui } from "./ui";

export function useNav() {
  const route = useRoute();
  const router = useRouter();
  return {
    go: (name: string) => router.push({ name, query: keptQuery(route.query) }),
    /** Ouvre un match de la période dans l'onglet Matchs. */
    openMatch: (replay: string | null | undefined) => {
      if (!replay) return;
      ui.match = replay;
      router.push({ name: "matchs", params: { match: replay }, query: keptQuery(route.query) });
    },
  };
}
