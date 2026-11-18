// Browser state that names a library's documents, sessions or conversations is kept per
// library, so a switch neither shows one library's ids in another nor loses them. The
// default library keeps the unsuffixed keys every install already has.

export const DEFAULT_LIBRARY = "default"
export const LIBRARY_MARKER_KEY = "luminary:library"

type KeyValueStore = Pick<Storage, "getItem" | "setItem" | "removeItem">

export function scopedKey(base: string, library: string): string {
  return library === DEFAULT_LIBRARY ? base : `${base}@${library}`
}

/** The library this page's browser state belongs to. */
export function storedLibrary(storage: Pick<Storage, "getItem">): string {
  try {
    return storage.getItem(LIBRARY_MARKER_KEY) || DEFAULT_LIBRARY
  } catch {
    return DEFAULT_LIBRARY
  }
}

export function rememberLibrary(storage: Pick<Storage, "setItem">, library: string): void {
  storage.setItem(LIBRARY_MARKER_KEY, library)
}

/** A Storage whose keys are scoped to the library the page loaded in. */
export function libraryScopedStorage(storage: KeyValueStore): KeyValueStore {
  const library = () => storedLibrary(storage)
  return {
    getItem: (name) => storage.getItem(scopedKey(name, library())),
    setItem: (name, value) => storage.setItem(scopedKey(name, library()), value),
    removeItem: (name) => storage.removeItem(scopedKey(name, library())),
  }
}

/** Drop a removed library's browser state, so a library given its id later starts clean. */
export function forgetLibrary(storage: Pick<Storage, "length" | "key" | "removeItem">, library: string): void {
  if (library === DEFAULT_LIBRARY) return
  const suffix = `@${library}`
  const keys: string[] = []
  for (let i = 0; i < storage.length; i++) {
    const key = storage.key(i)
    if (key?.endsWith(suffix)) keys.push(key)
  }
  keys.forEach((key) => storage.removeItem(key))
}
