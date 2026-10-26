"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Boxes, CheckCircle2, HardDrive, Loader2, Settings2, SlidersHorizontal } from "lucide-react"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "./ui/select"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

/**
 * Declares what is expected of this host.
 *
 * An assessment can see what the host does; it cannot see what it is
 * for. Everything on this page answers a question the host has no way of
 * answering itself — does this guest need a backup, must this one come
 * back by itself, is this storage essential — and each answer is what
 * turns an observation in the report into a warning, or takes it out of
 * the count entirely.
 *
 * Nothing here is required. A host with no declaration produces a
 * complete report; it just describes rather than judges.
 */

interface Guest { vmid: number; name: string; type: string }
interface Storage { id: string; type: string }
interface GuestRule {
  backup?: string; autostart?: string
  recovery_objective_hours?: number; note?: string
}
interface Policy {
  guests: Record<string, GuestRule>
  storages: Record<string, { role?: string }>
  defaults: Record<string, unknown>
  thresholds: Record<string, number>
}
interface Vocabulary {
  expectations: string[]
  roles: string[]
  thresholds: Record<string, number>
}

const EMPTY: Policy = { guests: {}, storages: {}, defaults: {}, thresholds: {} }

function PolicySelect({ value, options, prefix, onChange, inherited, inheritedKey, label, disabled }: {
  value: string; options: string[]; prefix: string
  onChange: (value: string) => void; inherited: string; inheritedKey?: string
  label: (key: string) => string; disabled?: boolean
}) {
  // One component behind every dropdown on this tab, so it is also the
  // one place that decides they look like the rest of the interface.
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger className="w-full min-w-0 text-foreground sm:w-[12.5rem]">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="inherit">{inherited}</SelectItem>
        {/* Declaring here what the default already says would be the same
            entry twice, reading the same. */}
        {options.filter((option) => option !== inheritedKey).map((option) => (
          <SelectItem key={option} value={option}>{label(`${prefix}.${option}`)}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function AuditPolicy() {
  const t = useT()
  const [policy, setPolicy] = useState<Policy>(EMPTY)
  const [vocabulary, setVocabulary] = useState<Vocabulary | null>(null)
  const [guests, setGuests] = useState<Guest[]>([])
  const [storages, setStorages] = useState<Storage[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [revision, setRevision] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  // The declaration is what turns an observation into a warning, so the
  // form stays locked until the reader says they are changing it.
  const [editing, setEditing] = useState(false)
  const locked = !editing || saving || !revision || conflict

  const load = useCallback(async () => {
    setLoading(true)
    setRevision(null)
    try {
      const [current, inventory]: any[] = await Promise.all([
        fetchApi("/api/audit/policy"),
        // The declaration is about this host's own guests and storages,
        // so they are listed rather than typed in by identifier.
        fetchApi("/api/audit/inventory?profile=inventory"),
      ])
      if (current?.success) {
        setPolicy({ ...EMPTY, ...current.policy })
        setVocabulary(current.vocabulary)
        setRevision(current.summary.revision)
        setDirty(false); setSaved(false); setConflict(false)
        setError(null)
      } else {
        setError(current?.message || t("audit.policy.failed"))
      }
      const sections = inventory?.inventory?.sections
      setGuests((sections?.guests || []).map((g: any) => ({
        vmid: g.vmid, name: g.name, type: g.type,
      })))
      setStorages((sections?.storages || []).map((s: any) => ({
        id: s.id, type: s.type,
      })))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => { load() }, [load])

  const setGuestRule = (vmid: number, field: keyof GuestRule, value: unknown) => {
    setPolicy((prev) => {
      const guests = { ...prev.guests }
      const rule: GuestRule = { ...(guests[String(vmid)] || {}) }
      // Absence inherits; explicit "unspecified" overrides the site default.
      if (value === "inherit" || value === "" || value === undefined) {
        delete rule[field]
      } else {
        ;(rule as Record<string, unknown>)[field] = value
      }
      if (Object.keys(rule).length === 0) delete guests[String(vmid)]
      else guests[String(vmid)] = rule
      return { ...prev, guests }
    })
    setDirty(true); setSaved(false)
  }

  const setStorageRole = (id: string, role: string) => {
    setPolicy((prev) => {
      const storages = { ...prev.storages }
      if (role === "inherit" || !role) delete storages[id]
      else storages[id] = { role }
      return { ...prev, storages }
    })
    setDirty(true); setSaved(false)
  }

  const setThreshold = (name: string, raw: string) => {
    setPolicy((prev) => {
      const thresholds = { ...prev.thresholds }
      const value = Number(raw)
      if (!raw.trim()) delete thresholds[name]
      else thresholds[name] = value
      return { ...prev, thresholds }
    })
    setDirty(true); setSaved(false)
  }

  const save = async () => {
    if (!revision || saving || conflict) return
    setSaving(true)
    try {
      const res: any = await fetchApi("/api/audit/policy", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...policy, expected_revision: revision }),
      })
      if (res?.success) {
        setRevision(res.summary.revision)
        setDirty(false); setSaved(true); setError(null); setEditing(false)
      }
      else setError(res?.message || t("audit.policy.failed"))
    } catch (e) {
      if ((e as { status?: number }).status === 409) {
        setConflict(true)
        setError(t("audit.policy.conflict"))
      } else setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const declared = useMemo(
    () => Object.keys(policy.guests).length + Object.keys(policy.storages).length
          + Object.keys(policy.thresholds).length + Object.keys(policy.defaults).length,
    [policy],
  )

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />{t("audit.policy.loading")}
      </div>
    )
  }

  const expectations = vocabulary?.expectations || ["required", "not_required", "unspecified"]
  const roles = vocabulary?.roles || ["essential", "optional", "unspecified"]

  return (
    <form onSubmit={(event) => { event.preventDefault(); void save() }}>
      {error && <p className="text-sm text-red-400 px-1">{error}</p>}
      {(conflict || !revision) && <Button type="button" onClick={() => void load()}>
        {t("audit.policy.reload")}
      </Button>}
      <Card className={editing
              ? "bg-accent border-border [&_input]:bg-background [&_[role=combobox]]:bg-background"
              : "bg-card border-border"}>
        <CardContent className="py-4 space-y-3">
          <p className="text-sm text-muted-foreground">{t("audit.policy.intro")}</p>
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="outline" className="tabular-nums">
              {t("audit.policy.declaredCount", { count: String(declared) })}
            </Badge>
            {saved && <span className="text-sm text-green-500">{t("audit.policy.saved")}</span>}
            {editing ? (
              <div className="ml-auto flex items-center gap-2">
                <button
                  type="button"
                  className="h-7 px-3 text-xs rounded-md border border-border bg-background
                             hover:bg-muted transition-colors text-muted-foreground"
                  onClick={() => { setEditing(false); void load() }}
                  disabled={saving}
                >
                  {t("actions.cancel")}
                </button>
                <button
                  type="submit"
                  className="h-7 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white
                             transition-colors disabled:opacity-50 flex items-center gap-1.5"
                  disabled={!dirty || saving}
                >
                  {saving
                    ? <Loader2 className="h-3 w-3 animate-spin" />
                    : <CheckCircle2 className="h-3 w-3" />}
                  {t("actions.save")}
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="ml-auto h-7 px-3 text-xs rounded-md border border-border bg-background
                           hover:bg-muted transition-colors flex items-center gap-1.5"
                onClick={() => { setEditing(true); setSaved(false) }}
                disabled={!revision || conflict}
              >
                <Settings2 className="h-3 w-3" />
                {t("actions.edit")}
              </button>
            )}
          </div>
        </CardContent>
      </Card>

      <fieldset disabled={locked} className="space-y-4 min-w-0">


      <Card className={editing
              ? "bg-accent border-border [&_input]:bg-background [&_[role=combobox]]:bg-background"
              : "bg-card border-border"}>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
            <Boxes className="h-4 w-4" />{t("audit.inventory.guests")}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 space-y-2">
          <p className="text-xs text-muted-foreground">{t("audit.policy.guestsNote")}</p>
          {guests.map((guest) => {
            const rule = policy.guests[String(guest.vmid)] || {}
            return (
              <div key={guest.vmid}
                   className="rounded-md border border-border p-3 space-y-2
                              sm:flex sm:flex-wrap sm:items-center sm:gap-3 sm:space-y-0">
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <Badge variant="outline" className="font-mono text-xs shrink-0">
                    {guest.vmid}
                  </Badge>
                  <span className="truncate font-medium text-foreground">
                    {guest.name || "—"}
                  </span>
                  <Badge variant="outline" className="text-xs uppercase shrink-0">
                    {guest.type}
                  </Badge>
                </div>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="w-20 shrink-0 sm:w-auto">{t("audit.policy.backup")}</span>
                  <PolicySelect label={t} disabled={locked}
                    inherited={policy.defaults.backup
                      ? t("audit.policy.inherit", { value: t(`audit.policy.expectation.${policy.defaults.backup}`) })
                      : t("audit.policy.inheritUnset")}
                    inheritedKey={policy.defaults.backup ? undefined : "unspecified"}
                    value={rule.backup || "inherit"}
                    options={expectations}
                    prefix="audit.policy.expectation"
                    onChange={(v) => setGuestRule(guest.vmid, "backup", v)}
                  />
                </label>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="w-20 shrink-0 sm:w-auto">{t("audit.policy.autostart")}</span>
                  <PolicySelect label={t} disabled={locked}
                    inherited={policy.defaults.autostart
                      ? t("audit.policy.inherit", { value: t(`audit.policy.expectation.${policy.defaults.autostart}`) })
                      : t("audit.policy.inheritUnset")}
                    inheritedKey={policy.defaults.autostart ? undefined : "unspecified"}
                    value={rule.autostart || "inherit"}
                    options={expectations}
                    prefix="audit.policy.expectation"
                    onChange={(v) => setGuestRule(guest.vmid, "autostart", v)}
                  />
                </label>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="w-20 shrink-0 sm:w-auto">{t("audit.policy.objective")}</span>
                  <input
                    type="number"
                    min={0.000001}
                    step="any"
                    inputMode="numeric"
                    value={rule.recovery_objective_hours ?? ""}
                    placeholder={policy.defaults.recovery_objective_hours
                      ? String(policy.defaults.recovery_objective_hours) : t("audit.policy.objectivePlaceholder")}
                    onChange={(e) => setGuestRule(
                      guest.vmid, "recovery_objective_hours",
                      e.target.value ? Number(e.target.value) : undefined)}
                    className="w-full min-w-0 rounded-md border border-border bg-background
                               px-2 py-1.5 text-sm text-foreground focus:outline-none
                               focus:ring-1 focus:ring-ring sm:w-24"
                  />
                  {rule.recovery_objective_hours == null && policy.defaults.recovery_objective_hours != null && (
                    <span>{t("audit.policy.inherit", { value: `${policy.defaults.recovery_objective_hours} ${t("audit.policy.objectivePlaceholder")}` })}</span>
                  )}
                </label>
              </div>
            )
          })}
          {guests.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("audit.policy.noGuests")}</p>
          )}
        </CardContent>
      </Card>

      <Card className={editing
              ? "bg-accent border-border [&_input]:bg-background [&_[role=combobox]]:bg-background"
              : "bg-card border-border"}>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
            <HardDrive className="h-4 w-4" />{t("audit.inventory.storage")}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 space-y-2">
          <p className="text-xs text-muted-foreground">{t("audit.policy.storagesNote")}</p>
          {storages.map((storage) => (
            <div key={storage.id}
                 className="rounded-md border border-border p-3 space-y-2
                            sm:flex sm:items-center sm:gap-3 sm:space-y-0">
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <Badge variant="outline" className="font-mono text-xs shrink-0">
                  {storage.id}
                </Badge>
                <span className="text-sm text-muted-foreground">{storage.type}</span>
              </div>
              <PolicySelect label={t} disabled={locked}
                inherited={policy.defaults.storage_role
                  ? t("audit.policy.inherit", { value: t(`audit.policy.role.${policy.defaults.storage_role}`) })
                  : t("audit.policy.inheritUnset")}
                inheritedKey={policy.defaults.storage_role ? undefined : "unspecified"}
                value={policy.storages[storage.id]?.role || "inherit"}
                options={roles}
                prefix="audit.policy.role"
                onChange={(v) => setStorageRole(storage.id, v)}
              />
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className={editing
              ? "bg-accent border-border [&_input]:bg-background [&_[role=combobox]]:bg-background"
              : "bg-card border-border"}>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base font-semibold text-foreground">
            <SlidersHorizontal className="h-4 w-4" />{t("audit.policy.thresholds")}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 space-y-2">
          <p className="text-xs text-muted-foreground">{t("audit.policy.thresholdsNote")}</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {Object.entries(vocabulary?.thresholds || {}).map(([name, shipped]) => (
              <label key={name}
                     className="flex flex-col items-end gap-1.5 rounded-md border
                                border-border p-2.5 sm:flex-row sm:items-center sm:gap-2">
                <span className="w-full min-w-0 text-left text-sm text-foreground sm:flex-1">
                  {t(`audit.policy.threshold.${name}`)}
                </span>
                <input
                  type="number"
                  min={0.000001}
                  max={name.endsWith("_percent") ? 100 : undefined}
                  step="any"
                  inputMode="decimal"
                  value={policy.thresholds[name] ?? ""}
                  placeholder={String(shipped)}
                  onChange={(e) => setThreshold(name, e.target.value)}
                  className="w-24 shrink-0 rounded-md border border-border bg-background
                             px-2 py-1.5 text-sm text-foreground tabular-nums
                             focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </label>
            ))}
          </div>
        </CardContent>
      </Card>
      </fieldset>
    </form>
  )
}
