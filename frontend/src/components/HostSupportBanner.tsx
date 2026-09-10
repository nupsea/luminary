// The support boundary, stated once, wherever the user is.
//
// Not dismissible, and deliberately: it is the reason everything else on an
// unsupported host feels broken, and hiding it leaves a user to conclude the
// product is bad rather than that the machine cannot run a local model. It
// names both ways forward, because I-16 means no key must keep meaning a
// working app -- reading, search, notes and the learner record are unaffected.

import { useQuery } from "@tanstack/react-query"
import { AlertTriangle } from "lucide-react"

import { apiGet } from "@/lib/apiClient"

interface HostSupport {
  supported: boolean
  reason: string | null
  host: string
  message: string | null
}

export function HostSupportBanner() {
  const { data } = useQuery({
    queryKey: ["host-support"],
    queryFn: () => apiGet<HostSupport>("/setup/host-support"),
    // The host does not change while the app is open.
    staleTime: Infinity,
    gcTime: Infinity,
  })

  if (!data || data.supported || !data.message) return null

  return (
    <div
      role="status"
      className="mx-4 mt-2 flex shrink-0 items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-300"
    >
      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
      <span className="flex-1">
        {data.message}
        <span className="ml-1 opacity-70">({data.host})</span>
      </span>
    </div>
  )
}
