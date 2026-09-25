"use client"

// Console output of a native OCI container: what the image's main process
// writes to stdout/stderr, kept on the host by liblxc. The first request
// brings the last N lines; while following, each poll sends back the byte
// offset and inode it holds and receives only what was appended. Nothing is
// cached — the backend reads the file on every request.

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Card, CardContent } from "./ui/card"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { AlertCircle, Download, FileText, Loader2, Pause, Play, RefreshCw } from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT } from "@/lib/i18n/provider"

interface ConsoleLogResponse {
  ok: boolean
  enabled: boolean
  lines: string[]
  offset: number
  inode: number | null
  reset?: boolean
  head_truncated?: boolean
  error?: string
}

const LINE_OPTIONS = [100, 500, 1000] as const
const POLL_MS = 2000

const lineTone = (line: string) => {
  if (/\b(error|fatal|panic|critical|exception)\b/i.test(line)) return "text-red-400"
  if (/\bwarn(ing)?\b/i.test(line)) return "text-amber-400"
  return "text-foreground/90"
}

export function OciConsoleLogPanel({ vmid, running }: { vmid: number; running: boolean }) {
  const t = useT()
  const [lineCount, setLineCount] = useState<number>(500)
  const [lines, setLines] = useState<string[]>([])
  const [enabled, setEnabled] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [follow, setFollow] = useState(true)
  const [filter, setFilter] = useState("")
  const position = useRef<{ offset: number; inode: number | null } | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const inFlight = useRef(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetchApi<ConsoleLogResponse>(`/api/lxc/${vmid}/console-log?lines=${lineCount}`)
      setEnabled(r.enabled)
      setLines(r.lines || [])
      position.current = { offset: r.offset, inode: r.inode }
      if (r.error) setError(r.error)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [vmid, lineCount])

  const poll = useCallback(async () => {
    const pos = position.current
    if (!pos || inFlight.current) return
    inFlight.current = true
    try {
      const inode = pos.inode === null ? "" : `&inode=${pos.inode}`
      const r = await fetchApi<ConsoleLogResponse>(
        `/api/lxc/${vmid}/console-log?lines=${lineCount}&offset=${pos.offset}${inode}`,
      )
      position.current = { offset: r.offset, inode: r.inode }
      if (r.reset) {
        setLines(r.lines || [])
      } else if (r.lines?.length) {
        setLines((prev) => {
          const next = prev.concat(r.lines)
          return next.length > lineCount ? next.slice(next.length - lineCount) : next
        })
      }
    } catch {
      // A failed poll leaves the view as it is; the next one retries.
    } finally {
      inFlight.current = false
    }
  }, [vmid, lineCount])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!follow || !running || !enabled || loading) return
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") poll()
    }, POLL_MS)
    poll()
    return () => clearInterval(timer)
  }, [follow, running, enabled, loading, poll])

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    return needle ? lines.filter((l) => l.toLowerCase().includes(needle)) : lines
  }, [lines, filter])

  useEffect(() => {
    if (follow && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
  }, [shown, follow])

  // Scrolling up to read stops following; the Follow button resumes it.
  const onScroll = () => {
    const el = scroller.current
    if (!el || !follow) return
    if (el.scrollHeight - el.scrollTop - el.clientHeight > 40) setFollow(false)
  }

  const download = () => {
    const blob = new Blob([lines.join("\n") + "\n"], { type: "text/plain;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `ct-${vmid}-console.log`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="h-full flex flex-col min-h-0">
      <Card className="border border-border bg-card/50 flex flex-col flex-1 min-h-0">
        <CardContent className="p-4 flex flex-col flex-1 min-h-0">
          <div className="flex items-center justify-between mb-2 gap-2 flex-wrap shrink-0">
            <div className="flex items-center gap-2">
              <div className="p-1.5 rounded-md bg-sky-500/10">
                <FileText className="h-4 w-4 text-sky-500" />
              </div>
              <h3 className="text-sm font-semibold text-foreground">{t("vmLxc.consoleLog.title")}</h3>
              {enabled && shown.length > 0 && (
                <Badge variant="secondary" className="text-xs h-5 ml-1">{shown.length}</Badge>
              )}
            </div>
            {enabled && (
              <div className="flex items-center gap-2 flex-wrap">
                <Select value={String(lineCount)} onValueChange={(v) => setLineCount(Number(v))}>
                  <SelectTrigger className="h-7 w-auto text-xs gap-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LINE_OPTIONS.map((n) => (
                      <SelectItem key={n} value={String(n)} className="text-xs">
                        {t("vmLxc.consoleLog.lastLines", { count: n })}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {running && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs gap-1"
                    onClick={() => setFollow((f) => !f)}
                    aria-pressed={follow}
                  >
                    {follow ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                    <span>{follow ? t("vmLxc.consoleLog.pause") : t("vmLxc.consoleLog.follow")}</span>
                  </Button>
                )}
                <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={load} disabled={loading}>
                  {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                  <span>{t("vmLxc.consoleLog.refresh")}</span>
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs gap-1"
                  onClick={download}
                  disabled={lines.length === 0}
                >
                  <Download className="h-3 w-3" />
                  <span>{t("vmLxc.consoleLog.download")}</span>
                </Button>
              </div>
            )}
          </div>

          <p className="text-xs text-muted-foreground mb-3 shrink-0">
            {t("vmLxc.consoleLog.description")}
            {enabled && !running && <> {t("vmLxc.consoleLog.stopped")}</>}
          </p>

          {enabled && (
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t("vmLxc.consoleLog.filter")}
              className="h-8 text-xs mb-3 shrink-0"
            />
          )}

          {loading && lines.length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-muted-foreground min-h-0">
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              <span className="text-sm">{t("vmLxc.consoleLog.loading")}</span>
            </div>
          ) : error ? (
            <div className="rounded-md border border-red-500/30 bg-red-500/5 p-4 text-sm shrink-0">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium text-red-500 mb-1">{t("vmLxc.consoleLog.readFailed")}</p>
                  <p className="text-xs text-muted-foreground break-all">{error}</p>
                </div>
              </div>
            </div>
          ) : !enabled ? (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-4 text-sm shrink-0">
              <div className="flex items-start gap-2">
                <FileText className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                <div className="space-y-2">
                  <p className="font-medium text-amber-500">{t("vmLxc.consoleLog.notAvailableTitle")}</p>
                  <p className="text-xs text-muted-foreground leading-relaxed">{t("vmLxc.consoleLog.notAvailableHint")}</p>
                </div>
              </div>
            </div>
          ) : lines.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center text-sm text-muted-foreground min-h-0">
              {t("vmLxc.consoleLog.empty")}
              <div className="text-xs mt-1">{t("vmLxc.consoleLog.emptyHint")}</div>
            </div>
          ) : shown.length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground min-h-0">
              {t("vmLxc.consoleLog.noMatches")}
            </div>
          ) : (
            <div
              ref={scroller}
              onScroll={onScroll}
              className="rounded-md border border-border bg-background/50 flex-1 overflow-y-auto min-h-0"
            >
              <pre className="text-[11px] font-mono leading-snug whitespace-pre-wrap break-all p-3">
                {shown.map((line, idx) => (
                  <div key={idx} className={lineTone(line)}>{line || " "}</div>
                ))}
              </pre>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
