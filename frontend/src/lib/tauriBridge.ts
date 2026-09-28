/** The desktop shell's command bridge, or null outside the Tauri app. */

type Invoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>

interface TauriGlobal {
  core?: { invoke?: Invoke }
}

export function tauriInvoke(): Invoke | null {
  const injected = (window as unknown as { __TAURI__?: TauriGlobal }).__TAURI__
  return injected?.core?.invoke ?? null
}
