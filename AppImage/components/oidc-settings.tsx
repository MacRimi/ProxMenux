"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Button } from "./ui/button"
import { Switch } from "./ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"
import { Plus, Trash2 } from "lucide-react"
import { ProfilePicker, type ProfileChoice } from "./profile-picker"

interface Configuration {
  enabled: boolean
  available: boolean
  provider_name: string
  issuer: string
  client_id: string
  public_url: string
  allowed_subjects: string[]
  subject_profiles: Record<string, { name: string | null } & ProfileChoice>
  token_auth_method: string
  has_client_secret: boolean
}

// An allowed subject: its immutable `sub`, a name to recognise it by and its
// profile. One without a saved profile administers, as every subject did.
interface Subject { sub: string; name: string; choice: ProfileChoice }

const subjectsOf = (data: Configuration): Subject[] => data.allowed_subjects.map(sub => {
  const saved = data.subject_profiles?.[sub]
  return { sub, name: saved?.name ?? "", choice: { profile: saved?.profile ?? "admin", custom: saved?.custom ?? null } }
})

export function OIDCSettings() {
  const t = useT()
  const [config, setConfig] = useState<Configuration | null>(null)
  const [secret, setSecret] = useState("")
  const [subjects, setSubjects] = useState<Subject[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    fetchApi<Configuration>("/api/auth/oidc/config").then(data => {
      setConfig(data)
      setSubjects(subjectsOf(data))
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
          allowed_subjects: subjects.map(s => s.sub.trim()).filter(Boolean),
          subject_profiles: Object.fromEntries(subjects.filter(s => s.sub.trim()).map(s =>
            [s.sub.trim(), { name: s.name.trim() || null, profile: s.choice.profile, custom: s.choice.custom }])),
          ...(secret ? { client_secret: secret } : {}),
        }),
      })
      setConfig(data)
      setSubjects(subjectsOf(data))
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
            <Select value={config.token_auth_method} disabled={busy}
              onValueChange={value => setConfig({ ...config, token_auth_method: value })}>
              <SelectTrigger id="oidc-auth-method" className="w-full text-foreground">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="client_secret_basic">client_secret_basic</SelectItem>
                <SelectItem value="client_secret_post">client_secret_post</SelectItem>
                <SelectItem value="none">{t("oidc.publicClient")}</SelectItem>
              </SelectContent>
            </Select>
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
          <Label>{t("oidc.allowedSubjects")}</Label>
          <p className="text-xs text-muted-foreground">{t("oidc.allowedSubjectsHelp")}</p>
          {subjects.map((subject, index) => {
            const update = (next: Partial<Subject>) =>
              setSubjects(subjects.map((s, i) => i === index ? { ...s, ...next } : s))
            return (
              <div key={index} className="rounded-lg border border-border p-3 space-y-3">
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="space-y-1 min-w-0">
                    <Label htmlFor={`oidc-sub-${index}`}>{t("oidc.subjectId")}</Label>
                    <Input id={`oidc-sub-${index}`} value={subject.sub} disabled={busy} spellCheck={false}
                      className="font-mono" onChange={event => update({ sub: event.target.value })} />
                  </div>
                  <div className="space-y-1 min-w-0">
                    <Label htmlFor={`oidc-name-${index}`}>{t("oidc.subjectName")}</Label>
                    <Input id={`oidc-name-${index}`} value={subject.name} disabled={busy} maxLength={64}
                      onChange={event => update({ name: event.target.value })} />
                  </div>
                </div>
                <div className="flex flex-col sm:flex-row sm:items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <ProfilePicker value={subject.choice} disabled={busy} idPrefix={`oidc-${index}`}
                      onChange={choice => update({ choice })} />
                  </div>
                  <Button variant="outline" size="sm" disabled={busy} className="self-start"
                    onClick={() => setSubjects(subjects.filter((_, i) => i !== index))}>
                    <Trash2 className="h-4 w-4 mr-1" />{t("oidc.removeSubject")}
                  </Button>
                </div>
              </div>
            )
          })}
          <Button variant="outline" size="sm" disabled={busy}
            onClick={() => setSubjects([...subjects, { sub: "", name: "", choice: { profile: "admin", custom: null } }])}>
            <Plus className="h-4 w-4 mr-1" />{t("oidc.addSubject")}
          </Button>
        </div>
        <div className="rounded-md bg-muted p-3 text-sm space-y-2">
          <p>{t("oidc.callback")}</p>
          <code className="block break-all text-xs">{config.public_url.replace(/\/$/, "")}/api/auth/oidc/callback</code>
          <p className="text-xs text-muted-foreground">{t("oidc.mfaHelp")}</p>
        </div>
        <Button className="bg-blue-500 hover:bg-blue-600 text-white" onClick={save}
          disabled={busy || (config.enabled && !config.available)}>
          {busy ? t("oidc.saving") : t(config.enabled ? "oidc.save" : "oidc.saveDisabled")}
        </Button>
      </>}
    </CardContent>
  </Card>
}
