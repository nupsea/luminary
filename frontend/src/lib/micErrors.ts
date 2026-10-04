// What to tell the user when the microphone could not be opened. The browser's own text
// ("Invalid constraint", "The request is not allowed...") names no cause and no step.

import { isMacPlatform } from "@/lib/keyboard"

type Os = "mac" | "windows" | "linux"

function currentOs(): Os {
  if (isMacPlatform()) return "mac"
  const ua = typeof navigator === "undefined" ? "" : navigator.userAgent || ""
  return /Win/i.test(ua) ? "windows" : "linux"
}

const ALLOW: Record<Os, string> = {
  mac: "Open System Settings > Privacy & Security > Microphone, turn on Luminary, then quit and reopen Luminary.",
  windows:
    "Open Settings > Privacy & security > Microphone, turn on microphone access for desktop apps, then try again.",
  linux: "Check that your desktop allows Luminary to use the microphone, then try again.",
}

const CONNECT: Record<Os, string> = {
  mac: "Connect a microphone or headset, check that it is selected in System Settings > Sound > Input, then try again.",
  windows:
    "Connect a microphone or headset, check that it is selected in Settings > System > Sound > Input, then try again.",
  linux: "Connect a microphone or headset, check that it is selected in your sound settings, then try again.",
}

export function micErrorMessage(err: unknown, os: Os = currentOs()): string {
  const { name = "", message = "" } = (err ?? {}) as { name?: string; message?: string }
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return `Luminary is not allowed to use the microphone. ${ALLOW[os]}`
    // WebKit reports "no input device" as an OverconstrainedError even for `{ audio: true }`.
    case "NotFoundError":
    case "OverconstrainedError":
      return `No microphone was found. ${CONNECT[os]} If one is connected: ${ALLOW[os]}`
    case "NotReadableError":
    case "AbortError":
      return "The microphone could not start. Another app may be using it: close that app and try again."
    default:
      return `The microphone could not be opened${message ? ` (${message})` : ""}. ${ALLOW[os]}`
  }
}
