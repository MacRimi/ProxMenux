"use client"

import { useState, useEffect } from "react"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import {
  Shield,
  Lock,
  User,
  AlertCircle,
  CheckCircle,
  Info,
  LogOut,
  Wrench,
  Package,
  Key,
  Copy,
  Eye,
  EyeOff,
} from "lucide-react"
import { APP_VERSION } from "./release-notes-modal"
import { getApiUrl, fetchApi } from "../lib/api-config"
import { TwoFactorSetup } from "./two-factor-setup"

interface ProxMenuxTool {
  key: string
  name: string
  enabled: boolean
}

export function Settings() {
  const [authEnabled, setAuthEnabled] = useState(false)
  const [totpEnabled, setTotpEnabled] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState("")

  // Setup form state
  const [showSetupForm, setShowSetupForm] = useState(false)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")

  // Change password form state
  const [showChangePassword, setShowChangePassword] = useState(false)
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmNewPassword, setConfirmNewPassword] = useState("")

  const [show2FASetup, setShow2FASetup] = useState(false)
  const [show2FADisable, setShow2FADisable] = useState(false)
  const [disable2FAPassword, setDisable2FAPassword] = useState("")

  const [proxmenuxTools, setProxmenuxTools] = useState<ProxMenuxTool[]>([])
  const [loadingTools, setLoadingTools] = useState(true)
  const [expandedVersions, setExpandedVersions] = useState<Record<string, boolean>>({
    [APP_VERSION]: true, // Current version expanded by default
  })

  // API Token state management
  const [showApiTokenSection, setShowApiTokenSection] = useState(false)
  const [apiToken, setApiToken] = useState("")
  const [apiTokenVisible, setApiTokenVisible] = useState(false)
  const [tokenPassword, setTokenPassword] = useState("")
  const [tokenTotpCode, setTokenTotpCode] = useState("")
  const [generatingToken, setGeneratingToken] = useState(false)
  const [tokenCopied, setTokenCopied] = useState(false)

  useEffect(() => {
    checkAuthStatus()
    loadProxmenuxTools()
  }, [])

  const checkAuthStatus = async () => {
    try {
      const response = await fetch(getApiUrl("/api/auth/status"))
      const data = await response.json()
      setAuthEnabled(data.auth_enabled || false)
      setTotpEnabled(data.totp_enabled || false) // Get 2FA status
    } catch (err) {
      console.error("Failed to check auth status:", err)
    }
  }

  const loadProxmenuxTools = async () => {
    try {
      const response = await fetch(getApiUrl("/api/proxmenux/installed-tools"))
      const data = await response.json()

      if (data.success) {
        setProxmenuxTools(data.installed_tools || [])
      }
    } catch (err) {
      console.error("Failed to load ProxMenux tools:", err)
    } finally {
      setLoadingTools(false)
    }
  }

  const handleEnableAuth = async () => {
    setError("")
    setSuccess("")

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
          enable_auth: true,
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || "Failed to enable authentication")
      }

      // Save token
      localStorage.setItem("proxmenux-auth-token", data.token)
      localStorage.setItem("proxmenux-auth-setup-complete", "true")

      setSuccess("Authentication enabled successfully!")
      setAuthEnabled(true)
      setShowSetupForm(false)
      setUsername("")
      setPassword("")
      setConfirmPassword("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to enable authentication")
    } finally {
      setLoading(false)
    }
  }

  const handleDisableAuth = async () => {
    if (
      !confirm(
        "Are you sure you want to disable authentication? This will remove password protection from your dashboard.",
      )
    ) {
      return
    }

    setLoading(true)
    setError("")
    setSuccess("")

    try {
      const token = localStorage.getItem("proxmenux-auth-token")
      const response = await fetch(getApiUrl("/api/auth/disable"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.message || "Failed to disable authentication")
      }

      localStorage.removeItem("proxmenux-auth-token")
      localStorage.removeItem("proxmenux-auth-setup-complete")

      setSuccess("Authentication disabled successfully! Reloading...")

      setTimeout(() => {
        window.location.reload()
      }, 1000)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disable authentication. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  const handleChangePassword = async () => {
    setError("")
    setSuccess("")

    if (!currentPassword || !newPassword) {
      setError("Please fill in all fields")
      return
    }

    if (newPassword !== confirmNewPassword) {
      setError("New passwords do not match")
      return
    }

    if (newPassword.length < 6) {
      setError("Password must be at least 6 characters")
      return
    }

    setLoading(true)

    try {
      const response = await fetch(getApiUrl("/api/auth/change-password"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("proxmenux-auth-token")}`,
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || "Failed to change password")
      }

      // Update token if provided
      if (data.token) {
        localStorage.setItem("proxmenux-auth-token", data.token)
      }

      setSuccess("Password changed successfully!")
      setShowChangePassword(false)
      setCurrentPassword("")
      setNewPassword("")
      setConfirmNewPassword("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change password")
    } finally {
      setLoading(false)
    }
  }

  const handleDisable2FA = async () => {
    setError("")
    setSuccess("")

    if (!disable2FAPassword) {
      setError("Please enter your password")
      return
    }

    setLoading(true)

    try {
      const token = localStorage.getItem("proxmenux-auth-token")
      const response = await fetch(getApiUrl("/api/auth/totp/disable"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ password: disable2FAPassword }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.message || "Failed to disable 2FA")
      }

      setSuccess("2FA disabled successfully!")
      setTotpEnabled(false)
      setShow2FADisable(false)
      setDisable2FAPassword("")
      checkAuthStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disable 2FA")
    } finally {
      setLoading(false)
    }
  }

  const handleLogout = () => {
    localStorage.removeItem("proxmenux-auth-token")
    localStorage.removeItem("proxmenux-auth-setup-complete")
    window.location.reload()
  }

  const handleGenerateApiToken = async () => {
    setError("")
    setSuccess("")

    if (!tokenPassword) {
      setError("Please enter your password")
      return
    }

    if (totpEnabled && !tokenTotpCode) {
      setError("Please enter your 2FA code")
      return
    }

    setGeneratingToken(true)

    try {
      console.log("[v0] Generating API token with password and 2FA:", { totpEnabled, hasTotpCode: !!tokenTotpCode })

      const response = await fetchApi("/api/auth/generate-api-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          password: tokenPassword,
          totp_token: totpEnabled ? tokenTotpCode : undefined,
        }),
      })

      console.log("[v0] Response status:", response.status, response.statusText)

      const data = await response.json()
      console.log("[v0] Parsed response data:", { success: data.success, hasToken: !!data.token })

      if (!response.ok) {
        throw new Error(data.message || data.error || "Failed to generate API token")
      }

      if (!data.success) {
        throw new Error(data.message || "Failed to generate API token")
      }

      if (!data.token) {
        throw new Error("No token received from server")
      }

      console.log("[v0] API token generated successfully")
      setApiToken(data.token)
      setSuccess("API token generated successfully! Make sure to copy it now as you won't be able to see it again.")
      setTokenPassword("")
      setTokenTotpCode("")
    } catch (err) {
      console.error("[v0] Token generation error:", err)
      setError(err instanceof Error ? err.message : "Failed to generate API token")
    } finally {
      setGeneratingToken(false)
    }
  }

  const copyApiToken = () => {
    navigator.clipboard.writeText(apiToken)
    setTokenCopied(true)
    setTimeout(() => setTokenCopied(false), 2000)
  }

  const toggleVersion = (version: string) => {
    setExpandedVersions((prev) => ({
      ...prev,
      [version]: !prev[version],
    }))
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground mt-2">Manage your dashboard security and preferences</p>
      </div>

      {/* Authentication Settings */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-blue-500" />
            <CardTitle>Authentication</CardTitle>
          </div>
          <CardDescription>Protect your dashboard with username and password authentication</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 flex items-start gap-2">
              <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-500">{error}</p>
            </div>
          )}

          {success && (
            <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-3 flex items-start gap-2">
              <CheckCircle className="h-5 w-5 text-green-500 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-green-500">{success}</p>
            </div>
          )}

          <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
            <div className="flex items-center gap-3">
              <div
                className={`w-10 h-10 rounded-full flex items-center justify-center ${authEnabled ? "bg-green-500/10" : "bg-gray-500/10"}`}
              >
                <Lock className={`h-5 w-5 ${authEnabled ? "text-green-500" : "text-gray-500"}`} />
              </div>
              <div>
                <p className="font-medium">Authentication Status</p>
                <p className="text-sm text-muted-foreground">
                  {authEnabled ? "Password protection is enabled" : "No password protection"}
                </p>
              </div>
            </div>
            <div
              className={`px-3 py-1 rounded-full text-sm font-medium ${authEnabled ? "bg-green-500/10 text-green-500" : "bg-gray-500/10 text-gray-500"}`}
            >
              {authEnabled ? "Enabled" : "Disabled"}
            </div>
          </div>

          {!authEnabled && !showSetupForm && (
            <div className="space-y-3">
              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-start gap-2">
                <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-blue-500">
                  Enable authentication to protect your dashboard when accessing from non-private networks.
                </p>
              </div>
              <Button onClick={() => setShowSetupForm(true)} className="w-full bg-blue-500 hover:bg-blue-600">
                <Shield className="h-4 w-4 mr-2" />
                Enable Authentication
              </Button>
            </div>
          )}

          {!authEnabled && showSetupForm && (
            <div className="space-y-4 border border-border rounded-lg p-4">
              <h3 className="font-semibold">Setup Authentication</h3>

              <div className="space-y-2">
                <Label htmlFor="setup-username">Username</Label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="setup-username"
                    type="text"
                    placeholder="Enter username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="pl-10"
                    disabled={loading}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="setup-password">Password</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="setup-password"
                    type="password"
                    placeholder="Enter password (min 6 characters)"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-10"
                    disabled={loading}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="setup-confirm-password">Confirm Password</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="setup-confirm-password"
                    type="password"
                    placeholder="Confirm password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="pl-10"
                    disabled={loading}
                  />
                </div>
              </div>

              <div className="flex gap-2">
                <Button onClick={handleEnableAuth} className="flex-1 bg-blue-500 hover:bg-blue-600" disabled={loading}>
                  {loading ? "Enabling..." : "Enable"}
                </Button>
                <Button onClick={() => setShowSetupForm(false)} variant="outline" className="flex-1" disabled={loading}>
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {authEnabled && (
            <div className="space-y-3">
              <Button onClick={handleLogout} variant="outline" className="w-full bg-transparent">
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </Button>

              {!showChangePassword && (
                <Button onClick={() => setShowChangePassword(true)} variant="outline" className="w-full">
                  <Lock className="h-4 w-4 mr-2" />
                  Change Password
                </Button>
              )}

              {showChangePassword && (
                <div className="space-y-4 border border-border rounded-lg p-4">
                  <h3 className="font-semibold">Change Password</h3>

                  <div className="space-y-2">
                    <Label htmlFor="current-password">Current Password</Label>
                    <div className="relative">
                      <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="current-password"
                        type="password"
                        placeholder="Enter current password"
                        value={currentPassword}
                        onChange={(e) => setCurrentPassword(e.target.value)}
                        className="pl-10"
                        disabled={loading}
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="new-password">New Password</Label>
                    <div className="relative">
                      <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="new-password"
                        type="password"
                        placeholder="Enter new password (min 6 characters)"
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        className="pl-10"
                        disabled={loading}
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="confirm-new-password">Confirm New Password</Label>
                    <div className="relative">
                      <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="confirm-new-password"
                        type="password"
                        placeholder="Confirm new password"
                        value={confirmNewPassword}
                        onChange={(e) => setConfirmNewPassword(e.target.value)}
                        className="pl-10"
                        disabled={loading}
                      />
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <Button
                      onClick={handleChangePassword}
                      className="flex-1 bg-blue-500 hover:bg-blue-600"
                      disabled={loading}
                    >
                      {loading ? "Changing..." : "Change Password"}
                    </Button>
                    <Button
                      onClick={() => setShowChangePassword(false)}
                      variant="outline"
                      className="flex-1"
                      disabled={loading}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}

              {!totpEnabled && (
                <div className="space-y-3">
                  <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-start gap-2">
                    <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                    <div className="text-sm text-blue-400">
                      <p className="font-medium mb-1">Two-Factor Authentication (2FA)</p>
                      <p className="text-blue-300">
                        Add an extra layer of security by requiring a code from your authenticator app in addition to
                        your password.
                      </p>
                    </div>
                  </div>

                  <Button onClick={() => setShow2FASetup(true)} variant="outline" className="w-full">
                    <Shield className="h-4 w-4 mr-2" />
                    Enable Two-Factor Authentication
                  </Button>
                </div>
              )}

              {totpEnabled && (
                <div className="space-y-3">
                  <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-3 flex items-center gap-2">
                    <CheckCircle className="h-5 w-5 text-green-500" />
                    <p className="text-sm text-green-500 font-medium">2FA is enabled</p>
                  </div>

                  {!show2FADisable && (
                    <Button onClick={() => setShow2FADisable(true)} variant="outline" className="w-full">
                      <Shield className="h-4 w-4 mr-2" />
                      Disable 2FA
                    </Button>
                  )}

                  {show2FADisable && (
                    <div className="space-y-4 border border-border rounded-lg p-4">
                      <h3 className="font-semibold">Disable Two-Factor Authentication</h3>
                      <p className="text-sm text-muted-foreground">Enter your password to confirm</p>

                      <div className="space-y-2">
                        <Label htmlFor="disable-2fa-password">Password</Label>
                        <div className="relative">
                          <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                          <Input
                            id="disable-2fa-password"
                            type="password"
                            placeholder="Enter your password"
                            value={disable2FAPassword}
                            onChange={(e) => setDisable2FAPassword(e.target.value)}
                            className="pl-10"
                            disabled={loading}
                          />
                        </div>
                      </div>

                      <div className="flex gap-2">
                        <Button onClick={handleDisable2FA} variant="destructive" className="flex-1" disabled={loading}>
                          {loading ? "Disabling..." : "Disable 2FA"}
                        </Button>
                        <Button
                          onClick={() => {
                            setShow2FADisable(false)
                            setDisable2FAPassword("")
                            setError("")
                          }}
                          variant="outline"
                          className="flex-1"
                          disabled={loading}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              <Button onClick={handleDisableAuth} variant="destructive" className="w-full" disabled={loading}>
                Disable Authentication
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* API Access Tokens */}
      {authEnabled && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Key className="h-5 w-5 text-purple-500" />
              <CardTitle>API Access Tokens</CardTitle>
            </div>
            <CardDescription>
              Generate long-lived API tokens for external integrations like Homepage and Home Assistant
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {error && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 flex items-start gap-2">
                <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-red-500">{error}</p>
              </div>
            )}

            {success && (
              <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-3 flex items-start gap-2">
                <CheckCircle className="h-5 w-5 text-green-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-green-500">{success}</p>
              </div>
            )}

            <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
              <div className="flex items-start gap-3">
                <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                <div className="space-y-2 text-sm text-blue-400">
                  <p className="font-medium">About API Tokens</p>
                  <ul className="list-disc list-inside space-y-1 text-blue-300">
                    <li>Tokens are valid for 1 year</li>
                    <li>Use them to access APIs from external services</li>
                    <li>Include in Authorization header: Bearer YOUR_TOKEN</li>
                    <li>See README.md for complete integration examples</li>
                  </ul>
                </div>
              </div>
            </div>

            {!showApiTokenSection && !apiToken && (
              <Button onClick={() => setShowApiTokenSection(true)} className="w-full bg-purple-500 hover:bg-purple-600">
                <Key className="h-4 w-4 mr-2" />
                Generate New API Token
              </Button>
            )}

            {showApiTokenSection && !apiToken && (
              <div className="space-y-4 border border-border rounded-lg p-4">
                <h3 className="font-semibold">Generate API Token</h3>
                <p className="text-sm text-muted-foreground">
                  Enter your credentials to generate a new long-lived API token
                </p>

                <div className="space-y-2">
                  <Label htmlFor="token-password">Password</Label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="token-password"
                      type="password"
                      placeholder="Enter your password"
                      value={tokenPassword}
                      onChange={(e) => setTokenPassword(e.target.value)}
                      className="pl-10"
                      disabled={generatingToken}
                    />
                  </div>
                </div>

                {totpEnabled && (
                  <div className="space-y-2">
                    <Label htmlFor="token-totp">2FA Code</Label>
                    <div className="relative">
                      <Shield className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="token-totp"
                        type="text"
                        placeholder="Enter 6-digit code"
                        value={tokenTotpCode}
                        onChange={(e) => setTokenTotpCode(e.target.value)}
                        className="pl-10"
                        maxLength={6}
                        disabled={generatingToken}
                      />
                    </div>
                  </div>
                )}

                <div className="flex gap-2">
                  <Button
                    onClick={handleGenerateApiToken}
                    className="flex-1 bg-purple-500 hover:bg-purple-600"
                    disabled={generatingToken}
                  >
                    {generatingToken ? "Generating..." : "Generate Token"}
                  </Button>
                  <Button
                    onClick={() => {
                      setShowApiTokenSection(false)
                      setTokenPassword("")
                      setTokenTotpCode("")
                      setError("")
                    }}
                    variant="outline"
                    className="flex-1"
                    disabled={generatingToken}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}

            {apiToken && (
              <div className="space-y-4 border border-green-500/20 bg-green-500/5 rounded-lg p-4">
                <div className="flex items-center gap-2 text-green-500">
                  <CheckCircle className="h-5 w-5" />
                  <h3 className="font-semibold">Your API Token</h3>
                </div>

                <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 flex items-start gap-2">
                  <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-red-500 font-medium">
                    Save this token now! You won't be able to see it again.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label>Token</Label>
                  <div className="relative">
                    <Input
                      value={apiToken}
                      readOnly
                      type={apiTokenVisible ? "text" : "password"}
                      className="pr-20 font-mono text-sm"
                    />
                    <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setApiTokenVisible(!apiTokenVisible)}
                        className="h-7 w-7 p-0"
                      >
                        {apiTokenVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={copyApiToken} className="h-7 w-7 p-0">
                        <Copy className={`h-4 w-4 ${tokenCopied ? "text-green-500" : ""}`} />
                      </Button>
                    </div>
                  </div>
                  {tokenCopied && (
                    <p className="text-xs text-green-500 flex items-center gap-1">
                      <CheckCircle className="h-3 w-3" />
                      Copied to clipboard!
                    </p>
                  )}
                </div>

                <div className="space-y-2">
                  <p className="text-sm font-medium">How to use this token:</p>
                  <div className="bg-muted/50 rounded p-3 text-xs font-mono">
                    <p className="text-muted-foreground mb-2"># Add to request headers:</p>
                    <p>Authorization: Bearer YOUR_TOKEN_HERE</p>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    See the README documentation for complete integration examples with Homepage and Home Assistant.
                  </p>
                </div>

                <Button
                  onClick={() => {
                    setApiToken("")
                    setShowApiTokenSection(false)
                  }}
                  variant="outline"
                  className="w-full"
                >
                  Done
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ProxMenux Optimizations */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Wrench className="h-5 w-5 text-orange-500" />
            <CardTitle>ProxMenux Optimizations</CardTitle>
          </div>
          <CardDescription>System optimizations and utilities installed via ProxMenux</CardDescription>
        </CardHeader>
        <CardContent>
          {loadingTools ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin h-8 w-8 border-4 border-orange-500 border-t-transparent rounded-full" />
            </div>
          ) : proxmenuxTools.length === 0 ? (
            <div className="text-center py-8">
              <Package className="h-12 w-12 text-muted-foreground mx-auto mb-3 opacity-50" />
              <p className="text-muted-foreground">No ProxMenux optimizations installed yet</p>
              <p className="text-sm text-muted-foreground mt-1">Run ProxMenux to configure system optimizations</p>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between mb-4 pb-2 border-b border-border">
                <span className="text-sm font-medium text-muted-foreground">Installed Tools</span>
                <span className="text-sm font-semibold text-orange-500">{proxmenuxTools.length} active</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {proxmenuxTools.map((tool) => (
                  <div
                    key={tool.key}
                    className="flex items-center gap-2 p-3 bg-muted/50 rounded-lg border border-border hover:bg-muted transition-colors"
                  >
                    <div className="w-2 h-2 rounded-full bg-green-500 flex-shrink-0" />
                    <span className="text-sm font-medium">{tool.name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <TwoFactorSetup
        open={show2FASetup}
        onClose={() => setShow2FASetup(false)}
        onSuccess={() => {
          setSuccess("2FA enabled successfully!")
          checkAuthStatus()
        }}
      />
    </div>
  )
}
