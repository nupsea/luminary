// The spaces on this machine (libraries, in the code): name and colour them, open one, remove one, and move one to
// another computer through a folder a sync service keeps (iCloud Drive, Dropbox, ...).

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Copy, FolderOpen, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { LIBRARIES_KEY, fetchLibraries, openLibrary, type LibraryList } from "@/hooks/useLibraries"
import { apiDelete, apiGet, apiPatch, apiPost, apiPut, detailFromError } from "@/lib/apiClient"
import {
  COLOR_IDS,
  LIBRARY_COLORS,
  ago,
  libraryColor,
  libraryIdFor,
  libraryInitials,
  libraryTitle,
  type LibraryColor,
} from "@/lib/libraryLook"
import { DEFAULT_LIBRARY, forgetLibrary } from "@/lib/libraryScope"
import { describeContents, suggestedLibraryName } from "@/lib/libraryTransfer"
import { formatBytes } from "@/lib/setupApi"
import { cn } from "@/lib/utils"
import type { components } from "@/types/api"

type LibraryItem = components["schemas"]["LibraryItem"]
type LibraryExport = components["schemas"]["LibraryExport"]
type LibraryImport = components["schemas"]["LibraryImport"]
type LibraryRemoved = components["schemas"]["LibraryRemoved"]
type DestinationList = components["schemas"]["DestinationList"]

const DESTINATIONS_KEY = ["libraries", "destinations"]

const BUTTON =
  "inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-foreground hover:bg-accent disabled:opacity-50"
const PRIMARY =
  "inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
const DANGER =
  "inline-flex items-center gap-1 rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
const INPUT =
  "rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground placeholder:text-muted-foreground"
const HEADING = "text-xs font-semibold uppercase tracking-wide text-muted-foreground"

const fail = (fallback: string) => (err: unknown) => toast.error(detailFromError(err, fallback).message)

export function LibraryTile({ item, size = "md" }: { item: LibraryItem; size?: "sm" | "md" }) {
  return (
    <span
      className={cn(
        "flex flex-shrink-0 items-center justify-center rounded-lg font-semibold",
        LIBRARY_COLORS[libraryColor(item)].tile,
        size === "sm" ? "h-6 w-6 text-[10px]" : "h-9 w-9 text-xs",
      )}
      aria-hidden
    >
      {libraryInitials(libraryTitle(item))}
    </span>
  )
}

function ColorPicker({ value, onChange }: { value: LibraryColor; onChange: (c: LibraryColor) => void }) {
  return (
    <div className="flex gap-1.5" role="radiogroup" aria-label="Colour">
      {COLOR_IDS.map((c) => (
        <button
          key={c}
          type="button"
          role="radio"
          aria-checked={value === c}
          aria-label={c}
          onClick={() => onChange(c)}
          className={cn(
            "flex h-5 w-5 items-center justify-center rounded-full",
            LIBRARY_COLORS[c].swatch,
            value === c && "ring-2 ring-foreground ring-offset-1 ring-offset-background",
          )}
        >
          {value === c && <Check size={11} className="text-white" />}
        </button>
      ))}
    </div>
  )
}

function summary(item: LibraryItem): string {
  const parts = item.contents ? [describeContents(item.contents)] : ["contents unreadable"]
  return [...parts, formatBytes(item.bytes)].join(" · ")
}

