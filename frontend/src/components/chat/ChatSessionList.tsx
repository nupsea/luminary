import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MessageSquarePlus, Pencil, Search, Trash2, X, Check } from "lucide-react"
import { toast } from "sonner"

import {
  type ChatSessionListItem,
  deleteChatSession,
  listChatSessions,
  renameChatSession,
} from "@/lib/chatSessionsApi"

interface ChatSessionListProps {
  activeSessionId: string | null
  onSelect: (sessionId: string) => void
  onNewChat: () => void
}

export function ChatSessionList({
  activeSessionId,
  onSelect,
  onNewChat,
}: ChatSessionListProps) {
  const qc = useQueryClient()
  const [rawQuery, setRawQuery] = useState("")
  const [debouncedQuery, setDebouncedQuery] = useState("")
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState("")
  const [pendingDelete, setPendingDelete] = useState<ChatSessionListItem | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(rawQuery), 250)
    return () => clearTimeout(t)
  }, [rawQuery])

  const { data: sessions, isLoading } = useQuery({
    queryKey: ["chat-sessions", debouncedQuery],
    queryFn: () => listChatSessions(debouncedQuery || undefined),
    staleTime: 5_000,
  })

  const renameMut = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      renameChatSession(id, { title }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["chat-sessions"] })
      setRenamingId(null)
    },
    onError: () => toast.error("Could not rename chat"),
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteChatSession(id),
    onSuccess: (_, id) => {
      void qc.invalidateQueries({ queryKey: ["chat-sessions"] })
      if (activeSessionId === id) onNewChat()
      toast.success("Chat deleted")
    },
    onError: () => toast.error("Delete failed"),
  })

  const startRename = (s: ChatSessionListItem) => {
    setRenamingId(s.id)
    setRenameValue(s.title)
  }

  const grouped = useMemo(() => {
    if (!sessions) return [] as Array<{ label: string; items: ChatSessionListItem[] }>
    const buckets: Record<string, ChatSessionListItem[]> = {
      Today: [],
      Yesterday: [],
      "This week": [],
      Older: [],
    }
    // Relative-time bucketing for display only; re-render variability is harmless.
    // eslint-disable-next-line react-hooks/purity
    const now = Date.now()
    for (const s of sessions) {
      const ts = new Date(s.last_message_at).getTime()
      const ageHours = (now - ts) / 3_600_000
      if (ageHours < 24) buckets.Today.push(s)
      else if (ageHours < 48) buckets.Yesterday.push(s)
      else if (ageHours < 24 * 7) buckets["This week"].push(s)
      else buckets.Older.push(s)
    }
    return Object.entries(buckets)
      .filter(([, items]) => items.length > 0)
      .map(([label, items]) => ({ label, items }))
  }, [sessions])

  return (
    <div className="flex h-full flex-col bg-muted/20 border-r border-border">
      <div className="px-3 pt-3 pb-2 flex items-center gap-2">
        <button
          onClick={onNewChat}
          className="flex flex-1 items-center justify-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent transition-colors"
          title="Start a new chat"
        >
          <MessageSquarePlus size={14} />
          New chat
        </button>
      </div>

      <div className="px-3 pb-2">
        <div className="relative">
          <Search
            size={12}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            type="text"
            value={rawQuery}
            onChange={(e) => setRawQuery(e.target.value)}
            placeholder="Search chats"
            className="w-full rounded-md border border-border bg-background pl-7 pr-7 py-1.5 text-xs outline-none focus:ring-1 focus:ring-ring"
          />
          {rawQuery && (
            <button
              onClick={() => setRawQuery("")}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:bg-accent"
              aria-label="Clear search"
            >
              <X size={11} />
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-1.5 pb-3">
        {isLoading ? (
          <div className="px-2 py-4 text-xs text-muted-foreground">Loading...</div>
        ) : !sessions || sessions.length === 0 ? (
          <div className="px-3 py-8 text-center text-xs text-muted-foreground">
            {debouncedQuery
              ? "No chats match your search."
              : "No chats yet. Send a message to start one."}
          </div>
        ) : (
          grouped.map((group) => (
            <div key={group.label} className="mb-3">
              <div className="px-2 pt-2 pb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                {group.label}
              </div>
              {group.items.map((s) => {
                const isActive = s.id === activeSessionId
                const isRenaming = renamingId === s.id
                return (
                  <div
                    key={s.id}
                    className={`group relative rounded-md px-2 py-1.5 text-xs cursor-pointer transition-colors ${
                      isActive ? "bg-accent" : "hover:bg-accent/60"
                    }`}
                    onClick={() => !isRenaming && onSelect(s.id)}
                  >
                    {isRenaming ? (
                      <div className="flex items-center gap-1">
                        <input
                          autoFocus
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              renameMut.mutate({ id: s.id, title: renameValue })
                            } else if (e.key === "Escape") {
                              setRenamingId(null)
                            }
                          }}
                          className="flex-1 rounded border border-border bg-background px-1.5 py-1 text-xs outline-none focus:ring-1 focus:ring-ring"
                        />
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            renameMut.mutate({ id: s.id, title: renameValue })
                          }}
                          className="rounded p-1 hover:bg-accent"
                          aria-label="Save rename"
                        >
                          <Check size={12} />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setRenamingId(null)
                          }}
                          className="rounded p-1 hover:bg-accent"
                          aria-label="Cancel rename"
                        >
                          <X size={12} />
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="flex items-start justify-between gap-1">
                          <div className="flex-1 min-w-0">
                            <div className="truncate font-medium">{s.title}</div>
                            {s.preview && (
                              <div className="truncate text-muted-foreground mt-0.5">
                                {s.preview}
                              </div>
                            )}
                          </div>
                          <div className="hidden group-hover:flex items-center gap-0.5 -mr-1">
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                startRename(s)
                              }}
                              className="rounded p-1 text-muted-foreground hover:bg-background hover:text-foreground"
                              aria-label="Rename chat"
                              title="Rename"
                            >
                              <Pencil size={11} />
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                setPendingDelete(s)
                              }}
                              className="rounded p-1 text-muted-foreground hover:bg-background hover:text-destructive"
                              aria-label="Delete chat"
                              title="Delete"
                            >
                              <Trash2 size={11} />
                            </button>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                )
              })}
            </div>
          ))
        )}
      </div>

      {pendingDelete && (
        <DeleteConfirmDialog
          session={pendingDelete}
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => {
            const id = pendingDelete.id
            setPendingDelete(null)
            deleteMut.mutate(id)
          }}
        />
      )}
    </div>
  )
}

function DeleteConfirmDialog({
  session,
  onCancel,
  onConfirm,
}: {
  session: ChatSessionListItem
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-sm rounded-lg border border-border bg-background p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold">Delete this chat?</h3>
        <p className="mt-2 text-xs text-muted-foreground">
          This will permanently remove "{session.title}" and all of its messages.
          This cannot be undone.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-accent"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}
