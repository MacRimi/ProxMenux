"use client"

// Security → Access activity: who signed in, who changed accounts, profiles
// and sign-in settings, and every action a profile refused (access_log.py).
// For administrators; nothing here can be changed.
import { useCallback, useEffect, useState } from "react"
import { RefreshCw } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Button } from "./ui/button"
import { Badge } from "./ui/badge"
import { fetchApi } from "../lib/api-config"
import { useAccess } from "../lib/access"
import { useI18n } from "../lib/i18n/provider"

interface AccessEvent {
  id: number
  at: number
  event: string
  actor: string | null
  target: string | null
  detail: Record<string, unknown> | null
  ip: string | null
  ok: boolean
}

const PAGE = 50

export function AccessLog() {
  const { t, language } = useI18n()
  const { capabilities } = useAccess()
  const [events, setEvents] = useState<AccessEvent[]>([])
  const [more, setMore] = useState(false)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (before?: number) => {
    setLoading(true)
    try {
      const data = await fetchApi<{ events: AccessEvent[] }>(
        `/api/auth/events?limit=${PAGE}${before ? `&before=${before}` : ""}`)
      setEvents(current => before ? [...current, ...data.events] : data.events)
      setMore(data.events.length === PAGE)
    } catch {
      // The card stays as it was.
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { if (capabilities.admin) load() }, [capabilities.admin, load])

  if (!capabilities.admin) return null

  const label = (key: string, fallback: string) => {
    const text = t(key)
    return text === key ? fallback : text
  }
  const permission = (name: string) => name === "admin" || name === "view" || name === "self" || name === "ticket"
    ? label(`accessLog.permissions.${name}`, name) : label(`users.actions.${name}`, name)
  const detail = (event: AccessEvent): string[] => {
    const d = event.detail || {}
    const parts: string[] = []
    if (typeof d.method === "string") parts.push(label(`accessLog.methods.${d.method}`, d.method))
    if (d.second_factor === true) parts.push(t("accessLog.secondFactor"))
    if (typeof d.profile === "string") parts.push(label(`users.profiles.${d.profile}`, d.profile))
    if (typeof d.mode === "string") parts.push(label(`accessLog.modes.${d.mode}`, d.mode))
    if (typeof d.permission === "string") parts.push(t("accessLog.missing", { permission: permission(d.permission) }))
    if (typeof d.enabled === "boolean") parts.push(t(d.enabled ? "accessLog.on" : "accessLog.off"))
    if (typeof d.scope === "string") parts.push(label(`accessLog.scopes.${d.scope}`, d.scope))
    if (typeof d.rules === "number") parts.push(t("accessLog.rules", { count: d.rules }))
    if (typeof d.subjects === "number") parts.push(t("accessLog.subjects", { count: d.subjects }))
    return parts
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle>{t("accessLog.title")}</CardTitle>
          <Button variant="outline" size="sm" className="h-7 px-3 text-xs gap-1.5 shrink-0" disabled={loading}
            onClick={() => load()}>
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />{t("actions.refresh")}
          </Button>
        </div>
        <CardDescription>{t("accessLog.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {!events.length && !loading && <p className="text-sm text-muted-foreground">{t("accessLog.empty")}</p>}
        {events.map(event => (
          <div key={event.id} className="rounded-lg border border-border p-3 text-sm space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{label(`accessLog.events.${event.event}`, event.event)}</span>
              {!event.ok && (
                <Badge variant="outline" className="text-red-500 border-red-500/40">
                  {t(event.event === "access.refused" ? "accessLog.refused" : "accessLog.failed")}
                </Badge>
              )}
              <span className="ml-auto text-xs text-muted-foreground tabular-nums">
                {new Date(event.at * 1000).toLocaleString(language)}
              </span>
            </div>
            <p className="text-muted-foreground [overflow-wrap:anywhere]">
              <span className="text-foreground">{event.actor || t("accessLog.noAccount")}</span>
              {event.target && <> → <span className="font-mono text-xs">{event.target}</span></>}
              {detail(event).map((part, index) => <span key={index}> · {part}</span>)}
              {event.ip && <span className="font-mono text-xs"> · {event.ip}</span>}
            </p>
          </div>
        ))}
        {more && (
          <Button variant="outline" size="sm" disabled={loading} onClick={() => load(events[events.length - 1]?.id)}>
            {t("accessLog.loadMore")}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
