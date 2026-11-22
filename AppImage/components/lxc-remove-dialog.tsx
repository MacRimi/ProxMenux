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
  check: string
  target: { vmid: number; name: string; node: string; status: string }
  disk: { storage: string; volume: string; size: string }
  backup: { state: "none" | "unverified"; archives: Array<{ storage: string; volid: string }> }
  backup_tasks: Array<{ upid: string; status: string }>
}

interface TrackedRemoval extends LxcRemovalReceipt {
  result: LxcRemovalTaskResult
}

interface LxcRemoveDialogProps {
  target: LxcTarget | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreateBackup: () => void
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

export function LxcRemoveDialog({ target, open, onOpenChange, onCreateBackup, onRemoved }: LxcRemoveDialogProps) {
  const t = useT()
  const [preview, setPreview] = useState<RemovalPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [typedVmid, setTypedVmid] = useState("")
  const [noBackupConfirmed, setNoBackupConfirmed] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [tracked, setTracked] = useState<TrackedRemoval | null>(null)
  const submitRef = useRef(false)
  const completedRef = useRef<number | null>(null)

  useEffect(() => {
    const receipt = loadLxcRemovalReceipt()
    if (!receipt) return
    if (receipt.task) {
      setTracked({ ...receipt, result: { state: "running", task: receipt.task } })
    } else {
      setTracked({ ...receipt, result: { state: "unknown", task: null, reason: "submission_unconfirmed" } })
    }
    onOpenChange(true)
  // Recover an in-flight task once, on page load. `onOpenChange` is stable in the parent.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const refreshPreview = async () => {
    if (!target || target.type !== "lxc") return
    setLoadingPreview(true)
    setPreviewError(null)
    setPreview(null)
    setTypedVmid("")
    setNoBackupConfirmed(false)
    try {
      setPreview(await fetchApi<RemovalPreview>(`/api/vms/${target.vmid}/remove-preview`))
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : String(error))
    } finally {
      setLoadingPreview(false)
    }
  }

  useEffect(() => {
    if (open && !tracked) void refreshPreview()
  // Preview is deliberately fresh per opening; no cached authorization is reused.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, target?.vmid])

  useEffect(() => {
    if (!tracked?.task || tracked.result.state !== "running") return
    let cancelled = false
    let failures = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    const inspect = async () => {
      try {
        const result = await readLxcRemovalTask(tracked.vmid, tracked.task as string)
        if (cancelled) return
        failures = 0
        setTracked(current => current && current.vmid === tracked.vmid ? { ...current, result } : current)
        if (result.state === "running") timer = setTimeout(() => void inspect(), 1500)
      } catch {
        failures += 1
        if (failures >= 3 && !cancelled) {
          setTracked(current => current && current.vmid === tracked.vmid
            ? { ...current, result: { state: "unknown", task: current.task, reason: "task_status_unavailable" } }
            : current)
        } else if (!cancelled) {
          timer = setTimeout(() => void inspect(), 1500)
        }
      }
    }
    void inspect()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [tracked?.task, tracked?.result.state, tracked?.vmid])

  useEffect(() => {
    if (tracked?.result.state !== "succeeded" || completedRef.current === tracked.vmid) return
    completedRef.current = tracked.vmid
    clearLxcRemovalReceipt(tracked.vmid)
    onRemoved(tracked.vmid)
  }, [onRemoved, tracked?.result.state, tracked?.vmid])

  const submit = async () => {
    if (!preview || !target || submitRef.current) return
    submitRef.current = true
    setSubmitting(true)
    try {
      const result = await fetchApi<LxcRemovalTaskResult>(`/api/vms/${target.vmid}/remove`, {
        method: "POST",
        body: JSON.stringify({
          check: preview.check,
          confirm_vmid: typedVmid,
          confirm_no_backup: noBackupConfirmed,
        }),
      })
      const receipt = { vmid: target.vmid, task: result.task }
      saveLxcRemovalReceipt(receipt)
      setTracked({ ...receipt, result })
    } catch (error) {
      const body = errorBody(error)
      if (body?.preview) setPreview(body.preview)
      setPreviewError(body?.error || (error instanceof Error ? error.message : String(error)))
    } finally {
      submitRef.current = false
      setSubmitting(false)
    }
  }

  const displayTarget = preview?.target || (target ? { vmid: target.vmid, name: target.name, node: "—", status: "—" } : null)
  const displayStatus = displayTarget?.status === "stopped" ? t("vmLxc.stopped")
    : displayTarget?.status === "running" ? t("vmLxc.running")
      : displayTarget?.status
  const terminal = tracked?.result
  const previewErrorText = previewError === "target_changed"
    ? t("vmLxc.remove.targetChanged")
    : t("vmLxc.remove.previewUnavailable")
  const removeEnabled = Boolean(
    preview?.eligible
    && typedVmid === String(preview.target.vmid)
    && (preview.backup.state !== "none" || noBackupConfirmed)
    && !previewError
    && !submitting,
  )

  const reviewAfterFailure = () => {
    if (!tracked || tracked.result.state !== "failed") return
    clearLxcRemovalReceipt(tracked.vmid)
    setTracked(null)
    void refreshPreview()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Trash2 className="h-5 w-5 text-red-500" />
            {t("vmLxc.remove.title")}
          </DialogTitle>
          <DialogDescription>{t("vmLxc.remove.description")}</DialogDescription>
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
                  {terminal.state === "failed" && terminal.exitstatus
                    ? terminal.exitstatus
                    : t(`vmLxc.remove.resultReason.${terminal.reason || terminal.state}`)}
                </p>
              </div>
            </div>
          </div>
        ) : loadingPreview ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> {t("vmLxc.remove.checking")}
          </div>
        ) : preview ? (
          <div className="space-y-4">
            {displayTarget && (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-md border p-3 text-sm">
                <div><dt className="text-xs text-muted-foreground">{t("vmLxc.remove.container")}</dt><dd className="font-medium break-words">{displayTarget.name} <span className="text-xs text-blue-400">LXC {displayTarget.vmid}</span></dd></div>
                <div><dt className="text-xs text-muted-foreground">{t("vmLxc.remove.node")}</dt><dd className="font-medium break-words">{displayTarget.node}</dd></div>
                <div><dt className="text-xs text-muted-foreground">{t("vmLxc.remove.status")}</dt><dd className="font-medium">{displayStatus}</dd></div>
                <div><dt className="text-xs text-muted-foreground">{t("vmLxc.remove.rootDisk")}</dt><dd className="font-medium break-all">{preview.disk.storage}{preview.disk.size ? ` · ${preview.disk.size}` : ""}</dd></div>
              </dl>
            )}

            {!preview.eligible ? (
              <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm" role="alert">
                <p className="font-medium text-red-400">{t("vmLxc.remove.blocked")}</p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
                  {preview.reasons.map(reason => <li key={reason}>{t(`vmLxc.remove.reasons.${reason}`)}</li>)}
                </ul>
              </div>
            ) : (
              <>
                <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-muted-foreground">
                  <strong className="text-red-400">{t("vmLxc.remove.irreversibleTitle")}</strong> {t("vmLxc.remove.irreversible")}
                </div>
                <div className="rounded-md border p-3 text-sm">
                  <p className="font-medium">{t("vmLxc.remove.backup")}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {preview.backup.state === "none"
                      ? t("vmLxc.remove.noBackup")
                      : t("vmLxc.remove.unverifiedBackup", { count: preview.backup.archives.length })}
                  </p>
                  {preview.backup.state === "none" && (
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      <Button type="button" variant="outline" size="sm" onClick={onCreateBackup}>{t("vmLxc.remove.createBackup")}</Button>
                      <Label className="flex items-center gap-2 text-xs font-normal">
                        <Checkbox checked={noBackupConfirmed} onCheckedChange={value => setNoBackupConfirmed(value === true)} />
                        {t("vmLxc.remove.confirmNoBackup")}
                      </Label>
                    </div>
                  )}
                </div>
                {preview.backup_tasks.length > 0 && (
                  <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-400">
                    {t("vmLxc.remove.backupTaskRunning")}
                  </div>
                )}
                <div>
                  <Label htmlFor="remove-lxc-vmid">{t("vmLxc.remove.typeVmid", { vmid: preview.target.vmid })}</Label>
                  <Input id="remove-lxc-vmid" className="mt-2" inputMode="numeric" autoComplete="off" value={typedVmid} onChange={event => setTypedVmid(event.target.value)} />
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-400" role="alert">
            {previewErrorText}
          </div>
        )}

        {previewError && preview && (
          <p className="text-xs text-red-400" role="alert">{previewErrorText}</p>
        )}
        <DialogFooter className="gap-2 sm:gap-0">
          {terminal?.state === "failed" && <Button type="button" variant="outline" onClick={reviewAfterFailure}>{t("vmLxc.remove.reviewAgain")}</Button>}
          {!terminal && <Button type="button" variant="outline" onClick={() => void refreshPreview()} disabled={loadingPreview || submitting}>{t("vmLxc.remove.checkAgain")}</Button>}
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{t("vmLxc.remove.cancel")}</Button>
          {preview?.eligible && !terminal && (
            <Button type="button" variant="destructive" disabled={!removeEnabled} onClick={() => void submit()}>
              {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t("vmLxc.remove.confirm")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
