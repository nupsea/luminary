// Per-section fetch envelope for the Monitoring page (invariant I-10:
// every section owns loading/error/empty independently). Optional
// refreshMs re-fetches silently -- state only changes on completion, so
// a failed refresh keeps the last good data on screen instead of
// blanking the table.

import { useCallback, useEffect, useRef, useState } from "react"

import { logger } from "@/lib/logger"

import type { SectionState } from "./types"

export function useSection<T>(
  name: string,
  fetcher: () => Promise<T>,
  fallback: T,
  refreshMs?: number,
) {
  const [state, setState] = useState<SectionState<T>>({
    loading: true,
    data: fallback,
    error: false,
  })
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  }, [fetcher])

  const load = useCallback(() => {
    let cancelled = false
    fetcherRef.current()
      .then((d) => {
        if (!cancelled) setState({ loading: false, data: d, error: false })
      })
      .catch((e: unknown) => {
        logger.warn("[Monitoring] section failed", name, e)
        if (!cancelled) setState((prev) => ({ ...prev, loading: false, error: true }))
      })
    return () => {
      cancelled = true
    }
  }, [name])

  useEffect(() => {
    const cancel = load()
    if (!refreshMs) return cancel
    const id = setInterval(load, refreshMs)
    return () => {
      cancel()
      clearInterval(id)
    }
  }, [load, refreshMs])

  return { ...state, reload: load }
}
