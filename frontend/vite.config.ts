import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import surfaceManifest from "../surface-manifest.json"

type Tier = "public" | "labs" | "dev"

// Surfaces above the build tier are build-stripped so their code never lands in a
// lower-tier dist (per the labs-drawer spec: dev = build-time strip; labs = runtime
// toggle that still ships the code). A `public` build strips both dev (Quality/
// Admin/Monitoring) and labs (e.g. Map/Viz) routed components; a `labs` build strips
// only dev. `dev` ships everything.
const TIER_ORDER: Record<Tier, number> = { public: 0, labs: 1, dev: 2 }

function strippedAliases(tier: Tier): Record<string, string> {
  const stripped = path.resolve(__dirname, "./src/lib/strippedSurface.tsx")
  const out: Record<string, string> = {}
  for (const s of surfaceManifest.surfaces as Array<{ tier: Tier; frontend?: { component?: string; components?: string[] } }>) {
    if (TIER_ORDER[s.tier] <= TIER_ORDER[tier]) continue
    // Always strip the routed page entry (pages/* are self-contained route roots).
    // Shared `components` are only stripped for dev-tier tools; labs surfaces list
    // shared building blocks there that always-on code may import, so leave them.
    const paths = [s.frontend?.component]
    if (s.tier === "dev") paths.push(...(s.frontend?.components ?? []))
    for (const p of paths.filter(Boolean) as string[]) out[`@/${p}`] = stripped
  }
  return out
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const tier = (process.env.VITE_SURFACE_TIER as Tier | undefined)
    ?? (mode === "production" ? "public" : "dev")

  return {
    plugins: [react()],
    resolve: {
      alias: {
        ...strippedAliases(tier),
        "@": path.resolve(__dirname, "./src"),
      },
    },
    define: {
      "import.meta.env.VITE_SURFACE_TIER": JSON.stringify(tier),
    },
    build: {
      chunkSizeWarningLimit: 2000,
    },
    server: {
      // surface-manifest.json lives at the repo root, one level above the vite root.
      fs: { allow: [path.resolve(__dirname, "..")] },
    },
  }
})
