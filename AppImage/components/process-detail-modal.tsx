"use client"

import { useEffect, useState } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./ui/dialog"
import { Input } from "./ui/input"
import { ScrollArea } from "./ui/scroll-area"
import { Cpu, MemoryStick, Search } from "lucide-react"
import { fetchApi } from "@/lib/api-config"
import { ProcessInfoModal } from "./process-info-modal"

interface ProcessInfo {
  pid: number
  user: string
  cpu: number
  mem: number
  rss_kb: number
  command: string
}

interface ProcessesResponse {
  processes: ProcessInfo[]
  sort: "cpu" | "mem"
  captured_at: number
}

interface ProcessDetailModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Which metric the parent card represents (drives default sort + emphasis) */
  sort: "cpu" | "mem"
}

const REFRESH_MS = 5000
const LIMIT = 25

const formatRss = (kb: number): string => {
  if (kb >= 1024 * 1024) return `${(kb / 1024 / 1024).toFixed(2)} GB`
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} MB`
  return `${kb} KB`
}

export function ProcessDetailModal({ open, onOpenChange, sort }: ProcessDetailModalProps) {
  const [data, setData] = useState<ProcessesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState("")
  const [selectedPid, setSelectedPid] = useState<number | null>(null)

  const fetchProcesses = async (silent = false) => {
    if (!silent) setLoading(true)
    setError(null)
    try {
      const res = await fetchApi<ProcessesResponse>(`/api/processes?sort=${sort}&limit=${LIMIT}`)
      setData(res)
    } catch (e: any) {
      setError(e?.message || "Failed to fetch processes")
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    fetchProcesses()
    const id = setInterval(() => fetchProcesses(true), REFRESH_MS)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sort])

  // Reset filter when dialog closes
  useEffect(() => {
    if (!open) setFilter("")
  }, [open])

  const filtered = (data?.processes ?? []).filter((p) => {
    if (!filter) return true
    const q = filter.toLowerCase()
    return (
      p.command.toLowerCase().includes(q) ||
      p.user.toLowerCase().includes(q) ||
      String(p.pid).includes(q)
    )
  })

  const Icon = sort === "cpu" ? Cpu : MemoryStick
  const title = sort === "cpu" ? "Top processes by CPU" : "Top processes by Memory"
  const description =
    sort === "cpu"
      ? "Snapshot from `ps` sorted by CPU usage. Auto-refreshes every 5 s while this dialog is open."
      : "Snapshot from `ps` sorted by resident memory. Auto-refreshes every 5 s while this dialog is open."

  // Accent palette matched to the Overview cards: CPU Usage donut uses
  // blue (#3b82f6), Memory cached uses rgba(99,102,241,0.55) — we keep
  // the same hues so the modal feels like a continuation of the card.
  const accent = sort === "cpu"
    ? { dot: "#3b82f6", bar: "#3b82f6", text: "text-blue-500" }
    : { dot: "#6366f1", bar: "#6366f1", text: "text-indigo-400" }

  // Scale bars to the largest value in the (filtered) list so the visual
  // ranking is preserved even when no process is near 100 %. CPU can
  // exceed 100 % on multi-threaded apps — falling back to max=1 prevents
  // a divide-by-zero when the list is empty.
  const maxPrimary = Math.max(
    1,
    ...filtered.map((p) => (sort === "cpu" ? p.cpu : p.mem))
  )

  // Mobile drops PID + USER; desktop keeps the full 5-column layout.
  // CPU and MEM columns are wider on desktop with a real gap between
  // them so the two metrics don't feel glued together.
  const gridCols =
    "grid-cols-[minmax(0,1fr)_70px_90px] sm:grid-cols-[60px_96px_minmax(140px,1fr)_110px_120px]"

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Icon className={`h-5 w-5 ${accent.text}`} />
              {title}
            </DialogTitle>
            <DialogDescription className="text-xs">{description}</DialogDescription>
          </DialogHeader>

          <div className="relative mb-2">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Filter by command, user or PID..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="pl-8 h-8 text-sm"
            />
          </div>

          {error ? (
            <div className="text-sm text-red-500 py-4">{error}</div>
          ) : (
            <ScrollArea className="h-[440px] border border-border rounded-md">
              <div className="min-w-full">
                {/* Sticky solid header so scrolled rows don't bleed through */}
                <div
                  className={`grid items-center gap-x-3 sm:gap-x-6 px-3 py-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground border-b border-border bg-card sticky top-0 z-10 ${gridCols}`}
                >
                  <div className="hidden sm:block">PID</div>
                  <div className="hidden sm:block truncate">User</div>
                  <div>Command</div>
                  <div className={`text-right ${sort === "cpu" ? accent.text : ""}`}>CPU %</div>
                  <div className={`text-right ${sort === "mem" ? accent.text : ""}`}>{sort === "mem" ? "Memory" : "Mem %"}</div>
                </div>

                {filtered.length === 0 && !loading ? (
                  <div className="text-center py-8 text-sm text-muted-foreground">
                    No processes match the filter
                  </div>
                ) : (
                  filtered.map((p) => {
                    const primary = sort === "cpu" ? p.cpu : p.mem
                    const barPct = Math.min(100, (primary / maxPrimary) * 100)
                    return (
                      <button
                        key={p.pid}
                        type="button"
                        onClick={() => setSelectedPid(p.pid)}
                        className={`w-full text-left grid items-center gap-x-3 sm:gap-x-6 px-3 py-2 border-b border-border/40 hover:bg-white/5 transition-colors ${gridCols}`}
                      >
                        <div className="hidden sm:flex font-mono text-xs items-center gap-1.5 min-w-0">
                          <span
                            className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                            style={{ background: accent.dot }}
                          />
                          <span className="truncate">{p.pid}</span>
                        </div>
                        <div className="hidden sm:block font-mono text-xs truncate" title={p.user}>{p.user}</div>
                        <div className="font-mono text-xs truncate min-w-0 flex items-center gap-1.5" title={p.command}>
                          {/* Mobile only: keep the accent dot since PID column is gone */}
                          <span
                            className="sm:hidden w-1.5 h-1.5 rounded-full flex-shrink-0"
                            style={{ background: accent.dot }}
                          />
                          <span className="truncate">{p.command}</span>
                        </div>

                        {/* Primary metric: value + sized progress bar in the accent colour */}
                        {sort === "cpu" ? (
                          <div className="flex flex-col items-end gap-1 min-w-0">
                            <span className={`font-mono text-sm font-semibold ${accent.text}`}>{p.cpu.toFixed(1)}</span>
                            <div className="w-full h-1 bg-muted rounded-full overflow-hidden">
                              <div className="h-full rounded-full" style={{ width: `${barPct}%`, background: accent.bar }} />
                            </div>
                          </div>
                        ) : (
                          <div className="font-mono text-xs text-right text-muted-foreground">{p.cpu.toFixed(1)}</div>
                        )}

                        {/* Secondary column: mem % when CPU is primary, RSS when memory is primary */}
                        {sort === "cpu" ? (
                          <div className="font-mono text-xs text-right text-muted-foreground">{p.mem.toFixed(1)}</div>
                        ) : (
                          <div className="flex flex-col items-end gap-1 min-w-0">
                            <span className={`font-mono text-sm font-semibold ${accent.text}`}>{formatRss(p.rss_kb)}</span>
                            <div className="w-full h-1 bg-muted rounded-full overflow-hidden">
                              <div className="h-full rounded-full" style={{ width: `${barPct}%`, background: accent.bar }} />
                            </div>
                          </div>
                        )}
                      </button>
                    )
                  })
                )}
              </div>
            </ScrollArea>
          )}

          {data?.captured_at && (
            <div className="text-[10px] text-muted-foreground text-right mt-1">
              Captured {new Date(data.captured_at * 1000).toLocaleTimeString()} · {filtered.length} of {data.processes.length} shown
            </div>
          )}
        </DialogContent>
      </Dialog>

      <ProcessInfoModal
        pid={selectedPid}
        accent={accent}
        onClose={() => setSelectedPid(null)}
      />
    </>
  )
}
