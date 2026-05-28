import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import surfaceManifest from "../surface-manifest.json"

type Tier = "public" | "labs" | "dev"

// dev-tier surfaces are build-stripped on public/labs bundles (per the labs-drawer
// spec: dev = build-time strip, labs = runtime toggle that still ships the code).
// Their component paths alias to a no-op so Quality/Admin/Monitoring never land in
// a non-dev dist.
function strippedAliases(tier: Tier): Record<string, string> {
  if (tier === "dev") return {}
  const stripped = path.resolve(__dirname, "./src/lib/strippedSurface.tsx")
  const out: Record<string, string> = {}
  for (const s of surfaceManifest.surfaces as Array<{ tier: Tier; frontend?: { component?: string; components?: string[] } }>) {
    if (s.tier !== "dev") continue
    const paths = [s.frontend?.component, ...(s.frontend?.components ?? [])].filter(Boolean) as string[]
    for (const p of paths) out[`@/${p}`] = stripped
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
