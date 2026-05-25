import { FlaskConical } from "lucide-react"
import { toast } from "sonner"
import { useSurfaceStore } from "@/store/surface"
import { surfaces } from "@/lib/surfaceManifest"

// Labs surfaces that register backend routers need a server restart before their
// endpoints respond — toggling here only changes the frontend immediately.
const LABS_WITH_BACKEND = new Set(
  surfaces
    .filter((s) => s.tier === "labs" && (s.backend?.routers?.length ?? 0) > 0)
    .map((s) => s.id),
)

export function SettingsLabsPanel() {
  const availableLabs = useSurfaceStore((s) => s.availableLabs)
  const labsEnabled = useSurfaceStore((s) => s.labsEnabled)
  const toggle = useSurfaceStore((s) => s.toggle)

  async function onToggle(id: string, on: boolean) {
    try {
      await toggle(id, on)
    } catch {
      toast.error("Could not update Labs settings.")
    }
  }

  if (availableLabs.length === 0) return null

  return (
    <section>
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold text-foreground">
        <FlaskConical size={15} className="text-amber-500" />
        Labs
      </h3>
      <p className="mb-3 text-xs text-muted-foreground">
        Experimental features — may change or be removed.
      </p>
      <div className="space-y-3">
        {availableLabs.map((s) => {
          const enabled = labsEnabled.has(s.id)
          return (
            <label key={s.id} className="flex cursor-pointer items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium text-foreground">{s.label}</p>
                {s.description && (
                  <p className="text-xs text-muted-foreground">{s.description}</p>
                )}
                {LABS_WITH_BACKEND.has(s.id) && (
                  <p className="mt-1 inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    Backend restart required to use these endpoints
                  </p>
                )}
              </div>
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => void onToggle(s.id, e.target.checked)}
                className="mt-0.5 h-4 w-4 flex-shrink-0 rounded border-border accent-primary"
              />
            </label>
          )
        })}
      </div>
    </section>
  )
}
