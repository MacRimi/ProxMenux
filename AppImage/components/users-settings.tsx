"use client"

// Security → Users: an administrator adds local users, chooses their profile,
// sets a new password for them or removes a second factor they lost. The
// Monitor always keeps one administrator (see permissions.py). A custom
// profile chooses the areas a user sees and the actions they may take.
import { useCallback, useEffect, useState } from "react"
import { KeyRound, Lock, ShieldCheck, SlidersHorizontal, Trash2, User, UserPlus } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Button } from "./ui/button"
import { Badge } from "./ui/badge"
import { Checkbox } from "./ui/checkbox"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { fetchApi } from "../lib/api-config"
import { AREAS, useAccess } from "../lib/access"
import { useT } from "../lib/i18n/provider"

export const PROFILES = ["admin", "operator", "operator_no_terminal", "observer", "custom"] as const
// Administering is not offered: whoever administers can give themselves any profile.
export const CUSTOM_ACTIONS = ["execute", "guests", "backup", "update", "terminal"] as const

interface Custom { areas: string[]; actions: string[] }

interface MonitorUser {
  username: string
  display_name: string | null
  profile: string
  custom: Custom | null
  totp_enabled: boolean
  primary: boolean
}

const EMPTY_CUSTOM: Custom = { areas: ["general"], actions: [] }

function CustomChoice({ value, onChange, disabled }: { value: Custom; onChange: (next: Custom) => void; disabled: boolean }) {
  const t = useT()
  const toggle = (list: string[], item: string, on: boolean) => on ? [...list, item] : list.filter(x => x !== item)
  const group = (title: string, items: readonly string[], key: "areas" | "actions", label: (item: string) => string) => (
    <fieldset className="space-y-2 min-w-0">
      <legend className="text-sm font-medium mb-1">{title}</legend>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {items.map(item => {
          const id = `custom-${key}-${item}`
          return (
            <label key={item} htmlFor={id} className="flex items-center gap-2 text-sm min-w-0">
              <Checkbox id={id} checked={value[key].includes(item)} disabled={disabled}
                onCheckedChange={on => onChange({ ...value, [key]: toggle(value[key], item, on === true) })} />
              <span className="min-w-0 [overflow-wrap:anywhere]">{label(item)}</span>
            </label>
          )
        })}
      </div>
    </fieldset>
  )
  return (
    <div className="space-y-4 rounded-md border border-border bg-muted/40 p-3">
      {group(t("users.customAreas"), AREAS, "areas", item => t(`users.areas.${item}`))}
      {group(t("users.customActions"), CUSTOM_ACTIONS, "actions", item => t(`users.actions.${item}`))}
      <p className="text-xs text-muted-foreground">{t("users.customHint")}</p>
    </div>
  )
}

