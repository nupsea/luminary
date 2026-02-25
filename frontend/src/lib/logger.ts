function ts(): string {
  return new Date().toISOString()
}

export const logger = {
  debug: (msg: string, ...args: unknown[]) =>
    console.debug(`[Luminary] [DEBUG] ${ts()} ${msg}`, ...args),
  info: (msg: string, ...args: unknown[]) =>
    console.info(`[Luminary] [INFO] ${ts()} ${msg}`, ...args),
  warn: (msg: string, ...args: unknown[]) =>
    console.warn(`[Luminary] [WARN] ${ts()} ${msg}`, ...args),
  error: (msg: string, ...args: unknown[]) =>
    console.error(`[Luminary] [ERROR] ${ts()} ${msg}`, ...args),
}
