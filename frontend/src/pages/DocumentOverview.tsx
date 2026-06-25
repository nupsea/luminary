// Retired: the document "overview" page (references + read/study/chat options) was replaced by
// opening the reader directly, with those actions in the reader header. This redirect keeps any
// stale /library/doc/:id link (bookmarks, history) landing in the reader instead of a dead page.

import { Navigate, useParams } from "react-router-dom"

export default function DocumentOverview() {
  const { id = "" } = useParams()
  return <Navigate to={id ? `/library?doc=${id}` : "/library"} replace />
}
