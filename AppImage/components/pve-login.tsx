"use client"

// Sign in with a Proxmox VE account. The Monitor keeps the Proxmox VE ticket
// as its session, and the local Proxmox VE API decides what it can do.
import type React from "react"
import { useEffect, useState } from "react"
import { AlertCircle, ExternalLink, KeyRound, Lock, User } from "lucide-react"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { getApiUrl } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

interface Realm { realm: string; type: string; comment: string; default: boolean }

// The session of the Proxmox VE web interface, when the browser sends its
// cookie: it does when both are opened over HTTPS by the same name.
export async function adoptPveSession(): Promise<boolean> {
  try {
    const response = await fetch(getApiUrl("/api/auth/pve/session"), { cache: "no-store", credentials: "include" })
    if (!response.ok) return false
    const data = await response.json()
    if (typeof data.ticket !== "string") return false
    localStorage.setItem("proxmenux-auth-token", data.ticket)
    return true
  } catch {
    return false
  }
}

export function PveLogin({ onLogin }: { onLogin: () => void }) {
  const t = useT()
  const [realms, setRealms] = useState<Realm[]>([])
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [realm, setRealm] = useState("pam")
  const [challenge, setChallenge] = useState<{ username: string; challenge: string; methods: string[] } | null>(null)
  const [code, setCode] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetch(getApiUrl("/api/auth/pve/realms"), { cache: "no-store" })
      .then(response => response.ok ? response.json() : null)
      .then(data => {
        const list: Realm[] = data?.realms || []
        setRealms(list)
        const preferred = list.find(r => r.default) || list.find(r => r.realm === "pam") || list[0]
        if (preferred) setRealm(preferred.realm)
      })
      .catch(() => {})
    // Back from the Proxmox VE web interface: its session signs in here.
    const retry = () => {
      if (document.visibilityState === "visible") {
        adoptPveSession().then(found => { if (found) onLogin() })
      }
    }
    document.addEventListener("visibilitychange", retry)
    return () => document.removeEventListener("visibilitychange", retry)
  }, [onLogin])

  const send = async (body: Record<string, string>) => {
    setLoading(true)
    setError("")
    try {
      const response = await fetch(getApiUrl("/api/auth/pve/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      const data = await response.json().catch(() => ({}))
      if (response.status === 429) throw new Error(t("pveLogin.tooManyAttempts"))
      if (!response.ok) throw new Error(t("pveLogin.failed"))
      if (data.need_tfa) {
        setChallenge({ username: data.username, challenge: data.challenge, methods: data.methods || [] })
        return
      }
      localStorage.setItem("proxmenux-auth-token", data.ticket)
      onLogin()
    } catch (err) {
      setError(err instanceof Error ? err.message : t("pveLogin.failed"))
    } finally {
      setLoading(false)
    }
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (challenge) {
      send({ username: challenge.username, challenge: challenge.challenge, code })
    } else {
      if (!username || !password) { setError(t("pveLogin.fillFields")); return }
      send({ username, password, realm })
    }
  }

  // Only security keys are configured: those work in the Proxmox VE web interface.
  const keysOnly = !!challenge && !challenge.methods.some(m => m === "totp" || m === "recovery")
  const webInterface = typeof window !== "undefined" ? `https://${window.location.hostname}:8006/` : ""

  return (
    <form onSubmit={submit} className="space-y-4">
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 flex items-start gap-2">
          <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-red-500">{error}</p>
        </div>
      )}

      {!challenge ? (
        <>
          <div className="space-y-2">
            <Label htmlFor="pve-username">{t("pveLogin.username")}</Label>
            <div className="relative">
              <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input id="pve-username" value={username} onChange={e => setUsername(e.target.value)}
                className="pl-10" autoComplete="username" disabled={loading} />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="pve-password">{t("pveLogin.password")}</Label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input id="pve-password" type="password" value={password} onChange={e => setPassword(e.target.value)}
                className="pl-10" autoComplete="current-password" disabled={loading} />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="pve-realm">{t("pveLogin.realm")}</Label>
            <Select value={realm} onValueChange={setRealm} disabled={loading}>
              <SelectTrigger id="pve-realm" className="w-full text-foreground">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(realms.length ? realms : [{ realm: "pam", type: "pam", comment: "", default: true }]).map(r => (
                  <SelectItem key={r.realm} value={r.realm}>{r.comment ? `${r.comment} (${r.realm})` : r.realm}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      ) : keysOnly ? (
        <p className="text-sm text-muted-foreground">{t("pveLogin.useWebInterface")}</p>
      ) : (
        <div className="space-y-2">
          <Label htmlFor="pve-code">{t("pveLogin.code")}</Label>
          <div className="relative">
            <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input id="pve-code" value={code} onChange={e => setCode(e.target.value)} autoFocus
              className="pl-10 font-mono tracking-wider" autoComplete="one-time-code" disabled={loading} />
          </div>
          <p className="text-xs text-muted-foreground">{t("pveLogin.codeHint")}</p>
        </div>
      )}

      {!keysOnly && (
        <Button type="submit" className="w-full bg-blue-500 hover:bg-blue-600" disabled={loading}>
          {loading ? t("login.signingIn") : challenge ? t("login.verifyCode") : t("login.signIn")}
        </Button>
      )}
      {challenge && (
        <Button type="button" variant="ghost" className="w-full" disabled={loading}
          onClick={() => { setChallenge(null); setCode(""); setError("") }}>
          {t("authSetup.back")}
        </Button>
      )}

      <div className="pt-2 border-t border-border/60 space-y-1">
        <a href={webInterface} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-sm text-blue-500 hover:underline">
          {t("pveLogin.webInterface")} <ExternalLink className="h-3.5 w-3.5" />
        </a>
        <p className="text-xs text-muted-foreground">{t("pveLogin.webInterfaceHint")}</p>
      </div>
    </form>
  )
}
