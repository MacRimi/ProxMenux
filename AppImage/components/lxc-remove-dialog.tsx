"use client"

import { useEffect, useRef, useState } from "react"
import { AlertTriangle, CheckCircle2, Loader2, Trash2 } from "lucide-react"

import { fetchApi } from "../lib/api-config"
import {
  clearLxcRemovalReceipt,
  loadLxcRemovalReceipt,
  readLxcRemovalTask,
  saveLxcRemovalReceipt,
  type LxcRemovalReceipt,
  type LxcRemovalTaskResult,
} from "../lib/lxc-removal"
import { useT } from "@/lib/i18n/provider"
import { Button } from "./ui/button"
import { Checkbox } from "./ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog"
import { Input } from "./ui/input"
import { Label } from "./ui/label"

type LxcTarget = { vmid: number; name: string; type: string }

interface RemovalPreview {
  eligible: boolean
  reasons: string[]
  check: string | null
  target: { vmid: number; name: string }
}

interface TrackedRemoval extends LxcRemovalReceipt {
  result: LxcRemovalTaskResult
}

interface LxcRemoveDialogProps {
  target: LxcTarget | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onRemoved: (vmid: number) => void
}

const resultStyle: Record<LxcRemovalTaskResult["state"], string> = {
  running: "border-blue-500/30 bg-blue-500/5 text-blue-400",
  succeeded: "border-green-500/30 bg-green-500/5 text-green-400",
  failed: "border-red-500/30 bg-red-500/5 text-red-400",
  warning: "border-amber-500/30 bg-amber-500/5 text-amber-400",
  unknown: "border-amber-500/30 bg-amber-500/5 text-amber-400",
}

function errorBody(error: unknown): { error?: string; preview?: RemovalPreview } | null {
  if (error && typeof error === "object" && "body" in error) {
    const body = (error as { body?: unknown }).body
    if (body && typeof body === "object") return body as { error?: string; preview?: RemovalPreview }
  }
  return null
}

