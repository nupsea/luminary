// The support boundary, stated once, wherever the user is.
//
// Not dismissible, and deliberately: it is the reason everything else on an
// unsupported host feels broken, and hiding it leaves a user to conclude the
// product is bad rather than that the machine cannot run a local model.
//
// It names the work that does not run under the SAVED mode, read from the routing
// report's refused rows, so it changes the moment the mode does -- from first run
// or from Settings -- and disappears when nothing is refused. I-16: no key must
// keep meaning a working app, so it names the mode that would run the rest and
// never switches it.

import { useQuery } from "@tanstack/react-query"
import { AlertTriangle } from "lucide-react"

import { apiGet } from "@/lib/apiClient"
import { hostNotice, type HostVerdict } from "@/lib/engineModes"
import { fetchRouting } from "@/lib/llmRouting"

export function HostSupportBanner() {
  const { data: host } = useQuery({
    queryKey: ["host-support"],
    queryFn: () => apiGet<HostVerdict>("/setup/host-support"),
    // The host does not change while the app is open.
    staleTime: Infinity,
    gcTime: Infinity,
  })
  const { data: routing } = useQuery({
    queryKey: ["llm-routing"],
    queryFn: fetchRouting,
    enabled: host?.supported === false,
  })

  const text = hostNotice(host, routing)
  if (!text) return null

  return (
    <div
      role="status"
      className="mx-4 mt-2 flex shrink-0 items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-300"
    >
      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
      <span className="flex-1">{text}</span>
    </div>
  )
}
