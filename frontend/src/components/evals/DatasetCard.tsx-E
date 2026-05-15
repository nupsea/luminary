import { Activity, Database, PlayCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { cn } from "@/lib/utils"
import type { GoldenDataset } from "./types"

function pct(value: number | null | undefined): string {
  if (value == null) return "n/a"
  return `${Math.round(value * 100)}%`
}

function statusVariant(status: string): "gray" | "blue" | "green" | "default" {
  if (status === "complete") return "green"
  if (status === "generating" || status === "pending") return "blue"
  if (status === "failed") return "gray"
  return "default"
}

interface DatasetCardProps {
  dataset: GoldenDataset
  selected: boolean
  onSelect: () => void
}

export function DatasetCard({ dataset, selected, onSelect }: DatasetCardProps) {
  const progress =
    dataset.target_count > 0 ? (dataset.generated_count / dataset.target_count) * 100 : 100
  const canOpen = true

  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={canOpen ? onSelect : undefined}
      onKeyDown={(event) => {
        if (canOpen && (event.key === "Enter" || event.key === " ")) onSelect()
      }}
      className={cn(
        "flex min-h-44 flex-col gap-3 rounded-md p-4",
        canOpen && "cursor-pointer",
        selected && "border-primary shadow-md",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-foreground">{dataset.name}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <Badge variant={statusVariant(dataset.status)}>{dataset.status}</Badge>
            {dataset.size && <Badge variant="gray">{dataset.size}</Badge>}
            <Badge variant={dataset.source === "db" ? "indigo" : "gray"}>{dataset.source}</Badge>
          </div>
        </div>
        {dataset.status === "complete" ? (
          <PlayCircle className="h-4 w-4 shrink-0 text-green-600" />
        ) : (
          <Activity className="h-4 w-4 shrink-0 text-primary" />
        )}
      </div>

      {(dataset.status === "generating" || dataset.status === "pending") && (
        <div className="space-y-1">
          <Progress value={progress} />
          <div className="text-xs text-muted-foreground">
            {dataset.generated_count}/{dataset.target_count} questions
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="text-muted-foreground">HR@5</div>
          <div className="font-medium">{pct(dataset.last_run?.hit_rate_5)}</div>
        </div>
        <div>
          <div className="text-muted-foreground">MRR</div>
          <div className="font-medium">{pct(dataset.last_run?.mrr)}</div>
        </div>
        <div>
          <div className="text-muted-foreground">Faith</div>
          <div className="font-medium">{pct(dataset.last_run?.faithfulness)}</div>
        </div>
      </div>

      <div className="mt-auto flex items-center gap-2 text-xs text-muted-foreground">
        <Database className="h-3.5 w-3.5" />
        <span className="truncate">{dataset.generator_model || "file-backed golden"}</span>
      </div>
    </Card>
  )
}
