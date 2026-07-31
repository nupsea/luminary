import { useQuery } from "@tanstack/react-query"

import {
  fetchCapabilities,
  fetchComponents,
  fetchStartupStatus,
  type Capabilities,
  type CapabilityKey,
} from "@/lib/setupApi"

/**
 * Startup progress.
 *
 * Polls while work is outstanding and stops once everything is ready, so a
 * settled app is not asking every two seconds forever. Retries indefinitely:
 * during a cold start the backend is legitimately not answering yet, and the
 * default two-strikes-and-give-up would leave the setup screen dead.
 */
export function useStartupStatus() {
  return useQuery({
    queryKey: ["setup", "status"],
    queryFn: fetchStartupStatus,
    refetchInterval: (query) => (query.state.data?.ready ? false : 2000),
    retry: true,
    retryDelay: 1500,
  })
}

export function useComponents() {
  return useQuery({
    queryKey: ["setup", "components"],
    queryFn: fetchComponents,
    staleTime: 30_000,
  })
}

export function useCapabilities() {
  return useQuery({
    queryKey: ["setup", "capabilities"],
    queryFn: fetchCapabilities,
    staleTime: 30_000,
  })
}

/**
 * Whether a feature may be offered.
 *
 * Defaults to true while unknown so a slow capabilities call never hides
 * working features -- the backend rejects what it cannot do anyway.
 */
export function useCapability(key: CapabilityKey) {
  const { data } = useCapabilities()
  return capabilityOf(data, key)
}

export function capabilityOf(data: Capabilities | undefined, key: CapabilityKey) {
  const cap = data?.[key]
  return {
    available: cap?.available ?? true,
    requires: cap?.requires ?? [],
    known: cap !== undefined,
  }
}
