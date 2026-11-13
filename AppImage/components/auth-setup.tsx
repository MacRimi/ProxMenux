"use client"

import { useState, useRef } from "react"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogTitle } from "./ui/dialog"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Shield, Lock, User, AlertCircle, Eye, EyeOff, Upload, Trash2, KeyRound, ShieldAlert } from "lucide-react"
import { getApiUrl } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

interface AuthSetupProps {
  onComplete: () => void
  // A new installation asks for the code the installer showed in the console.
  setupCodeRequired?: boolean
}

// The first-run screen: nothing else of the Monitor is served until it is
// answered. With a password, an account is created; without one, the owner
// chooses read-only or open.
export function AuthSetup({ onComplete, setupCodeRequired = false }: AuthSetupProps) {
  const t = useT()
  const [step, setStep] = useState<"choice" | "setup" | "mode">("choice")
  const [setupCode, setSetupCode] = useState("")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  // Profile (Fase 2 — v1.2.2). Both optional decorations on top of the
  // mandatory username + password. Persisted via PUT /api/auth/profile
  // and POST /api/auth/profile/avatar after the user lands a successful
  // /api/auth/setup so we don't change the setup endpoint's contract.
  const [displayName, setDisplayName] = useState("")
  const [avatarFile, setAvatarFile] = useState<File | null>(null)
  const [avatarPreviewUrl, setAvatarPreviewUrl] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // A refused setup code gets its own explanation; anything else, the message.
  const errorText = (data: { error?: string; message?: string }, fallback: string) => {
    if (data.error === "setup_code_invalid") return t("authSetup.codeInvalid")
    if (data.error === "setup_code_rate_limited") return t("authSetup.codeRateLimited")
    return data.error || data.message || fallback
  }

  const handleChooseMode = async (mode: "read_only" | "open" | "proxmox") => {
    setLoading(true)
    setError("")

    try {
      const response = await fetch(getApiUrl("/api/auth/mode"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, setup_code: setupCode }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(errorText(data, t("authSetup.savePreferenceFailed")))
      }
      localStorage.removeItem("proxmenux-auth-token") // Remove any old token
      onComplete()
    } catch (err) {
      setError(err instanceof Error ? err.message : t("authSetup.savePreferenceFailed"))
    } finally {
      setLoading(false)
    }
  }

  const handleAvatarPick = () => fileInputRef.current?.click()

  const handleAvatarChange = (file: File | null) => {
    // Revoke the previous local preview so we don't leak blob URLs while
    // the user picks another file before submitting.
    if (avatarPreviewUrl) {
      URL.revokeObjectURL(avatarPreviewUrl)
    }
    setAvatarFile(file)
    setAvatarPreviewUrl(file ? URL.createObjectURL(file) : null)
  }

  const handleSetupAuth = async () => {
    setError("")

    if (!username || !password) {
      setError(t("authSetup.fillFields"))
      return
    }

    if (password !== confirmPassword) {
      setError(t("authSetup.passwordMismatch"))
      return
    }

    if (password.length < 6) {
      setError(t("authSetup.passwordTooShort"))
      return
    }

    setLoading(true)

    try {
      const response = await fetch(getApiUrl("/api/auth/setup"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username,
          password,
          setup_code: setupCode,
        }),
      })

      const data = await response.json().catch(() => ({}))

      if (!response.ok) {
        throw new Error(errorText(data, t("authSetup.setupFailed")))
      }

      if (data.token) {
        localStorage.setItem("proxmenux-auth-token", data.token)
        localStorage.removeItem("proxmenux-auth-declined")
      }

      // Profile decorations (Fase 2). Sent as a follow-up to the setup
      // call so the /api/auth/setup endpoint stays minimal (username +
      // password only) — these calls reuse the existing profile
      // endpoints and the JWT we just received. Failures here are
      // non-fatal: the user is already authenticated and can finish
      // configuring the profile from the /profile page.
      const token = data.token
      if (token) {
        const trimmedDisplayName = displayName.trim()
        if (trimmedDisplayName) {
          try {
            await fetch(getApiUrl("/api/auth/profile"), {
              method: "PUT",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${token}`,
              },
              body: JSON.stringify({ display_name: trimmedDisplayName }),
            })
          } catch (e) {
            console.warn("[auth-setup] failed to save display_name:", e)
          }
        }
        if (avatarFile) {
          try {
            await fetch(getApiUrl("/api/auth/profile/avatar"), {
              method: "POST",
              headers: {
                "Content-Type": avatarFile.type,
                Authorization: `Bearer ${token}`,
              },
              body: avatarFile,
            })
          } catch (e) {
            console.warn("[auth-setup] failed to upload avatar:", e)
          }
        }
      }

      // Release the local preview blob now that the file has been
      // uploaded (or skipped). The header avatar pulls a fresh copy
      // from the backend.
      if (avatarPreviewUrl) {
        URL.revokeObjectURL(avatarPreviewUrl)
        setAvatarPreviewUrl(null)
      }

      // Notify the header AvatarMenu (mounted on dashboard load with
      // auth_enabled=false) to re-fetch its status + profile so the
      // avatar appears immediately after first-time setup instead of
      // requiring a page refresh.
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("proxmenux:profile-changed"))
      }

      onComplete()
    } catch (err) {
      console.error("Auth setup error:", err)
      setError(err instanceof Error ? err.message : t("authSetup.setupFailed"))
    } finally {
      setLoading(false)
    }
  }

  const errorBox = error && (
    <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 flex items-start gap-2">
      <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
      <p className="text-sm text-red-500">{error}</p>
    </div>
  )

  const setupCodeField = setupCodeRequired && (
    <div className="space-y-2">
      <Label htmlFor="setup-code" className="text-sm">
        {t("authSetup.setupCode")}
      </Label>
      <div className="relative">
        <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          id="setup-code"
          type="text"
          placeholder="XXXX-XXXX-XXXX"
          value={setupCode}
          onChange={(e) => setSetupCode(e.target.value)}
          className="pl-10 text-base font-mono uppercase tracking-wider"
          disabled={loading}
          autoComplete="off"
          spellCheck={false}
        />
      </div>
      <p className="text-[11px] text-muted-foreground">{t("authSetup.setupCodeHint")}</p>
    </div>
  )

  return (
    <Dialog open onOpenChange={() => { /* the first-run screen stays until it is answered */ }}>
      <DialogContent
        hideClose
        onEscapeKeyDown={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
        className="max-w-md max-h-[90vh] overflow-y-auto"
      >
        <DialogTitle className="sr-only">
          {step === "choice" ? t("authSetup.choiceTitle") : step === "mode" ? t("authSetup.noPasswordTitle") : t("authSetup.passwordTitle")}
        </DialogTitle>
        {step === "choice" ? (
          <div className="space-y-6 py-2">
            <div className="text-center space-y-2">
              <div className="mx-auto w-16 h-16 bg-blue-500/10 rounded-full flex items-center justify-center">
                <Shield className="h-8 w-8 text-blue-500" />
              </div>
              <h2 className="text-2xl font-bold">{t("authSetup.protectTitle")}</h2>
              <p className="text-muted-foreground text-sm">
                {t("authSetup.protectDescription")}
              </p>
            </div>

            <div className="space-y-3">
              <Button onClick={() => setStep("setup")} className="w-full bg-blue-500 hover:bg-blue-600" size="lg">
                <Lock className="h-4 w-4 mr-2" />
                {t("authSetup.setupPassword")}
              </Button>
              <Button
                onClick={() => { setError(""); setStep("mode") }}
                variant="outline"
                className="w-full bg-transparent"
                size="lg"
                disabled={loading}
              >
                {t("authSetup.skipProtection")}
              </Button>
            </div>

            <p className="text-xs text-center text-muted-foreground">{t("authSetup.enableLater")}</p>
          </div>
        ) : step === "mode" ? (
          <div className="space-y-6 py-2">
            <div className="text-center space-y-2">
              <h2 className="text-2xl font-bold">{t("authSetup.noPasswordTitle")}</h2>
              <p className="text-muted-foreground text-sm">{t("authSetup.noPasswordDescription")}</p>
            </div>

            {errorBox}
            {setupCodeField}

            <div className="space-y-3">
              <div className="rounded-lg border border-border bg-accent/40 p-4 space-y-3">
                <div className="flex items-start gap-3">
                  <Eye className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <p className="font-semibold">{t("authSetup.readOnlyTitle")}</p>
                    <p className="text-sm text-muted-foreground">{t("authSetup.readOnlyDescription")}</p>
                  </div>
                </div>
                <Button onClick={() => handleChooseMode("read_only")} className="w-full bg-blue-500 hover:bg-blue-600" disabled={loading}>
                  {t("authSetup.chooseReadOnly")}
                </Button>
              </div>

              <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 space-y-3">
                <div className="flex items-start gap-3">
                  <ShieldAlert className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <p className="font-semibold">{t("authSetup.openTitle")}</p>
                    <p className="text-sm text-muted-foreground">{t("authSetup.openDescription")}</p>
                  </div>
                </div>
                <Button onClick={() => handleChooseMode("open")} variant="outline"
                  className="w-full border-red-500/40 text-red-500 hover:bg-red-500/10 hover:text-red-500" disabled={loading}>
                  {t("authSetup.chooseOpen")}
                </Button>
              </div>
            </div>

            <Button onClick={() => { setError(""); setStep("choice") }} variant="ghost" className="w-full" disabled={loading}>
              {t("authSetup.back")}
            </Button>
          </div>
        ) : (
          <div className="space-y-6 py-2">
            <div className="text-center space-y-2">
              <div className="mx-auto w-16 h-16 bg-blue-500/10 rounded-full flex items-center justify-center">
                <Lock className="h-8 w-8 text-blue-500" />
              </div>
              <h2 className="text-2xl font-bold">{t("authSetup.setupTitle")}</h2>
              <p className="text-muted-foreground text-sm">{t("authSetup.setupDescription")}</p>
            </div>

            {errorBox}

            <div className="space-y-4">
              {setupCodeField}

              <div className="space-y-2">
                <Label htmlFor="username" className="text-sm">
                  {t("authSetup.username")}
                </Label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="username"
                    type="text"
                    placeholder={t("authSetup.usernamePlaceholder")}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="pl-10 text-base"
                    disabled={loading}
                    autoComplete="username"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="password" className="text-sm">
                  {t("authSetup.password")}
                </Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    placeholder={t("authSetup.passwordPlaceholder")}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-10 text-base"
                    disabled={loading}
                    autoComplete="new-password"
                  />
                  <Button
                    variant="ghost"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2"
                    disabled={loading}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="confirm-password" className="text-sm">
                  {t("authSetup.confirmPassword")}
                </Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="confirm-password"
                    type={showConfirmPassword ? "text" : "password"}
                    placeholder={t("authSetup.confirmPasswordPlaceholder")}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="pl-10 text-base"
                    disabled={loading}
                    autoComplete="new-password"
                  />
                  <Button
                    variant="ghost"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2"
                    disabled={loading}
                  >
                    {showConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                </div>
              </div>

              {/* Optional profile decorations (Fase 2). Visually
                  separated from the mandatory credential fields by a
                  divider + a small heading so the operator understands
                  they can skip everything below and still complete the
                  setup. Both are saved with follow-up calls after the
                  setup endpoint returns the JWT. */}
              <div className="pt-3 border-t border-border/60 space-y-4">
                <p className="text-xs text-muted-foreground uppercase tracking-wider">
                  {t("authSetup.profileOptional")}
                </p>

                <div className="space-y-2">
                  <Label htmlFor="display-name" className="text-sm">
                    {t("authSetup.displayName")}
                  </Label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="display-name"
                      type="text"
                      placeholder={t("authSetup.displayNamePlaceholder")}
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      maxLength={64}
                      className="pl-10 text-base"
                      disabled={loading}
                    />
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    {t("authSetup.displayNameHint")}
                  </p>
                </div>

                <div className="space-y-2">
                  <Label className="text-sm">{t("authSetup.avatar")}</Label>
                  <div className="flex items-center gap-3">
                    {avatarPreviewUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={avatarPreviewUrl}
                        alt=""
                        className="w-14 h-14 rounded-full object-cover border border-border bg-cyan-500/5 shrink-0"
                      />
                    ) : (
                      <span className="w-14 h-14 rounded-full bg-cyan-500/15 text-cyan-600 dark:text-cyan-300 flex items-center justify-center text-xl font-semibold border border-border shrink-0">
                        {(displayName || username || "U").trim().charAt(0).toUpperCase() || "U"}
                      </span>
                    )}
                    <div className="flex flex-col gap-1.5 min-w-0">
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/png,image/jpeg,image/webp,image/gif"
                        className="hidden"
                        onChange={(e) => {
                          const file = e.target.files?.[0] || null
                          handleAvatarChange(file)
                          if (fileInputRef.current) fileInputRef.current.value = ""
                        }}
                      />
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={handleAvatarPick}
                          disabled={loading}
                          className="h-7 text-xs"
                        >
                          <Upload className="h-3 w-3 mr-1.5" />
                          {avatarFile ? t("authSetup.change") : t("authSetup.chooseImage")}
                        </Button>
                        {avatarFile && (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => handleAvatarChange(null)}
                            disabled={loading}
                            className="h-7 text-xs text-red-500 hover:text-red-500 hover:bg-red-500/10"
                          >
                            <Trash2 className="h-3 w-3 mr-1.5" />
                            {t("authSetup.clear")}
                          </Button>
                        )}
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        {t("authSetup.avatarHint")}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <Button onClick={handleSetupAuth} className="w-full bg-blue-500 hover:bg-blue-600" disabled={loading}>
                {loading ? t("authSetup.settingUp") : t("authSetup.setupAuthentication")}
              </Button>
              {/* The accounts of Proxmox VE instead of one of the Monitor's own. */}
              <div className="rounded-lg border border-border bg-accent/40 p-3 space-y-2">
                <p className="text-sm font-medium">{t("authSetup.pveTitle")}</p>
                <p className="text-xs text-muted-foreground">{t("authSetup.pveDescription")}</p>
                <Button onClick={() => handleChooseMode("proxmox")} variant="outline" className="w-full" disabled={loading}>
                  {t("authSetup.choosePve")}
                </Button>
              </div>
              <Button onClick={() => { setError(""); setStep("choice") }} variant="ghost" className="w-full" disabled={loading}>
                {t("authSetup.back")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
