// Pairing and revoking devices: the only way a caller other than this app reaches the backend.
// A code is shown here and typed on the other device, which gets a token; revoking cuts it off.

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { apiDelete, apiGet, apiPost, detailFromError } from "@/lib/apiClient"
import type { components } from "@/types/api"

type Device = components["schemas"]["DeviceResponse"]
type PairingCode = components["schemas"]["PairingCodeResponse"]

const DEVICES_KEY = ["devices"]

function formatWhen(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "never"
}

export function DevicesSettings() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError } = useQuery({
    queryKey: DEVICES_KEY,
    queryFn: () => apiGet<Device[]>("/devices"),
  })
  const [code, setCode] = useState<PairingCode | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)

  const issue = useMutation({
    mutationFn: () => apiPost<PairingCode>("/devices/pairing-code"),
    onSuccess: setCode,
    onError: (err) => toast.error(detailFromError(err, "Could not create a pairing code").message),
  })
  const revoke = useMutation({
    mutationFn: (id: string) => apiDelete(`/devices/${id}`),
    onSuccess: () => {
      setConfirming(null)
      void queryClient.invalidateQueries({ queryKey: DEVICES_KEY })
    },
    onError: (err) => toast.error(detailFromError(err, "Could not revoke the device").message),
  })

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Anything other than this app (your phone, your own server, a browser extension) needs a
        pairing code from here before it can reach your library.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => issue.mutate()}
          disabled={issue.isPending}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {code ? "Show a new code" : "Pair a device"}
        </button>
        {code && (
          <div>
            <p className="font-mono text-lg font-semibold tracking-widest text-foreground">
              {code.code}
            </p>
            <p className="text-xs text-muted-foreground">
              Enter it on the other device before{" "}
              {new Date(code.expires_at).toLocaleTimeString()}. It works once.
            </p>
          </div>
        )}
      </div>

      {isLoading && <div className="h-12 animate-pulse rounded-md bg-muted" />}
      {isError && <p className="text-xs text-destructive">Couldn't load paired devices.</p>}
      {data && data.length === 0 && (
        <p className="text-xs text-muted-foreground">No devices paired yet.</p>
      )}
      {data && data.length > 0 && (
        <ul className="divide-y divide-border rounded-md border border-border">
          {data.map((device) => (
            <li key={device.id} className="flex items-center justify-between gap-3 px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground">{device.name}</p>
                <p className="text-xs text-muted-foreground">
                  {device.revoked_at
                    ? `Revoked ${formatWhen(device.revoked_at)}`
                    : `Paired ${formatWhen(device.created_at)} · last seen ${formatWhen(device.last_seen_at)}`}
                </p>
              </div>
              {!device.revoked_at &&
                (confirming === device.id ? (
                  <div className="flex flex-shrink-0 gap-2">
                    <button
                      onClick={() => revoke.mutate(device.id)}
                      disabled={revoke.isPending}
                      className="rounded-md bg-destructive px-2 py-1 text-xs font-medium text-destructive-foreground disabled:opacity-50"
                    >
                      Revoke
                    </button>
                    <button
                      onClick={() => setConfirming(null)}
                      className="rounded-md border border-border px-2 py-1 text-xs text-foreground hover:bg-accent"
                    >
                      Keep
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirming(device.id)}
                    className="flex-shrink-0 rounded-md border border-border px-2 py-1 text-xs text-foreground hover:bg-accent"
                  >
                    Revoke…
                  </button>
                ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
