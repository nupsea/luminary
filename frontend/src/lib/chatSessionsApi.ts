import { API_BASE } from "@/lib/config"

export interface ChatSessionListItem {
  id: string
  title: string
  scope: "single" | "all"
  document_ids: string[]
  model: string | null
  title_auto: boolean
  created_at: string
  updated_at: string
  last_message_at: string
  preview: string
}

export interface PersistedMessage {
  id: string
  session_id: string
  role: "user" | "assistant"
  content: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  extra: Record<string, any> | null
  created_at: string
}

export interface ChatSessionDetail extends Omit<ChatSessionListItem, "preview"> {
  messages: PersistedMessage[]
}

export interface CreateSessionInput {
  scope: "single" | "all"
  document_ids: string[]
  model: string | null
  title?: string
}

export interface AppendMessageInput {
  role: "user" | "assistant"
  content: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  extra?: Record<string, any> | null
}

const BASE = `${API_BASE}/chat/sessions`

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new Error(`Request failed: ${res.status} ${body || res.statusText}`)
  }
  return (await res.json()) as T
}

export async function listChatSessions(q?: string): Promise<ChatSessionListItem[]> {
  const url = q && q.trim() ? `${BASE}?q=${encodeURIComponent(q.trim())}` : BASE
  return jsonOrThrow<ChatSessionListItem[]>(await fetch(url))
}

export async function createChatSession(input: CreateSessionInput): Promise<ChatSessionListItem> {
  return jsonOrThrow<ChatSessionListItem>(
    await fetch(BASE, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  )
}

export async function getChatSession(id: string): Promise<ChatSessionDetail> {
  return jsonOrThrow<ChatSessionDetail>(await fetch(`${BASE}/${id}`))
}

export async function renameChatSession(
  id: string,
  body: { title?: string; auto_from_message?: string },
): Promise<ChatSessionListItem> {
  return jsonOrThrow<ChatSessionListItem>(
    await fetch(`${BASE}/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  )
}

export async function deleteChatSession(id: string): Promise<void> {
  const res = await fetch(`${BASE}/${id}`, { method: "DELETE" })
  if (!res.ok) {
    throw new Error(`Delete failed: ${res.status}`)
  }
}

export async function appendChatMessage(
  sessionId: string,
  input: AppendMessageInput,
): Promise<PersistedMessage> {
  return jsonOrThrow<PersistedMessage>(
    await fetch(`${BASE}/${sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  )
}