function LibraryRow({ item, busy, onOpen }: { item: LibraryItem; busy: boolean; onOpen: () => void }) {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<"view" | "edit" | "remove">("view")
  const [name, setName] = useState(libraryTitle(item))
  const [color, setColor] = useState<LibraryColor>(libraryColor(item))
  const [confirm, setConfirm] = useState("")

  const save = useMutation({
    mutationFn: () => apiPatch<LibraryList>(`/libraries/${item.id}`, { name: name.trim() || null, color }),
    onSuccess: (list) => {
      queryClient.setQueryData(LIBRARIES_KEY, list)
      setMode("view")
    },
    onError: fail("Could not rename the space"),
  })
  const remove = useMutation({
    mutationFn: () => apiDelete<LibraryRemoved>(`/libraries/${item.id}`),
    onSuccess: (result) => {
      forgetLibrary(localStorage, result.library)
      toast.success(
        result.removed_now
          ? `Removed ${libraryTitle(item)}.`
          : `Removed ${libraryTitle(item)}. Its files are deleted when Luminary next starts.`,
      )
      void queryClient.invalidateQueries({ queryKey: LIBRARIES_KEY })
    },
    onError: fail("Could not remove the space"),
  })

  return (
    <li className="space-y-2 px-3 py-2.5">
      <div className="flex items-center gap-3">
        <LibraryTile item={item} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground">
            {libraryTitle(item)}
            {item.active && (
              <span className="ml-2 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                open
              </span>
            )}
          </p>
          <p className="truncate text-xs text-muted-foreground">{summary(item)}</p>
        </div>
        {mode === "view" && (
          <div className="flex flex-shrink-0 gap-1.5">
            {!item.active && (
              <button onClick={onOpen} disabled={busy} className={BUTTON}>
                Open
              </button>
            )}
            <button onClick={() => setMode("edit")} className={BUTTON} title="Rename or recolour" aria-label="Edit">
              <Pencil size={12} />
            </button>
            {!item.active && item.id !== DEFAULT_LIBRARY && (
              <button onClick={() => setMode("remove")} className={BUTTON} title="Remove" aria-label="Remove">
                <Trash2 size={12} />
              </button>
            )}
          </div>
        )}
      </div>

      {mode === "edit" && (
        <form
          className="space-y-2 pl-12"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={40}
            aria-label="Space name"
            className={cn(INPUT, "w-full")}
            autoFocus
          />
          <ColorPicker value={color} onChange={setColor} />
          <div className="flex gap-2">
            <button type="submit" disabled={save.isPending} className={PRIMARY}>
              Save
            </button>
            <button type="button" onClick={() => setMode("view")} className={BUTTON}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {mode === "remove" && (
        <form
          className="space-y-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault()
            if (confirm === item.id) remove.mutate()
          }}
        >
          <p className="text-foreground">
            This deletes every document, note, card and review in {libraryTitle(item)} from this
            computer. Export it first if you might want it back. Type{" "}
            <code className="font-mono font-semibold">{item.id}</code> to confirm.
          </p>
          <input
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            aria-label="Type the space id to confirm"
            className={cn(INPUT, "w-full")}
            autoFocus
          />
          <div className="flex gap-2">
            <button type="submit" disabled={confirm !== item.id || remove.isPending} className={DANGER}>
              <Trash2 size={12} /> Remove {libraryTitle(item)}
            </button>
            <button type="button" onClick={() => setMode("view")} className={BUTTON}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </li>
  )
}

function NewLibrary({ taken, onCreated }: { taken: string[]; onCreated: (list: LibraryList) => void }) {
  const [name, setName] = useState("")
  const [color, setColor] = useState<LibraryColor>("blue")
  const id = libraryIdFor(name, taken)
  const create = useMutation({
    mutationFn: () => apiPost<LibraryList>("/libraries", { library: id, name: name.trim(), color }),
    onSuccess: (list) => {
      onCreated(list)
      setName("")
    },
    onError: fail("Could not create the space"),
  })
  return (
    <form
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (name.trim()) create.mutate()
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={40}
          placeholder="Name, e.g. Personal, Work, Kids"
          aria-label="New space name"
          className={cn(INPUT, "min-w-0 flex-1")}
        />
        <button type="submit" disabled={!name.trim() || create.isPending} className={PRIMARY}>
          <Plus size={12} /> Create
        </button>
      </div>
      <div className="flex items-center justify-between gap-2">
        <ColorPicker value={color} onChange={setColor} />
        {name.trim() && <span className="text-[11px] text-muted-foreground">folder: {id}</span>}
      </div>
    </form>
  )
}

function ExportPanel({ libraries, destinations }: { libraries: LibraryItem[]; destinations: DestinationList["destinations"] }) {
  const queryClient = useQueryClient()
  const [library, setLibrary] = useState(() => libraries.find((l) => l.active)?.id ?? DEFAULT_LIBRARY)
  // A sync folder, when there is one: it is what reaches the other computer.
  const [destination, setDestination] = useState(
    () => destinations.find((d) => d.kind !== "exports")?.id ?? "exports",
  )
  const [exported, setExported] = useState<LibraryExport | null>(null)

  const run = useMutation({
    mutationFn: () => apiPost<LibraryExport>(`/libraries/${library}/export`, { destination }),
    onSuccess: (result) => {
      setExported(result)
      void queryClient.invalidateQueries({ queryKey: DESTINATIONS_KEY })
    },
    onError: fail("Could not export the space"),
  })
  const reveal = useMutation({
    mutationFn: (ref: { destination: string; name: string }) => apiPost("/libraries/reveal", ref),
    onError: fail("Could not show the file"),
  })

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-foreground">
        <span>Export</span>
        <select value={library} onChange={(e) => setLibrary(e.target.value)} aria-label="Space to export" className={INPUT}>
          {libraries.map((l) => (
            <option key={l.id} value={l.id}>
              {libraryTitle(l)}
            </option>
          ))}
        </select>
        <span>to</span>
        <select
          value={destination}
          onChange={(e) => setDestination(e.target.value)}
          aria-label="Export to"
          className={cn(INPUT, "min-w-0 max-w-[14rem]")}
        >
          {destinations.map((d) => (
            <option key={d.id} value={d.id}>
              {d.kind === "exports" ? "Luminary Exports (this computer only)" : d.name}
            </option>
          ))}
        </select>
        <button onClick={() => run.mutate()} disabled={run.isPending} className={PRIMARY}>
          {run.isPending ? "Exporting…" : "Export"}
        </button>
      </div>
      {run.isPending && (
        <p className="text-xs text-muted-foreground">
          Copying the database, vectors and files into one archive. A large space takes a few minutes.
        </p>
      )}
      {exported && (
        <div className="space-y-1.5 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs">
          <p className="text-foreground">
            Exported {describeContents(exported.contents)} ({formatBytes(exported.bytes)}) to{" "}
            <span className="font-medium">{exported.destination_name}</span>:
          </p>
          <code className="block break-all font-mono text-[11px] text-foreground">{exported.path}</code>
          <div className="flex gap-2">
            <button
              onClick={() => reveal.mutate({ destination: exported.destination, name: exported.name })}
              className={BUTTON}
            >
              <FolderOpen size={12} /> Show in folder
            </button>
            <button onClick={() => void navigator.clipboard.writeText(exported.path)} className={BUTTON}>
              <Copy size={12} /> Copy path
            </button>
          </div>
          <p className="text-muted-foreground">
            {exported.destination === "exports"
              ? "Copy this file to the other computer (AirDrop, a USB drive) and import it there."
              : `Once ${exported.destination_name} has synced it, open Spaces on the other computer: it is listed there under Import.`}
          </p>
        </div>
      )}
    </div>
  )
}

function ImportPanel({
  libraries,
  destinations,
  refreshing,
  onRefresh,
  onOpen,
}: {
  libraries: LibraryItem[]
  destinations: DestinationList["destinations"]
  refreshing: boolean
  onRefresh: () => void
  onOpen: (id: string) => void
}) {
  const queryClient = useQueryClient()
  const taken = libraries.map((l) => l.id)
  const [picked, setPicked] = useState<{ destination: string; name: string } | null>(null)
  const [libraryName, setLibraryName] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [imported, setImported] = useState<LibraryImport | null>(null)

  const done = (result: LibraryImport) => {
    setImported(result)
    setPicked(null)
    setFile(null)
    setLibraryName("")
    void queryClient.invalidateQueries({ queryKey: LIBRARIES_KEY })
  }
  const fromFolder = useMutation({
    mutationFn: (req: { destination: string; name: string; library: string }) =>
      apiPost<LibraryImport>("/libraries/import-from-folder", req),
    onSuccess: done,
    onError: fail("Could not import the space"),
  })
  const fromFile = useMutation({
    mutationFn: ({ upload, library }: { upload: File; library: string }) => {
      const form = new FormData()
      form.append("file", upload)
      form.append("library", library)
      return apiPost<LibraryImport>("/libraries/import", form)
    },
    onSuccess: done,
    onError: fail("Could not import the space"),
  })
  const pending = fromFolder.isPending || fromFile.isPending
  const suggest = (fileName: string) => libraryIdFor(suggestedLibraryName(fileName) || "imported", taken)
  const found = destinations.flatMap((d) => d.archives.map((a) => ({ ...a, destination: d })))

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground">Found in your folders</p>
        <button onClick={onRefresh} disabled={refreshing} className={BUTTON} aria-label="Look again">
          <RefreshCw size={12} className={cn(refreshing && "animate-spin")} /> Look again
        </button>
      </div>
      {found.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
          No exported spaces in {destinations.map((d) => (d.kind === "exports" ? "Luminary Exports" : d.name)).join(", ")}.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {found.map((a) => {
            const key = `${a.destination.id}/${a.name}`
            const open = picked?.destination === a.destination.id && picked.name === a.name
            return (
              <li key={key} className="space-y-2 px-3 py-2">
                <div className="flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-[11px] text-foreground">{a.name}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {a.destination.kind === "exports" ? "Luminary Exports" : a.destination.name} ·{" "}
                      {formatBytes(a.bytes)} · {ago(a.modified)}
                    </p>
                  </div>
                  {!open && (
                    <button
                      onClick={() => {
                        setPicked({ destination: a.destination.id, name: a.name })
                        setLibraryName(suggest(a.name))
                      }}
                      disabled={pending}
                      className={BUTTON}
                    >
                      Import…
                    </button>
                  )}
                </div>
                {open && (
                  <form
                    className="flex flex-wrap items-center gap-2"
                    onSubmit={(e) => {
                      e.preventDefault()
                      if (libraryName.trim()) fromFolder.mutate({ ...picked, library: libraryName.trim() })
                    }}
                  >
                    <span className="text-xs text-muted-foreground">as</span>
                    <input
                      value={libraryName}
                      onChange={(e) => setLibraryName(e.target.value.toLowerCase())}
                      aria-label="Folder name for the imported space"
                      className={cn(INPUT, "min-w-0 flex-1 font-mono text-xs")}
                      autoFocus
                    />
                    <button type="submit" disabled={!libraryName.trim() || pending} className={PRIMARY}>
                      {fromFolder.isPending ? "Importing…" : "Import"}
                    </button>
                    <button type="button" onClick={() => setPicked(null)} className={BUTTON}>
                      Cancel
                    </button>
                  </form>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
          Import a file from somewhere else
        </summary>
        <form
          className="mt-2 space-y-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (file && libraryName.trim()) fromFile.mutate({ upload: file, library: libraryName.trim() })
          }}
        >
          <input
            type="file"
            accept=".gz,application/gzip"
            aria-label="Exported space file"
            onChange={(e) => {
              const chosen = e.target.files?.[0] ?? null
              setFile(chosen)
              setPicked(null)
              if (chosen) setLibraryName(suggest(chosen.name))
            }}
            className="block w-full text-xs text-foreground file:mr-2 file:rounded-md file:border file:border-border file:bg-background file:px-2 file:py-1 file:text-xs"
          />
          {file && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground">as</span>
              <input
                value={libraryName}
                onChange={(e) => setLibraryName(e.target.value.toLowerCase())}
                aria-label="Name for the imported space"
                className={cn(INPUT, "min-w-0 flex-1 font-mono text-xs")}
              />
              <button type="submit" disabled={!libraryName.trim() || pending} className={PRIMARY}>
                {fromFile.isPending ? "Importing…" : "Import"}
              </button>
            </div>
          )}
        </form>
      </details>

      {pending && (
        <p className="text-xs text-muted-foreground">
          Checking and unpacking every file. A large space takes a few minutes.
        </p>
      )}
      {imported && (
        <div className="space-y-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs">
          <p className="text-foreground">
            Imported <span className="font-medium">{libraryTitle({ id: imported.library, name: imported.name })}</span>:{" "}
            {describeContents(imported.contents)}, {imported.files.toLocaleString()} files, all checked. Exported from
            space "{imported.source_library}" on {new Date(imported.created_at).toLocaleString()} by Luminary{" "}
            {imported.app_version}.
          </p>
          <button onClick={() => onOpen(imported.library)} className={PRIMARY}>
            Open it
          </button>
        </div>
      )}
    </div>
  )
}

export function LibraryManager() {
  const queryClient = useQueryClient()
  const libraries = useQuery({ queryKey: LIBRARIES_KEY, queryFn: fetchLibraries })
  const destinations = useQuery({
    queryKey: DESTINATIONS_KEY,
    queryFn: () => apiGet<DestinationList>("/libraries/destinations"),
  })

  const switchTo = useMutation({
    mutationFn: (library: string) => apiPut<LibraryList>("/libraries/active", { library }),
    onSuccess: (list) => openLibrary(list.active),
    onError: fail("Could not open that space"),
  })

  const items = libraries.data?.libraries ?? []
  const synced = (destinations.data?.destinations ?? []).filter((d) => d.kind !== "exports")

  return (
    <div className="space-y-5">
      <p className="text-xs text-muted-foreground">
        Keep separate spaces for separate parts of life: personal reading, work, the kids' books. Each has its
        own library of documents, its own notes, cards and study history, and Luminary works in one at a time.
      </p>

      <section className="space-y-2">
        <h4 className={HEADING}>Your spaces</h4>
        {libraries.isLoading && <div className="h-14 animate-pulse rounded-md bg-muted" />}
        {libraries.isError && <p className="text-xs text-destructive">Couldn't load the spaces.</p>}
        {items.length > 0 && (
          <ul className="divide-y divide-border rounded-md border border-border">
            {items.map((item) => (
              <LibraryRow
                key={item.id}
                item={item}
                busy={switchTo.isPending}
                onOpen={() => switchTo.mutate(item.id)}
              />
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <h4 className={HEADING}>New space</h4>
        <NewLibrary
          taken={items.map((i) => i.id)}
          onCreated={(list) => {
            queryClient.setQueryData(LIBRARIES_KEY, list)
            toast.success("Space created. Open it to start adding to it.")
          }}
        />
      </section>

      <section className="space-y-3">
        <h4 className={HEADING}>Move to another computer</h4>
        <p className="text-xs text-muted-foreground">
          {synced.length > 0
            ? `Export into ${synced.map((d) => d.name).join(", ")} and the other computer, signed in to the same service, finds it under Import.`
            : "No sync folder found (iCloud Drive, Dropbox, Google Drive, OneDrive, Box). Exports go to Luminary Exports in your home folder; copy the file across yourself."}{" "}
          Only the finished archive is ever written there: a space in use is never synced.
        </p>
        {destinations.isLoading && <div className="h-10 animate-pulse rounded-md bg-muted" />}
        {destinations.isError && <p className="text-xs text-destructive">Couldn't look for export folders.</p>}
        {destinations.data && items.length > 0 && (
          <>
            <ExportPanel libraries={items} destinations={destinations.data.destinations} />
            <div className="border-t border-border" />
            <ImportPanel
              libraries={items}
              destinations={destinations.data.destinations}
              refreshing={destinations.isFetching}
              onRefresh={() => void destinations.refetch()}
              onOpen={(id) => switchTo.mutate(id)}
            />
          </>
        )}
      </section>
    </div>
  )
}
