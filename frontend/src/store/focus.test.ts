import { beforeEach, describe, expect, it, vi } from "vitest"

// Stub localStorage in node env BEFORE importing the store (the store reads at module load).
const data: Record<string, string> = {}
const localStorageMock = {
  getItem: vi.fn((k: string) => data[k] ?? null),
  setItem: vi.fn((k: string, v: string) => {
    data[k] = v
  }),
  removeItem: vi.fn((k: string) => {
    delete data[k]
  }),
  clear: vi.fn(() => {
    for (const k of Object.keys(data)) delete data[k]
  }),
}
vi.stubGlobal("localStorage", localStorageMock)

const {
  useFocusStore,
  DEFAULT_FOCUS_MINUTES,
  DEFAULT_BREAK_MINUTES,
} = await import("./focus")

function reset() {
  useFocusStore.setState({
    sessionId: null,
    phase: "idle",
    secondsLeft: DEFAULT_FOCUS_MINUTES * 60,
    focusMinutes: DEFAULT_FOCUS_MINUTES,
    breakMinutes: DEFAULT_BREAK_MINUTES,
    surface: "none",
    goalId: null,
    muted: false,
    lastTickAt: null,
    errorMessage: null,
  })
}

describe("useFocusStore -- transitions", () => {
  beforeEach(reset)

  it("starts in idle with default focus minutes (25)", () => {
    const s = useFocusStore.getState()
    expect(s.phase).toBe("idle")
    expect(s.focusMinutes).toBe(25)
    expect(s.breakMinutes).toBe(5)
    expect(s.secondsLeft).toBe(25 * 60)
  })

  it("enterFocus sets phase=focus and stores session id + secondsLeft", () => {
    useFocusStore.getState().enterFocus("sess-1", 1500)
    const s = useFocusStore.getState()
    expect(s.phase).toBe("focus")
    expect(s.sessionId).toBe("sess-1")
    expect(s.secondsLeft).toBe(1500)
    expect(s.lastTickAt).not.toBeNull()
  })

  it("enterPaused flips phase to paused without changing secondsLeft", () => {
    useFocusStore.getState().enterFocus("sess-1", 1500)
    useFocusStore.setState({ secondsLeft: 1234 })
    useFocusStore.getState().enterPaused()
    const s = useFocusStore.getState()
    expect(s.phase).toBe("paused")
    expect(s.secondsLeft).toBe(1234)
  })

  it("enterBreak sets phase=break and reseeds secondsLeft", () => {
    useFocusStore.getState().enterFocus("sess-1", 1500)
    useFocusStore.getState().enterBreak(300)
    const s = useFocusStore.getState()
    expect(s.phase).toBe("break")
    expect(s.secondsLeft).toBe(300)
  })

  it("enterIdle clears session id and resets secondsLeft to focusMinutes*60", () => {
    useFocusStore.getState().enterFocus("sess-1", 200)
    useFocusStore.getState().enterIdle()
    const s = useFocusStore.getState()
    expect(s.phase).toBe("idle")
    expect(s.sessionId).toBeNull()
    expect(s.secondsLeft).toBe(s.focusMinutes * 60)
  })
})

describe("useFocusStore -- tick semantics", () => {
  beforeEach(reset)

  it("decrements secondsLeft by 1 in focus phase", () => {
    useFocusStore.getState().enterFocus("sess-1", 10)
    useFocusStore.getState().tick()
    expect(useFocusStore.getState().secondsLeft).toBe(9)
  })

  it("decrements secondsLeft by 1 in break phase", () => {
    useFocusStore.getState().enterBreak(10)
    useFocusStore.getState().tick()
    expect(useFocusStore.getState().secondsLeft).toBe(9)
  })

  it("does NOT decrement in paused phase", () => {
    useFocusStore.getState().enterFocus("sess-1", 10)
    useFocusStore.getState().enterPaused()
    useFocusStore.getState().tick()
    expect(useFocusStore.getState().secondsLeft).toBe(10)
  })

  it("does NOT decrement in idle phase", () => {
    useFocusStore.getState().tick()
    expect(useFocusStore.getState().secondsLeft).toBe(25 * 60)
  })

  it("clamps to zero, never negative", () => {
    useFocusStore.getState().enterFocus("sess-1", 0)
    useFocusStore.getState().tick()
    expect(useFocusStore.getState().secondsLeft).toBe(0)
  })
})

describe("useFocusStore -- minute setters", () => {
  beforeEach(reset)

  it("setFocusMinutes mirrors into secondsLeft when idle", () => {
    useFocusStore.getState().setFocusMinutes(30)
    const s = useFocusStore.getState()
    expect(s.focusMinutes).toBe(30)
    expect(s.secondsLeft).toBe(30 * 60)
  })

  it("setFocusMinutes does not change secondsLeft when in focus phase", () => {
    useFocusStore.getState().enterFocus("sess-1", 100)
    useFocusStore.getState().setFocusMinutes(45)
    const s = useFocusStore.getState()
    expect(s.focusMinutes).toBe(45)
    expect(s.secondsLeft).toBe(100)
  })

  it("setBreakMinutes only updates the breakMinutes field", () => {
    useFocusStore.getState().setBreakMinutes(10)
    expect(useFocusStore.getState().breakMinutes).toBe(10)
  })
})

describe("useFocusStore -- popover settings", () => {
  beforeEach(reset)

  it("setMuted toggles the mute flag", () => {
    expect(useFocusStore.getState().muted).toBe(false)
    useFocusStore.getState().setMuted(true)
    expect(useFocusStore.getState().muted).toBe(true)
  })

  it("setSurface stores the inferred surface", () => {
    useFocusStore.getState().setSurface("recall")
    expect(useFocusStore.getState().surface).toBe("recall")
  })

  it("setGoalId stores the attached goal id (or null to clear)", () => {
    useFocusStore.getState().setGoalId("goal-9")
    expect(useFocusStore.getState().goalId).toBe("goal-9")
    useFocusStore.getState().setGoalId(null)
    expect(useFocusStore.getState().goalId).toBeNull()
  })

  it("setError surfaces an inline error message", () => {
    useFocusStore.getState().setError("backend offline")
    expect(useFocusStore.getState().errorMessage).toBe("backend offline")
    useFocusStore.getState().setError(null)
    expect(useFocusStore.getState().errorMessage).toBeNull()
  })
})

describe("useFocusStore -- hydrate", () => {
  beforeEach(reset)

  it("merges persisted snapshot fields into state", () => {
    useFocusStore.getState().hydrate({
      sessionId: "sess-9",
      phase: "focus",
      secondsLeft: 42,
      focusMinutes: 50,
    })
    const s = useFocusStore.getState()
    expect(s.sessionId).toBe("sess-9")
    expect(s.phase).toBe("focus")
    expect(s.secondsLeft).toBe(42)
    expect(s.focusMinutes).toBe(50)
    // Untouched fields stay at defaults.
    expect(s.breakMinutes).toBe(5)
  })
})
