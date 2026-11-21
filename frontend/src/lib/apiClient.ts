// apiClient — the only module that calls fetch (enforced by eslint.config.js).
// Centralises: transport (base URL + auth headers), JSON encode/decode, query params,
// ApiError mapping, 204 handling.

import { API_BASE } from "@/lib/config"

/** Where requests go and what every one of them carries. Set once at boot. */
export interface ApiTransport {
  baseUrl: string
  /** Headers added to every request unless the caller set the same name, e.g. a device token. */
  headers?: () => HeadersInit
  /** A fetch to use instead of the global one, e.g. a native client that pins the server's certificate. */
  fetch?: typeof fetch
}

let transport: ApiTransport = { baseUrl: API_BASE }

/** Replace the transport; the desktop app keeps the default (same origin, no token).
 *  Call before the first render: components memoise URLs built from the base. */
export function configureTransport(next: ApiTransport): void {
  transport = next
}

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

/**
 * The server's own `detail` message from a failed request, or a fallback.
 *
 * FastAPI puts the actionable text in `detail`; `ApiError.message` is
 * `HTTP 409: {"detail":"..."}`, which is not something to show a user. Lives
 * here because every caller of `request` gets an `ApiError` and needs the same
 * unwrapping — it was written twice before this, once against `Response` and
 * once against `ApiError`.
 */
/** An error whose fix is installing components the app can fetch itself.
 *
 *  Carries the ids so the caller can offer the install rather than restating a
 *  sentence the user has to act on somewhere else.
 */
export class ComponentsRequiredError extends Error {
  readonly components: string[]
  constructor(message: string, components: string[]) {
    super(message)
    this.name = "ComponentsRequiredError"
    this.components = components
  }
}

export function detailFromError(err: unknown, fallback: string): Error {
  if (err instanceof ApiError) {
    try {
      const parsed = JSON.parse(err.body) as { detail?: unknown }
      if (typeof parsed.detail === "string" && parsed.detail) return new Error(parsed.detail)
      // A structured detail must not fall through to the generic fallback: it
      // carries a better message than `fallback` plus the components to offer.
      if (parsed.detail && typeof parsed.detail === "object") {
        const d = parsed.detail as { message?: unknown; components?: unknown }
        const message = typeof d.message === "string" && d.message ? d.message : fallback
        if (Array.isArray(d.components) && d.components.length > 0) {
          return new ComponentsRequiredError(message, d.components.map(String))
        }
        if (message !== fallback) return new Error(message)
      }
    } catch {
      // body wasn't JSON
    }
    return new Error(fallback)
  }
  return err instanceof Error ? err : new Error(fallback)
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

export function apiBaseUrl(): string {
  return transport.baseUrl
}

/** The URL of an API path, for `src=` and other places that cannot carry headers. */
export function apiUrl(path: string): string {
  return path.startsWith("http") ? path : `${transport.baseUrl}${path}`
}

function buildUrl(path: string, params?: QueryParams): string {
  const base = apiUrl(path)
  if (!params) return base
  const url = new URL(base, window.location.origin)
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue
    url.searchParams.set(key, String(value))
  }
  return url.toString()
}

// The transport's headers (a device token) go only to the server the transport points at.
function isTransportOrigin(url: string): boolean {
  const here = typeof window === "undefined" ? undefined : window.location.origin
  try {
    return new URL(url, here).origin === new URL(transport.baseUrl, here).origin
  } catch {
    return !/^[a-z][a-z\d+.-]*:/i.test(url) && !/^[a-z][a-z\d+.-]*:/i.test(transport.baseUrl)
  }
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

/**
 * The raw `Response`, whatever its status: for streams (SSE over fetch), binary
 * downloads and callers that map statuses to their own messages.
 */
export async function apiFetch(
  path: string,
  { body, params, headers, ...init }: RequestOptions = {},
): Promise<Response> {
  const hasBody = body !== undefined && body !== null
  const encoded = hasBody && !isPlainBody(body) ? JSON.stringify(body) : (body as BodyInit | null | undefined)
  const finalHeaders = new Headers(headers)
  if (hasBody && !isPlainBody(body) && !finalHeaders.has("Content-Type")) {
    finalHeaders.set("Content-Type", "application/json")
  }
  const url = buildUrl(path, params)
  if (transport.headers && isTransportOrigin(url)) {
    new Headers(transport.headers()).forEach((value, name) => {
      if (!finalHeaders.has(name)) finalHeaders.set(name, value)
    })
  }
  // Looked up per call, not captured at import, so a replaced global fetch is the one used.
  const send = transport.fetch ?? fetch
  return send(url, {
    ...init,
    headers: finalHeaders,
    body: encoded ?? undefined,
  })
}

// Returns parsed JSON, or `null` for 204 No Content. Throws `ApiError` on non-2xx.
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const res = await apiFetch(path, options)
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
