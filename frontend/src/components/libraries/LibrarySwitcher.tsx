// The open library, at the top of the rail: its tile opens a list to switch libraries.

import { useEffect, useRef, useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { Check, Library, Settings2 } from "lucide-react"
import { toast } from "sonner"

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { openLibrary, useLibraries, type LibraryList } from "@/hooks/useLibraries"
import { apiPut, detailFromError } from "@/lib/apiClient"
import { libraryTitle } from "@/lib/libraryLook"
import { cn } from "@/lib/utils"

import { LibraryManager, LibraryTile } from "./LibraryManager"

function countsLine(contents: LibraryList["libraries"][number]["contents"]): string {
  if (!contents) return ""
  return `${contents.documents.toLocaleString()} docs · ${contents.flashcards.toLocaleString()} cards`
}

export function LibrarySwitcher() {
  const data = useLibraries()
  const [open, setOpen] = useState(false)
  const [managing, setManaging] = useState(false)
  const [anchor, setAnchor] = useState<DOMRect | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)

  const switchTo = useMutation({
    mutationFn: (library: string) => apiPut<LibraryList>("/libraries/active", { library }),
    onSuccess: (list) => openLibrary(list.active),
    onError: (err) => toast.error(detailFromError(err, "Could not open that library").message),
  })

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !menu.current?.contains(e.target as Node) && !button.current?.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", close)
    document.addEventListener("keydown", close)
    return () => {
      document.removeEventListener("mousedown", close)
      document.removeEventListener("keydown", close)
    }
  }, [open])

  // A paired device is refused the list: it has no libraries to switch.
  if (!data) return null
  const active = data.libraries.find((l) => l.active)

  return (
    <>
      <button
        ref={button}
        onClick={() => {
          setAnchor(button.current?.getBoundingClientRect() ?? null)
          setOpen((o) => !o)
        }}
        title={active ? `Library: ${libraryTitle(active)}` : "Libraries"}
        aria-label="Switch library"
        aria-expanded={open}
        className="mb-2 rounded-xl p-1 transition-colors hover:bg-accent"
      >
        {active ? <LibraryTile item={active} /> : <Library size={18} />}
      </button>

      {open && anchor && (
        <div
          ref={menu}
          role="menu"
          style={{ top: anchor.top, left: anchor.right + 8 }}
          className="fixed z-50 w-64 rounded-lg border border-border bg-popover p-1.5 text-popover-foreground shadow-lg"
        >
          <p className="px-2 pb-1 pt-0.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Libraries
          </p>
          {data.libraries.map((lib) => (
            <button
              key={lib.id}
              role="menuitem"
              disabled={switchTo.isPending}
              onClick={() => (lib.active ? setOpen(false) : switchTo.mutate(lib.id))}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-accent disabled:opacity-60",
                lib.active && "bg-accent/60",
              )}
            >
              <LibraryTile item={lib} size="sm" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-foreground">{libraryTitle(lib)}</span>
                <span className="block truncate text-[11px] text-muted-foreground">
                  {switchTo.isPending && switchTo.variables === lib.id ? "Opening…" : countsLine(lib.contents)}
                </span>
              </span>
              {lib.active && <Check size={14} className="text-primary" />}
            </button>
          ))}
          <div className="my-1 border-t border-border" />
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false)
              setManaging(true)
            }}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-foreground hover:bg-accent"
          >
            <Settings2 size={14} className="text-muted-foreground" /> New, rename, move…
          </button>
        </div>
      )}

      <Dialog open={managing} onOpenChange={setManaging}>
        <DialogContent className="max-h-[85vh] max-w-xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Libraries</DialogTitle>
            <DialogDescription className="sr-only">Create, rename, open, remove and move libraries.</DialogDescription>
          </DialogHeader>
          <LibraryManager />
        </DialogContent>
      </Dialog>
    </>
  )
}
