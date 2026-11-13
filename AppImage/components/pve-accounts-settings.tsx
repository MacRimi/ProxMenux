"use client"

// Security → Proxmox VE accounts: let the users and realms of Proxmox VE sign
// in, next to the local account or instead of it.
import { useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Button } from "./ui/button"
import { Switch } from "./ui/switch"
import { getApiUrl } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

interface Status { access_mode: string; pve_auth: boolean; local_account: boolean; setup_code_required: boolean }

const authHeaders = (): Record<string, string> => {
  const token = typeof window !== "undefined" ? localStorage.getItem("proxmenux-auth-token") : null
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function PveAccountsSettings() {
  const t = useT()
  const [status, setStatus] = useState<Status | null>(null)
  const [setupCode, setSetupCode] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const load = () => fetch(getApiUrl("/api/auth/status"), { headers: authHeaders(), cache: "no-store" })
    .then(response => response.ok ? response.json() : null)
    .then(data => { if (data) setStatus(data) })
    .catch(() => {})
  useEffect(() => { load() }, [])

  const send = async (url: string, method: string, body: object) => {
    setBusy(true)
    setError("")
    try {
      const response = await fetch(getApiUrl(url), {
        method, headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify(body),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(data.error === "setup_code_invalid" ? t("authSetup.codeInvalid")
          : data.error === "setup_code_rate_limited" ? t("authSetup.codeRateLimited")
          : data.message || t("pveAccounts.saveFailed"))
      }
      // Who can sign in changed: load the dashboard again with it.
      setTimeout(() => window.location.reload(), 600)
    } catch (err) {
      setError(err instanceof Error ? err.message : t("pveAccounts.saveFailed"))
    } finally {
      setBusy(false)
    }
  }

  if (!status || status.access_mode === "undecided") return null
  const mode = status.access_mode

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("pveAccounts.title")}</CardTitle>
        <CardDescription>{t("pveAccounts.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <p role="alert" className="text-sm text-red-500">{error}</p>}

        {mode === "password" && (
          <div className="flex items-center justify-between gap-4">
            <Label htmlFor="pve-accounts-enabled">{t("pveAccounts.enable")}</Label>
            <Switch id="pve-accounts-enabled" checked={status.pve_auth} disabled={busy}
              onCheckedChange={enabled => send("/api/auth/pve/config", "PUT", { enabled })} />
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
                  autoComplete="off" spellCheck={false} disabled={busy} />
                <p className="text-xs text-muted-foreground">{t("authSetup.setupCodeHint")}</p>
              </div>
            )}
            <Button onClick={() => send("/api/auth/mode", "POST", { mode: "proxmox", setup_code: setupCode })}
              className="bg-blue-500 hover:bg-blue-600" disabled={busy}>
              {t("authSetup.choosePve")}
            </Button>
          </div>
        )}

        <div className="rounded-md bg-muted p-3 text-sm space-y-2">
          <p>{t("pveAccounts.whoGetsIn")}</p>
          <p className="text-xs text-muted-foreground">{t("pveAccounts.sharedSession")}</p>
        </div>
      </CardContent>
    </Card>
  )
}
