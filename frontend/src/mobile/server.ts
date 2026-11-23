import { apiGet, configureTransport } from "@/lib/apiClient"

/** A Luminary server as the phone reaches it: its origin, and the API under it. */
export interface Server {
  origin: string
  apiBase: string
}

const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"])

/**
 * The server a typed address names, or why it cannot be used. Beyond loopback only https is
 * accepted: a phone refuses cleartext, and the token must never cross a network in the clear
 * (#535). The API lives under /api on a server, as on the bundled app.
 */
export function parseServer(input: string): Server | { error: string } {
  let url: URL
  try {
    url = new URL(input.trim().includes("://") ? input.trim() : `https://${input.trim()}`)
  } catch {
    return { error: "That is not an address." }
  }
  if (url.protocol !== "https:" && !(url.protocol === "http:" && LOOPBACK.has(url.hostname))) {
    return { error: "Use the server's https address, such as its Tailscale name." }
  }
  return { origin: url.origin, apiBase: `${url.origin}/api` }
}

interface Health {
  status: string
  version: string
  mode: string
}

/** Point every request at *server* and ask whether a Luminary answers there. */
export async function connect(server: Server): Promise<Health> {
  configureTransport({ baseUrl: server.apiBase })
  return apiGet<Health>("/health")
}
