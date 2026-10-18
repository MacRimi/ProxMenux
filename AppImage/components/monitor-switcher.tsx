"use client"

import { useEffect, useState } from "react"
import useSWR, { mutate as refreshCache } from "swr"
import { ArrowLeft, ChevronDown, DatabaseBackup, ExternalLink, Plus, Server, Trash2 } from "lucide-react"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Switch } from "./ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "./ui/dropdown-menu"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

interface MonitorLink {
  key: string
  name: string
  product: "pve" | "pbs"
  group: "cluster" | "standalone" | "pbs"
  url: string | null
  status: "online" | "offline" | "unknown"
  native_url?: string | null
  manual: boolean
  hidden: boolean
  custom_url: boolean
}
interface MonitorLinks { self: { name: string; product: string }; links: MonitorLink[] }

const GROUPS = ["cluster", "standalone", "pbs"] as const
const fetcher = (url: string) => fetchApi<MonitorLinks>(url)
const ORIGIN_KEY = "proxmenux-came-from"

interface Origin { url: string; name: string; product: "pve" | "pbs" }

// The Monitor a jump came from, as the browser reached it. Only a bare http(s)
// origin is accepted, and the parameters leave the address at once.
function takeOrigin(): (Origin & { fresh?: boolean }) | null {
  if (typeof window === "undefined") return null
  const params = new URLSearchParams(window.location.search)
  const from = params.get("pmx_from")
  if (from !== null) {
    const name = params.get("pmx_name") || ""
    const product = params.get("pmx_product") === "pbs" ? "pbs" : "pve"
    for (const key of ["pmx_from", "pmx_name", "pmx_product"]) params.delete(key)
    const query = params.toString()
    window.history.replaceState(null, "", window.location.pathname + (query ? `?${query}` : "") + window.location.hash)
    try {
      const parsed = new URL(from)
      if (/^https?:$/.test(parsed.protocol) && parsed.origin === from && parsed.origin !== window.location.origin) {
        const origin: Origin = { url: parsed.origin, name: (name || parsed.hostname).slice(0, 64), product }
        try { sessionStorage.setItem(ORIGIN_KEY, JSON.stringify(origin)) } catch { /* private mode */ }
        return { ...origin, fresh: true }
      }
    } catch { /* not an address */ }
  }
  try {
    const stored = JSON.parse(sessionStorage.getItem(ORIGIN_KEY) || "null")
    return stored && typeof stored.url === "string" && /^https?:\/\//.test(stored.url) ? stored : null
  } catch { return null }
}

// Where a link leads: its Monitor, or the native PBS interface when no Monitor answers there.
function destination(link: MonitorLink): { href: string; native: boolean } | null {
  if (link.product === "pbs" && link.status !== "online" && link.native_url) return { href: link.native_url, native: true }
  return link.url ? { href: link.url, native: false } : null
}

function ProductIcon({ product, className }: { product: string; className?: string }) {
  return product === "pbs" ? <DatabaseBackup className={className} /> : <Server className={className} />
}

