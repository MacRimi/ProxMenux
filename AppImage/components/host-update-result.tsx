"use client"

import { useEffect, useRef, useState } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./ui/dialog"
import { Button } from "./ui/button"
import { getAuthToken } from "../lib/api-config"
import { scriptCompletion } from "../lib/script-completion"
import { useT } from "../lib/i18n/provider"
import "xterm/css/xterm.css"

export function HostUpdateResult({ jobId, getApiUrl, onClose }: {
  jobId: string | null
  getApiUrl: (path: string) => string
  onClose: () => void
}) {
  const t = useT()
  const container = useRef<HTMLDivElement>(null)
  const [revision, setRevision] = useState(0)
  const [exitCode, setExitCode] = useState<number | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (!jobId) return
    const controller = new AbortController()
    let terminal: import("xterm").Terminal | undefined
    let observer: ResizeObserver | undefined
    let disposed = false
    setExitCode(null); setFailed(false)
    const timeout = setTimeout(() => controller.abort(), 10000)
    void (async () => {
      try {
        const token = getAuthToken()
        const response = await fetch(getApiUrl(`/api/host-update-jobs/${encodeURIComponent(jobId)}/result`), {
          headers: token ? { Authorization: `Bearer ${token}` } : {}, signal: controller.signal,
        })
        if (!response.ok) throw Error("unavailable")
        const value = await response.json()
        if (value.state !== "complete" || !Number.isSafeInteger(value.exit_code)
          || typeof value.text !== "string" || value.text.length > 256 * 1024
          || typeof value.truncated !== "boolean") throw Error("invalid result")
        const [{ Terminal }, { FitAddon }] = await Promise.all([import("xterm"), import("xterm-addon-fit")])
        if (controller.signal.aborted || !container.current) return
        terminal = new Terminal({ disableStdin: true, convertEol: true, fontSize: 12,
          screenReaderMode: true, theme: { background: "#000000", foreground: "#dddddd" } })
        const fit = new FitAddon()
        terminal.loadAddon(fit); terminal.open(container.current); fit.fit()
        if (value.truncated) terminal.writeln(t("vmLxc.updates.backgroundOutputTrimmed"))
        terminal.write(value.text)
        observer = new ResizeObserver(() => { if (!controller.signal.aborted) fit.fit() })
        observer.observe(container.current)
        setExitCode(value.exit_code)
      } catch {
        if (!disposed) setFailed(true)
      } finally { clearTimeout(timeout) }
    })()
    return () => { disposed = true; controller.abort(); clearTimeout(timeout); observer?.disconnect(); terminal?.dispose() }
  }, [jobId, getApiUrl, revision, t])
  const kind = exitCode === null ? null : scriptCompletion(exitCode, 130).kind
  return <Dialog open={jobId !== null} onOpenChange={open => { if (!open) onClose() }}>
    <DialogContent className="max-w-4xl w-[95vw] max-h-[85vh] overflow-y-auto p-4 sm:p-5">
      <DialogHeader><DialogTitle>{t("healthStatus.hostUpdate.resultTitle")}</DialogTitle>
        <DialogDescription>{t("healthStatus.hostUpdate.resultReadOnly")}</DialogDescription></DialogHeader>
      {failed && <div role="alert" className="text-sm text-amber-500">
        <p>{t("healthStatus.hostUpdate.resultUnavailable")}</p>
        <Button size="sm" variant="outline" className="mt-3" onClick={() => setRevision(value => value + 1)}>{t("healthStatus.hostUpdate.retryResult")}</Button>
      </div>}
      <div ref={container} className="h-[45vh] min-h-[180px] bg-black rounded overflow-hidden" />
      <div className="flex items-center justify-between gap-3">
        <p role="status" className={`text-xs ${exitCode === 0 ? "text-green-500" : "text-muted-foreground"}`}>
          {kind === null ? t(failed ? "healthStatus.hostUpdate.resultUnavailable" : "healthStatus.hostUpdate.loadingResult")
            : kind === "cancelled" ? t("scriptTerminal.cancelled") : exitCode === 0
            ? t("scriptTerminal.completedSuccessfully") : t("scriptTerminal.completedWithError", { code: exitCode })}
        </p>
        <Button size="sm" variant="outline" onClick={onClose}>{t("healthStatus.hostUpdate.closeResult")}</Button>
      </div>
    </DialogContent>
  </Dialog>
}