export function UsersSettings() {
  const t = useT()
  const { mode, capabilities } = useAccess()
  const [users, setUsers] = useState<MonitorUser[]>([])
  const [me, setMe] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [adding, setAdding] = useState(false)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [profile, setProfile] = useState<string>("operator_no_terminal")
  const [newCustom, setNewCustom] = useState<Custom>(EMPTY_CUSTOM)
  const [resetting, setResetting] = useState<string | null>(null)
  const [newPassword, setNewPassword] = useState("")
  const [removing, setRemoving] = useState<string | null>(null)
  // The user whose custom choice is being edited, and that choice.
  const [customizing, setCustomizing] = useState<{ username: string; custom: Custom } | null>(null)

  const visible = mode === "password" && capabilities.admin

  const load = useCallback(() => {
    fetchApi<{ users: MonitorUser[] }>("/api/auth/users").then(data => setUsers(data.users)).catch(() => {})
    fetchApi<{ username: string | null }>("/api/auth/status").then(data => setMe(data.username)).catch(() => {})
  }, [])
  useEffect(() => { if (visible) load() }, [visible, load])

  const failure = (err: unknown) => {
    const code = (err as { body?: { error?: string } })?.body?.error
    const key = code ? `users.errors.${code}` : ""
    const translated = key ? t(key) : ""
    return translated && translated !== key ? translated : err instanceof Error ? err.message : t("users.errors.user_change_failed")
  }

  const send = async (url: string, method: string, body: object | undefined, done: string) => {
    setBusy(true)
    setError("")
    setNotice("")
    try {
      const data = await fetchApi<{ users: MonitorUser[] }>(url, { method, body: body ? JSON.stringify(body) : undefined })
      setUsers(data.users)
      setNotice(done)
      return true
    } catch (err) {
      setError(failure(err))
      return false
    } finally {
      setBusy(false)
    }
  }

  const userUrl = (name: string) => `/api/auth/users/${encodeURIComponent(name)}`

  const add = async () => {
    if (password !== confirm) { setError(t("users.passwordsDiffer")); return }
    const body = { username: username.trim(), password, profile, ...(profile === "custom" ? { custom: newCustom } : {}) }
    if (await send("/api/auth/users", "POST", body, t("users.added"))) {
      setAdding(false)
      setUsername("")
      setPassword("")
      setConfirm("")
      setNewCustom(EMPTY_CUSTOM)
    }
  }

  const changeProfile = (user: MonitorUser, next: string) => {
    // A custom profile is saved with its choice, from the editor below.
    if (next === "custom") {
      setCustomizing({ username: user.username, custom: user.custom ?? EMPTY_CUSTOM })
      return
    }
    setCustomizing(null)
    send(userUrl(user.username), "PUT", { profile: next }, t("users.profileChanged"))
  }

  const saveCustom = async () => {
    if (!customizing) return
    if (await send(userUrl(customizing.username), "PUT", { profile: "custom", custom: customizing.custom },
      t("users.profileChanged"))) setCustomizing(null)
  }

  const setNewPasswordFor = async (name: string) => {
    if (await send(userUrl(name), "PUT", { password: newPassword }, t("users.passwordSet"))) {
      setResetting(null)
      setNewPassword("")
    }
  }

  const summary = (custom: Custom) => [
    custom.areas.map(a => t(`users.areas.${a}`)).join(", "),
    custom.actions.length ? custom.actions.map(a => t(`users.actions.${a}`)).join(", ") : t("users.noActions"),
  ].join(" · ")

  if (!visible) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("users.title")}</CardTitle>
        <CardDescription>{t("users.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
        {notice && <p className="text-sm text-green-500">{notice}</p>}

        <div className="space-y-2">
          {users.map(user => {
            const editing = customizing?.username === user.username
            return (
              <div key={user.username} className="rounded-lg border border-border p-3 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <User className="h-4 w-4 text-muted-foreground shrink-0" />
                  <span className="font-medium break-all">{user.username}</span>
                  {user.display_name && <span className="text-sm text-muted-foreground break-all">{user.display_name}</span>}
                  {user.username === me && <Badge variant="outline">{t("users.you")}</Badge>}
                  {user.primary && <Badge variant="outline">{t("users.primary")}</Badge>}
                  {user.totp_enabled && (
                    <Badge variant="outline" className="gap-1"><ShieldCheck className="h-3 w-3" />2FA</Badge>
                  )}
                </div>
                {user.profile === "custom" && user.custom && !editing && (
                  <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{summary(user.custom)}</p>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <Select value={editing ? "custom" : user.profile} disabled={busy}
                    onValueChange={value => changeProfile(user, value)}>
                    <SelectTrigger aria-label={t("users.profile")} className="h-9 w-full min-w-0 text-foreground sm:w-[14rem]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PROFILES.map(p => <SelectItem key={p} value={p}>{t(`users.profiles.${p}`)}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  {user.profile === "custom" && !editing && (
                    <Button variant="outline" size="sm" disabled={busy}
                      onClick={() => setCustomizing({ username: user.username, custom: user.custom ?? EMPTY_CUSTOM })}>
                      <SlidersHorizontal className="h-4 w-4 mr-1" />{t("users.customize")}
                    </Button>
                  )}
                  <Button variant="outline" size="sm" disabled={busy}
                    onClick={() => { setResetting(resetting === user.username ? null : user.username); setNewPassword("") }}>
                    <KeyRound className="h-4 w-4 mr-1" />{t("users.setPassword")}
                  </Button>
                  {user.totp_enabled && user.username !== me && (
                    <Button variant="outline" size="sm" disabled={busy}
                      onClick={() => send(userUrl(user.username), "PUT", { reset_totp: true }, t("users.totpRemoved"))}>
                      {t("users.removeTotp")}
                    </Button>
                  )}
                  {user.username !== me && (
                    removing === user.username ? (
                      <>
                        <Button variant="destructive" size="sm" disabled={busy}
                          onClick={async () => {
                            if (await send(userUrl(user.username), "DELETE", undefined, t("users.removed"))) setRemoving(null)
                          }}>
                          {t("users.confirmRemove")}
                        </Button>
                        <Button variant="outline" size="sm" disabled={busy} onClick={() => setRemoving(null)}>
                          {t("actions.cancel")}
                        </Button>
                      </>
                    ) : (
                      <Button variant="outline" size="sm" disabled={busy} onClick={() => setRemoving(user.username)}>
                        <Trash2 className="h-4 w-4 mr-1" />{t("users.remove")}
                      </Button>
                    )
                  )}
                </div>
                {removing === user.username && <p className="text-xs text-muted-foreground">{t("users.removeHint")}</p>}
                {editing && customizing && (
                  <div className="space-y-2">
                    <CustomChoice value={customizing.custom} disabled={busy}
                      onChange={custom => setCustomizing({ username: user.username, custom })} />
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" className="bg-blue-500 hover:bg-blue-600" disabled={busy || !customizing.custom.areas.length}
                        onClick={saveCustom}>
                        {t("actions.save")}
                      </Button>
                      <Button size="sm" variant="outline" disabled={busy} onClick={() => setCustomizing(null)}>
                        {t("actions.cancel")}
                      </Button>
                    </div>
                  </div>
                )}
                {resetting === user.username && (
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="space-y-1 min-w-0 flex-1">
                      <Label htmlFor={`new-password-${user.username}`}>{t("users.newPassword")}</Label>
                      <Input id={`new-password-${user.username}`} type="password" autoComplete="new-password"
                        value={newPassword} onChange={e => setNewPassword(e.target.value)} disabled={busy} />
                    </div>
                    <Button size="sm" className="bg-blue-500 hover:bg-blue-600" disabled={busy || !newPassword}
                      onClick={() => setNewPasswordFor(user.username)}>
                      {t("actions.save")}
                    </Button>
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {!adding ? (
          <Button className="bg-blue-500 hover:bg-blue-600 text-white" onClick={() => { setAdding(true); setError(""); setNotice("") }}>
            <UserPlus className="h-4 w-4 mr-2" />{t("users.add")}
          </Button>
        ) : (
          <div className="space-y-3 rounded-lg border border-border p-4">
            <div className="space-y-2">
              <Label htmlFor="new-user-name">{t("users.username")}</Label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input id="new-user-name" value={username} onChange={e => setUsername(e.target.value)}
                  className="pl-10" autoComplete="off" spellCheck={false} disabled={busy} />
              </div>
              <p className="text-xs text-muted-foreground">{t("users.usernameHint")}</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-user-password">{t("users.password")}</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input id="new-user-password" type="password" value={password} onChange={e => setPassword(e.target.value)}
                  className="pl-10" autoComplete="new-password" disabled={busy} />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-user-confirm">{t("users.confirmPassword")}</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input id="new-user-confirm" type="password" value={confirm} onChange={e => setConfirm(e.target.value)}
                  className="pl-10" autoComplete="new-password" disabled={busy} />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-user-profile">{t("users.profile")}</Label>
              <Select value={profile} onValueChange={setProfile} disabled={busy}>
                <SelectTrigger id="new-user-profile" className="w-full text-foreground">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROFILES.map(p => <SelectItem key={p} value={p}>{t(`users.profiles.${p}`)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            {profile === "custom" && <CustomChoice value={newCustom} onChange={setNewCustom} disabled={busy} />}
            <div className="flex flex-wrap gap-2">
              <Button className="bg-blue-500 hover:bg-blue-600" onClick={add}
                disabled={busy || !username.trim() || !password || (profile === "custom" && !newCustom.areas.length)}>
                {t("users.add")}
              </Button>
              <Button variant="outline" disabled={busy} onClick={() => setAdding(false)}>{t("actions.cancel")}</Button>
            </div>
          </div>
        )}

        <div className="rounded-md bg-muted p-3 space-y-2 text-sm">
          {PROFILES.map(p => (
            <p key={p}>
              <span className="font-medium">{t(`users.profiles.${p}`)}</span>
              <span className="text-muted-foreground">: {t(`users.profileHints.${p}`)}</span>
            </p>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
