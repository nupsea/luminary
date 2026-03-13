/**
 * useReviewNotification -- S118
 *
 * Behaviour:
 * 1. On first mount: calls Notification.requestPermission() once per browser
 *    profile (guarded by localStorage key "luminary:notifPermRequested").
 * 2. Registers a visibilitychange listener. When the document becomes visible:
 *    a. If Notification.permission !== "granted", skip.
 *    b. If reviewRemindersEnabled is false, skip.
 *    c. Check "luminary:lastReviewNotif" timestamp. If < 4 hours ago, skip.
 *    d. Write current timestamp to "luminary:lastReviewNotif" (before fetch,
 *       to prevent concurrent events from each passing the throttle check).
 *    e. Fetch GET /study/due-count.
 *    f. If due_today > 0, fire new Notification with title "Luminary" and
 *       body "X card(s) due for review today". Clicking navigates to /study.
 * 3. Cleans up the visibilitychange listener on unmount.
 *
 * Must be called from a component inside <BrowserRouter> so useNavigate works.
 */

import { useEffect, useRef } from "react"
import { useNavigate } from "react-router-dom"
import { useAppStore } from "@/store"

const API_BASE = "http://localhost:8000"
const FOUR_HOURS_MS = 4 * 60 * 60 * 1000
const PERM_REQUESTED_KEY = "luminary:notifPermRequested"
const LAST_NOTIF_KEY = "luminary:lastReviewNotif"

export function useReviewNotification(): void {
  const reviewRemindersEnabled = useAppStore((s) => s.reviewRemindersEnabled)
  const navigate = useNavigate()
  // Use a ref so the visibilitychange closure always has the current navigate function
  // without needing to re-register the listener on every render.
  const navigateRef = useRef(navigate)
  useEffect(() => {
    navigateRef.current = navigate
  }, [navigate])

  // Effect 1: Request permission once on first mount.
  useEffect(() => {
    if (
      typeof Notification === "undefined" ||
      Notification.permission !== "default" ||
      localStorage.getItem(PERM_REQUESTED_KEY)
    ) {
      return
    }
    // Write the flag BEFORE requesting to prevent double-prompts on rapid reload.
    localStorage.setItem(PERM_REQUESTED_KEY, "1")
    void Notification.requestPermission()
  }, [])

  // Effect 2: visibilitychange listener for notification dispatch.
  useEffect(() => {
    async function handleVisibilityChange() {
      if (document.visibilityState !== "visible") return
      if (typeof Notification === "undefined") return
      if (Notification.permission !== "granted") return
      if (!reviewRemindersEnabled) return

      const lastNotif = parseInt(localStorage.getItem(LAST_NOTIF_KEY) ?? "0", 10)
      if (Date.now() - lastNotif < FOUR_HOURS_MS) return

      // Write the throttle timestamp BEFORE the first await so that any
      // concurrent visibilitychange events entering this function (while the
      // fetch is suspended at the await) see the updated timestamp and bail
      // out immediately. Without this, multiple concurrent events each pass
      // the throttle check and each fire a separate notification.
      localStorage.setItem(LAST_NOTIF_KEY, String(Date.now()))

      try {
        const res = await fetch(`${API_BASE}/study/due-count`)
        if (!res.ok) return
        const data = (await res.json()) as { due_today: number }
        if (data.due_today <= 0) return

        const count = data.due_today
        const notif = new Notification("Luminary", {
          body: `${count} ${count !== 1 ? "cards" : "card"} due for review today`,
        })
        notif.onclick = () => {
          window.focus()
          navigateRef.current("/study")
        }
      } catch {
        // Network error -- silently skip; notification is best-effort.
      }
    }

    document.addEventListener("visibilitychange", handleVisibilityChange)
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange)
    }
  }, [reviewRemindersEnabled])
}