export function MonitorSwitcher({ nodeName, compact = false }: { nodeName: string; compact?: boolean }) {
  const t = useT()
  const [manageOpen, setManageOpen] = useState(false)
  // The backend keeps the list ready, so the menu opens already filled.
  const { data, error, isLoading } = useSWR<MonitorLinks>("/api/monitor-links", fetcher, { revalidateOnFocus: false, refreshInterval: 300000 })

  const [origin, setOrigin] = useState<(Origin & { fresh?: boolean }) | null>(null)
  const [offerOrigin, setOfferOrigin] = useState(false)
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState("")
  useEffect(() => { setOrigin(takeOrigin()) }, [])
  const originKnown = !!origin && !!data?.links.some(link => link.url === origin.url)
  useEffect(() => {
    // Offered once, right after arriving, when this Monitor has no way back yet.
    if (origin?.fresh && data && !originKnown) setOfferOrigin(true)
  }, [origin, data, originKnown])

  // The address carries where the jump comes from, so the other Monitor can offer the way back.
  const withOrigin = (href: string) => {
    const params = new URLSearchParams({ pmx_from: window.location.origin, pmx_name: nodeName, pmx_product: data?.self.product === "pbs" ? "pbs" : "pve" })
    return `${href}/?${params.toString()}`
  }
  const open = (href: string, newTab: boolean) => {
    if (newTab) window.open(href, "_blank", "noopener,noreferrer")
    else window.location.assign(href)
  }
  const go = (link: MonitorLink, newTab: boolean) => {
    const target = destination(link)
    if (!target) return
    if (target.native) open(target.href, true)
    else open(withOrigin(target.href), newTab)
  }
  const addOrigin = async () => {
    if (!origin) return
    setAdding(true); setAddError("")
    try {
      await fetchApi("/api/monitor-links", { method: "POST", body: JSON.stringify({ name: origin.name, url: origin.url, product: origin.product }) })
      await refreshCache("/api/monitor-links")
      setOfferOrigin(false)
    } catch (err) {
      setAddError(err instanceof Error ? err.message : t("monitorLinks.saveFailed"))
    } finally { setAdding(false) }
  }

  return <div onClick={event => event.stopPropagation()}>
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className={`gap-2 border-border bg-transparent hover:bg-secondary ${compact ? "h-8 px-2.5 text-xs" : ""}`}>
          <Server className={compact ? "h-3.5 w-3.5" : "h-4 w-4"} />
          <span className="max-w-[12rem] truncate">{t("status.node", { node: nodeName })}</span>
          <ChevronDown className="h-3.5 w-3.5 opacity-70" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel className="text-xs font-medium text-muted-foreground">{t("monitorLinks.thisNode")}</DropdownMenuLabel>
        <DropdownMenuItem disabled className="gap-2 opacity-100">
          <span className="h-2 w-2 rounded-full bg-green-500" />
          <ProductIcon product={data?.self.product || ""} className="h-4 w-4 text-muted-foreground" />
          <span className="truncate font-medium">{nodeName}</span>
        </DropdownMenuItem>
        {origin && !originKnown && <DropdownMenuItem className="gap-2" onSelect={() => open(withOrigin(origin.url), false)}>
          <ArrowLeft className="h-4 w-4 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate">{t("monitorLinks.backTo", { name: origin.name })}</span>
        </DropdownMenuItem>}
        {isLoading && <p className="px-2 py-1.5 text-xs text-muted-foreground">{t("monitorLinks.checking")}</p>}
        {error && <p className="px-2 py-1.5 text-xs text-amber-500">{t("monitorLinks.loadFailed")}</p>}
        {data && data.links.length === 0 && <p className="px-2 py-1.5 text-xs text-muted-foreground">{t("monitorLinks.empty")}</p>}
        {data && GROUPS.map(group => {
          const rows = data.links.filter(link => link.group === group)
          if (rows.length === 0) return null
          return <div key={group}>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs font-medium text-muted-foreground">{t(`monitorLinks.groups.${group}`)}</DropdownMenuLabel>
            {rows.map(link => {
              const target = destination(link)
              return <DropdownMenuItem key={link.key} disabled={!target} className="gap-2" onSelect={() => go(link, false)}>
                <span className={`h-2 w-2 shrink-0 rounded-full ${link.status === "online" ? "bg-green-500" : "bg-gray-500"}`} />
                <ProductIcon product={link.product} className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate">{link.name}</span>
                {target?.native
                  ? <span className="shrink-0 text-[11px] text-muted-foreground">{t("monitorLinks.pbsInterface")}</span>
                  : link.status !== "online" && <span className="shrink-0 text-[11px] text-muted-foreground">{t("monitorLinks.noResponse")}</span>}
                {target && <button type="button" aria-label={t("monitorLinks.openNewTab")} title={t("monitorLinks.openNewTab")}
                  className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
                  onClick={event => { event.preventDefault(); event.stopPropagation(); go(link, true) }}>
                  <ExternalLink className="h-3.5 w-3.5" />
                </button>}
              </DropdownMenuItem>
            })}
          </div>
        })}
        <DropdownMenuSeparator />
        <DropdownMenuItem className="gap-2" onSelect={() => setManageOpen(true)}>
          <Plus className="h-4 w-4" />{t("monitorLinks.manage")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    {manageOpen && <ManageLinksDialog open={manageOpen} onOpenChange={setManageOpen} />}
    {origin && <Dialog open={offerOrigin} onOpenChange={setOfferOrigin}>
      <DialogContent className="max-w-md" onClick={event => event.stopPropagation()}>
        <DialogHeader>
          <DialogTitle>{t("monitorLinks.cameFromTitle")}</DialogTitle>
          <DialogDescription>{t("monitorLinks.cameFromBody", { name: origin.name })}</DialogDescription>
        </DialogHeader>
        <p className="break-all rounded-md border border-border bg-muted/40 px-3 py-2 font-mono text-sm">{origin.url}</p>
        {addError && <p role="alert" className="text-sm text-red-500">{addError}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" disabled={adding} onClick={() => setOfferOrigin(false)}>{t("monitorLinks.notNow")}</Button>
          <Button disabled={adding} onClick={addOrigin}><Plus className="mr-2 h-4 w-4" />{t("monitorLinks.add")}</Button>
        </div>
      </DialogContent>
    </Dialog>}
  </div>
}

function ManageLinksDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useT()
  const { data, mutate } = useSWR<MonitorLinks>("/api/monitor-links?all=1", fetcher, { revalidateOnFocus: false })
  const [form, setForm] = useState({ name: "", url: "", product: "pve" })
  const [addresses, setAddresses] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true); setError("")
    try {
      await action()
      await mutate()
      await refreshCache("/api/monitor-links")
    } catch (err) {
      setError(err instanceof Error ? err.message : t("monitorLinks.saveFailed"))
    } finally { setBusy(false) }
  }
  const send = (path: string, method: string, body?: unknown) =>
    fetchApi(path, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })

  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" onClick={event => event.stopPropagation()}>
      <DialogHeader>
        <DialogTitle>{t("monitorLinks.dialogTitle")}</DialogTitle>
        <DialogDescription>{t("monitorLinks.dialogDescription")}</DialogDescription>
      </DialogHeader>

      <div className="space-y-3 rounded-lg border border-border p-4">
        <p className="text-sm font-medium">{t("monitorLinks.addTitle")}</p>
        <div className="grid gap-3 sm:grid-cols-[1fr_1.5fr_auto]">
          <div className="space-y-1.5">
            <Label htmlFor="monitor-link-name">{t("monitorLinks.name")}</Label>
            <Input id="monitor-link-name" value={form.name} disabled={busy} onChange={event => setForm({ ...form, name: event.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="monitor-link-url">{t("monitorLinks.address")}</Label>
            <Input id="monitor-link-url" value={form.url} disabled={busy} placeholder="https://192.168.1.20:8008"
              onChange={event => setForm({ ...form, url: event.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="monitor-link-product">{t("monitorLinks.type")}</Label>
            <Select value={form.product} disabled={busy} onValueChange={product => setForm({ ...form, product })}>
              <SelectTrigger id="monitor-link-product" className="w-full sm:w-56"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="pve">Proxmox VE</SelectItem>
                <SelectItem value="pbs">Proxmox Backup Server</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <Button size="sm" disabled={busy || !form.url.trim()} onClick={() => run(async () => {
          await send("/api/monitor-links", "POST", form)
          setForm({ name: "", url: "", product: "pve" })
        })}><Plus className="mr-2 h-4 w-4" />{t("monitorLinks.add")}</Button>
      </div>

      {error && <p role="alert" className="text-sm text-red-500">{error}</p>}

      <div className="space-y-3">
        {data?.links.length === 0 && <p className="text-sm text-muted-foreground">{t("monitorLinks.empty")}</p>}
        {data?.links.map(link => {
          const address = addresses[link.key] ?? (link.manual || link.custom_url ? link.url || "" : "")
          return <div key={link.key} className={`space-y-2 rounded-lg border border-border p-3 ${link.hidden ? "opacity-60" : ""}`}>
            <div className="flex items-center gap-2">
              <ProductIcon product={link.product} className="h-4 w-4 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate font-medium">{link.name}</span>
              <span className="text-xs text-muted-foreground">{link.manual ? t("monitorLinks.added") : t("monitorLinks.detected")}</span>
              {!link.manual && <label className="flex items-center gap-2 text-xs text-muted-foreground">
                {t("monitorLinks.visible")}
                <Switch checked={!link.hidden} disabled={busy} className="data-[state=checked]:bg-blue-600"
                  onCheckedChange={checked => run(() => send(`/api/monitor-links/${encodeURIComponent(link.key)}`, "PATCH", { hidden: !checked }))} />
              </label>}
              {link.manual && <Button variant="ghost" size="sm" disabled={busy} aria-label={t("monitorLinks.remove")}
                onClick={() => run(() => send(`/api/monitor-links/${encodeURIComponent(link.key)}`, "DELETE"))}>
                <Trash2 className="h-4 w-4 text-red-500" />
              </Button>}
            </div>
            <div className="flex gap-2">
              <Input value={address} disabled={busy} aria-label={t("monitorLinks.address")}
                placeholder={link.manual ? "" : `${t("monitorLinks.autoAddress")}${link.url ? `: ${link.url}` : ""}`}
                onChange={event => setAddresses({ ...addresses, [link.key]: event.target.value })} />
              <Button variant="outline" size="sm" className="h-10" disabled={busy || addresses[link.key] === undefined}
                onClick={() => run(async () => {
                  await send(`/api/monitor-links/${encodeURIComponent(link.key)}`, "PATCH", { url: addresses[link.key] })
                  setAddresses(({ [link.key]: _, ...rest }) => rest)
                })}>{t("monitorLinks.save")}</Button>
            </div>
          </div>
        })}
      </div>
    </DialogContent>
  </Dialog>
}
