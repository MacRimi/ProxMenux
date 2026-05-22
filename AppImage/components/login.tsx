"use client"

import type React from "react"

import { useState, useEffect } from "react"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Checkbox } from "./ui/checkbox"
import { Lock, User, AlertCircle, Server, Shield, Eye, EyeOff } from "lucide-react"
import { getApiUrl } from "../lib/api-config"
import Image from "next/image"

interface LoginProps {
  onLogin: () => void
}

export function Login({ onLogin }: LoginProps) {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [totpCode, setTotpCode] = useState("")
  const [requiresTotp, setRequiresTotp] = useState(false)
  const [rememberMe, setRememberMe] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    // The Login screen is, by construction, the recovery path from any
    // 401 cascade (the api-config wrapper redirects here when an
    // expired/invalid JWT is detected). Clear the cascade-prevention
    // flag on mount so a successful login can subsequently fire a fresh
    // reload if a NEW 401 ever occurs. Without this clear, any 401 set
    // earlier in the session sticks around forever and the next 401
    // (e.g. mid-2FA, or right after a successful login if the token was
    // briefly stale) is silently swallowed by the de-dup — the user
    // sees a blank/stuck dashboard.
    try {
      sessionStorage.removeItem("proxmenux-auth-401-handled")
    } catch {
      // private browsing — best-effort
    }

    const savedUsername = localStorage.getItem("proxmenux-saved-username")
    const savedPassword = localStorage.getItem("proxmenux-saved-password")

    if (savedUsername && savedPassword) {
      setUsername(savedUsername)
      setPassword(savedPassword)
      setRememberMe(true)
    }
  }, [])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")

    if (!username || !password) {
      setError("Please enter username and password")
      return
    }

    if (requiresTotp && !totpCode) {
      setError("Please enter your 2FA code")
      return
    }

    setLoading(true)

    try {
      const response = await fetch(getApiUrl("/api/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username,
          password,
          totp_token: totpCode || undefined, // Include 2FA code if provided
        }),
      })

      const data = await response.json()

      if (data.requires_totp) {
        setRequiresTotp(true)
        setLoading(false)
        return
      }

      if (!response.ok) {
        throw new Error(data.message || "Login failed")
      }

      localStorage.setItem("proxmenux-auth-token", data.token)
      try {
        sessionStorage.removeItem("proxmenux-auth-401-handled")
      } catch {
        // ignore
      }

      if (rememberMe) {
        localStorage.setItem("proxmenux-saved-username", username)
        localStorage.setItem("proxmenux-saved-password", password)
      } else {
        localStorage.removeItem("proxmenux-saved-username")
        localStorage.removeItem("proxmenux-saved-password")
      }

      onLogin()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center space-y-4">
          <div className="flex justify-center">
            <div className="w-20 h-20 relative flex items-center justify-center bg-primary/10 rounded-lg">
              <Image
                src="/images/proxmenux-logo.png"
                alt="ProxMenux Logo"
                width={80}
                height={80}
                className="object-contain"
                priority
                onError={(e) => {
                  const target = e.target as HTMLImageElement
                  target.style.display = "none"
                  const fallback = target.parentElement?.querySelector(".fallback-icon")
                  if (fallback) {
                    fallback.classList.remove("hidden")
                  }
                }}
              />
              <Server className="h-12 w-12 text-primary absolute fallback-icon hidden" />
            </div>
          </div>
          <div>
            <h1 className="text-3xl font-bold">ProxMenux Monitor</h1>
            <p className="text-muted-foreground mt-2">Sign in to access your dashboard</p>
          </div>
        </div>

        <div className="bg-card border border-border rounded-lg p-6 shadow-lg">
          <form onSubmit={handleLogin} className="space-y-4">
            {error && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 flex items-start gap-2">
                <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-500">{error}</p>
              </div>
            )}

            {!requiresTotp ? (
              <>
                <div className="space-y-2">
                  <Label htmlFor="login-username" className="text-sm">
                    Username
                  </Label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="login-username"
                      type="text"
                      placeholder="Enter your username"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className="pl-10 text-base"
                      disabled={loading}
                      autoComplete="username"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="login-password" className="text-sm">
                    Password
                  </Label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="login-password"
                      type={showPassword ? "text" : "password"}
                      placeholder="Enter your password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="pl-10 pr-10 text-base"
                      disabled={loading}
                      autoComplete="current-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                      disabled={loading}
                      tabIndex={-1}
                    >
                      {showPassword ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>

                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="remember-me"
                    checked={rememberMe}
                    onCheckedChange={(checked) => setRememberMe(checked as boolean)}
                    disabled={loading}
                  />
                  <Label htmlFor="remember-me" className="text-sm font-normal cursor-pointer select-none">
                    Remember me
                  </Label>
                </div>
              </>
            ) : (
              <div className="space-y-4">
                <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-start gap-2">
                  <Shield className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-blue-500">Two-Factor Authentication</p>
                    <p className="text-xs text-blue-500 mt-1">Enter the 6-digit code from your authentication app</p>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="totp-code" className="text-sm">
                    Authentication Code
                  </Label>
                  <Input
                    id="totp-code"
                    type="text"
                    placeholder="000000"
                    value={totpCode}
                    onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    className="text-center text-lg tracking-widest font-mono text-base"
                    maxLength={6}
                    disabled={loading}
                    autoComplete="one-time-code"
                    autoFocus
                  />
                  <p className="text-xs text-muted-foreground text-center">
                    You can also use a backup code (format: XXXX-XXXX)
                  </p>
                </div>

                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setRequiresTotp(false)
                    setTotpCode("")
                    setError("")
                  }}
                  className="w-full"
                >
                  Back to login
                </Button>
              </div>
            )}

            <Button type="submit" className="w-full bg-blue-500 hover:bg-blue-600" disabled={loading}>
              {loading ? "Signing in..." : requiresTotp ? "Verify Code" : "Sign In"}
            </Button>
          </form>
        </div>

        <p className="text-center text-sm text-muted-foreground">ProxMenux Monitor v1.2.1.3-beta</p>
      </div>
    </div>
  )
}
