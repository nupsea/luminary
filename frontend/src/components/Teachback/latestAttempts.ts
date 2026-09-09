/**
 * One card, one verdict: the latest attempt.
 *
 * "Answer this one again" submits a second explanation for a card already
 * answered, and every count in the run used to be per submission. The same
 * question appeared twice in the summary, and the average included a score the
 * learner had already replaced with the one shown next to it -- a 10 improved
 * to a 45, beside a 90, read as "3 scored, averaging 48" over a run of two
 * cards. It is two cards averaging 68.
 *
 * The earlier attempts are kept. They are the record of how the learner got
 * there, and `attemptCount` is what lets the summary say so. They are just not
 * the verdict.
 *
 * Submission order is the ordering, not `results` order: the API returns rows
 * by id and gives the client no timestamp to sort on.
 */

import type { PendingTeachback, TeachbackResultItem } from "@/lib/studyApi"

export interface StandingAttempt {
  attempt: PendingTeachback
  /** How many explanations this card has had, this one included. */
  attemptCount: number
}

/** The attempt that stands for each card, in the order the cards were first met. */
export function standingAttempts(pending: PendingTeachback[]): StandingAttempt[] {
  const order: string[] = []
  const byCard = new Map<string, StandingAttempt>()
  for (const attempt of pending) {
    const seen = byCard.get(attempt.flashcardId)
    if (seen) {
      byCard.set(attempt.flashcardId, { attempt, attemptCount: seen.attemptCount + 1 })
    } else {
      order.push(attempt.flashcardId)
      byCard.set(attempt.flashcardId, { attempt, attemptCount: 1 })
    }
  }
  return order.map((cardId) => byCard.get(cardId)!)
}

export interface RunTally {
  /** Distinct cards answered in this run. */
  answered: number
  /** Distinct cards whose standing attempt has a score. */
  scored: number
  /** Of those, how many reached the pass mark. */
  passed: number
  /** Mean of the standing scores, or null while any of them is still scoring. */
  avgScore: number | null
  /** Cards whose standing attempt has not come back yet. */
  stillScoring: number
}

export const PASS_MARK = 60
// The completeness remark is derived from the score, never from the list being
// empty. "Nothing material was left out." sat next to completeness 5/100 in a
// real run: the sentence came from an empty missed_points and the number came
// from the model, and nothing reconciled them.
const COMPLETE_ENOUGH = 70

export function completenessNote(completeness: {
  score: number
  missed_points: string[]
}): string {
  if (completeness.missed_points.length > 0) {
    return `Missed: ${completeness.missed_points.join("; ")}`
  }
  return completeness.score >= COMPLETE_ENOUGH
    ? "Nothing the question asked for was left out."
    : "Scored low, but the evaluator named nothing that was missing."
}


/**
 * The run's numbers, over cards rather than submissions.
 *
 * `avgScore` is null while a standing attempt is unscored rather than a mean of
 * whatever happens to have finished: an average over a subset is a number for a
 * run that is not over, and it moves as the stragglers land. It is never 0 for
 * a missing verdict -- an unscored card is unscored, not a zero.
 */
export function tallyRun(
  pending: PendingTeachback[],
  results: TeachbackResultItem[] | undefined,
): RunTally {
  const standing = standingAttempts(pending)
  const verdicts = standing.map(({ attempt }) =>
    results?.find((r) => r.id === attempt.id),
  )
  const complete = verdicts.filter((r) => r?.status === "complete" && r.score !== null)
  // An attempt whose submission failed outright carries an "error-" id and no
  // row to poll; it is answered, and it is not scored.
  const stillScoring = standing.filter(({ attempt }, i) => {
    if (attempt.id.startsWith("error-")) return false
    const verdict = verdicts[i]
    return !verdict || verdict.status === "pending"
  }).length

  const scores = complete.map((r) => r!.score as number)
  return {
    answered: standing.length,
    scored: scores.length,
    passed: scores.filter((s) => s >= PASS_MARK).length,
    avgScore:
      stillScoring > 0 || scores.length === 0
        ? null
        : Math.round(scores.reduce((a, b) => a + b, 0) / scores.length),
    stillScoring,
  }
}
