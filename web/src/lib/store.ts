// État partagé de l'application : joueur connecté, profil, contenu du tableau de bord pour les filtres de l'adresse,
// flux « nouveau match traité ». Pas de Pinia : l'état se résume à ces quelques valeurs.
import { reactive } from "vue";
import type { LocationQuery } from "vue-router";
import { api, ApiError, type Moi, type Profil, type Tableau } from "@/api/client";

/** Filtres envoyés à l'API (la référence, elle, est choisie dans le navigateur : tout le contenu la contient). */
export const API_FILTERS = ["du", "au", "avec", "sans", "j"] as const;

export type Status = "loading" | "anon" | "import" | "ready" | "error";

export const store = reactive({
  status: "loading" as Status,
  moi: null as Moi | null,
  profil: null as Profil | null,
  tableau: null as Tableau | null,
  /** Clé des filtres du contenu affiché ; celui-ci reste à l'écran pendant le calcul du suivant. */
  key: null as string | null,
  loading: false,
  error: null as string | null,
  /** Message discret en bas de l'écran (« Nouveau match ajouté »…). */
  toast: null as string | null,
});

const str = (v: unknown): string => (Array.isArray(v) ? String(v[0] ?? "") : v == null ? "" : String(v));

/** Paramètres de l'API tirés de l'adresse (vides retirés). */
export function apiQuery(q: LocationQuery): URLSearchParams {
  const p = new URLSearchParams();
  for (const k of API_FILTERS) {
    const v = str(q[k]);
    if (v) p.set(k, v);
  }
  return p;
}

/** Filtres de l'adresse à garder quand on change d'onglet ou de match. */
export function keptQuery(q: LocationQuery): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k of [...API_FILTERS, "ref"]) {
    const v = str(q[k]);
    if (v) out[k] = v;
  }
  return out;
}

let toastTimer: ReturnType<typeof setTimeout> | undefined;
export function toast(msg: string, ms = 5000): void {
  store.toast = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (store.toast = null), ms);
}

/** Joueur connecté et état de l'import. 401 → page de connexion ; aucune partie prête → page d'import. */
export async function loadMe(): Promise<void> {
  try {
    store.moi = await api.moi();
    store.status = store.moi.parties > 0 ? "ready" : "import";
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      store.moi = null;
      store.status = "anon";
    } else if (store.status === "loading") {
      store.status = "error";
      store.error = "Le serveur ne répond pas. Réessaie dans un instant.";
    }
  }
}

let ctrl: AbortController | null = null;
let profilVersion = -1;

/** Contenu du tableau de bord pour ces filtres (le navigateur revalide avec l'ETag : 304 si rien n'a changé). */
export async function loadDashboard(q: LocationQuery, force = false): Promise<void> {
  const me = store.moi;
  if (!me) return;
  const params = apiQuery(q);
  const key = params.toString();
  if (!force && key === store.key && store.tableau) return;
  ctrl?.abort();
  const c = (ctrl = new AbortController());
  store.loading = true;
  try {
    const needProfil = !store.profil || profilVersion !== me.version;
    const [profil, tableau] = await Promise.all([
      needProfil ? api.profil(me.id, c.signal) : Promise.resolve(store.profil as Profil),
      api.tableau(me.id, params, c.signal),
    ]);
    if (c.signal.aborted) return;
    store.profil = profil;
    profilVersion = me.version;
    store.tableau = tableau;
    store.key = key;
    store.error = null;
  } catch (e) {
    if (c.signal.aborted) return;
    if (e instanceof ApiError && e.status === 401) {
      store.status = "anon";
      return;
    }
    if (e instanceof ApiError && e.status === 404) {
      store.status = "import"; // plus aucune partie prête (base vidée, rattrapage en cours…)
      return;
    }
    store.error =
      e instanceof ApiError
        ? "Le tableau de bord n'a pas pu être calculé. Réessaie dans un instant."
        : "Le serveur ne répond pas. Réessaie dans un instant.";
  } finally {
    if (ctrl === c) store.loading = false;
  }
}

// ------------------------------------------------------------------ nouveau match traité

let source: EventSource | null = null;
let poll: ReturnType<typeof setInterval> | undefined;
let onNew: (() => void) | null = null;

/** Après chaque match traité : le joueur est rechargé, puis `refresh` (le tableau de bord relit ses données). */
export function watchEvents(refresh: () => void): void {
  onNew = refresh;
  if (source || poll) return;
  const changed = async () => {
    const before = store.moi?.version;
    const wasImport = store.status === "import";
    await loadMe();
    if (store.moi && store.moi.version !== before) {
      if (!wasImport) toast("Nouveau match ajouté");
      onNew?.();
    }
  };
  const startPolling = () => {
    source?.close();
    source = null;
    if (!poll) poll = setInterval(changed, 60_000); // sans flux possible : une fois par minute
  };
  if (typeof EventSource === "undefined") return startPolling();
  source = new EventSource("/api/moi/evenements");
  source.addEventListener("partie", () => void changed());
  source.addEventListener("connecte", () => void changed()); // reconnexion : rattrape ce qui a pu être manqué
  // Coupure : le navigateur se reconnecte seul ; s'il abandonne (flux refusé), on interroge /api/moi.
  source.onerror = () => {
    if (source?.readyState === EventSource.CLOSED) startPolling();
  };
}

export function stopEvents(): void {
  source?.close();
  source = null;
  clearInterval(poll);
  poll = undefined;
}
