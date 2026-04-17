import { useQuery } from "@tanstack/react-query"
import { 
  BookOpen, 
  ChevronRight, 
  FileText, 
  Grid, 
  Layers, 
  Play, 
  Search, 
  Tag as TagIcon,
  Zap
} from "lucide-react"
import { useState } from "react"
import { motion } from "framer-motion"
import { API_BASE } from "@/lib/config"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"

interface CollectionTopic {
  tag: string
  card_count: number
  note_count: number
}

interface CollectionSource {
  id: string
  title: string
  type: "document" | "note"
}

interface SubEnclave {
  id: string
  name: string
  card_count: number
}

interface DashboardData {
  collection_id: string
  collection_name: string
  due_today: number
  new_today: number
  mastery_pct: number
  topics: CollectionTopic[]
  sources: CollectionSource[]
  sub_collections: SubEnclave[]
}

interface CollectionStudyDashboardProps {
  collectionId: string
  onBack: () => void
  onStartStudy: (filters?: any) => void
  onGenerateFromGraph: () => void
  onGenerateCloze: () => void
  onNavigateToCollection: (id: string) => void
}

async function fetchDashboard(id: string): Promise<DashboardData> {
  const res = await fetch(`${API_BASE}/study/collections/${id}/dashboard`)
  if (!res.ok) throw new Error("Failed to load dashboard")
  return res.json()
}

