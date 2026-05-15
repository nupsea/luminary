// ---------------------------------------------------------------------------
// apiClient -- single fetch entry point for the Luminary frontend.
//
// All `*Api.ts` modules should funnel through `request<T>` (or the verb
// helpers below) instead of calling `fetch` directly. This centralises:
//   - base URL prefixing (`API_BASE` from config)
//   - JSON encoding/decoding
//   - query-param serialisation
//   - error mapping (failures throw `ApiError`, never plain `Error`)
//   - 204 No Content handling (returns `null`)
//
// See `frontend/src/lib/goalsApi.ts` for the canonical usage pattern.
// ---------------------------------------------------------------------------

import { API_BASE } from "@/lib/config"

export class ApiError extends Error {
  readonly status: number
  readonly body: string
  constructor(status: number, statusText: string, body: string) {
    super(`HTTP ${status}: ${body || statusText}`)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

export type QueryParams = Record<
  string,
  string | number | boolean | null | undefined
>

export interface RequestOptions extends Omit<RequestInit, "body"> {
  // Object bodies are JSON-encoded; strings, FormData, Blob etc. are passed through.
  body?: unknown
  // Query string params; nullish values are skipped.
  params?: QueryParams
}

function buildUrl(path: string, params?: QueryParams): string {
  const base = path.startsWith("http") ? path : `${API_BASE}${path}`
  if (!params) return base
  const url = new URL(base)
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue
    url.searchParams.set(key, String(value))
  }
  return url.toString()
}

function isPlainBody(body: unknown): boolean {
  return (
    body instanceof FormData ||
    body instanceof Blob ||
    body instanceof ArrayBuffer ||
    body instanceof URLSearchParams ||
    typeof body === "string"
  )
}

// Returns parsed JSON, or `null` for 204 No Content. Throws `ApiError` on non-2xx.
export async function request<T>(
  path: string,
  { body, params, headers, ...init }: RequestOptions = {},
): Promise<T> {
  const hasBody = body !== undefined && body !== null
  const encoded = hasBody && !isPlainBody(body) ? JSON.stringify(body) : (body as BodyInit | null | undefined)
  const finalHeaders = new Headers(headers)
  if (hasBody && !isPlainBody(body) && !finalHeaders.has("Content-Type")) {
    finalHeaders.set("Content-Type", "application/json")
  }
  const res = await fetch(buildUrl(path, params), {
    ...init,
    headers: finalHeaders,
    body: encoded ?? undefined,
  })
  if (!res.ok) {
    const errBody = await res.text().catch(() => "")
    throw new ApiError(res.status, res.statusText, errBody)
  }
  if (res.status === 204) return null as T
  return (await res.json()) as T
}

export const apiGet = <T>(path: string, params?: QueryParams): Promise<T> =>
  request<T>(path, { params })

export const apiPost = <T>(path: string, body?: unknown): Promise<T> =>
  request<T>(path, { method: "POST", body })

export const apiPatch = <T>(path: string, body?: unknown): Promise<T> =>
  request<T>(path, { method: "PATCH", body })

export const apiPut = <T>(path: string, body?: unknown): Promise<T> =>
  request<T>(path, { method: "PUT", body })

export const apiDelete = <T = void>(path: string): Promise<T> =>
  request<T>(path, { method: "DELETE" })
