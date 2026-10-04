import { describe, expect, it } from "vitest"

import { micErrorMessage } from "./micErrors"

const domError = (name: string, message = "") => Object.assign(new Error(message), { name })

describe("micErrorMessage", () => {
  it("sends a denied Mac user to the Microphone privacy setting", () => {
    const text = micErrorMessage(domError("NotAllowedError"), "mac")
    expect(text).toContain("Privacy & Security > Microphone")
  })

  it("treats WebKit's no-device OverconstrainedError as a missing microphone", () => {
    const text = micErrorMessage(domError("OverconstrainedError", "Invalid constraint"), "mac")
    expect(text).toMatch(/^No microphone was found/)
    expect(text).toContain("Sound > Input")
  })

  it("gives Windows its own settings path", () => {
    expect(micErrorMessage(domError("NotAllowedError"), "windows")).toContain(
      "Settings > Privacy & security > Microphone",
    )
  })

  it("says the device is busy when it cannot be read", () => {
    expect(micErrorMessage(domError("NotReadableError"), "linux")).toContain("Another app")
  })

  it("keeps an unknown error's own text beside the step", () => {
    expect(micErrorMessage(domError("WeirdError", "boom"), "mac")).toContain("(boom)")
  })
})
