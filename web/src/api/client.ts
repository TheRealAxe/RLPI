// Accès à l'API FastAPI. Types générés depuis l'OpenAPI (schema.d.ts : `npm run api-types`, voir
// scripts/export_openapi.py) : le contrat API ↔ interface est vérifié à la compilation.
import type { components } from "./schema";

type S = components["schemas"];
export type Moi = S["Moi"];
export type Profil = S["Profil"];
export type Tableau = S["Tableau"];
export type Contenu = S["Contenu"];
export type Perf = S["Perf"];
export type PerfMatch = S["PerfMatch"];
export type Value = S["Value"];
export type Curve = S["Curve"];
export type Touch = S["Touch"];
export type Peer = S["Peer"];
export type Metric = S["Metric"];
export type Reference = S["Reference"];
export type Heat = S["Heat"];
export type Passes = S["Passes"];
export type Style = S["Style"];
export type Progress = S["Progress"];
export type Synergy = S["Synergy"];
export type SynergyPair = S["SynergyPair"];
export type TechRow = S["TechRow"];
export type Modeles = S["Modeles"];
export type Actualisation = S["Actualisation"];
export type Clip = S["Clip"];

/** Erreur HTTP lisible : statut + message de l'API (`detail`) quand il existe. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function detail(r: Response): Promise<string> {
  try {
    const j = await r.json();
    if (typeof j?.detail === "string") return j.detail;
  } catch {
    /* corps vide ou non JSON */
  }
  return `Erreur ${r.status}`;
}

export async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, { credentials: "same-origin", signal, headers: { Accept: "application/json" } });
  if (!r.ok) throw new ApiError(r.status, await detail(r));
  return (await r.json()) as T;
}

export async function postJson<T>(url: string, body?: unknown): Promise<T | null> {
  const r = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new ApiError(r.status, await detail(r));
  return r.status === 204 ? null : ((await r.json()) as T);
}

const player = (id: string) => `/api/joueurs/${encodeURIComponent(id)}`;

export const api = {
  moi: (signal?: AbortSignal) => getJson<Moi>("/api/moi", signal),
  actualiser: () => postJson<Actualisation>("/api/moi/actualiser"),
  profil: (id: string, signal?: AbortSignal) => getJson<Profil>(`${player(id)}/profil`, signal),
  tableau: (id: string, q: URLSearchParams, signal?: AbortSignal) =>
    getJson<Tableau>(`${player(id)}/tableau${q.toString() ? "?" + q : ""}`, signal),
  modeles: (signal?: AbortSignal) => getJson<Modeles>("/api/modeles", signal),
  /** Clip 3D d'une touche (passer par lib/clips.ts : loadClip). */
  clip: (id: string, match: string, i: number, signal?: AbortSignal) =>
    getJson<Clip>(`${player(id)}/matchs/${encodeURIComponent(match)}/clips/${i}`, signal),
};
