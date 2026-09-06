// The receipt line under an answer.

import type { AnswerReceipt } from "./types"

export function AnswerReceiptLine({ receipt }: { receipt: AnswerReceipt }) {
  const local = receipt.engine === "local"
  // A null ttft means no model was called (a cached or pass-through answer). Showing
  // 0s there would read as "instant" for work that never happened.
  const timing =
    receipt.ttft_seconds !== null
      ? `first token ${receipt.ttft_seconds.toFixed(1)}s · ${receipt.total_seconds.toFixed(1)}s total`
      : `${receipt.total_seconds.toFixed(1)}s total · no model call`
  // The budget reason is only worth surfacing when something narrowed it; the
  // default carries no decision the reader needs to know about.
  const narrowed =
    receipt.context_budget_reason && !receipt.context_budget_reason.startsWith("default")
      ? receipt.context_budget_reason
      : null
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
      <span className={local ? "text-green-700 dark:text-green-400" : "text-blue-700 dark:text-blue-400"}>
        {local ? "Ran on this machine" : "Sent to the cloud"}
      </span>
      <span>·</span>
      <span className="font-mono">{receipt.model}</span>
      <span>·</span>
      <span>{timing}</span>
      {receipt.passages_sent !== null && (
        <>
          <span>·</span>
          <span>
            {local
              ? `${receipt.passages_sent} passage${receipt.passages_sent === 1 ? "" : "s"} used`
              : `${receipt.passages_sent} passage${receipt.passages_sent === 1 ? "" : "s"} sent`}
          </span>
        </>
      )}
      {narrowed && (
        <>
          <span>·</span>
          <span className="text-amber-700 dark:text-amber-400">
            context narrowed: {narrowed}
          </span>
        </>
      )}
    </div>
  )
}
