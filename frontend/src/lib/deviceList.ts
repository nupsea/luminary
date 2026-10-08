import type { components } from "@/types/api"

type Device = components["schemas"]["DeviceResponse"]

const RECENT_REVOKED_SHOWN = 3

// Every active device stays visible: anything that can reach the library must not be hidden.
export function splitDevices(devices: Device[], recentShown = RECENT_REVOKED_SHOWN) {
  const active = devices.filter((d) => !d.revoked_at)
  const revoked = devices
    .filter((d) => d.revoked_at)
    .sort((a, b) => (b.revoked_at ?? "").localeCompare(a.revoked_at ?? ""))
  return {
    active,
    recentRevoked: revoked.slice(0, recentShown),
    olderRevoked: revoked.slice(recentShown),
  }
}