export function LxcRemoveDialog({ target, open, onOpenChange, onRemoved }: LxcRemoveDialogProps) {
  const t = useT()
  const [preview, setPreview] = useState<RemovalPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [typedVmid, setTypedVmid] = useState("")
  const [purge, setPurge] = useState(false)
  const [destroyUnreferenced, setDestroyUnreferenced] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [tracked, setTracked] = useState<TrackedRemoval | null>(null)
  const submitRef = useRef(false)
  const previewRequest = useRef(0)
  const completedRef = useRef<string | null>(null)
  const active = tracked && (!target || tracked.vmid === target.vmid) ? tracked : null
  const running = active?.result.state === "running"
  const activeVmid = active?.vmid
  const activeCheck = active?.check

  useEffect(() => {
    const receipt = loadLxcRemovalReceipt()
    if (!receipt || target) return
    setTracked({ ...receipt, result: { state: "running", task: null, reason: "dispatch_pending" } })
    onOpenChange(true)
  // Recover an in-flight task once, on page load. `onOpenChange` is stable in the parent.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const refreshPreview = async () => {
    if (!target || target.type !== "lxc") return
    const request = ++previewRequest.current
    setLoadingPreview(true)
    setPreviewError(null)
    setPreview(null)
    setTypedVmid("")
    setPurge(false)
    setDestroyUnreferenced(false)
    try {
      const result = await fetchApi<RemovalPreview>(`/api/vms/${target.vmid}/remove-preview`, {
        signal: AbortSignal.timeout(10_000),
      })
      if (previewRequest.current === request) setPreview(result)
    } catch (error) {
      if (previewRequest.current === request) setPreviewError(error instanceof Error ? error.message : String(error))
    } finally {
      if (previewRequest.current === request) setLoadingPreview(false)
    }
  }

  useEffect(() => {
    if (!open || !target) return
    if (active) return
    const receipt = loadLxcRemovalReceipt(target.vmid)
    if (receipt) {
      setTracked({ ...receipt, result: { state: "running", task: null, reason: "dispatch_pending" } })
    } else {
      setTracked(null)
      void refreshPreview()
    }
    return () => { previewRequest.current += 1 }
  // Preview is deliberately fresh per opening; no cached authorization is reused.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, target?.vmid])

  useEffect(() => {
    if (!open || !activeVmid || !activeCheck || !running) return
    let cancelled = false
    let failures = 0
    const deadline = Date.now() + 180_000
    let timer: ReturnType<typeof setTimeout> | undefined
    const inspect = async () => {
      let result: LxcRemovalTaskResult
      try {
        result = await readLxcRemovalTask({ vmid: activeVmid, check: activeCheck })
      } catch {
        result = { state: "unknown", task: null, reason: "task_status_unavailable" }
      }
      if (cancelled) return
      failures = result.state === "unknown" ? failures + 1 : 0
      if (Date.now() < deadline && result.state === "unknown" && failures < 3) {
        timer = setTimeout(() => void inspect(), 1500)
        return
      }
      if (result.state === "running" && Date.now() >= deadline) {
        result = { state: "unknown", task: result.task, reason: "task_still_running" }
      }
      setTracked(current => current?.check === activeCheck
        ? { ...current, result: { ...result, task: result.task ?? current.result.task } }
        : current)
      if (result.state === "running") timer = setTimeout(() => void inspect(), 1500)
    }
    void inspect()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [open, activeVmid, activeCheck, running])

  useEffect(() => {
    if (active?.result.state !== "succeeded" || completedRef.current === active.check) return
    completedRef.current = active.check
    clearLxcRemovalReceipt(active.vmid)
    onRemoved(active.vmid)
  }, [onRemoved, active])

  const submit = async () => {
    if (!preview?.check || !target || preview.target.vmid !== target.vmid || !removeEnabled || submitRef.current) return
    const receipt = { vmid: target.vmid, check: preview.check }
    const request = previewRequest.current
    if (!saveLxcRemovalReceipt(receipt)) {
      setPreviewError("receipt_unavailable")
      return
    }
    submitRef.current = true
    setSubmitting(true)
    try {
      const result = await fetchApi<LxcRemovalTaskResult>(`/api/vms/${target.vmid}/remove`, {
        method: "POST",
        signal: AbortSignal.timeout(30_000),
        body: JSON.stringify({
          check: preview.check,
          confirm_vmid: typedVmid,
          purge,
          destroy_unreferenced_disks: destroyUnreferenced,
        }),
      })
      setTracked({ ...receipt, result })
    } catch (error) {
      const body = errorBody(error)
      if (body?.error && ["target_changed", "removal_blocked", "check_expired", "check_mismatch",
        "confirmation_required"].includes(body.error)) {
        clearLxcRemovalReceipt(receipt.vmid)
        if (previewRequest.current === request) {
          if (body.preview) setPreview(body.preview)
          setPreviewError(body.error === "removal_blocked" ? null : body.error)
        }
      } else {
        setTracked({ ...receipt, result: { state: "unknown", task: null, reason: "submission_unconfirmed" } })
      }
    } finally {
      submitRef.current = false
      setSubmitting(false)
    }
  }

  const displayTarget = preview?.target.vmid === target?.vmid ? preview?.target : null
  const blocked = Boolean(displayTarget && preview && !preview.eligible)
  const terminal = active?.result
  const previewErrorText = previewError === "target_changed"
    ? t("vmLxc.remove.targetChanged")
    : previewError === "receipt_unavailable" ? t("vmLxc.remove.receiptUnavailable")
      : t("vmLxc.remove.previewUnavailable")
  const removeEnabled = Boolean(
    preview?.eligible
    && preview.check && displayTarget
    && typedVmid === String(preview.target.vmid)
    && !previewError
    && !submitting,
  )

  const reviewAfterFailure = () => {
    if (!target || !active || active.result.state !== "failed") return
    clearLxcRemovalReceipt(active.vmid)
    setTracked(null)
    void refreshPreview()
  }

  const refreshTask = () => {
    if (!active) return
    setTracked({ ...active, result: { ...active.result, state: "running", reason: "checking_task" } })
  }

  const changeOpen = (nextOpen: boolean) => {
    if (!nextOpen) {
      setTypedVmid("")
      setPurge(false)
      setDestroyUnreferenced(false)
      if (active?.result.state === "succeeded") setTracked(null)
    }
    onOpenChange(nextOpen)
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Trash2 className="h-5 w-5 text-red-500" />
            {t("vmLxc.remove.title")}
          </DialogTitle>
          <DialogDescription>{target
            ? t("vmLxc.remove.target", { name: displayTarget?.name || target.name, vmid: target.vmid })
            : t("vmLxc.remove.description")}</DialogDescription>
        </DialogHeader>

        {terminal ? (
          <div className={`rounded-md border p-4 text-sm ${resultStyle[terminal.state]}`} role="status">
            <div className="flex items-start gap-2">
              {terminal.state === "running" ? <Loader2 className="h-4 w-4 mt-0.5 animate-spin shrink-0" />
                : terminal.state === "succeeded" ? <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
                  : <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />}
              <div>
                <p className="font-medium">{t(`vmLxc.remove.result.${terminal.state}`)}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {(terminal.state === "failed" || terminal.state === "warning") && terminal.exitstatus
                    ? terminal.exitstatus
                    : t(`vmLxc.remove.resultReason.${terminal.reason || terminal.state}`)}
                </p>
              </div>
            </div>
          </div>
        ) : blocked && preview ? (
          <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm" role="alert">
            <p className="font-medium text-red-400">{t("vmLxc.remove.blocked")}</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
              {preview.reasons.map(reason => <li key={reason}>{t(`vmLxc.remove.reasons.${reason}`)}</li>)}
            </ul>
          </div>
        ) : target && !previewError ? (
          <div className="space-y-4">
            <div>
              <Label htmlFor="remove-lxc-vmid">{t("vmLxc.remove.typeVmid", { vmid: target.vmid })}</Label>
              <Input
                id="remove-lxc-vmid" className="mt-2" inputMode="numeric" autoComplete="off" value={typedVmid}
                disabled={submitting} onChange={event => setTypedVmid(event.target.value)}
                onKeyDown={event => { if (event.key === "Enter") void submit() }}
              />
            </div>
            <Label className="flex items-start gap-2 font-normal">
              <Checkbox checked={purge} disabled={submitting} onCheckedChange={value => setPurge(value === true)} />
              <span>{t("vmLxc.remove.purge")}<span className="mt-1 block text-xs text-muted-foreground">{t("vmLxc.remove.purgeHint")}</span></span>
            </Label>
            <Label className="flex items-start gap-2 font-normal">
              <Checkbox checked={destroyUnreferenced} disabled={submitting} onCheckedChange={value => setDestroyUnreferenced(value === true)} />
              <span>{t("vmLxc.remove.destroyUnreferenced")}<span className="mt-1 block text-xs text-muted-foreground">{t("vmLxc.remove.destroyUnreferencedHint")}</span></span>
            </Label>
            <p className="text-sm text-amber-400">{t("vmLxc.remove.referencedDisks")}</p>
            {loadingPreview && (
              <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
                <Loader2 className="h-4 w-4 animate-spin" /> {t("vmLxc.remove.checking")}
              </p>
            )}
          </div>
        ) : (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-400" role="alert">
            {previewErrorText}
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          {terminal?.state === "unknown" && <Button type="button" variant="outline" onClick={refreshTask}>{t("vmLxc.remove.checkTask")}</Button>}
          {target && terminal?.state === "failed" && <Button type="button" variant="outline" onClick={reviewAfterFailure}>{t("vmLxc.remove.reviewAgain")}</Button>}
          {!terminal && (previewError || blocked) && <Button type="button" variant="outline" onClick={() => void refreshPreview()} disabled={loadingPreview || submitting}>{t("vmLxc.remove.checkAgain")}</Button>}
          <Button type="button" variant="outline" onClick={() => changeOpen(false)}>
            {t(terminal?.state === "succeeded" ? "actions.close" : "vmLxc.remove.cancel")}
          </Button>
          {target && !terminal && !blocked && !previewError && (
            <Button type="button" variant="destructive" disabled={!removeEnabled} onClick={() => void submit()}>
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t("vmLxc.remove.confirm")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
