import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import surfaceManifest from "../surface-manifest.json"

type Mode = "full" | "public"

// Surfaces above the build mode are build-stripped so their code never lands in
// a public dist: a `public` build strips every full-mode routed component
// (Map/Viz, Quality, Admin, Monitoring, ...); a `full` build ships everything.
const MODE_ORDER: Record<Mode, number> = { public: 0, full: 1 }

function strippedAliases(luminaryMode: Mode): Record<string, string> {
  const stripped = path.resolve(__dirname, "./src/lib/strippedSurface.tsx")
  const out: Record<string, string> = {}
  for (const s of surfaceManifest.surfaces as Array<{ mode: Mode; rail?: string; frontend?: { component?: string; components?: string[] } }>) {
    if (MODE_ORDER[s.mode] <= MODE_ORDER[luminaryMode]) continue
    // Always strip the routed page entry (pages/* are self-contained route roots).
    // Shared `components` are only stripped for dev-rail tools; other full-mode
    // surfaces list shared building blocks there that always-on code may import,
    // so leave them.
    const paths = [s.frontend?.component]
    if (s.rail === "dev") paths.push(...(s.frontend?.components ?? []))
    for (const p of paths.filter(Boolean) as string[]) out[`@/${p}`] = stripped
  }
  return out
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const luminaryMode = (process.env.VITE_LUMINARY_MODE as Mode | undefined)
    ?? (mode === "production" ? "public" : "full")

  return {
    plugins: [react()],
    resolve: {
      alias: {
        ...strippedAliases(luminaryMode),
        "@": path.resolve(__dirname, "./src"),
      },
    },
    define: {
      "import.meta.env.VITE_LUMINARY_MODE": JSON.stringify(luminaryMode),
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
