import { describe, expect, it } from "vitest"

import { splitDevices } from "./deviceList"

function device(id: string, revoked_at: string | null = null) {
  return { id, name: id, created_at: "2026-10-01T00:00:00", last_seen_at: null, revoked_at }
}

describe("splitDevices", () => {
  it("keeps every active device visible, however many are revoked", () => {
    const devices = [
      device("a"),
      device("b"),
      ...[1, 2, 3, 4, 5].map((n) => device(`r${n}`, `2026-10-0${n}T00:00:00`)),
    ]
    const { active, recentRevoked, olderRevoked } = splitDevices(devices)
    expect(active.map((d) => d.id)).toEqual(["a", "b"])
    expect(recentRevoked.map((d) => d.id)).toEqual(["r5", "r4", "r3"])
    expect(olderRevoked.map((d) => d.id)).toEqual(["r2", "r1"])
  })

  it("hides nothing when three or fewer are revoked", () => {
    const { recentRevoked, olderRevoked } = splitDevices([
      device("r1", "2026-10-01T00:00:00"),
      device("r2", "2026-10-02T00:00:00"),
      device("r3", "2026-10-03T00:00:00"),
    ])
    expect(recentRevoked).toHaveLength(3)
    expect(olderRevoked).toHaveLength(0)
  })
})
