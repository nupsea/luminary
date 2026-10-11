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
    // A supported verdict turns if the chat model loading now lands on the
    // processor (I-60). The prompt-cache notice clears once Ollama restarts capped.
    refetchInterval: (query) => {
      const v = query.state.data
      if (v?.supported && v.settling) return 5_000
      return v?.prompt_cache_unbounded ? 15_000 : false
    },
  })
  return data
}
