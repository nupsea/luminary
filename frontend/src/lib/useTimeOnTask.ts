/**
 * Sample foreground time on a surface, for the hub's weekly split.
 *
 * The server cannot measure this. A reader who opens a document and reads for
 * twenty minutes issues one request, so without a client sample the only
 * honest answer for reading and note time is "unknown".
 *
 * What this reports is narrow and must stay described that way: the surface was
 * mounted and the tab was visible. It is not proof anyone was reading. Beats
 * stop while the tab is hidden, and the server refuses to credit a gap longer
 * than one continuous stretch, so a backgrounded tab accrues nothing rather
 * than silently banking the time it was away.
 */

import { useEffect } from "react"

import { apiPost } from "@/lib/apiClient"
import { logger } from "@/lib/logger"

/** The activities the hub splits a week into. */
export type TimeOnTaskActivity = "document" | "note" | "review" | "study"

/**
 * Matches the server's own cadence. The server does not depend on it holding --
 * it credits the measured gap -- but beating far slower than its ceiling would
 * make every gap look discontinuous and accrue nothing.
 */
const HEARTBEAT_MS = 15_000

/**
 * Beat while `active` and the tab is visible.
 *
 * `memberId` may be null for an activity with no single subject. Passing
 * undefined while a page is still loading its id is fine: no beat is sent until
 * there is something to attribute the time to.
 */
export function useTimeOnTask(
  activity: TimeOnTaskActivity,
  memberId?: string | null,
  active = true,
): void {
  useEffect(() => {
    if (!active || memberId === undefined) return

    let stopped = false

    const beat = () => {
      // Hidden tabs are not time on task. Skipping the beat (rather than
      // pausing the timer) means the resulting gap trips the server's
      // continuity ceiling, which is what keeps an idle tab from accruing.
      if (typeof document !== "undefined" && document.hidden) return
      void apiPost("/engagement/heartbeat", {
        activity,
        member_id: memberId ?? null,
      }).catch((err) => {
        // A dropped beat costs a sample, never the session: the next one
        // resumes accrual. Failing loudly here would put an error state on a
        // page whose actual job succeeded.
        if (!stopped) logger.info("[time-on-task] beat failed", String(err))
      })
    }

    beat()
    const timer = setInterval(beat, HEARTBEAT_MS)

    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [activity, memberId, active])
}
