"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Textarea } from "./ui/textarea"
import { Button } from "./ui/button"
import { Switch } from "./ui/switch"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

interface Configuration {
  enabled: boolean
  available: boolean
  provider_name: string
  issuer: string
  client_id: string
  public_url: string
  allowed_subjects: string[]
  token_auth_method: string
  has_client_secret: boolean
}

export function OIDCSettings() {
  const t = useT()
  const [config, setConfig] = useState<Configuration | null>(null)
  const [secret, setSecret] = useState("")
  const [subjects, setSubjects] = useState("")
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    fetchApi<Configuration>("/api/auth/oidc/config").then(data => {
      setConfig(data)
      setSubjects(data.allowed_subjects.join("\n"))
    }).catch(() => setError(t("oidc.localRequired")))
  }, [t])

  const save = async () => {
    if (!config) return
    setBusy(true)
    setError("")
    setMessage("")
    try {
      const data = await fetchApi<Configuration>("/api/auth/oidc/config", {
        method: "PUT",
        body: JSON.stringify({
          enabled: config.enabled, provider_name: config.provider_name,
          issuer: config.issuer, client_id: config.client_id, public_url: config.public_url,
          token_auth_method: config.token_auth_method,
          allowed_subjects: subjects.split("\n").map(s => s.trim()).filter(Boolean),
          ...(secret ? { client_secret: secret } : {}),
        }),
      })
      setConfig(data)
      setSecret("")
      setMessage(t(data.enabled ? "oidc.saved" : "oidc.disabledSaved"))
    } catch (err) {
      setError(err instanceof Error ? err.message : t("oidc.saveFailed"))
    } finally { setBusy(false) }
  }

  return <Card>
    <CardHeader>
      <CardTitle>{t("oidc.title")}</CardTitle>
      <CardDescription>{t("oidc.description")}</CardDescription>
    </CardHeader>
    <CardContent className="space-y-4">
      {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
      {message && <p role="status" className="text-sm text-green-500">{message}</p>}
      {config && <>
        {!config.available && <p className="text-sm text-amber-500">{t("oidc.unavailable")}</p>}
        <div className="flex items-center justify-between gap-4">
          <Label htmlFor="oidc-enabled">{t("oidc.enable")}</Label>
          <Switch id="oidc-enabled" checked={config.enabled} disabled={busy || !config.available}
            onCheckedChange={enabled => setConfig({ ...config, enabled })} />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {(["provider_name", "issuer", "public_url", "client_id"] as const).map(field =>
            <div key={field} className="space-y-2">
              <Label htmlFor={`oidc-${field}`}>{t(`oidc.${field}`)}</Label>
              <Input id={`oidc-${field}`} value={config[field]} disabled={busy}
                type={field === "issuer" || field === "public_url" ? "url" : "text"}
                onChange={event => setConfig({ ...config, [field]: event.target.value })} />
            </div>)}
          <div className="space-y-2">
            <Label htmlFor="oidc-auth-method">{t("oidc.authMethod")}</Label>
            <select id="oidc-auth-method" className="h-10 w-full rounded-md border bg-background px-3 text-sm"
              value={config.token_auth_method} disabled={busy}
              onChange={event => setConfig({ ...config, token_auth_method: event.target.value })}>
              <option value="client_secret_basic">client_secret_basic</option>
              <option value="client_secret_post">client_secret_post</option>
              <option value="none">{t("oidc.publicClient")}</option>
            </select>
          </div>
          {config.token_auth_method !== "none" && <div className="space-y-2">
            <Label htmlFor="oidc-secret">{t("oidc.secret")}</Label>
            <Input id="oidc-secret" type="password" autoComplete="new-password" value={secret} disabled={busy}
              placeholder={config.has_client_secret ? t("oidc.secretKept") : ""}
              onChange={event => setSecret(event.target.value)} />
          </div>}
        </div>
        <p className="text-xs text-muted-foreground">{t("oidc.urlHelp")}</p>
        <div className="space-y-2">
          <Label htmlFor="oidc-subjects">{t("oidc.subjects")}</Label>
          <Textarea id="oidc-subjects" value={subjects} disabled={busy} rows={3}
            onChange={event => setSubjects(event.target.value)} />
          <p className="text-xs text-muted-foreground">{t("oidc.subjectHelp")}</p>
        </div>
        <div className="rounded-md bg-muted p-3 text-sm space-y-2">
          <p>{t("oidc.callback")}</p>
          <code className="block break-all text-xs">{config.public_url.replace(/\/$/, "")}/api/auth/oidc/callback</code>
          <p className="text-xs text-muted-foreground">{t("oidc.mfaHelp")}</p>
        </div>
        <Button onClick={save} disabled={busy || (config.enabled && !config.available)}>
          {busy ? t("oidc.saving") : t(config.enabled ? "oidc.save" : "oidc.saveDisabled")}
        </Button>
      </>}
    </CardContent>
  </Card>
}
