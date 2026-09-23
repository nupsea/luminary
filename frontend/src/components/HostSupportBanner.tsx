// The support boundary, stated once, wherever the user is. Not dismissible: hidden,
// an unsupported host just looks like a broken product. Names the work the SAVED
// mode refuses and never switches the mode itself (I-16).

import { useQuery } from "@tanstack/react-query"
import { AlertTriangle } from "lucide-react"

import { useHostVerdict } from "@/hooks/useHostVerdict"
import { hostNotice } from "@/lib/engineModes"
import { fetchRouting } from "@/lib/llmRouting"

export function HostSupportBanner() {
  const host = useHostVerdict()
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
