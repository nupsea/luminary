export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:7820"

// PDF.js worker URL — bundled locally so the viewer works offline.
// Vite resolves this at build time to a hashed asset path in the output bundle.
export const PDFJS_WORKER_URL = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString()
