import type { QueryClient } from "@tanstack/react-query"

import { apiGet, apiPost } from "@/lib/apiClient"
import type { CloudModel, CloudProvider } from "@/lib/cloudModels"

export interface KeyCheck {
  // verified: accepted. rejected: refused and not saved. unchecked: saved, provider unreachable.
  status: "verified" | "rejected" | "unchecked"
  saved: boolean
  message: string
}

export function saveProviderKey(provider: CloudProvider, apiKey: string): Promise<KeyCheck> {
  return apiPost<KeyCheck>("/settings/llm/key", { provider, api_key: apiKey })
}

export function cloudModelsQuery(provider: CloudProvider, hasKey: boolean) {
  return {
    // With no key the list is curated, with one it is what that key reaches.
    queryKey: ["llm-models", provider, hasKey],
    queryFn: () => apiGet<CloudModel[]>("/settings/llm/models", { provider }),
    staleTime: 5 * 60 * 1000,
  }
}

/** Everything that reads a key, a model list or the route is stale once either changes. */
export function invalidateKeyedQueries(queryClient: QueryClient) {
  for (const key of [
    "llm-settings",
    "llm-models",
    "chat-cloud-models",
    "study-cloud-models",
    "practice-cloud-models",
    "llm-routing",
  ]) {
    void queryClient.invalidateQueries({ queryKey: [key] })
  }
}
