"use client"

import { useState, useEffect } from "react"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import {
  Shield, Lock, User, AlertCircle, CheckCircle, Info, LogOut, Key, Copy, Eye, EyeOff,
  Trash2, RefreshCw, Clock, ShieldCheck, Globe, FileKey, AlertTriangle,
  Flame, Bug, Search, Download, Power, PowerOff, Plus, Minus, Activity,
} from "lucide-react"
import { getApiUrl, fetchApi } from "../lib/api-config"
import { TwoFactorSetup } from "./two-factor-setup"
import { ScriptTerminalModal } from "./script-terminal-modal"

interface ApiTokenEntry {
  id: string
  name: string
  token_prefix: string
  created_at: string
  expires_at: string
  revoked: boolean
}

export function Security() {
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

  // API Token state management
  const [showApiTokenSection, setShowApiTokenSection] = useState(false)
  const [apiToken, setApiToken] = useState("")
  const [apiTokenVisible, setApiTokenVisible] = useState(false)
  const [tokenPassword, setTokenPassword] = useState("")
  const [tokenTotpCode, setTokenTotpCode] = useState("")
  const [generatingToken, setGeneratingToken] = useState(false)
  const [tokenCopied, setTokenCopied] = useState(false)

  // Token list state
  const [existingTokens, setExistingTokens] = useState<ApiTokenEntry[]>([])
  const [loadingTokens, setLoadingTokens] = useState(false)
  const [revokingTokenId, setRevokingTokenId] = useState<string | null>(null)
  const [tokenName, setTokenName] = useState("API Token")

  // Proxmox Firewall state
  const [firewallLoading, setFirewallLoading] = useState(true)
  const [firewallData, setFirewallData] = useState<{
    pve_firewall_installed: boolean
    pve_firewall_active: boolean
    cluster_fw_enabled: boolean
    host_fw_enabled: boolean
    rules_count: number
    rules: Array<{ raw: string; direction?: string; action?: string; dport?: string; p?: string; source_file?: string; section?: string }>
    monitor_port_open: boolean
  } | null>(null)
  const [firewallAction, setFirewallAction] = useState(false)

  // Security Tools state
  const [toolsLoading, setToolsLoading] = useState(true)
  const [fail2banInfo, setFail2banInfo] = useState<{
    installed: boolean; active: boolean; version: string; jails: string[]; banned_ips_count: number
  } | null>(null)
  const [lynisInfo, setLynisInfo] = useState<{
    installed: boolean; version: string; last_scan: string | null; hardening_index: number | null
  } | null>(null)
  const [showFail2banInstaller, setShowFail2banInstaller] = useState(false)
  const [showLynisInstaller, setShowLynisInstaller] = useState(false)

  // Fail2Ban detailed state
  interface JailDetail {
    name: string
    currently_failed: number
    total_failed: number
    currently_banned: number
    total_banned: number
    banned_ips: string[]
    findtime: string
    bantime: string
    maxretry: string
  }
  interface F2bEvent {
    timestamp: string
    jail: string
    ip: string
    action: "ban" | "unban" | "found"
  }
  const [f2bDetails, setF2bDetails] = useState<{
    installed: boolean; active: boolean; version: string; jails: JailDetail[]
  } | null>(null)
  const [f2bActivity, setF2bActivity] = useState<F2bEvent[]>([])
  const [f2bDetailsLoading, setF2bDetailsLoading] = useState(false)
  const [f2bUnbanning, setF2bUnbanning] = useState<string | null>(null)
  const [f2bActiveTab, setF2bActiveTab] = useState<"jails" | "activity">("jails")

  // SSL/HTTPS state
  const [sslEnabled, setSslEnabled] = useState(false)
  const [sslSource, setSslSource] = useState<"none" | "proxmox" | "custom">("none")
  const [sslCertPath, setSslCertPath] = useState("")
  const [sslKeyPath, setSslKeyPath] = useState("")
  const [proxmoxCertAvailable, setProxmoxCertAvailable] = useState(false)
  const [proxmoxCertInfo, setProxmoxCertInfo] = useState<{subject?: string; expires?: string; issuer?: string; is_self_signed?: boolean} | null>(null)
  const [loadingSsl, setLoadingSsl] = useState(true)
  const [configuringSsl, setConfiguringSsl] = useState(false)
  const [showCustomCertForm, setShowCustomCertForm] = useState(false)
  const [customCertPath, setCustomCertPath] = useState("")
  const [customKeyPath, setCustomKeyPath] = useState("")

  useEffect(() => {
    checkAuthStatus()
    loadApiTokens()
    loadSslStatus()
    loadFirewallStatus()
    loadSecurityTools()
  }, [])

  const loadFirewallStatus = async () => {
    try {
      setFirewallLoading(true)
      const data = await fetchApi("/api/security/firewall/status")
      if (data.success) {
        setFirewallData({
          pve_firewall_installed: data.pve_firewall_installed,
          pve_firewall_active: data.pve_firewall_active,
          cluster_fw_enabled: data.cluster_fw_enabled,
          host_fw_enabled: data.host_fw_enabled,
          rules_count: data.rules_count,
          rules: data.rules || [],
          monitor_port_open: data.monitor_port_open,
        })
      }
    } catch {
      // Silently fail
    } finally {
      setFirewallLoading(false)
    }
  }

  const loadSecurityTools = async () => {
    try {
      setToolsLoading(true)
      const data = await fetchApi("/api/security/tools")
      if (data.success && data.tools) {
        setFail2banInfo(data.tools.fail2ban || null)
        setLynisInfo(data.tools.lynis || null)
      }
    } catch {
      // Silently fail
    } finally {
      setToolsLoading(false)
    }
  }

  const loadFail2banDetails = async () => {
    try {
      setF2bDetailsLoading(true)
      const [detailsRes, activityRes] = await Promise.all([
        fetchApi("/api/security/fail2ban/details"),
        fetchApi("/api/security/fail2ban/activity"),
      ])
      if (detailsRes.success) {
        setF2bDetails({
          installed: detailsRes.installed,
          active: detailsRes.active,
          version: detailsRes.version,
          jails: detailsRes.jails || [],
        })
      }
      if (activityRes.success) {
        setF2bActivity(activityRes.events || [])
      }
    } catch {
      // Silently fail
    } finally {
      setF2bDetailsLoading(false)
    }
  }

  const handleUnbanIp = async (jail: string, ip: string) => {
    const key = `${jail}:${ip}`
    setF2bUnbanning(key)
    setError("")
    setSuccess("")
    try {
      const data = await fetchApi("/api/security/fail2ban/unban", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jail, ip }),
      })
      if (data.success) {
        setSuccess(data.message || `IP ${ip} unbanned from ${jail}`)
        loadFail2banDetails()
        loadSecurityTools()
      } else {
        setError(data.message || "Failed to unban IP")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to unban IP")
    } finally {
      setF2bUnbanning(null)
    }
  }

  // Load fail2ban details when basic info shows it's installed and active
  useEffect(() => {
    if (fail2banInfo?.installed && fail2banInfo?.active) {
      loadFail2banDetails()
    }
  }, [fail2banInfo?.installed, fail2banInfo?.active])

  const formatBanTime = (seconds: string) => {
    const s = parseInt(seconds, 10)
    if (isNaN(s) || s <= 0) return seconds
    if (s < 60) return `${s}s`
    if (s < 3600) return `${Math.floor(s / 60)}m`
    if (s < 86400) return `${Math.floor(s / 3600)}h`
    return `${Math.floor(s / 86400)}d`
  }

  const handleFirewallToggle = async (level: "host" | "cluster", enable: boolean) => {
    setFirewallAction(true)
    setError("")
    setSuccess("")
    try {
      const endpoint = enable ? "/api/security/firewall/enable" : "/api/security/firewall/disable"
      const data = await fetchApi(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ level }),
      })
      if (data.success) {
        setSuccess(data.message || `Firewall ${enable ? "enabled" : "disabled"} at ${level} level`)
        loadFirewallStatus()
      } else {
        setError(data.message || "Failed to update firewall")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update firewall")
    } finally {
      setFirewallAction(false)
    }
  }

  const handleMonitorPortToggle = async (add: boolean) => {
    setFirewallAction(true)
    setError("")
    setSuccess("")
    try {
      const data = await fetchApi("/api/security/firewall/monitor-port", {
        method: add ? "POST" : "DELETE",
      })
      if (data.success) {
        setSuccess(data.message || `Monitor port rule ${add ? "added" : "removed"}`)
        loadFirewallStatus()
      } else {
        setError(data.message || "Failed to update monitor port rule")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update monitor port rule")
    } finally {
      setFirewallAction(false)
    }
  }

  const checkAuthStatus = async () => {
    try {
      const response = await fetch(getApiUrl("/api/auth/status"))
      const data = await response.json()
      setAuthEnabled(data.auth_enabled || false)
      setTotpEnabled(data.totp_enabled || false)
    } catch (err) {
      console.error("Failed to check auth status:", err)
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

  const loadApiTokens = async () => {
    try {
      setLoadingTokens(true)
      const data = await fetchApi("/api/auth/api-tokens")
      if (data.success) {
        setExistingTokens(data.tokens || [])
      }
    } catch {
      // Silently fail - tokens section is optional
    } finally {
      setLoadingTokens(false)
    }
  }

  const handleRevokeToken = async (tokenId: string) => {
    if (!confirm("Are you sure you want to revoke this token? Any integration using it will stop working immediately.")) {
      return
    }

    setRevokingTokenId(tokenId)
    setError("")
    setSuccess("")

    try {
      const data = await fetchApi(`/api/auth/api-tokens/${tokenId}`, {
        method: "DELETE",
      })

      if (data.success) {
        setSuccess("Token revoked successfully")
        setExistingTokens((prev) => prev.filter((t) => t.id !== tokenId))
      } else {
        setError(data.message || "Failed to revoke token")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revoke token")
    } finally {
      setRevokingTokenId(null)
    }
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
      const data = await fetchApi("/api/auth/generate-api-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          password: tokenPassword,
          totp_token: totpEnabled ? tokenTotpCode : undefined,
          token_name: tokenName || "API Token",
        }),
      })

      if (!data.success) {
        setError(data.message || data.error || "Failed to generate API token")
        return
      }

      if (!data.token) {
        setError("No token received from server")
        return
      }

      setApiToken(data.token)
      setSuccess("API token generated successfully! Make sure to copy it now as you won't be able to see it again.")
      setTokenPassword("")
      setTokenTotpCode("")
      setTokenName("API Token")
      loadApiTokens()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate API token. Please try again.")
    } finally {
      setGeneratingToken(false)
    }
  }

  const copyToClipboard = async (text: string) => {
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        await navigator.clipboard.writeText(text)
      } else {
        const textarea = document.createElement("textarea")
        textarea.value = text
        textarea.style.position = "fixed"
        textarea.style.left = "-9999px"
        textarea.style.top = "-9999px"
        textarea.style.opacity = "0"
        document.body.appendChild(textarea)
        textarea.focus()
        textarea.select()
        document.execCommand("copy")
        document.body.removeChild(textarea)
      }
      return true
    } catch {
      return false
    }
  }

  const copyApiToken = async () => {
    const ok = await copyToClipboard(apiToken)
    if (ok) {
      setTokenCopied(true)
      setTimeout(() => setTokenCopied(false), 2000)
    }
  }

  const loadSslStatus = async () => {
    try {
      setLoadingSsl(true)
      const data = await fetchApi("/api/ssl/status")
      if (data.success) {
        setSslEnabled(data.ssl_enabled || false)
        setSslSource(data.source || "none")
        setSslCertPath(data.cert_path || "")
        setSslKeyPath(data.key_path || "")
        setProxmoxCertAvailable(data.proxmox_available || false)
        setProxmoxCertInfo(data.cert_info || null)
      }
    } catch {
      // Silently fail
    } finally {
      setLoadingSsl(false)
    }
  }

  const handleEnableSsl = async (source: "proxmox" | "custom", certPath?: string, keyPath?: string) => {
    setConfiguringSsl(true)
    setError("")
    setSuccess("")

    try {
      const body: Record<string, string> = { source }
      if (source === "custom" && certPath && keyPath) {
        body.cert_path = certPath
        body.key_path = keyPath
      }

      const data = await fetchApi("/api/ssl/configure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })

      if (data.success) {
        setSuccess(data.message || "SSL configured successfully. Restart the monitor service to apply.")
        setSslEnabled(true)
        setSslSource(source)
        setShowCustomCertForm(false)
        setCustomCertPath("")
        setCustomKeyPath("")
        loadSslStatus()
      } else {
        setError(data.message || "Failed to configure SSL")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to configure SSL")
    } finally {
      setConfiguringSsl(false)
    }
  }

  const handleDisableSsl = async () => {
    if (!confirm("Are you sure you want to disable HTTPS? The monitor will revert to HTTP after restart.")) {
      return
    }

    setConfiguringSsl(true)
    setError("")
    setSuccess("")

    try {
      const data = await fetchApi("/api/ssl/disable", { method: "POST" })

      if (data.success) {
        setSuccess(data.message || "SSL disabled. Restart the monitor service to apply.")
        setSslEnabled(false)
        setSslSource("none")
        setSslCertPath("")
        setSslKeyPath("")
        loadSslStatus()
      } else {
        setError(data.message || "Failed to disable SSL")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disable SSL")
    } finally {
      setConfiguringSsl(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Security</h1>
        <p className="text-muted-foreground mt-2">Manage authentication, encryption, and access control</p>
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

      {/* SSL/HTTPS Configuration */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-green-500" />
            <CardTitle>SSL / HTTPS</CardTitle>
          </div>
          <CardDescription>
            Serve ProxMenux Monitor over HTTPS using your Proxmox host certificate or a custom certificate
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {loadingSsl ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin h-8 w-8 border-4 border-green-500 border-t-transparent rounded-full" />
            </div>
          ) : (
            <>
              {/* Current Status */}
              <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center ${sslEnabled ? "bg-green-500/10" : "bg-gray-500/10"}`}>
                    <Globe className={`h-5 w-5 ${sslEnabled ? "text-green-500" : "text-gray-500"}`} />
                  </div>
                  <div>
                    <p className="font-medium">
                      {sslEnabled ? "HTTPS Enabled" : "HTTP (No SSL)"}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {sslEnabled
                        ? `Using ${sslSource === "proxmox" ? "Proxmox host" : "custom"} certificate`
                        : "Monitor is served over unencrypted HTTP"}
                    </p>
                  </div>
                </div>
                <div className={`px-3 py-1 rounded-full text-sm font-medium ${sslEnabled ? "bg-green-500/10 text-green-500" : "bg-gray-500/10 text-gray-500"}`}>
                  {sslEnabled ? "HTTPS" : "HTTP"}
                </div>
              </div>

              {/* Active certificate info */}
              {sslEnabled && (
                <div className="space-y-2 p-3 bg-green-500/5 border border-green-500/20 rounded-lg">
                  <div className="flex items-center gap-2 text-sm font-medium text-green-500">
                    <FileKey className="h-4 w-4" />
                    Active Certificate
                  </div>
                  <div className="grid gap-1 text-sm text-muted-foreground">
                    <p><span className="font-medium text-foreground">Cert:</span> <code className="text-xs">{sslCertPath}</code></p>
                    <p><span className="font-medium text-foreground">Key:</span> <code className="text-xs">{sslKeyPath}</code></p>
                  </div>
                  <Button
                    onClick={handleDisableSsl}
                    variant="outline"
                    size="sm"
                    disabled={configuringSsl}
                    className="mt-2 text-red-500 border-red-500/30 hover:bg-red-500/10 bg-transparent"
                  >
                    {configuringSsl ? "Disabling..." : "Disable HTTPS"}
                  </Button>
                </div>
              )}

              {/* Proxmox certificate detection */}
              {!sslEnabled && proxmoxCertAvailable && (
                <div className="space-y-3 p-4 border border-border rounded-lg">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-green-500" />
                    <h3 className="font-semibold text-sm">Proxmox Host Certificate Detected</h3>
                  </div>

                  {proxmoxCertInfo && (
                    <div className="grid gap-1 text-sm text-muted-foreground bg-muted/50 p-3 rounded">
                      {proxmoxCertInfo.subject && (
                        <p><span className="font-medium text-foreground">Subject:</span> {proxmoxCertInfo.subject}</p>
                      )}
                      {proxmoxCertInfo.issuer && (
                        <p><span className="font-medium text-foreground">Issuer:</span> {proxmoxCertInfo.issuer}</p>
                      )}
                      {proxmoxCertInfo.expires && (
                        <p><span className="font-medium text-foreground">Expires:</span> {proxmoxCertInfo.expires}</p>
                      )}
                      {proxmoxCertInfo.is_self_signed && (
                        <div className="flex items-center gap-1.5 mt-1 text-yellow-500">
                          <AlertTriangle className="h-3.5 w-3.5" />
                          <span className="text-xs">Self-signed certificate (browsers will show a security warning)</span>
                        </div>
                      )}
                    </div>
                  )}

                  <Button
                    onClick={() => handleEnableSsl("proxmox")}
                    className="w-full bg-green-600 hover:bg-green-700 text-white"
                    disabled={configuringSsl}
                  >
                    {configuringSsl ? (
                      <div className="flex items-center gap-2">
                        <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                        Configuring...
                      </div>
                    ) : (
                      <>
                        <ShieldCheck className="h-4 w-4 mr-2" />
                        Use Proxmox Certificate
                      </>
                    )}
                  </Button>
                </div>
              )}

              {!sslEnabled && !proxmoxCertAvailable && (
                <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3 flex items-start gap-2">
                  <AlertTriangle className="h-5 w-5 text-yellow-500 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-yellow-500">
                    No Proxmox host certificate detected. You can configure a custom certificate below.
                  </p>
                </div>
              )}

              {/* Custom certificate option */}
              {!sslEnabled && (
                <div className="space-y-3">
                  {!showCustomCertForm ? (
                    <Button
                      onClick={() => setShowCustomCertForm(true)}
                      variant="outline"
                      className="w-full"
                    >
                      <FileKey className="h-4 w-4 mr-2" />
                      Use Custom Certificate
                    </Button>
                  ) : (
                    <div className="space-y-4 border border-border rounded-lg p-4">
                      <h3 className="font-semibold text-sm">Custom Certificate Paths</h3>
                      <p className="text-xs text-muted-foreground">
                        Enter the absolute paths to your SSL certificate and private key files on the Proxmox server.
                      </p>

                      <div className="space-y-2">
                        <Label htmlFor="ssl-cert-path">Certificate Path (.pem / .crt)</Label>
                        <Input
                          id="ssl-cert-path"
                          type="text"
                          placeholder="/etc/ssl/certs/mydomain.pem"
                          value={customCertPath}
                          onChange={(e) => setCustomCertPath(e.target.value)}
                          disabled={configuringSsl}
                        />
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="ssl-key-path">Private Key Path (.key / .pem)</Label>
                        <Input
                          id="ssl-key-path"
                          type="text"
                          placeholder="/etc/ssl/private/mydomain.key"
                          value={customKeyPath}
                          onChange={(e) => setCustomKeyPath(e.target.value)}
                          disabled={configuringSsl}
                        />
                      </div>

                      <div className="flex gap-2">
                        <Button
                          onClick={() => handleEnableSsl("custom", customCertPath, customKeyPath)}
                          className="flex-1 bg-green-600 hover:bg-green-700 text-white"
                          disabled={configuringSsl || !customCertPath || !customKeyPath}
                        >
                          {configuringSsl ? "Configuring..." : "Enable HTTPS"}
                        </Button>
                        <Button
                          onClick={() => {
                            setShowCustomCertForm(false)
                            setCustomCertPath("")
                            setCustomKeyPath("")
                          }}
                          variant="outline"
                          className="flex-1"
                          disabled={configuringSsl}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Info note about restart */}
              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-start gap-2">
                <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-blue-500">
                  Changes to SSL configuration require a monitor service restart to take effect.
                  The service will automatically use HTTPS on port 8008 when enabled.
                </p>
              </div>
            </>
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
                    <li>{'Include in Authorization header: Bearer YOUR_TOKEN'}</li>
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
                  <Label htmlFor="token-name">Token Name</Label>
                  <div className="relative">
                    <Key className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="token-name"
                      type="text"
                      placeholder="e.g. Homepage, Home Assistant"
                      value={tokenName}
                      onChange={(e) => setTokenName(e.target.value)}
                      className="pl-10"
                      disabled={generatingToken}
                    />
                  </div>
                </div>

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
                      setTokenName("API Token")
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

                <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 flex items-start gap-2">
                  <AlertCircle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <p className="text-sm text-amber-600 dark:text-amber-400 font-semibold">
                      Important: Save this token now!
                    </p>
                    <p className="text-xs text-amber-600/80 dark:text-amber-400/80">
                      {"You won't be able to see it again. Store it securely."}
                    </p>
                  </div>
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
                    <p>{'Authorization: Bearer YOUR_TOKEN_HERE'}</p>
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

            {/* Existing Tokens List */}
            {!loadingTokens && existingTokens.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-muted-foreground">Active Tokens</h3>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={loadApiTokens}
                    className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                  >
                    <RefreshCw className="h-3 w-3 mr-1" />
                    Refresh
                  </Button>
                </div>

                <div className="space-y-2">
                  {existingTokens.map((token) => (
                    <div
                      key={token.id}
                      className="flex items-center justify-between p-3 bg-muted/50 rounded-lg border border-border"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-full bg-blue-500/10 flex items-center justify-center flex-shrink-0">
                          <Key className="h-4 w-4 text-blue-500" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium truncate">{token.name}</p>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <code className="font-mono">{token.token_prefix}</code>
                            <span className="flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              {token.created_at
                                ? new Date(token.created_at).toLocaleDateString()
                                : "Unknown"}
                            </span>
                          </div>
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRevokeToken(token.id)}
                        disabled={revokingTokenId === token.id}
                        className="h-8 px-2 text-red-500 hover:text-red-400 hover:bg-red-500/10 flex-shrink-0"
                      >
                        {revokingTokenId === token.id ? (
                          <div className="animate-spin h-4 w-4 border-2 border-red-500 border-t-transparent rounded-full" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                        <span className="ml-1 text-xs hidden sm:inline">Revoke</span>
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {loadingTokens && (
              <div className="flex items-center justify-center py-4">
                <div className="animate-spin h-5 w-5 border-2 border-blue-500 border-t-transparent rounded-full" />
                <span className="ml-2 text-sm text-muted-foreground">Loading tokens...</span>
              </div>
            )}

            {!loadingTokens && existingTokens.length === 0 && !showApiTokenSection && !apiToken && (
              <div className="text-center py-4 text-sm text-muted-foreground">
                No API tokens created yet
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Proxmox Firewall */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Flame className="h-5 w-5 text-orange-500" />
            <CardTitle>Proxmox Firewall</CardTitle>
          </div>
          <CardDescription>
            Manage the Proxmox VE built-in firewall at cluster and host level
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {firewallLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin h-8 w-8 border-4 border-orange-500 border-t-transparent rounded-full" />
            </div>
          ) : !firewallData?.pve_firewall_installed ? (
            <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4 flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-yellow-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-yellow-500">Proxmox Firewall Not Detected</p>
                <p className="text-sm text-muted-foreground mt-1">
                  The pve-firewall service was not found on this system. It should be included with Proxmox VE by default.
                </p>
              </div>
            </div>
          ) : (
            <>
              {/* Firewall Status Overview */}
              <div className="grid gap-3 sm:grid-cols-2">
                {/* Cluster Firewall */}
                <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg border border-border">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center ${firewallData.cluster_fw_enabled ? "bg-green-500/10" : "bg-gray-500/10"}`}>
                      <Globe className={`h-5 w-5 ${firewallData.cluster_fw_enabled ? "text-green-500" : "text-gray-500"}`} />
                    </div>
                    <div>
                      <p className="font-medium text-sm">Cluster Firewall</p>
                      <p className="text-xs text-muted-foreground">
                        {firewallData.cluster_fw_enabled ? "Active" : "Disabled"}
                      </p>
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={firewallAction}
                    onClick={() => handleFirewallToggle("cluster", !firewallData.cluster_fw_enabled)}
                    className={firewallData.cluster_fw_enabled
                      ? "text-red-500 border-red-500/30 hover:bg-red-500/10 bg-transparent"
                      : "text-green-500 border-green-500/30 hover:bg-green-500/10 bg-transparent"
                    }
                  >
                    {firewallData.cluster_fw_enabled ? (
                      <><PowerOff className="h-3.5 w-3.5 mr-1" /> Disable</>
                    ) : (
                      <><Power className="h-3.5 w-3.5 mr-1" /> Enable</>
                    )}
                  </Button>
                </div>

                {/* Host Firewall */}
                <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg border border-border">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center ${firewallData.host_fw_enabled ? "bg-green-500/10" : "bg-gray-500/10"}`}>
                      <Shield className={`h-5 w-5 ${firewallData.host_fw_enabled ? "text-green-500" : "text-gray-500"}`} />
                    </div>
                    <div>
                      <p className="font-medium text-sm">Host Firewall</p>
                      <p className="text-xs text-muted-foreground">
                        {firewallData.host_fw_enabled ? "Active" : "Disabled"}
                      </p>
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={firewallAction}
                    onClick={() => handleFirewallToggle("host", !firewallData.host_fw_enabled)}
                    className={firewallData.host_fw_enabled
                      ? "text-red-500 border-red-500/30 hover:bg-red-500/10 bg-transparent"
                      : "text-green-500 border-green-500/30 hover:bg-green-500/10 bg-transparent"
                    }
                  >
                    {firewallData.host_fw_enabled ? (
                      <><PowerOff className="h-3.5 w-3.5 mr-1" /> Disable</>
                    ) : (
                      <><Power className="h-3.5 w-3.5 mr-1" /> Enable</>
                    )}
                  </Button>
                </div>
              </div>

              {/* ProxMenux Monitor Port 8008 */}
              <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg border border-border">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center ${firewallData.monitor_port_open ? "bg-green-500/10" : "bg-yellow-500/10"}`}>
                    <Activity className={`h-5 w-5 ${firewallData.monitor_port_open ? "text-green-500" : "text-yellow-500"}`} />
                  </div>
                  <div>
                    <p className="font-medium text-sm">ProxMenux Monitor Port (8008/TCP)</p>
                    <p className="text-xs text-muted-foreground">
                      {firewallData.monitor_port_open
                        ? "Port 8008 is allowed in the firewall"
                        : "Port 8008 is not configured in the firewall"}
                    </p>
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={firewallAction}
                  onClick={() => handleMonitorPortToggle(!firewallData.monitor_port_open)}
                  className={firewallData.monitor_port_open
                    ? "text-red-500 border-red-500/30 hover:bg-red-500/10 bg-transparent"
                    : "text-green-500 border-green-500/30 hover:bg-green-500/10 bg-transparent"
                  }
                >
                  {firewallData.monitor_port_open ? (
                    <><Minus className="h-3.5 w-3.5 mr-1" /> Remove Rule</>
                  ) : (
                    <><Plus className="h-3.5 w-3.5 mr-1" /> Add Rule</>
                  )}
                </Button>
              </div>

              {!firewallData.monitor_port_open && (firewallData.cluster_fw_enabled || firewallData.host_fw_enabled) && (
                <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3 flex items-start gap-2">
                  <AlertTriangle className="h-5 w-5 text-yellow-500 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-yellow-500">
                    The firewall is active but port 8008 is not allowed. ProxMenux Monitor may be inaccessible from other devices. Add the rule above to fix this.
                  </p>
                </div>
              )}

              {/* Active Rules */}
              {firewallData.rules.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-muted-foreground">
                      Active Rules ({firewallData.rules_count})
                    </h3>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={loadFirewallStatus}
                      className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                    >
                      <RefreshCw className="h-3 w-3 mr-1" />
                      Refresh
                    </Button>
                  </div>
                  <div className="max-h-48 overflow-y-auto space-y-1">
                    {firewallData.rules.map((rule, idx) => (
                      <div key={idx} className="flex items-center gap-2 p-2 bg-muted/30 rounded text-xs font-mono">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                          rule.action === "ACCEPT" ? "bg-green-500/10 text-green-500" :
                          rule.action === "DROP" ? "bg-red-500/10 text-red-500" :
                          "bg-gray-500/10 text-gray-500"
                        }`}>
                          {rule.action || "?"}
                        </span>
                        <span className="text-muted-foreground">{rule.direction || "IN"}</span>
                        {rule.p && <span className="text-blue-400">{rule.p}</span>}
                        {rule.dport && <span className="text-foreground">:{rule.dport}</span>}
                        <span className="text-muted-foreground/60 ml-auto">{rule.source_file}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-start gap-2">
                <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-blue-500">
                  For advanced firewall configuration (IP sets, security groups, per-VM rules), use the Proxmox web interface at port 8006.
                </p>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Fail2Ban */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bug className="h-5 w-5 text-red-500" />
              <CardTitle>Fail2Ban</CardTitle>
            </div>
            {fail2banInfo?.installed && fail2banInfo?.active && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => { loadFail2banDetails(); loadSecurityTools(); }}
                className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
              >
                <RefreshCw className="h-3 w-3 mr-1" />
                Refresh
              </Button>
            )}
          </div>
          <CardDescription>
            Intrusion prevention system that bans IPs after repeated failed login attempts
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {toolsLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin h-8 w-8 border-4 border-red-500 border-t-transparent rounded-full" />
            </div>
          ) : !fail2banInfo?.installed ? (
            /* --- NOT INSTALLED --- */
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-gray-500/10 flex items-center justify-center">
                    <Bug className="h-5 w-5 text-gray-500" />
                  </div>
                  <div>
                    <p className="font-medium">Fail2Ban Not Installed</p>
                    <p className="text-sm text-muted-foreground">Protect SSH and Proxmox web interface from brute force attacks</p>
                  </div>
                </div>
                <div className="px-3 py-1 rounded-full text-sm font-medium bg-gray-500/10 text-gray-500">
                  Not Installed
                </div>
              </div>

              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
                <div className="flex items-start gap-3">
                  <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <div className="space-y-2 text-sm text-blue-400">
                    <p className="font-medium">What Fail2Ban will configure:</p>
                    <ul className="list-disc list-inside space-y-1 text-blue-300">
                      <li>SSH protection (max 2 retries, 9h ban)</li>
                      <li>Proxmox web interface protection (port 8006, max 3 retries, 1h ban)</li>
                      <li>Global settings with nftables backend</li>
                    </ul>
                  </div>
                </div>
              </div>

              <Button
                onClick={() => setShowFail2banInstaller(true)}
                className="w-full bg-red-600 hover:bg-red-700 text-white"
              >
                <Download className="h-4 w-4 mr-2" />
                Install and Configure Fail2Ban
              </Button>
            </div>
          ) : (
            /* --- INSTALLED --- */
            <div className="space-y-4">
              {/* Status bar */}
              <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center ${fail2banInfo.active ? "bg-green-500/10" : "bg-yellow-500/10"}`}>
                    <Bug className={`h-5 w-5 ${fail2banInfo.active ? "text-green-500" : "text-yellow-500"}`} />
                  </div>
                  <div>
                    <p className="font-medium">Fail2Ban {fail2banInfo.version}</p>
                    <p className="text-sm text-muted-foreground">
                      {fail2banInfo.active ? "Service is running" : "Service is not running"}
                    </p>
                  </div>
                </div>
                <div className={`px-3 py-1 rounded-full text-sm font-medium ${fail2banInfo.active ? "bg-green-500/10 text-green-500" : "bg-yellow-500/10 text-yellow-500"}`}>
                  {fail2banInfo.active ? "Active" : "Inactive"}
                </div>
              </div>

              {fail2banInfo.active && f2bDetails && (
                <>
                  {/* Summary stats */}
                  <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
                    <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                      <p className="text-xs text-muted-foreground mb-1">Jails</p>
                      <p className="text-xl font-bold">{f2bDetails.jails.length}</p>
                    </div>
                    <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                      <p className="text-xs text-muted-foreground mb-1">Banned IPs</p>
                      <p className={`text-xl font-bold ${f2bDetails.jails.reduce((a, j) => a + j.currently_banned, 0) > 0 ? "text-red-500" : "text-green-500"}`}>
                        {f2bDetails.jails.reduce((a, j) => a + j.currently_banned, 0)}
                      </p>
                    </div>
                    <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                      <p className="text-xs text-muted-foreground mb-1">Total Bans</p>
                      <p className="text-xl font-bold text-orange-500">
                        {f2bDetails.jails.reduce((a, j) => a + j.total_banned, 0)}
                      </p>
                    </div>
                    <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                      <p className="text-xs text-muted-foreground mb-1">Failed Attempts</p>
                      <p className="text-xl font-bold text-yellow-500">
                        {f2bDetails.jails.reduce((a, j) => a + j.total_failed, 0)}
                      </p>
                    </div>
                  </div>

                  {/* Tab switcher */}
                  <div className="flex gap-1 p-1 bg-muted/30 rounded-lg">
                    <button
                      onClick={() => setF2bActiveTab("jails")}
                      className={`flex-1 px-3 py-2 rounded-md text-sm font-medium transition-all ${
                        f2bActiveTab === "jails"
                          ? "bg-red-500 text-white shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      <Shield className="h-3.5 w-3.5 inline mr-1.5" />
                      Jails & Banned IPs
                    </button>
                    <button
                      onClick={() => setF2bActiveTab("activity")}
                      className={`flex-1 px-3 py-2 rounded-md text-sm font-medium transition-all ${
                        f2bActiveTab === "activity"
                          ? "bg-red-500 text-white shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      <Clock className="h-3.5 w-3.5 inline mr-1.5" />
                      Recent Activity
                    </button>
                  </div>

                  {/* JAILS TAB */}
                  {f2bActiveTab === "jails" && (
                    <div className="space-y-3">
                      {f2bDetails.jails.map((jail) => (
                        <div key={jail.name} className="border border-border rounded-lg overflow-hidden">
                          {/* Jail header */}
                          <div className="flex items-center justify-between p-3 bg-muted/40">
                            <div className="flex items-center gap-2.5">
                              <div className={`w-2.5 h-2.5 rounded-full ${jail.currently_banned > 0 ? "bg-red-500 animate-pulse" : "bg-green-500"}`} />
                              <span className="font-semibold text-sm">{jail.name}</span>
                            </div>
                            <div className="flex items-center gap-3 text-xs text-muted-foreground">
                              <span title="Max retries before ban">
                                Retries: <span className="text-foreground font-medium">{jail.maxretry}</span>
                              </span>
                              <span title="Ban duration">
                                Ban: <span className="text-foreground font-medium">{formatBanTime(jail.bantime)}</span>
                              </span>
                              <span title="Time window for counting failures">
                                Window: <span className="text-foreground font-medium">{formatBanTime(jail.findtime)}</span>
                              </span>
                            </div>
                          </div>

                          {/* Jail stats bar */}
                          <div className="grid grid-cols-4 gap-px bg-border">
                            <div className="p-2.5 bg-card text-center">
                              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Banned</p>
                              <p className={`text-lg font-bold ${jail.currently_banned > 0 ? "text-red-500" : "text-green-500"}`}>
                                {jail.currently_banned}
                              </p>
                            </div>
                            <div className="p-2.5 bg-card text-center">
                              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Total Bans</p>
                              <p className="text-lg font-bold text-orange-500">{jail.total_banned}</p>
                            </div>
                            <div className="p-2.5 bg-card text-center">
                              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Failed Now</p>
                              <p className="text-lg font-bold text-yellow-500">{jail.currently_failed}</p>
                            </div>
                            <div className="p-2.5 bg-card text-center">
                              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Total Failed</p>
                              <p className="text-lg font-bold text-muted-foreground">{jail.total_failed}</p>
                            </div>
                          </div>

                          {/* Banned IPs list */}
                          {jail.banned_ips.length > 0 && (
                            <div className="border-t border-border">
                              <div className="px-3 py-2 bg-red-500/5">
                                <p className="text-xs font-semibold text-red-500 mb-2">
                                  Banned IPs ({jail.banned_ips.length})
                                </p>
                                <div className="space-y-1.5">
                                  {jail.banned_ips.map((ip) => (
                                    <div key={ip} className="flex items-center justify-between px-3 py-2 bg-card rounded-md border border-red-500/20">
                                      <div className="flex items-center gap-2.5">
                                        <div className="w-2 h-2 rounded-full bg-red-500" />
                                        <code className="text-sm font-mono">{ip}</code>
                                      </div>
                                      <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={() => handleUnbanIp(jail.name, ip)}
                                        disabled={f2bUnbanning === `${jail.name}:${ip}`}
                                        className="h-7 px-2.5 text-xs text-green-500 hover:text-green-400 hover:bg-green-500/10"
                                      >
                                        {f2bUnbanning === `${jail.name}:${ip}` ? (
                                          <div className="animate-spin h-3 w-3 border-2 border-green-500 border-t-transparent rounded-full" />
                                        ) : (
                                          <>
                                            <ShieldCheck className="h-3 w-3 mr-1" />
                                            Unban
                                          </>
                                        )}
                                      </Button>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          )}

                          {jail.currently_banned === 0 && (
                            <div className="px-3 py-3 border-t border-border text-center">
                              <p className="text-xs text-muted-foreground">No IPs currently banned in this jail</p>
                            </div>
                          )}
                        </div>
                      ))}

                      {f2bDetails.jails.length === 0 && (
                        <div className="text-center py-6 text-muted-foreground text-sm">
                          No jails configured
                        </div>
                      )}
                    </div>
                  )}

                  {/* ACTIVITY TAB */}
                  {f2bActiveTab === "activity" && (
                    <div className="space-y-1.5 max-h-80 overflow-y-auto">
                      {f2bActivity.length === 0 ? (
                        <div className="text-center py-6 text-muted-foreground text-sm">
                          No recent activity in the Fail2Ban log
                        </div>
                      ) : (
                        f2bActivity.map((event, idx) => (
                          <div key={idx} className="flex items-center gap-3 px-3 py-2 bg-muted/20 rounded-md hover:bg-muted/40 transition-colors">
                            <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
                              event.action === "ban" ? "bg-red-500" :
                              event.action === "unban" ? "bg-green-500" :
                              "bg-yellow-500"
                            }`} />
                            <div className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                              event.action === "ban" ? "bg-red-500/10 text-red-500" :
                              event.action === "unban" ? "bg-green-500/10 text-green-500" :
                              "bg-yellow-500/10 text-yellow-500"
                            }`}>
                              {event.action}
                            </div>
                            <code className="text-xs font-mono text-foreground flex-shrink-0">{event.ip}</code>
                            <span className="text-xs text-muted-foreground">{event.jail}</span>
                            <span className="text-[10px] text-muted-foreground/70 ml-auto flex-shrink-0">{event.timestamp}</span>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </>
              )}

              {fail2banInfo.active && !f2bDetails && f2bDetailsLoading && (
                <div className="flex items-center justify-center py-4">
                  <div className="animate-spin h-6 w-6 border-3 border-red-500 border-t-transparent rounded-full" />
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Lynis */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Search className="h-5 w-5 text-cyan-500" />
            <CardTitle>Lynis Security Audit</CardTitle>
          </div>
          <CardDescription>
            System security auditing tool that performs comprehensive security scans
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {toolsLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin h-8 w-8 border-4 border-cyan-500 border-t-transparent rounded-full" />
            </div>
          ) : !lynisInfo?.installed ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-gray-500/10 flex items-center justify-center">
                    <Search className="h-5 w-5 text-gray-500" />
                  </div>
                  <div>
                    <p className="font-medium">Lynis Not Installed</p>
                    <p className="text-sm text-muted-foreground">Comprehensive security auditing and hardening tool</p>
                  </div>
                </div>
                <div className="px-3 py-1 rounded-full text-sm font-medium bg-gray-500/10 text-gray-500">
                  Not Installed
                </div>
              </div>

              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
                <div className="flex items-start gap-3">
                  <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <div className="space-y-2 text-sm text-blue-400">
                    <p className="font-medium">Lynis features:</p>
                    <ul className="list-disc list-inside space-y-1 text-blue-300">
                      <li>System hardening scoring (0-100)</li>
                      <li>Vulnerability detection and suggestions</li>
                      <li>Compliance checking (PCI-DSS, HIPAA, etc.)</li>
                      <li>Installed from latest GitHub source</li>
                    </ul>
                  </div>
                </div>
              </div>

              <Button
                onClick={() => setShowLynisInstaller(true)}
                className="w-full bg-cyan-600 hover:bg-cyan-700 text-white"
              >
                <Download className="h-4 w-4 mr-2" />
                Install Lynis
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Status */}
              <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-green-500/10 flex items-center justify-center">
                    <Search className="h-5 w-5 text-green-500" />
                  </div>
                  <div>
                    <p className="font-medium">Lynis {lynisInfo.version}</p>
                    <p className="text-sm text-muted-foreground">Security auditing tool installed</p>
                  </div>
                </div>
                <div className="px-3 py-1 rounded-full text-sm font-medium bg-green-500/10 text-green-500">
                  Installed
                </div>
              </div>

              {/* Last Scan Info */}
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="p-3 bg-muted/30 rounded-lg border border-border">
                  <p className="text-xs text-muted-foreground mb-1">Last Scan</p>
                  <p className="text-sm font-medium">
                    {lynisInfo.last_scan || "No scan performed yet"}
                  </p>
                </div>
                <div className="p-3 bg-muted/30 rounded-lg border border-border">
                  <p className="text-xs text-muted-foreground mb-1">Hardening Index</p>
                  <p className={`text-lg font-bold ${
                    lynisInfo.hardening_index === null ? "text-muted-foreground" :
                    lynisInfo.hardening_index >= 70 ? "text-green-500" :
                    lynisInfo.hardening_index >= 50 ? "text-yellow-500" :
                    "text-red-500"
                  }`}>
                    {lynisInfo.hardening_index !== null ? `${lynisInfo.hardening_index}/100` : "N/A"}
                  </p>
                </div>
              </div>

              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-start gap-2">
                <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-blue-500">
                  Run audits from the Proxmox terminal with: <code className="text-xs bg-blue-500/10 px-1.5 py-0.5 rounded">lynis audit system</code>
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Script Terminal Modals */}
      <ScriptTerminalModal
        open={showFail2banInstaller}
        onClose={() => {
          setShowFail2banInstaller(false)
          loadSecurityTools()
        }}
        scriptPath="/usr/local/share/proxmenux/scripts/security/fail2ban_installer.sh"
        scriptName="fail2ban_installer"
        params={{ EXECUTION_MODE: "web" }}
        title="Fail2Ban Installation"
        description="Installing and configuring Fail2Ban for SSH and Proxmox protection..."
      />
      <ScriptTerminalModal
        open={showLynisInstaller}
        onClose={() => {
          setShowLynisInstaller(false)
          loadSecurityTools()
        }}
        scriptPath="/usr/local/share/proxmenux/scripts/security/lynis_installer.sh"
        scriptName="lynis_installer"
        params={{ EXECUTION_MODE: "web" }}
        title="Lynis Installation"
        description="Installing Lynis security auditing tool from GitHub..."
      />

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