export function CollectionStudyDashboard({ 
  collectionId, 
  onBack,
  onStartStudy,
  onGenerateFromGraph,
  onGenerateCloze,
  onNavigateToCollection
}: CollectionStudyDashboardProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["collection-dashboard", collectionId],
    queryFn: () => fetchDashboard(collectionId),
  })

  const [selectedTopic, setSelectedTopic] = useState<string | null>(null)
  const [selectedSources, setSelectedSources] = useState<Set<string>>(new Set())

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <p className="text-muted-foreground">Failed to load study dashboard</p>
        <button onClick={onBack} className="text-primary hover:underline">Go back</button>
      </div>
    )
  }

  const toggleSource = (id: string) => {
    const next = new Set(selectedSources)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelectedSources(next)
  }

  const handleStart = () => {
    onStartStudy({
      collection_id: collectionId,
      tag: selectedTopic || undefined,
      document_ids: Array.from(selectedSources).filter(id => data.sources.find(s => s.id === id && s.type === "document")),
      note_ids: Array.from(selectedSources).filter(id => data.sources.find(s => s.id === id && s.type === "note")),
    })
  }

  return (
    <div className="flex h-full flex-col gap-8 overflow-auto p-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button 
            onClick={onBack}
            className="flex h-8 w-8 items-center justify-center rounded-full hover:bg-accent"
          >
            <ChevronRight className="rotate-180" size={20} />
          </button>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              {data.collection_name}
            </h1>
            <p className="text-sm text-muted-foreground font-medium">Focused Study Environment</p>
          </div>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-border bg-card/50 px-4 py-1">
          <Layers size={14} className="text-primary" />
          <span className="text-xs font-medium uppercase">{data.sources.length} Sources</span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        {/* Main Section */}
        <div className="lg:col-span-2 flex flex-col gap-8">
          {/* Readiness Card */}
          <Card className="relative overflow-hidden border-none bg-gradient-to-br from-violet-600/20 to-emerald-600/10 p-8 shadow-2xl transition-all hover:scale-[1.01]">
            <div className="flex flex-col gap-6">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-2xl font-bold text-foreground">Ready to Study</h2>
                  <p className="text-muted-foreground">You have {data.due_today} flashcards due for review today.</p>
                </div>
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/20 text-primary">
                  <Zap size={24} />
                </div>
              </div>
              
              <div className="flex gap-4">
                <div className="rounded-xl bg-background/50 px-4 py-2 border border-border/50">
                  <p className="text-xs text-muted-foreground uppercase">New</p>
                  <p className="text-lg font-bold text-foreground">{data.new_today}</p>
                </div>
                <div className="rounded-xl bg-background/50 px-4 py-2 border border-border/50">
                  <p className="text-xs text-muted-foreground uppercase">Review</p>
                  <p className="text-lg font-bold text-foreground">{data.due_today}</p>
                </div>
                <div className="flex-1 rounded-xl bg-background/50 px-4 py-2 border border-border/50">
                  <div className="flex justify-between mb-1">
                    <p className="text-xs text-muted-foreground uppercase">Mastery</p>
                    <p className="text-xs font-bold text-foreground">{data.mastery_pct}%</p>
                  </div>
                  <Progress value={data.mastery_pct} className="h-1.5" />
                </div>
              </div>

              <button 
                onClick={handleStart}
                disabled={data.due_today + data.new_today === 0}
                className="flex items-center justify-center gap-2 rounded-xl bg-primary py-4 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/20 transition-all hover:bg-primary/90 hover:shadow-xl active:scale-[0.98] disabled:opacity-50"
              >
                <Play size={18} fill="currentColor" />
                Start Studying
              </button>
            </div>
            {/* Subtle glow effect */}
            <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-primary/10 blur-[100px]" />
          </Card>

          {/* Sub-Enclaves Grid */}
          {data.sub_collections.length > 0 && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <h3 className="flex items-center gap-2 font-semibold text-foreground">
                  <Layers size={18} className="text-primary" />
                  Nested Contexts
                </h3>
                <span className="text-xs text-muted-foreground">{data.sub_collections.length} Sub-Enclaves</span>
              </div>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {data.sub_collections.map((sub) => (
                  <motion.div
                    key={sub.id}
                    whileHover={{ scale: 1.02, x: 4 }}
                    onClick={() => onNavigateToCollection(sub.id)}
                    className="group flex cursor-pointer items-center justify-between rounded-2xl border border-border bg-card/60 p-4 transition-all hover:border-primary/50 hover:bg-card hover:shadow-md"
                  >
                    <div className="flex items-center gap-4">
                      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary transition-all group-hover:bg-primary group-hover:text-white">
                        <Layers size={20} />
                      </div>
                      <div>
                        <h4 className="font-semibold text-foreground group-hover:text-primary transition-colors">{sub.name}</h4>
                        <p className="text-[10px] uppercase font-bold text-muted-foreground">{sub.card_count} Cards Total</p>
                      </div>
                    </div>
                    <ChevronRight size={18} className="text-muted-foreground/40 group-hover:text-primary group-hover:translate-x-1 transition-all" />
                  </motion.div>
                ))}
              </div>
            </div>
          )}

          {/* Topics Grid */}
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h3 className="flex items-center gap-2 font-semibold text-foreground">
                <Grid size={18} className="text-primary" />
                Study Topics
              </h3>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Search size={12} />
                Explore all topics
              </div>
            </div>
            
            <div className="space-y-6">
              {/* Actionable Topics (with cards) */}
              {data.topics.filter(t => t.card_count > 0).length > 0 ? (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {data.topics.filter(t => t.card_count > 0).map((topic) => (
                    <motion.div
                      key={topic.tag}
                      whileHover={{ y: -4 }}
                      onClick={() => setSelectedTopic(selectedTopic === topic.tag ? null : topic.tag)}
                      className={`group relative cursor-pointer overflow-hidden rounded-2xl border p-5 transition-all ${
                        selectedTopic === topic.tag 
                          ? 'border-primary bg-primary/5 ring-1 ring-primary' 
                          : 'border-border bg-card hover:border-primary/50'
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-secondary text-secondary-foreground transition-colors group-hover:bg-primary/20 group-hover:text-primary">
                          <TagIcon size={20} />
                        </div>
                        <div className="text-right">
                          <p className="text-lg font-semibold text-foreground">{topic.tag}</p>
                          <p className="text-xs font-bold text-primary">{topic.card_count} Cards</p>
                        </div>
                      </div>
                      <div className="mt-4 flex items-center justify-between">
                        <span className="text-[10px] uppercase font-medium text-muted-foreground">
                          {topic.note_count} Digitized Notes
                        </span>
                        <div className={`h-1.5 w-1.5 rounded-full ${selectedTopic === topic.tag ? 'bg-primary animate-pulse' : 'bg-transparent'}`} />
                      </div>
                    </motion.div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-card/30 p-10 text-center">
                  <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
                    <Grid size={24} />
                  </div>
                  <h4 className="text-sm font-semibold text-foreground">No studies available yet</h4>
                  <p className="mt-1 text-xs text-muted-foreground">Use the synthesis engine to generate flashcards for this enclave.</p>
                </div>
              )}

              {/* Informational Topics (no cards) */}
              {data.topics.filter(t => t.card_count === 0).length > 0 && (
                <div className="space-y-3">
                  <h4 className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/80">
                    Recognized Concepts ({data.topics.filter(t => t.card_count === 0).length})
                  </h4>
                  <div className="flex flex-wrap gap-2">
                    {data.topics.filter(t => t.card_count === 0).map((topic) => (
                      <div 
                        key={topic.tag} 
                        className="flex items-center gap-2 rounded-full border border-border bg-muted/20 px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
                      >
                        <TagIcon size={12} className="opacity-60" />
                        <span className="font-medium">{topic.tag}</span>
                        <span className="ml-1 rounded-sm bg-muted-foreground/10 px-1 py-0.5 text-[8px] font-bold">
                          {topic.note_count} NOTES
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Sidebar Section */}
        <div className="flex flex-col gap-6">
          <div className="rounded-2xl border border-border bg-card/30 p-6 backdrop-blur-xl">
            <div className="mb-6 flex items-center justify-between">
              <h3 className="font-semibold text-foreground">Sources ({data.sources.length})</h3>
              <button 
                onClick={() => {
                  if (selectedSources.size === data.sources.length) {
                    setSelectedSources(new Set())
                  } else {
                    setSelectedSources(new Set(data.sources.map(s => s.id)))
                  }
                }}
                className="text-xs font-semibold text-primary hover:underline uppercase"
              >
                {selectedSources.size === data.sources.length ? 'Deselect All' : 'Select All'}
              </button>
           </div>
            
            <div className="flex flex-col gap-3 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
              {data.sources.map((source) => (
                <div 
                  key={source.id}
                  onClick={() => toggleSource(source.id)}
                  className={`flex cursor-pointer items-center justify-between rounded-xl p-3 transition-colors ${
                    selectedSources.has(source.id) 
                      ? 'bg-primary/10 border-primary/20 border' 
                      : 'hover:bg-accent border border-transparent'
                  }`}
                >
                  <div className="flex items-center gap-3 overflow-hidden">
                    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                      source.type === 'document' ? 'bg-blue-500/10 text-blue-500' : 'bg-amber-500/10 text-amber-500'
                    }`}>
                      {source.type === 'document' ? <BookOpen size={16} /> : <FileText size={16} />}
                    </div>
                    <span className="truncate text-xs font-medium text-foreground">{source.title}</span>
                  </div>
                  <div className={`h-4 w-4 rounded-full border transition-all ${
                    selectedSources.has(source.id) 
                      ? 'bg-primary border-primary flex items-center justify-center' 
                      : 'border-muted-foreground/30'
                  }`}>
                    {selectedSources.has(source.id) && <div className="h-1.5 w-1.5 rounded-full bg-white" />}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <Card 
            className="flex flex-col gap-4 p-6 border-2 border-dashed border-primary/30 bg-primary/5 hover:bg-primary/10 transition-all cursor-pointer group shadow-xl shadow-primary/5"
            onClick={onGenerateFromGraph}
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground group-hover:scale-110 transition-transform shadow-lg shadow-primary/20">
              <Layers size={24} />
            </div>
            <div>
              <p className="font-bold text-base text-foreground underline decoration-primary/30 underline-offset-4">Synthesis Engine</p>
              <p className="text-xs text-muted-foreground mt-2 leading-relaxed">
                Connect concepts across your selected sources and generate high-quality flashcards for this enclave.
              </p>
            </div>
            <div className="mt-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-primary">
              <span>Start Flash Synthesis</span>
              <ChevronRight size={14} className="group-hover:translate-x-1 transition-transform" />
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
