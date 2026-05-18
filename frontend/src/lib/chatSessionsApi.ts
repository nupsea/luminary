import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/apiClient"

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

const PATH = "/chat/sessions"

export const listChatSessions = (q?: string): Promise<ChatSessionListItem[]> =>
  apiGet<ChatSessionListItem[]>(PATH, { q: q?.trim() || undefined })

export const createChatSession = (
  input: CreateSessionInput,
): Promise<ChatSessionListItem> => apiPost<ChatSessionListItem>(PATH, input)

export const getChatSession = (id: string): Promise<ChatSessionDetail> =>
  apiGet<ChatSessionDetail>(`${PATH}/${id}`)

export const renameChatSession = (
  id: string,
  body: { title?: string; auto_from_message?: string },
): Promise<ChatSessionListItem> =>
  apiPatch<ChatSessionListItem>(`${PATH}/${id}`, body)

export const deleteChatSession = (id: string): Promise<void> =>
  apiDelete(`${PATH}/${id}`)

export const appendChatMessage = (
  sessionId: string,
  input: AppendMessageInput,
): Promise<PersistedMessage> =>
  apiPost<PersistedMessage>(`${PATH}/${sessionId}/messages`, input)
