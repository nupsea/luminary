// An install must refresh every screen that names a model, not just the one that ran it.

import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"

import { refreshModelState } from "./setupApi"

describe("refreshModelState", () => {
  it("refreshes Ask's Auto model, the model banner, Settings and the setup screen together", async () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, "invalidateQueries")
    await refreshModelState(qc)
    const keys = spy.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey))
    for (const key of ["setup", "llm-settings", "host-support", "settings-models"]) {
      expect(keys).toContain(JSON.stringify([key]))
    }
  })
})
