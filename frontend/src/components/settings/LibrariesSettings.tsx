// The libraries on this machine: which one Luminary opens, and moving one to another computer.
// A library moves as one exported archive, imported on the other machine as a new library.

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { LIBRARIES_KEY, fetchLibraries, openLibrary, type LibraryList } from "@/hooks/useActiveLibrary"
import { apiPost, apiPut, detailFromError } from "@/lib/apiClient"
import { describeContents, suggestedLibraryName } from "@/lib/libraryTransfer"
import { formatBytes } from "@/lib/setupApi"
import type { components } from "@/types/api"

type LibraryExport = components["schemas"]["LibraryExport"]
type LibraryImport = components["schemas"]["LibraryImport"]

const BUTTON =
  "rounded-md border border-border px-2 py-1 text-xs text-foreground hover:bg-accent disabled:opacity-50"
const PRIMARY =
  "rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
const INPUT =
  "rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground placeholder:text-muted-foreground"

export function LibrariesSettings() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError } = useQuery({ queryKey: LIBRARIES_KEY, queryFn: fetchLibraries })
  const [newName, setNewName] = useState("")
  const [exported, setExported] = useState<LibraryExport | null>(null)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importName, setImportName] = useState("")
  const [imported, setImported] = useState<LibraryImport | null>(null)

  const refresh = (list: LibraryList) => queryClient.setQueryData(LIBRARIES_KEY, list)

  const switchTo = useMutation({
    mutationFn: (library: string) => apiPut<LibraryList>("/libraries/active", { library }),
    onSuccess: (list) => openLibrary(list.active),
    onError: (err) => toast.error(detailFromError(err, "Could not open that library").message),
  })
  const create = useMutation({
    mutationFn: (library: string) => apiPost<LibraryList>("/libraries", { library }),
    onSuccess: (list) => {
      refresh(list)
      setNewName("")
    },
    onError: (err) => toast.error(detailFromError(err, "Could not create the library").message),
  })
  const exportLibrary = useMutation({
    mutationFn: (library: string) => apiPost<LibraryExport>(`/libraries/${library}/export`),
    onSuccess: setExported,
    onError: (err) => toast.error(detailFromError(err, "Could not export the library").message),
  })
  const importLibrary = useMutation({
    mutationFn: ({ file, library }: { file: File; library: string }) => {
      const form = new FormData()
      form.append("file", file)
      form.append("library", library)
      return apiPost<LibraryImport>("/libraries/import", form)
    },
    onSuccess: (result) => {
      setImported(result)
      setImportFile(null)
      setImportName("")
      void queryClient.invalidateQueries({ queryKey: LIBRARIES_KEY })
    },
    onError: (err) => toast.error(detailFromError(err, "Could not import the library").message),
  })

  const busy = switchTo.isPending || exportLibrary.isPending || importLibrary.isPending

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Each library has its own documents, notes, cards and study history. Luminary opens one at
        a time. To move a library to another computer, export it, copy the file across, and
        import it there.
      </p>

      {isLoading && <div className="h-12 animate-pulse rounded-md bg-muted" />}
      {isError && <p className="text-xs text-destructive">Couldn't load the libraries.</p>}
      {data && (
        <ul className="divide-y divide-border rounded-md border border-border">
          {data.libraries.map((lib) => (
            <li key={lib.id} className="flex items-center justify-between gap-3 px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground">
                  {lib.id}
                  {lib.active && (
                    <span className="ml-2 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                      open
                    </span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground">{formatBytes(lib.bytes)}</p>
              </div>
              <div className="flex flex-shrink-0 gap-2">
                {!lib.active && (
                  <button onClick={() => switchTo.mutate(lib.id)} disabled={busy} className={BUTTON}>
                    Open
                  </button>
                )}
                <button onClick={() => exportLibrary.mutate(lib.id)} disabled={busy} className={BUTTON}>
                  {exportLibrary.isPending && exportLibrary.variables === lib.id ? "Exporting…" : "Export"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {exported && (
        <div className="space-y-1 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs">
          <p className="text-foreground">
            Exported <span className="font-medium">{exported.library}</span> (
            {describeContents(exported.contents)}, {formatBytes(exported.bytes)}) to:
          </p>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 break-all font-mono text-[11px] text-foreground">
              {exported.path}
            </code>
            <button
              onClick={() => void navigator.clipboard.writeText(exported.path)}
              className={BUTTON}
            >
              Copy path
            </button>
          </div>
          <p className="text-muted-foreground">
            Copy this file to the other computer by any means (AirDrop, a USB drive, a synced
            folder) and import it there. It is checked file by file when imported.
          </p>
        </div>
      )}

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (newName.trim()) create.mutate(newName.trim())
        }}
      >
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value.toLowerCase())}
          placeholder="name, e.g. personal"
          aria-label="New library name"
          className={INPUT}
        />
        <button type="submit" disabled={!newName.trim() || create.isPending} className={BUTTON}>
          Create empty library
        </button>
      </form>

      <section className="space-y-2">
        <h4 className="text-xs font-semibold text-foreground">Import a library</h4>
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (importFile && importName.trim()) {
              setImported(null)
              importLibrary.mutate({ file: importFile, library: importName.trim() })
            }
          }}
        >
          <input
            type="file"
            accept=".gz,application/gzip"
            aria-label="Exported library file"
            onChange={(e) => {
              const file = e.target.files?.[0] ?? null
              setImportFile(file)
              if (file && !importName) setImportName(suggestedLibraryName(file.name))
            }}
            className="block w-full text-xs text-foreground file:mr-2 file:rounded-md file:border file:border-border file:bg-background file:px-2 file:py-1 file:text-xs"
          />
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={importName}
              onChange={(e) => setImportName(e.target.value.toLowerCase())}
              placeholder="name on this computer, e.g. office"
              aria-label="Name for the imported library"
              className={`${INPUT} min-w-0 flex-1`}
            />
            <button
              type="submit"
              disabled={!importFile || !importName.trim() || busy}
              className={PRIMARY}
            >
              {importLibrary.isPending ? "Importing…" : "Import"}
            </button>
          </div>
          {importLibrary.isPending && (
            <p className="text-xs text-muted-foreground">
              Checking and unpacking every file. A large library takes a few minutes.
            </p>
          )}
        </form>

        {imported && (
          <div className="space-y-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs">
            <p className="text-foreground">
              Imported <span className="font-medium">{imported.library}</span>:{" "}
              {describeContents(imported.contents)}, {imported.files.toLocaleString()} files, all
              checked. Exported from library "{imported.source_library}" on{" "}
              {new Date(imported.created_at).toLocaleString()} by Luminary {imported.app_version}.
            </p>
            <button onClick={() => switchTo.mutate(imported.library)} disabled={busy} className={PRIMARY}>
              Open {imported.library}
            </button>
          </div>
        )}
      </section>
    </div>
  )
}
