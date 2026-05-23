"use client"

import { useState, useEffect, useRef } from "react"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogTitle } from "./ui/dialog"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Shield, Lock, User, AlertCircle, Eye, EyeOff, Upload, Trash2 } from "lucide-react"
import { getApiUrl } from "../lib/api-config"

interface AuthSetupProps {
  onComplete: () => void
}

export function AuthSetup({ onComplete }: AuthSetupProps) {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState<"choice" | "setup">("choice")
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

  useEffect(() => {
    const checkOnboardingStatus = async () => {
      try {
        const response = await fetch(getApiUrl("/api/auth/status"))
        
        // Check if response is valid JSON before parsing
        if (!response.ok) {
          // API not available - don't show modal in preview
          return
        }
        
        const contentType = response.headers.get("content-type")
        if (!contentType || !contentType.includes("application/json")) {
          return
        }
        
        const data = await response.json()

        // Show modal if auth is not configured and not declined
        if (!data.auth_configured) {
          setTimeout(() => setOpen(true), 500)
        }
      } catch {
        // API not available (preview environment) - don't show modal
      }
    }

    checkOnboardingStatus()
  }, [])

  const handleSkipAuth = async () => {
    setLoading(true)
    setError("")

    try {
      const response = await fetch(getApiUrl("/api/auth/skip"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || "Failed to skip authentication")
      }

      if (data.auth_declined) {
      }

      localStorage.setItem("proxmenux-auth-declined", "true")
      localStorage.removeItem("proxmenux-auth-token") // Remove any old token
      setOpen(false)
      onComplete()
    } catch (err) {
      console.error("[v0] Auth skip error:", err)
      setError(err instanceof Error ? err.message : "Failed to save preference")
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
      setError("Please fill in all fields")
      return
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match")
      return
    }

    if (password.length < 6) {
      setError("Password must be at least 6 characters")
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
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || "Failed to setup authentication")
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

      setOpen(false)
      onComplete()
    } catch (err) {
      console.error("[v0] Auth setup error:", err)
      setError(err instanceof Error ? err.message : "Failed to setup authentication")
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto">
        <DialogTitle className="sr-only">
          {step === "choice" ? "Setup Dashboard Protection" : "Create Password"}
        </DialogTitle>
        {step === "choice" ? (
          <div className="space-y-6 py-2">
            <div className="text-center space-y-2">
              <div className="mx-auto w-16 h-16 bg-blue-500/10 rounded-full flex items-center justify-center">
                <Shield className="h-8 w-8 text-blue-500" />
              </div>
              <h2 className="text-2xl font-bold">Protect Your Dashboard?</h2>
              <p className="text-muted-foreground text-sm">
                Add an extra layer of security to protect your Proxmox data when accessing from non-private networks.
              </p>
            </div>

            <div className="space-y-3">
              <Button onClick={() => setStep("setup")} className="w-full bg-blue-500 hover:bg-blue-600" size="lg">
                <Lock className="h-4 w-4 mr-2" />
                Yes, Setup Password
              </Button>
              <Button
                onClick={handleSkipAuth}
                variant="outline"
                className="w-full bg-transparent"
                size="lg"
                disabled={loading}
              >
                No, Continue Without Protection
              </Button>
            </div>

            <p className="text-xs text-center text-muted-foreground">You can always enable this later in Settings</p>
          </div>
        ) : (
          <div className="space-y-6 py-2">
            <div className="text-center space-y-2">
              <div className="mx-auto w-16 h-16 bg-blue-500/10 rounded-full flex items-center justify-center">
                <Lock className="h-8 w-8 text-blue-500" />
              </div>
              <h2 className="text-2xl font-bold">Setup Authentication</h2>
              <p className="text-muted-foreground text-sm">Create a username and password to protect your dashboard</p>
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 flex items-start gap-2">
                <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-500">{error}</p>
              </div>
            )}

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="username" className="text-sm">
                  Username
                </Label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="username"
                    type="text"
                    placeholder="Enter username"
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
                  Password
                </Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    placeholder="Enter password"
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
                  Confirm Password
                </Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="confirm-password"
                    type={showConfirmPassword ? "text" : "password"}
                    placeholder="Confirm password"
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
                  Profile · optional
                </p>

                <div className="space-y-2">
                  <Label htmlFor="display-name" className="text-sm">
                    Display name
                  </Label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="display-name"
                      type="text"
                      placeholder="Shown above the username in the menu"
                      value={displayName}
                      onChange={(e) => setDisplayName(e.target.value)}
                      maxLength={64}
                      className="pl-10 text-base"
                      disabled={loading}
                    />
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    Leave empty to render the username itself. Up to 64 characters.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label className="text-sm">Avatar</Label>
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
                          {avatarFile ? "Change" : "Choose image"}
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
                            Clear
                          </Button>
                        )}
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        PNG, JPEG, WebP or GIF · up to 2 MB · pre-crop square for best results.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <Button onClick={handleSetupAuth} className="w-full bg-blue-500 hover:bg-blue-600" disabled={loading}>
                {loading ? "Setting up..." : "Setup Authentication"}
              </Button>
              <Button onClick={() => setStep("choice")} variant="ghost" className="w-full" disabled={loading}>
                Back
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
