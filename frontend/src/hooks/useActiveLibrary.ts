import { useEffect } from "react"
import { useQuery } from "@tanstack/react-query"

import { apiGet } from "@/lib/apiClient"
import { rememberLibrary, storedLibrary } from "@/lib/libraryScope"
import type { components } from "@/types/api"

export type LibraryList = components["schemas"]["LibraryList"]

export const LIBRARIES_KEY = ["libraries"]

export function fetchLibraries(): Promise<LibraryList> {
  return apiGet<LibraryList>("/libraries")
}

/** Point this page at the library the backend serves, and reload it there. */
export function openLibrary(library: string): void {
  rememberLibrary(localStorage, library)
  window.location.reload()
}

/** The backend's active library. A page holding another library's browser state reloads. */
export function useActiveLibrary(): string | null {
  const { data } = useQuery({
    queryKey: LIBRARIES_KEY,
    queryFn: fetchLibraries,
    staleTime: 60_000,
    // A paired device is refused the list and works in its own library regardless.
    retry: false,
  })
  const active = data?.active ?? null
  useEffect(() => {
    if (active !== null && active !== storedLibrary(localStorage)) openLibrary(active)
  }, [active])
  return active
}
