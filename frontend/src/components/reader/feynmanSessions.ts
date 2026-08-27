// Feynman session lookups, split out of DocumentReader so a public build can
// drop them. `feynman` is a full-mode surface; the query in DocumentReader was
// already `enabled: LUMINARY_MODE === "full"` and so never ran for a public
// user, but the "/feynman/sessions" call still compiled into the Learning
// chunk. Behind a folded dynamic import this module is not emitted at all.
import { apiGet } from "@/lib/apiClient"

/** section_id -> ISO timestamp of that section's most recent Feynman session. */
export async function lastPracticedBySection(documentId: string): Promise<Map<string, string>> {
  try {
    const sessions = await apiGet<Array<{ section_id: string | null; created_at: string }>>(
      "/feynman/sessions",
      { document_id: documentId },
    )
    const byId = new Map<string, string>()
    // Sessions are returned in created_at desc; first hit per section wins.
    for (const s of sessions) {
      if (!s.section_id) continue
      if (!byId.has(s.section_id)) byId.set(s.section_id, s.created_at)
    }
    return byId
  } catch {
    return new Map<string, string>()
  }
}
