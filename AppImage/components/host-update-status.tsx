"use client"

import { useEffect, useRef, useState, type ReactNode } from "react"
import * as Confirm from "@radix-ui/react-alert-dialog"
import { Button } from "./ui/button"
import { getAuthToken } from "@/lib/api-config"
import { useT } from "@/lib/i18n/provider"
import { CheckCircle2, AlertTriangle, Info, ChevronRight } from "lucide-react"

function headers() {
  const token = getAuthToken()
  return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) }
}
type Url = (path: string) => string
type Context = { hostname: string; boot_id: string; allowed: boolean; reason: string }
const compact = "h-10 sm:h-[34px] px-3 text-xs"

export function RestartAfterUpdate({ getApiUrl, disabled, unavailable = false, label, detail, icon }: {
  getApiUrl: Url; disabled: boolean; unavailable?: boolean; label: string; detail: string; icon: ReactNode
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [context, setContext] = useState<Context | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const [pending, setPending] = useState(false)
  const [accepted, setAccepted] = useState(false)
  const [error, setError] = useState(false)
  const sending = useRef(false)
  const alive = useRef(true)
  const postRequest = useRef<AbortController | null>(null)
  useEffect(() => { alive.current = true; return () => { alive.current = false; postRequest.current?.abort() } }, [])
  useEffect(() => {
    let disposed = false, reading = false
    let active: AbortController | undefined
    setContext(null); setSubmitted(false); setError(false); sending.current = false
    const read = async () => {
      if (reading) return
      reading = true
      const controller = new AbortController(); active = controller
      const timeout = setTimeout(() => controller.abort(), 6000)
      try {
        const response = await fetch(getApiUrl("/api/health/reboot-context"), { headers: headers(), signal: controller.signal })
        if (!response.ok) throw Error("unavailable")
        const value: Context = await response.json()
        if (!value || typeof value.hostname !== "string" || typeof value.allowed !== "boolean" || typeof value.boot_id !== "string" || !value.boot_id) throw Error("invalid")
        if (!disposed) { setContext(value); setError(false) }
      } catch { if (!disposed) { setContext(null); setError(true) } }
      finally { clearTimeout(timeout); reading = false }
    }
    void read()
    // A retained health snapshot must never grant permission after reconnect
    // or remount. This cheap read does not run APT or a full health check.
    const interval = setInterval(read, open ? 2000 : 30000)
    return () => { disposed = true; clearInterval(interval); active?.abort() }
  }, [open, getApiUrl])
  useEffect(() => {
    if (!accepted) return
    let disposed = false, reading = false
    const controller = new AbortController()
    const interval = setInterval(async () => {
      if (reading) return
      reading = true
      try {
        const response = await fetch(getApiUrl("/api/health/reboot-after-update/status"), { headers: headers(), signal: controller.signal })
        if (!response.ok) return
        const value = await response.json()
        if (!disposed && (value.state === "failed" || value.state === "cancelled")) { setAccepted(false); setError(true) }
      } catch { /* Loss of connection does not prove reboot completion. */ }
      finally { reading = false }
    }, 2000)
    const timeout = setTimeout(() => { clearInterval(interval); controller.abort() }, 10000)
    return () => { disposed = true; controller.abort(); clearInterval(interval); clearTimeout(timeout) }
  }, [accepted, getApiUrl])
  const confirm = async () => {
    if (disabled || unavailable || !context?.allowed || sending.current || submitted) return
    sending.current = true; setSubmitted(true); setPending(true); setError(false)
    const controller = new AbortController(); postRequest.current = controller
    const timeout = setTimeout(() => controller.abort(), 15000)
    try {
      const response = await fetch(getApiUrl("/api/health/reboot-after-update"), {
        method: "POST", headers: headers(), body: JSON.stringify({ confirm: true, hostname: context.hostname, boot_id: context.boot_id }), signal: controller.signal,
      })
      if (response.status !== 202 || (await response.json()).accepted !== true) throw Error("unconfirmed")
      if (alive.current) { setAccepted(true); setOpen(false) }
    } catch { if (alive.current) setError(true) }
    finally { clearTimeout(timeout); postRequest.current = null; if (alive.current) setPending(false) }
  }
  return <section className="py-1.5 px-2 sm:px-3">
    <div className="flex flex-col sm:flex-row sm:items-center gap-3">
      <div className="flex items-start gap-2 flex-1 min-w-0 text-[10px] sm:text-xs"><span className="shrink-0">{icon}</span>
        <div><span className="font-medium mr-2">{label}</span><span className="text-muted-foreground break-words">{detail}</span></div></div>
      <Button variant="outline" className={`${compact} self-start sm:shrink-0 border-amber-500/40 text-amber-500`}
        disabled={disabled || unavailable || !context?.allowed || pending || accepted} onClick={() => setOpen(true)}>{t("healthStatus.restart.button")}</Button>
    </div>
    {disabled && <p className="mt-2 text-xs text-muted-foreground">{t("healthStatus.restart.blocked")}</p>}
    {accepted && <p role="status" className="mt-2 text-xs text-blue-500">{t("healthStatus.restart.accepted")}</p>}
    {error && !open && <p role="alert" className="mt-2 text-xs text-amber-500">{t("healthStatus.restart.unconfirmed")}</p>}
    <Confirm.Root open={open} onOpenChange={setOpen}><Confirm.Portal>
      <Confirm.Overlay className="fixed inset-0 bg-black/75 z-[70]" />
      <Confirm.Content className="fixed z-[80] w-[92vw] max-w-[520px] rounded-lg border bg-card text-foreground p-5 shadow-lg" style={{ top: "50%", left: "50%", transform: "translate(-50%,-50%)" }}>
        <Confirm.Title className="text-base font-semibold">{t("healthStatus.restart.title", { server: context?.hostname ?? "…" })}</Confirm.Title>
        <Confirm.Description className="mt-3 text-sm text-muted-foreground">{t("healthStatus.restart.impact")}</Confirm.Description>
        {(disabled || context?.reason === "busy") && <p className="mt-3 text-xs text-amber-500">{t("healthStatus.restart.blocked")}</p>}
        {context?.reason === "current" && <p className="mt-3 text-xs text-muted-foreground">{t("healthStatus.hostUpdate.noReboot")}</p>}
        {(error || context?.reason === "unknown") && <p role="alert" className="mt-3 text-xs text-amber-500">{t("healthStatus.restart.unconfirmed")}</p>}
        <div className="mt-5 flex justify-end gap-2.5">
          <Confirm.Cancel asChild><Button variant="outline" className={compact} disabled={pending}>{t("healthStatus.restart.cancel")}</Button></Confirm.Cancel>
          <Confirm.Action asChild><Button variant="destructive" className={compact} disabled={disabled || unavailable || !context?.allowed || pending || submitted}
            onClick={event => { event.preventDefault(); void confirm() }}>{t("healthStatus.restart.confirm")}</Button></Confirm.Action>
        </div>
      </Confirm.Content>
    </Confirm.Portal></Confirm.Root>
  </section>
}

type Versions = { installed: string | null; available: string | null; state: "available" | "current" | "unknown"; checked_at: string | null; channel: "stable" | "beta" }
export function ProxMenuxVersionCard({ getApiUrl }: { getApiUrl: Url }) {
  const t = useT()
  const [value, setValue] = useState<Versions | null>(null)
  useEffect(() => {
    let disposed = false, reading = false
    let active: AbortController | undefined
    const read = async () => {
      if (reading || document.visibilityState !== "visible") return
      reading = true
      const controller = new AbortController(); active = controller
      const timeout = setTimeout(() => controller.abort(), 6000)
      try {
        const response = await fetch(getApiUrl("/api/health/proxmenux-version"), { headers: headers(), signal: controller.signal })
        if (!response.ok) throw Error("unavailable")
        const data: Versions = await response.json()
        if (!["available", "current", "unknown"].includes(data?.state)) throw Error("invalid")
        const validVersion = (version: unknown) => typeof version === "string" && /^\d+(?:\.\d+){1,5}$/.test(version)
        if (!["stable", "beta"].includes(data.channel) ||
            (data.installed !== null && !validVersion(data.installed)) ||
            (data.available !== null && !validVersion(data.available)) ||
            (data.state !== "unknown" && (!validVersion(data.installed) || !validVersion(data.available) || !data.checked_at)) ||
            (data.checked_at !== null && !Number.isFinite(Date.parse(data.checked_at)))) throw Error("invalid")
        if (!disposed) setValue(data)
      } catch { if (!disposed) setValue(previous => previous ? { ...previous, state: "unknown" } : null) }
      finally { clearTimeout(timeout); reading = false }
    }
    void read()
    const interval = setInterval(read, 300000)
    window.addEventListener("focus", read); document.addEventListener("visibilitychange", read)
    return () => { disposed = true; active?.abort(); clearInterval(interval); window.removeEventListener("focus", read); document.removeEventListener("visibilitychange", read) }
  }, [getApiUrl])
  const state = value?.state ?? "unknown"
  const versions = <dl className="grid grid-cols-2 gap-4">
      <div><dt className="text-muted-foreground mb-1">{t("healthStatus.versions.installed")}</dt><dd className="font-mono font-semibold">{value?.installed ?? t("healthStatus.versions.unverified")}</dd></div>
      <div><dt className="text-muted-foreground mb-1">{t(state === "unknown" && value?.available ? "healthStatus.versions.lastKnown" : "healthStatus.versions.latest")}</dt><dd className="font-mono font-semibold">{value?.available ?? t("healthStatus.versions.unverified")}</dd></div>
    </dl>
  const metadata = <>
    {value && <p className="mt-3 text-muted-foreground">{t(`healthStatus.versions.${value.channel}`)}</p>}
    {value?.checked_at && <p className="mt-1 text-muted-foreground">{t("healthStatus.versions.checked", { time: new Date(value.checked_at).toLocaleString() })}</p>}
  </>
  if (state !== "available") return <details aria-label={t("healthStatus.versions.title")} className="group text-[10px] sm:text-xs">
    <summary className="flex items-start gap-2 py-1.5 px-2 sm:px-3 rounded-md hover:bg-muted/40 cursor-pointer list-none [&::-webkit-details-marker]:hidden">
      {state === "current" ? <CheckCircle2 aria-hidden="true" className="h-3 w-3 sm:h-3.5 sm:w-3.5 shrink-0 text-green-500" /> : <AlertTriangle aria-hidden="true" className="h-3 w-3 sm:h-3.5 sm:w-3.5 shrink-0 text-amber-500" />}
      <span className="font-medium shrink-0">ProxMenux</span>
      <span className={`flex-1 min-w-0 break-words ${state === "current" ? "text-muted-foreground" : "text-amber-500"}`}>
        {state === "current" ? t("healthStatus.versions.currentVersion", { version: value!.installed! }) : t("healthStatus.versions.unknown")}
      </span>
      <ChevronRight aria-hidden="true" className="h-3 w-3 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
    </summary>
    <div className="ml-7 mr-2 sm:mr-3 pb-2">
      {state === "unknown" && versions}
      {metadata}
    </div>
  </details>
  return <section aria-label={t("healthStatus.versions.title")} className="mt-3 mx-2 sm:mx-3 rounded-lg border bg-muted/10 p-3 text-[10px] sm:text-xs">
    <div className="flex flex-wrap items-center justify-between gap-2 mb-3"><h3 className="font-semibold">{t("healthStatus.versions.title")}</h3>
      <span className="flex items-center gap-1.5 text-blue-500"><Info aria-hidden="true" className="h-3.5 w-3.5" />{t("healthStatus.versions.available")}</span></div>
    {versions}
    {metadata}
  </section>
}
