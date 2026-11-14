"use client"

// Security → Proxmox VE accounts: let the users and realms of Proxmox VE sign
// in, next to the local account or instead of it.
import { useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Button } from "./ui/button"
import { Switch } from "./ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react"
import { fetchApi, getApiUrl } from "../lib/api-config"
import { useAccess } from "../lib/access"
import { useT } from "../lib/i18n/provider"
import { ProfilePicker, type ProfileChoice } from "./profile-picker"
import { EDIT_CONTENT_CLASS, EditControls, EditableArea, SWITCH_CLASS } from "./edit-controls"

interface Status { access_mode: string; pve_auth: boolean; local_account: boolean; setup_code_required: boolean }

const authHeaders = (): Record<string, string> => {
  const token = typeof window !== "undefined" ? localStorage.getItem("proxmenux-auth-token") : null
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// The profile of Proxmox VE users and groups: the rule of a user wins, then
// the first rule of one of their groups; without one, their privileges on /
// decide. A rule never lets in a user without privileges on /.
interface Rule { kind: "user" | "group"; name: string; choice: ProfileChoice }
interface Directory { users: string[]; groups: string[] }

type SavedRule = { kind: "user" | "group"; name: string } & ProfileChoice

const rulesOf = (saved: SavedRule[]): Rule[] =>
  saved.map(r => ({ kind: r.kind, name: r.name, choice: { profile: r.profile, custom: r.custom ?? null } }))

function PveProfileRules({ rules, setRules, directory }: {
  rules: Rule[]; setRules: (next: Rule[]) => void; directory: Directory
}) {
  const t = useT()
  const update = (index: number, next: Partial<Rule>) => setRules(rules.map((r, i) => i === index ? { ...r, ...next } : r))
  const move = (index: number, step: number) => {
    const next = [...rules]
    const [rule] = next.splice(index, 1)
    next.splice(index + step, 0, rule)
    setRules(next)
  }

  return (
    <div className="space-y-3 border-t border-border pt-4">
      <div>
        <h3 className="font-semibold">{t("pveAccounts.rulesTitle")}</h3>
        <p className="text-sm text-muted-foreground">{t("pveAccounts.rulesHelp")}</p>
      </div>
      {rules.map((rule, index) => {
        const names = rule.kind === "user" ? directory.users : directory.groups
        return (
          <div key={index} className="rounded-lg border border-border p-3 space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <Select value={rule.kind} onValueChange={kind => update(index, { kind: kind as Rule["kind"], name: "" })}>
                <SelectTrigger aria-label={t("pveAccounts.ruleKind")} className="w-full text-foreground"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="user">{t("pveAccounts.kindUser")}</SelectItem>
                  <SelectItem value="group">{t("pveAccounts.kindGroup")}</SelectItem>
                </SelectContent>
              </Select>
              {names.length ? (
                <Select value={rule.name || undefined} onValueChange={name => update(index, { name })}>
                  <SelectTrigger aria-label={t("pveAccounts.ruleName")} className="w-full min-w-0 text-foreground">
                    <SelectValue placeholder={t("pveAccounts.chooseName")} />
                  </SelectTrigger>
                  <SelectContent>
                    {[...new Set([...(rule.name ? [rule.name] : []), ...names])].map(name =>
                      <SelectItem key={name} value={name}>{name}</SelectItem>)}
                  </SelectContent>
                </Select>
              ) : (
                <Input aria-label={t("pveAccounts.ruleName")} value={rule.name} spellCheck={false}
                  placeholder={rule.kind === "user" ? "user@pve" : "group"}
                  onChange={event => update(index, { name: event.target.value })} />
              )}
            </div>
            <ProfilePicker value={rule.choice} disabled={false} idPrefix={`pve-rule-${index}`}
              onChange={choice => update(index, { choice })} />
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" disabled={index === 0} onClick={() => move(index, -1)}
                aria-label={t("pveAccounts.moveUp")}><ArrowUp className="h-4 w-4" /></Button>
              <Button variant="outline" size="sm" disabled={index === rules.length - 1} onClick={() => move(index, 1)}
                aria-label={t("pveAccounts.moveDown")}><ArrowDown className="h-4 w-4" /></Button>
              <Button variant="outline" size="sm" onClick={() => setRules(rules.filter((_, i) => i !== index))}>
                <Trash2 className="h-4 w-4 mr-1" />{t("pveAccounts.removeRule")}
              </Button>
            </div>
          </div>
        )
      })}
      <Button variant="outline" size="sm"
        onClick={() => setRules([...rules, { kind: "group", name: "", choice: { profile: "observer", custom: null } }])}>
        <Plus className="h-4 w-4 mr-1" />{t("pveAccounts.addRule")}
      </Button>
    </div>
  )
}

export function PveAccountsSettings() {
  const t = useT()
  const { capabilities } = useAccess()
  const [status, setStatus] = useState<Status | null>(null)
  const [setupCode, setSetupCode] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [editing, setEditing] = useState(false)
  const [enabled, setEnabled] = useState(false)
  const [rules, setRules] = useState<Rule[]>([])
  const [savedRules, setSavedRules] = useState<Rule[]>([])
  const [directory, setDirectory] = useState<Directory>({ users: [], groups: [] })

  const load = () => fetch(getApiUrl("/api/auth/status"), { headers: authHeaders(), cache: "no-store" })
    .then(response => response.ok ? response.json() : null)
    .then(data => { if (data) { setStatus(data); setEnabled(!!data.pve_auth) } })
    .catch(() => {})
  useEffect(() => { load() }, [])

  // The rules exist for an administrator while the accounts can sign in.
  const showRules = !!status?.pve_auth && capabilities.admin
  useEffect(() => {
    if (!showRules) return
    fetchApi<{ rules: SavedRule[] } & Directory>("/api/auth/pve/profiles")
      .then(data => { setRules(rulesOf(data.rules)); setSavedRules(rulesOf(data.rules)); setDirectory({ users: data.users, groups: data.groups }) })
      .catch(() => {})
  }, [showRules])

  const failure = (data: { error?: string; message?: string }) =>
    data.error === "setup_code_invalid" ? t("authSetup.codeInvalid")
      : data.error === "setup_code_rate_limited" ? t("authSetup.codeRateLimited")
      : data.message || t("pveAccounts.saveFailed")

  // Choosing Proxmox VE accounts without a local one: an action of its own.
  const choose = async () => {
    setBusy(true)
    setError("")
    try {
      const response = await fetch(getApiUrl("/api/auth/mode"), {
        method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ mode: "proxmox", setup_code: setupCode }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(failure(data))
      // Who can sign in changed: load the dashboard again with it.
      setTimeout(() => window.location.reload(), 600)
    } catch (err) {
      setError(err instanceof Error ? err.message : t("pveAccounts.saveFailed"))
    } finally {
      setBusy(false)
    }
  }

  const save = async () => {
    if (!status) return
    setBusy(true)
    setError("")
    setNotice("")
    try {
      if (showRules && enabled && JSON.stringify(rules) !== JSON.stringify(savedRules)) {
        const data = await fetchApi<{ rules: SavedRule[] }>("/api/auth/pve/profiles", {
          method: "PUT", body: JSON.stringify({
            rules: rules.map(r => ({ kind: r.kind, name: r.name, profile: r.choice.profile, custom: r.choice.custom })),
          }),
        })
        setRules(rulesOf(data.rules))
        setSavedRules(rulesOf(data.rules))
      }
      if (status.access_mode === "password" && enabled !== status.pve_auth) {
        const response = await fetch(getApiUrl("/api/auth/pve/config"), {
          method: "PUT", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify({ enabled }),
        })
        const data = await response.json().catch(() => ({}))
        if (!response.ok) throw new Error(failure(data))
        setTimeout(() => window.location.reload(), 600)
      }
      setNotice(t("pveAccounts.rulesSaved"))
      setEditing(false)
    } catch (err) {
      const code = (err as { body?: { error?: string } })?.body?.error
      const key = code ? (code.startsWith("pve_") ? `pveAccounts.errors.${code}` : `users.errors.${code}`) : ""
      const translated = key ? t(key) : ""
      setError(translated && translated !== key ? translated : err instanceof Error ? err.message : t("pveAccounts.saveFailed"))
    } finally {
      setBusy(false)
    }
  }

  const cancel = () => {
    setEnabled(!!status?.pve_auth)
    setRules(savedRules)
    setSetupCode("")
    setError("")
    setEditing(false)
  }

  if (!status || status.access_mode === "undecided") return null
  const mode = status.access_mode
  // Without a local account the card only offers an action, which confirms on its own.
  const savable = mode === "password" || showRules
  // Only fields to fill in call for the contrast of edit mode, not a lone toggle.
  const hasFields = (showRules && enabled) || ((mode === "open" || mode === "read_only") && status.setup_code_required)

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle>{t("pveAccounts.title")}</CardTitle>
          <EditControls editing={editing} saving={busy} onSave={save} onCancel={cancel} showSave={savable}
            onEdit={() => { setNotice(""); setEditing(true) }} canSave={!rules.some(r => !r.name.trim())} />
        </div>
        <CardDescription>{t("pveAccounts.description")}</CardDescription>
      </CardHeader>
      <CardContent className={editing && hasFields ? EDIT_CONTENT_CLASS : undefined}>
        <EditableArea editing={editing && !busy} className="space-y-4">
        {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
        {notice && <p className="text-sm text-green-500">{notice}</p>}

        {mode === "password" && (
          <div className="flex items-center justify-between gap-4">
            <Label htmlFor="pve-accounts-enabled">{t("pveAccounts.enable")}</Label>
            <Switch id="pve-accounts-enabled" checked={enabled} className={SWITCH_CLASS}
              onCheckedChange={setEnabled} />
          </div>
        )}

        {mode === "proxmox" && <p className="text-sm">{t("pveAccounts.onlyWay")}</p>}

        {(mode === "open" || mode === "read_only") && (
          <div className="space-y-3">
            {status.setup_code_required && (
              <div className="space-y-2">
                <Label htmlFor="pve-setup-code">{t("authSetup.setupCode")}</Label>
                <Input id="pve-setup-code" value={setupCode} onChange={e => setSetupCode(e.target.value)}
                  placeholder="XXXX-XXXX-XXXX" className="font-mono uppercase tracking-wider"
                  autoComplete="off" spellCheck={false} />
                <p className="text-xs text-muted-foreground">{t("authSetup.setupCodeHint")}</p>
              </div>
            )}
            <Button onClick={choose} className="bg-blue-500 hover:bg-blue-600 text-white">
              {t("authSetup.choosePve")}
            </Button>
          </div>
        )}

        <div className="rounded-md bg-card border border-border p-3 text-sm space-y-2">
          <p>{t("pveAccounts.whoGetsIn")}</p>
          <p className="text-xs text-muted-foreground">{t("pveAccounts.sharedSession")}</p>
        </div>

        {showRules && enabled && <PveProfileRules rules={rules} setRules={setRules} directory={directory} />}
        </EditableArea>
      </CardContent>
    </Card>
  )
}
