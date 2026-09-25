import { useQuery, useQueryClient } from "@tanstack/react-query"

import { apiGet } from "@/lib/apiClient"
import type { HostVerdict } from "@/lib/engineModes"

export function useHostVerdict(): HostVerdict | undefined {
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ["host-support"],
    queryFn: async () => {
      const before = queryClient.getQueryData<HostVerdict>(["host-support"])
      const verdict = await apiGet<HostVerdict>("/setup/host-support")
      if (before && before.supported !== verdict.supported) {
        // What runs, and what may be installed, both follow the verdict.
        void queryClient.invalidateQueries({ queryKey: ["llm-routing"] })
        void queryClient.invalidateQueries({ queryKey: ["setup"] })
      }
      return verdict
    },
    staleTime: Infinity,
    gcTime: Infinity,
    // A supported verdict turns when the first loaded model lands on the
    // processor, which can happen minutes into a session.
    refetchInterval: (query) => {
      const v = query.state.data
      return v?.supported && v.measured === false ? 30_000 : false
    },
  })
  return data
}
