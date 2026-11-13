"use client"

// Security → Users: an administrator adds local users, chooses their profile,
// sets a new password for them or removes a second factor they lost. The
// Monitor always keeps one administrator (see permissions.py).
import { useCallback, useEffect, useState } from "react"
import { KeyRound, Lock, ShieldCheck, Trash2, User, UserPlus } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Button } from "./ui/button"
import { Badge } from "./ui/badge"
import { fetchApi } from "../lib/api-config"
import { useAccess } from "../lib/access"
import { useT } from "../lib/i18n/provider"

export const PROFILES = ["admin", "operator", "operator_no_terminal", "observer"] as const

interface MonitorUser {
  username: string
  display_name: string | null
  profile: string
  totp_enabled: boolean
  primary: boolean
}

const selectClass = "h-9 rounded-md border border-input bg-background px-2 text-sm"

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
  const [resetting, setResetting] = useState<string | null>(null)
  const [newPassword, setNewPassword] = useState("")
  const [removing, setRemoving] = useState<string | null>(null)

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

  const add = async () => {
    if (password !== confirm) { setError(t("users.passwordsDiffer")); return }
    if (await send("/api/auth/users", "POST", { username: username.trim(), password, profile }, t("users.added"))) {
      setAdding(false)
      setUsername("")
      setPassword("")
      setConfirm("")
    }
  }

  const setNewPasswordFor = async (name: string) => {
    if (await send(`/api/auth/users/${encodeURIComponent(name)}`, "PUT", { password: newPassword }, t("users.passwordSet"))) {
      setResetting(null)
      setNewPassword("")
    }
  }

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
          {users.map(user => (
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
              <div className="flex flex-wrap items-center gap-2">
                <select aria-label={t("users.profile")} className={selectClass} value={user.profile} disabled={busy}
                  onChange={e => send(`/api/auth/users/${encodeURIComponent(user.username)}`, "PUT",
                    { profile: e.target.value }, t("users.profileChanged"))}>
                  {PROFILES.map(p => <option key={p} value={p}>{t(`users.profiles.${p}`)}</option>)}
                </select>
                <Button variant="outline" size="sm" disabled={busy}
                  onClick={() => { setResetting(resetting === user.username ? null : user.username); setNewPassword("") }}>
                  <KeyRound className="h-4 w-4 mr-1" />{t("users.setPassword")}
                </Button>
                {user.totp_enabled && user.username !== me && (
                  <Button variant="outline" size="sm" disabled={busy}
                    onClick={() => send(`/api/auth/users/${encodeURIComponent(user.username)}`, "PUT",
                      { reset_totp: true }, t("users.totpRemoved"))}>
                    {t("users.removeTotp")}
                  </Button>
                )}
                {user.username !== me && (
                  removing === user.username ? (
                    <>
                      <Button variant="destructive" size="sm" disabled={busy}
                        onClick={async () => {
                          if (await send(`/api/auth/users/${encodeURIComponent(user.username)}`, "DELETE", undefined,
                            t("users.removed"))) setRemoving(null)
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
          ))}
        </div>

        {!adding ? (
          <Button variant="outline" onClick={() => { setAdding(true); setError(""); setNotice("") }}>
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
              <select id="new-user-profile" className={`${selectClass} w-full`} value={profile}
                onChange={e => setProfile(e.target.value)} disabled={busy}>
                {PROFILES.map(p => <option key={p} value={p}>{t(`users.profiles.${p}`)}</option>)}
              </select>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button className="bg-blue-500 hover:bg-blue-600" disabled={busy || !username.trim() || !password} onClick={add}>
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
