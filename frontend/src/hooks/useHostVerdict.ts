import { useQuery } from "@tanstack/react-query"

import { apiGet } from "@/lib/apiClient"
import type { HostVerdict } from "@/lib/engineModes"

export function useHostVerdict(): HostVerdict | undefined {
  const { data } = useQuery({
    queryKey: ["host-support"],
    queryFn: () => apiGet<HostVerdict>("/setup/host-support"),
    // The host does not change while the app is open.
    staleTime: Infinity,
    gcTime: Infinity,
  })
  return data
}
