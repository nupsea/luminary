import { onlineManager } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"
import { createQueryClient } from "./queryClient"

describe("createQueryClient with the machine offline", () => {
  afterEach(() => {
    onlineManager.setOnline(true)
  })

  it("still reaches the local backend for queries and mutations", async () => {
    const client = createQueryClient()
    // The state the webview's "offline" event puts the manager in.
    onlineManager.setOnline(false)

    const fetchDocs = vi.fn().mockResolvedValue(["doc"])
    const docs = await client.fetchQuery({ queryKey: ["documents"], queryFn: fetchDocs })
    expect(docs).toEqual(["doc"])

    const save = vi.fn().mockResolvedValue("saved")
    const mutation = client.getMutationCache().build(client, { mutationFn: save })
    await expect(mutation.execute(undefined)).resolves.toBe("saved")
  })
})
