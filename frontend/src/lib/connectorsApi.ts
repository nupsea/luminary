import { ApiError, apiDelete, apiGet, apiPost, apiPut, detailFromError } from "@/lib/apiClient"
import type { components } from "@/types/api"

export type Connector = components["schemas"]["ConnectorItem"]
export type ConnectorField = components["schemas"]["ConnectorField"]
export type ConnectorStatus = components["schemas"]["ConnectorStatus"]
export type ConnectorPreview = components["schemas"]["ConnectorPreview"]
export type ConnectorChoice = components["schemas"]["ConnectorChoice"]

/** Picked option values, by choice field. */
export type Picks = Record<string, string[]>

export const CONNECTORS_KEY = ["connectors"] as const

/** The installed connector that claims `url`, by prefix and first by name: the rule the
 *  backend's `connector_for_url` applies, so the dialog routes a link where ingest will. */
export function connectorForUrl(connectors: Connector[], url: string): Connector | null {
  const link = url.trim()
  if (!link) return null
  const sorted = [...connectors].sort((a, b) => a.name.localeCompare(b.name))
  return sorted.find((c) => c.url_prefixes.some((p) => link.startsWith(p))) ?? null
}

/** The connector a 401 asks the user to sign in to, or null for any other failure. */
export function signInRequiredFor(err: unknown): string | null {
  if (!(err instanceof ApiError) || err.status !== 401) return null
  try {
    const body = JSON.parse(err.body) as { connector?: unknown }
    return typeof body.connector === "string" && body.connector ? body.connector : null
  } catch {
    return null
  }
}

export function defaultPicks(preview: ConnectorPreview): Picks {
  return Object.fromEntries((preview.choices ?? []).map((c) => [c.field, [...(c.default ?? [])]]))
}

/** A multiple choice toggles `value`; a single one replaces its pick. */
export function togglePick(picks: Picks, choice: ConnectorChoice, value: string): Picks {
  const current = picks[choice.field] ?? []
  if (!choice.multiple) return { ...picks, [choice.field]: [value] }
  const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
  // Keep the connector's own order rather than the order of clicks.
  const order = choice.options.map((o) => o.value)
  return { ...picks, [choice.field]: next.sort((a, b) => order.indexOf(a) - order.indexOf(b)) }
}

/** The fetch input from the picks, and the labels of choices left empty. */
export function pickInput(
  preview: ConnectorPreview,
  picks: Picks,
): { input: Record<string, string | string[]>; missing: string[] } {
  const input: Record<string, string | string[]> = {}
  const missing: string[] = []
  for (const choice of preview.choices ?? []) {
    const values = picks[choice.field] ?? []
    if (values.length === 0) missing.push(choice.label)
    else input[choice.field] = choice.multiple ? values : values[0]
  }
  return { input, missing }
}

/** The values to send for a connector's fields (its sign-in or its inputs), and the labels
 *  of required fields left blank. */
export function fieldValues(
  fields: ConnectorField[],
  form: Record<string, string>,
): { values: Record<string, string>; missing: string[] } {
  const values: Record<string, string> = {}
  const missing: string[] = []
  for (const field of fields) {
    const value = (form[field.name] ?? "").trim()
    if (value) values[field.name] = value
    else if (field.required ?? true) missing.push(field.label)
  }
  return { values, missing }
}

export const listConnectors = async (): Promise<Connector[]> =>
  (await apiGet<{ connectors: Connector[] }>("/connectors")).connectors

export const connectorStatus = (name: string): Promise<ConnectorStatus> =>
  apiGet<ConnectorStatus>(`/connectors/${encodeURIComponent(name)}/status`)

export async function connectConnector(
  name: string,
  values: Record<string, string>,
): Promise<ConnectorStatus> {
  try {
    return await apiPut<ConnectorStatus>(`/connectors/${encodeURIComponent(name)}/credentials`, {
      values,
    })
  } catch (err) {
    throw detailFromError(err, "Could not connect")
  }
}

export async function disconnectConnector(name: string): Promise<void> {
  try {
    await apiDelete(`/connectors/${encodeURIComponent(name)}/credentials`)
  } catch (err) {
    throw detailFromError(err, "Could not disconnect")
  }
}

/** Throws the raw error, so a 401 still names the connector to sign in to. */
export const previewLink = (name: string, url: string): Promise<ConnectorPreview> =>
  apiPost<ConnectorPreview>(`/connectors/${encodeURIComponent(name)}/preview`, { url })

export const ingestLink = async (
  name: string,
  url: string,
  input: Record<string, string | string[]>,
): Promise<string> =>
  (
    await apiPost<{ document_id: string }>(`/connectors/${encodeURIComponent(name)}/ingest`, {
      url,
      input,
    })
  ).document_id
