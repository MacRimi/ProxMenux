"use client"

import { useState, useEffect } from "react"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogTitle } from "./ui/dialog"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Shield, Lock, User, AlertCircle, Eye, EyeOff } from "lucide-react"
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

  useEffect(() => {
    const checkOnboardingStatus = async () => {
      try {
        const response = await fetch(getApiUrl("/api/auth/status"))
        const data = await response.json()

        console.log("[v0] Auth status for modal check:", data)

        // Show modal if auth is not configured and not declined
        if (!data.auth_configured) {
          setTimeout(() => setOpen(true), 500)
        }
      } catch (error) {
        console.error("[v0] Failed to check auth status:", error)
        // Fail-safe: show modal if we can't check status
        setTimeout(() => setOpen(true), 500)
      }
    }

    checkOnboardingStatus()
  }, [])

  const handleSkipAuth = async () => {
    setLoading(true)
    setError("")

    try {
      console.log("[v0] Skipping authentication setup...")
      const response = await fetch(getApiUrl("/api/auth/skip"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      })

      const data = await response.json()
      console.log("[v0] Auth skip response:", data)

      if (!response.ok) {
        throw new Error(data.error || "Failed to skip authentication")
      }

      if (data.auth_declined) {
        console.log("[v0] Authentication skipped successfully - APIs should be accessible without token")
      }

      console.log("[v0] Authentication skipped successfully")
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
      console.log("[v0] Setting up authentication...")
      const response = await fetch(getApiUrl("/api/auth/setup"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username,
          password,
        }),
      })

      const data = await response.json()
      console.log("[v0] Auth setup response:", data)

      if (!response.ok) {
        throw new Error(data.error || "Failed to setup authentication")
      }

      if (data.token) {
        localStorage.setItem("proxmenux-auth-token", data.token)
        localStorage.removeItem("proxmenux-auth-declined")
        console.log("[v0] Authentication setup successful")
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
