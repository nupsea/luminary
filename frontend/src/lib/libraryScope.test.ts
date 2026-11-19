import { describe, expect, it } from "vitest"

import {
  LIBRARY_MARKER_KEY,
  forgetLibrary,
  libraryScopedStorage,
  rememberLibrary,
  scopedKey,
  storedLibrary,
} from "./libraryScope"

function memoryStorage() {
  const map = new Map<string, string>()
  return {
    map,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
  }
}

describe("libraryScope", () => {
  it("keeps the default library on the keys an install already has", () => {
    expect(scopedKey("luminary-app-store", "default")).toBe("luminary-app-store")
    expect(scopedKey("luminary-app-store", "work")).toBe("luminary-app-store@work")
  })

  it("reads the default library before any switch", () => {
    expect(storedLibrary(memoryStorage())).toBe("default")
  })

  it("never shows one library's state in another, and keeps both", () => {
    const raw = memoryStorage()
    const scoped = libraryScopedStorage(raw)
    scoped.setItem("luminary-app-store", '{"doc":"odyssey"}')

    rememberLibrary(raw, "work")
    expect(scoped.getItem("luminary-app-store")).toBeNull()
    scoped.setItem("luminary-app-store", '{"doc":"iliad"}')

    rememberLibrary(raw, "default")
    expect(scoped.getItem("luminary-app-store")).toBe('{"doc":"odyssey"}')
    expect(raw.map.get("luminary-app-store@work")).toBe('{"doc":"iliad"}')
    expect(raw.map.get(LIBRARY_MARKER_KEY)).toBe("default")
  })

  it("removes only the current library's key", () => {
    const raw = memoryStorage()
    const scoped = libraryScopedStorage(raw)
    scoped.setItem("k", "a")
    rememberLibrary(raw, "work")
    scoped.setItem("k", "b")
    scoped.removeItem("k")
    expect(raw.map.get("k")).toBe("a")
    expect(raw.map.has("k@work")).toBe(false)
  })

  it("forgets a removed library's state and no other library's", () => {
    const store = memoryStorage()
    for (const key of ["luminary-app-store", "luminary-app-store@kids", "recent@kids", "luminary-app-store@my-kids"]) {
      store.setItem(key, "{}")
    }
    const storage = {
      ...store,
      get length() {
        return store.map.size
      },
      key: (i: number) => [...store.map.keys()][i] ?? null,
    }
    forgetLibrary(storage, "kids")
    expect([...store.map.keys()].sort()).toEqual(["luminary-app-store", "luminary-app-store@my-kids"])
    forgetLibrary(storage, "default")
    expect(store.map.size).toBe(2)
  })
})
