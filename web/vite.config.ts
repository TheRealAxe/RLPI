// Interface Vue du RLPI. Servie par FastAPI (rlpi.web.spa) à la racine du site.
// En développement : `npm run dev` (port 5173), l'API étant servie par `python -m rlpi.web` (port 8765) ou par
// docker-compose.dev.yml (port 3001, variable RLPI_API).
import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

const api = process.env.RLPI_API ?? "http://localhost:3001"; // = RLPI_PUBLIC_URL de docker-compose.dev.yml
const proxied = ["/api", "/auth", "/dev", "/moi", "/health"];

export default defineConfig({
  base: "/",
  plugins: [vue()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    // Jetons Plateau (Design/) et polices (src/rlpi/assets/fonts) : une seule copie, lue hors de web/
    fs: { allow: [".."] },
    // Les écritures vérifient l'en-tête Origin (RLPI_PUBLIC_URL) : en développement, le proxy présente celle de l'API.
    proxy: Object.fromEntries(
      proxied.map((p) => [
        p,
        {
          target: api,
          changeOrigin: false,
          configure: (proxy: { on: (ev: "proxyReq", cb: (req: { getHeader(n: string): unknown; setHeader(n: string, v: string): void }) => void) => void }) =>
            proxy.on("proxyReq", (req) => {
              if (req.getHeader("origin")) req.setHeader("origin", new URL(api).origin);
            }),
        },
      ]),
    ),
  },
  build: { outDir: "dist", assetsDir: "assets", sourcemap: false },
  test: { environment: "jsdom", include: ["src/**/*.test.ts"] },
});
