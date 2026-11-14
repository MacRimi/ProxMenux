"use client"

// Security → Users: an administrator adds local users, chooses their profile,
// sets a new password for them or removes a second factor they lost. The
// Monitor always keeps one administrator (see permissions.py). A custom
// profile chooses the areas a user sees and the actions they may take.
// Everything is shown but used only after Edit: profile changes wait for Save,
// and the actions on a user confirm on their own.
import { useCallback, useEffect, useState } from "react"
import { KeyRound, Lock, ShieldCheck, Trash2, User, UserPlus } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Button } from "./ui/button"
import { Badge } from "./ui/badge"
import { fetchApi } from "../lib/api-config"
import { useAccess } from "../lib/access"
import { PROFILES, ProfilePicker, type Custom, type ProfileChoice } from "./profile-picker"
import { EDIT_CONTENT_CLASS, EditControls, EditableArea } from "./edit-controls"
import { useT } from "../lib/i18n/provider"

interface MonitorUser {
  username: string
  display_name: string | null
  profile: string
  custom: Custom | null
  totp_enabled: boolean
  primary: boolean
}

export function UsersSettings() {
  const t = useT()
  const { mode, capabilities } = useAccess()
  const [users, setUsers] = useState<MonitorUser[]>([])
  const [me, setMe] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [editing, setEditing] = useState(false)
  // Profiles chosen while editing, by user, saved together.
  const [drafts, setDrafts] = useState<Record<string, ProfileChoice>>({})
  const [adding, setAdding] = useState(false)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [newChoice, setNewChoice] = useState<ProfileChoice>({ profile: "operator_no_terminal", custom: null })
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
      const data = await fetchApi<{ users: MonitorUser[]; token?: string }>(url, { method, body: body ? JSON.stringify(body) : undefined })
      // A new password of the own account ends its other sessions; this one goes on.
      if (data.token) localStorage.setItem("proxmenux-auth-token", data.token)
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
  const choiceOf = (user: MonitorUser): ProfileChoice => drafts[user.username] ?? { profile: user.profile, custom: user.custom }
  const changed = users.filter(user => {
    const draft = drafts[user.username]
    return draft && JSON.stringify(draft) !== JSON.stringify({ profile: user.profile, custom: user.custom })
  })

  const add = async () => {
    if (password !== confirm) { setError(t("users.passwordsDiffer")); return }
    const body = { username: username.trim(), password, profile: newChoice.profile,
      ...(newChoice.profile === "custom" ? { custom: newChoice.custom } : {}) }
    if (await send("/api/auth/users", "POST", body, t("users.added"))) {
      setAdding(false)
      setUsername("")
      setPassword("")
      setConfirm("")
      setNewChoice({ profile: "operator_no_terminal", custom: null })
    }
  }

  const setNewPasswordFor = async (name: string) => {
    if (await send(userUrl(name), "PUT", { password: newPassword }, t("users.passwordSet"))) {
      setResetting(null)
      setNewPassword("")
    }
  }

  const save = async () => {
    for (const user of changed) {
      const draft = drafts[user.username]
      const ok = await send(userUrl(user.username), "PUT",
        { profile: draft.profile, ...(draft.profile === "custom" ? { custom: draft.custom } : {}) }, t("users.profileChanged"))
      if (!ok) return
    }
    setDrafts({})
    setEditing(false)
  }

  const cancel = () => {
    setDrafts({})
    setAdding(false)
    setResetting(null)
    setRemoving(null)
    setNewPassword("")
    setError("")
    setEditing(false)
  }

  const summary = (custom: Custom) => [
    custom.areas.map(a => t(`users.areas.${a}`)).join(", "),
    custom.actions.length ? custom.actions.map(a => t(`users.actions.${a}`)).join(", ") : t("users.noActions"),
  ].join(" · ")

  if (!visible) return null

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle>{t("users.title")}</CardTitle>
          <EditControls editing={editing} saving={busy} onSave={save} onCancel={cancel}
            onEdit={() => { setNotice(""); setEditing(true) }}
            canSave={changed.length > 0 && changed.every(u => drafts[u.username].profile !== "custom"
              || (drafts[u.username].custom?.areas.length ?? 0) > 0)} />
        </div>
        <CardDescription>{t("users.description")}</CardDescription>
      </CardHeader>
      <CardContent className={editing ? EDIT_CONTENT_CLASS : undefined}>
        <EditableArea editing={editing && !busy} className="space-y-4">
        {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
        {notice && <p className="text-sm text-green-500">{notice}</p>}

        <div className="space-y-2">
          {users.map(user => {
            const choice = choiceOf(user)
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
                {editing ? (
                  <ProfilePicker value={choice} disabled={false} idPrefix={`user-${user.username}`}
                    onChange={next => setDrafts({ ...drafts, [user.username]: next })} />
                ) : (
                  <div className="space-y-1">
                    <ProfilePicker value={choice} disabled showCustom={false} onChange={() => {}} />
                    {choice.profile === "custom" && choice.custom && (
                      <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{summary(choice.custom)}</p>
                    )}
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="outline" size="sm"
                    onClick={() => { setResetting(resetting === user.username ? null : user.username); setNewPassword("") }}>
                    <KeyRound className="h-4 w-4 mr-1" />{t("users.setPassword")}
                  </Button>
                  {user.totp_enabled && user.username !== me && (
                    <Button variant="outline" size="sm"
                      onClick={() => send(userUrl(user.username), "PUT", { reset_totp: true }, t("users.totpRemoved"))}>
                      {t("users.removeTotp")}
                    </Button>
                  )}
                  {user.username !== me && (
                    removing === user.username ? (
                      <>
                        <Button variant="destructive" size="sm"
                          onClick={async () => {
                            if (await send(userUrl(user.username), "DELETE", undefined, t("users.removed"))) setRemoving(null)
                          }}>
                          {t("users.confirmRemove")}
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setRemoving(null)}>
                          {t("actions.cancel")}
                        </Button>
                      </>
                    ) : (
                      <Button variant="outline" size="sm" onClick={() => setRemoving(user.username)}>
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
                        value={newPassword} onChange={e => setNewPassword(e.target.value)} />
                    </div>
                    <Button size="sm" className="bg-blue-500 hover:bg-blue-600 text-white" disabled={!newPassword}
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
                  className="pl-10" autoComplete="off" spellCheck={false} />
              </div>
              <p className="text-xs text-muted-foreground">{t("users.usernameHint")}</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-user-password">{t("users.password")}</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input id="new-user-password" type="password" value={password} onChange={e => setPassword(e.target.value)}
                  className="pl-10" autoComplete="new-password" />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-user-confirm">{t("users.confirmPassword")}</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input id="new-user-confirm" type="password" value={confirm} onChange={e => setConfirm(e.target.value)}
                  className="pl-10" autoComplete="new-password" />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-user-profile">{t("users.profile")}</Label>
              <ProfilePicker id="new-user-profile" value={newChoice} disabled={false} idPrefix="new-user"
                onChange={setNewChoice} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button className="bg-blue-500 hover:bg-blue-600 text-white" onClick={add}
                disabled={!username.trim() || !password || (newChoice.profile === "custom" && !(newChoice.custom?.areas.length))}>
                {t("users.add")}
              </Button>
              <Button variant="outline" onClick={() => setAdding(false)}>{t("actions.cancel")}</Button>
            </div>
          </div>
        )}

        <div className="rounded-md bg-card border border-border p-3 space-y-2 text-sm">
          {PROFILES.map(p => (
            <p key={p}>
              <span className="font-medium">{t(`users.profiles.${p}`)}</span>
              <span className="text-muted-foreground">: {t(`users.profileHints.${p}`)}</span>
            </p>
          ))}
        </div>
        </EditableArea>
      </CardContent>
    </Card>
  )
}
