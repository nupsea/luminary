import { afterEach, describe, expect, it, vi } from "vitest"

import {
  ApiError,
  apiBaseUrl,
  apiFetch,
  apiUrl,
  ComponentsRequiredError,
  configureTransport,
  detailFromError,
  request,
} from "./apiClient"
import { API_BASE } from "./config"

function apiError(detail: unknown, status = 503): ApiError {
  return new ApiError(status, "Service Unavailable", JSON.stringify({ detail }))
}

describe("detailFromError", () => {
  it("uses a string detail", () => {
    expect(detailFromError(apiError("no such document", 404), "fallback").message).toBe(
      "no such document",
    )
  })

  it("carries components from a structured detail", () => {
    // The regression this guards: `detail` became an object, and the old code
    // only understood strings -- so a message naming exactly what to install
    // was discarded and the user saw the bare fallback instead.
    const err = detailFromError(
      apiError({
        message: "YouTube needs Speech to text and Audio and video support.",
        components: ["transcription", "ffmpeg"],
      }),
      "Upload failed",
    )
    expect(err).toBeInstanceOf(ComponentsRequiredError)
    expect(err.message).toContain("Speech to text")
    expect((err as ComponentsRequiredError).components).toEqual(["transcription", "ffmpeg"])
  })

  it("keeps a structured message even with no components", () => {
    const err = detailFromError(apiError({ message: "something specific" }), "Upload failed")
    expect(err).not.toBeInstanceOf(ComponentsRequiredError)
    expect(err.message).toBe("something specific")
  })

  it("falls back when the detail carries nothing usable", () => {
    expect(detailFromError(apiError({}), "Upload failed").message).toBe("Upload failed")
    expect(detailFromError(new Error("boom"), "Upload failed").message).toBe("boom")
  })
})

describe("transport", () => {
  const originalFetch = globalThis.fetch

  afterEach(() => {
    globalThis.fetch = originalFetch
    configureTransport({ baseUrl: API_BASE })
  })

  function stubFetch(response: Response): ReturnType<typeof vi.fn> {
    const stub = vi.fn().mockResolvedValue(response)
    globalThis.fetch = stub as unknown as typeof fetch
    return stub
  }

  it("defaults to the build-time base and adds no headers", async () => {
    const stub = stubFetch(new Response("{}", { status: 200 }))
    await apiFetch("/notes")
    const [url, init] = stub.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(`${API_BASE}/notes`)
    expect([...new Headers(init.headers).keys()]).toEqual([])
    expect(apiUrl("/images/x/raw")).toBe(`${API_BASE}/images/x/raw`)
  })

  it("applies the transport's base, headers and fetch, and lets the caller's header win", async () => {
    const native = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }))
    const global = stubFetch(new Response("{}", { status: 200 }))
    configureTransport({
      baseUrl: "https://desk.example:7820",
      headers: () => ({ Authorization: "Bearer lum_x", "X-Trace": "transport" }),
      fetch: native as unknown as typeof fetch,
    })
    await apiFetch("/notes", { headers: { "X-Trace": "caller" } })
    expect(global).not.toHaveBeenCalled()
    const [url, init] = native.mock.calls[0] as [string, RequestInit]
    expect(url).toBe("https://desk.example:7820/notes")
    const headers = new Headers(init.headers)
    expect(headers.get("Authorization")).toBe("Bearer lum_x")
    expect(headers.get("X-Trace")).toBe("caller")
    expect(apiUrl("/documents/d/file")).toBe("https://desk.example:7820/documents/d/file")
    expect(apiBaseUrl()).toBe("https://desk.example:7820")
  })

  it("passes an absolute URL through unprefixed", () => {
    configureTransport({ baseUrl: "https://desk.example:7820" })
    expect(apiUrl("http://localhost:9/x")).toBe("http://localhost:9/x")
  })

  it("returns a non-2xx response from apiFetch, and request maps it to ApiError", async () => {
    stubFetch(new Response('{"detail":"gone"}', { status: 404, statusText: "Not Found" }))
    const res = await apiFetch("/notes/n")
    expect(res.status).toBe(404)
    stubFetch(new Response('{"detail":"gone"}', { status: 404, statusText: "Not Found" }))
    const err = await request("/notes/n").catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(404)
    expect(detailFromError(err, "fallback").message).toBe("gone")
  })

  it("streams a response body", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"token":"a"}\n\n'))
        controller.enqueue(new TextEncoder().encode('data: {"token":"b"}\n\n'))
        controller.close()
      },
    })
    stubFetch(new Response(body, { status: 200 }))
    const res = await apiFetch("/qa", { method: "POST", body: { question: "q" } })
    expect(await res.text()).toBe('data: {"token":"a"}\n\ndata: {"token":"b"}\n\n')
  })

  it("encodes an object body as JSON and passes a string body through", async () => {
    const stub = stubFetch(new Response("{}", { status: 200 }))
    await apiFetch("/qa", { method: "POST", body: { question: "q" } })
    await apiFetch("/qa", { method: "POST", body: '{"raw":1}', headers: { "Content-Type": "application/json" } })
    const [, objInit] = stub.mock.calls[0] as [string, RequestInit]
    const [, strInit] = stub.mock.calls[1] as [string, RequestInit]
    expect(objInit.body).toBe('{"question":"q"}')
    expect(new Headers(objInit.headers).get("Content-Type")).toBe("application/json")
    expect(strInit.body).toBe('{"raw":1}')
  })

  it("forwards the abort signal", async () => {
    const controller = new AbortController()
    globalThis.fetch = vi.fn((_url: string, init: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))
      }),
    ) as unknown as typeof fetch
    const pending = apiFetch("/explain", { method: "POST", signal: controller.signal })
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: "AbortError" })
  })
})
