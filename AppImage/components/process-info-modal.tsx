"use client"

import { useEffect, useState } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./ui/dialog"
import { ScrollArea } from "./ui/scroll-area"
import { Activity, FileText, HardDrive, Clock } from "lucide-react"
import { fetchApi } from "@/lib/api-config"

interface ProcessDetail {
  pid: number
  comm: string
  cmdline: string
  exe: string | null
  cwd: string | null
  state: string
  ppid: number
  parent_name: string | null
  threads: number
  vm_rss_kb: number
  vm_size_kb: number
  vm_swap_kb: number
  user: string
  group: string
  uid: number
  gid: number
  start_time: string | null
  elapsed: string | null
  cpu: number
  mem: number
  io_read_bytes: number | null
  io_write_bytes: number | null
  fd_count: number | null
  captured_at: number
}

interface ProcessInfoModalProps {
  pid: number | null
  accent: { dot: string; bar: string; text: string }
  onClose: () => void
}

const REFRESH_MS = 3000

const formatKb = (kb: number | null | undefined): string => {
  if (kb == null) return "—"
  if (kb >= 1024 * 1024) return `${(kb / 1024 / 1024).toFixed(2)} GB`
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} MB`
  return `${kb} KB`
}

const formatBytes = (b: number | null | undefined): string => {
  if (b == null) return "—"
  if (b >= 1024 * 1024 * 1024) return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`
  if (b >= 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${b} B`
}

// Linux process states from /proc/<pid>/status. The first char of `State:`
// is the canonical letter — the rest of the field is a human label like
// "(running)". We expand the bare letter to something readable.
const stateLabel = (state: string): string => {
  const letter = (state || "").trim().charAt(0).toUpperCase()
  const map: Record<string, string> = {
    R: "Running",
    S: "Sleeping",
    D: "Disk wait",
    Z: "Zombie",
    T: "Stopped",
    t: "Tracing stop",
    X: "Dead",
    I: "Idle",
  }
  return map[letter] || state || "—"
}

export function ProcessInfoModal({ pid, accent, onClose }: ProcessInfoModalProps) {
  const [data, setData] = useState<ProcessDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const open = pid != null

  const fetchDetail = async (silent = false) => {
    if (pid == null) return
    if (!silent) setLoading(true)
    setError(null)
    try {
      const res = await fetchApi<ProcessDetail>(`/api/processes/${pid}`)
      setData(res)
    } catch (e: any) {
      // 404 means the process exited while the modal was open — surface a
      // clear message instead of stale data, but don't auto-close (user may
      // want to read the last snapshot).
      setError(e?.message?.includes("404") ? "Process exited" : (e?.message || "Failed to fetch process"))
      if (e?.message?.includes("404")) setData(null)
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    if (pid == null) {
      setData(null)
      setError(null)
      return
    }
    fetchDetail()
    const id = setInterval(() => fetchDetail(true), REFRESH_MS)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid])

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 min-w-0">
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ background: accent.dot }}
            />
            <span className="truncate font-mono text-base">{data?.comm || "Process"}</span>
            <span className="text-xs text-muted-foreground font-mono flex-shrink-0">PID {pid}</span>
          </DialogTitle>
          <DialogDescription className="text-xs">
            Live snapshot from <span className="font-mono">/proc/{pid}</span>. Auto-refreshes every {REFRESH_MS / 1000} s while open.
          </DialogDescription>
        </DialogHeader>

        {error && !data ? (
          <div className="text-sm text-red-500 py-4">{error}</div>
        ) : !data ? (
          <div className="text-sm text-muted-foreground py-8 text-center">
            {loading ? "Loading…" : "—"}
          </div>
        ) : (
          <ScrollArea className="max-h-[480px] pr-2">
            <div className="space-y-4">
              {/* Overview */}
              <Section icon={<Activity className="h-4 w-4 text-blue-400" />} title="Overview">
                <Row label="State" value={stateLabel(data.state)} />
                <Row label="Parent" value={data.parent_name ? `${data.parent_name} (PID ${data.ppid})` : `PID ${data.ppid}`} mono />
                <Row label="Threads" value={String(data.threads)} mono />
                <Row label="Open FDs" value={data.fd_count != null ? String(data.fd_count) : "—"} mono />
                <Row label="User" value={`${data.user} (${data.uid})`} mono />
                <Row label="Group" value={`${data.group} (${data.gid})`} mono />
              </Section>

              {/* Resources */}
              <Section icon={<HardDrive className="h-4 w-4 text-amber-400" />} title="Resources">
                <Row label="CPU" value={`${data.cpu.toFixed(1)} %`} mono valueClass={accent.text} />
                <Row label="Memory" value={`${data.mem.toFixed(1)} %`} mono valueClass={accent.text} />
                <Row label="Resident (RSS)" value={formatKb(data.vm_rss_kb)} mono />
                <Row label="Virtual size" value={formatKb(data.vm_size_kb)} mono />
                <Row label="Swap" value={formatKb(data.vm_swap_kb)} mono />
                <Row label="I/O read" value={formatBytes(data.io_read_bytes)} mono />
                <Row label="I/O write" value={formatBytes(data.io_write_bytes)} mono />
              </Section>

              {/* Command */}
              <Section icon={<FileText className="h-4 w-4 text-purple-400" />} title="Command">
                <Row label="Name" value={data.comm} mono />
                <Row label="Command line" value={data.cmdline || data.comm} mono wrap />
                <Row label="Executable" value={data.exe || "—"} mono wrap />
                <Row label="Working dir" value={data.cwd || "—"} mono wrap />
              </Section>

              {/* Times */}
              <Section icon={<Clock className="h-4 w-4 text-emerald-400" />} title="Lifetime">
                <Row label="Started" value={data.start_time || "—"} mono />
                <Row label="Running for" value={data.elapsed || "—"} mono />
              </Section>
            </div>
          </ScrollArea>
        )}

        {data?.captured_at && (
          <div className="text-[10px] text-muted-foreground text-right mt-1">
            Captured {new Date(data.captured_at * 1000).toLocaleTimeString()}
            {error ? ` · ${error}` : ""}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="border border-border rounded-md overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 bg-card text-xs font-medium uppercase tracking-wider text-muted-foreground border-b border-border">
        {icon}
        {title}
      </div>
      <div className="divide-y divide-border/40">{children}</div>
    </div>
  )
}

function Row({
  label,
  value,
  mono,
  wrap,
  valueClass,
}: {
  label: string
  value: string
  mono?: boolean
  wrap?: boolean
  valueClass?: string
}) {
  return (
    <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-2 px-3 py-1.5 text-xs">
      <div className="text-muted-foreground">{label}</div>
      <div
        className={`${mono ? "font-mono" : ""} ${wrap ? "break-all" : "truncate"} ${valueClass || ""}`}
        title={value}
      >
        {value}
      </div>
    </div>
  )
}
