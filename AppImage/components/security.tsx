"use client"

import { useState, useEffect } from "react"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import {
  Shield, Lock, User, AlertCircle, CheckCircle, Info, LogOut, Key, Copy, Eye, EyeOff,
  Trash2, RefreshCw, Clock, ShieldCheck, Globe, FileKey, AlertTriangle,
  Flame, Bug, Search, Download, Power, PowerOff, Plus, Minus, Activity, Settings, Ban,
  FileText, Printer, Play, BarChart3, TriangleAlert, ChevronDown,
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
    rules: Array<{ raw: string; direction?: string; action?: string; dport?: string; p?: string; source?: string; source_file?: string; section?: string; rule_index: number }>
    monitor_port_open: boolean
  } | null>(null)
  const [firewallAction, setFirewallAction] = useState(false)
  const [showAddRule, setShowAddRule] = useState(false)
  const [newRule, setNewRule] = useState({
    direction: "IN",
    action: "ACCEPT",
    protocol: "tcp",
    dport: "",
    sport: "",
    source: "",
    iface: "",
    comment: "",
    level: "host",
  })
  const [addingRule, setAddingRule] = useState(false)
  const [deletingRuleIdx, setDeletingRuleIdx] = useState<number | null>(null)

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

  // Lynis audit state
  interface LynisWarning { test_id: string; severity: string; description: string; solution: string }
  interface LynisSuggestion { test_id: string; description: string; solution: string; details: string }
  interface LynisCheck {
    name: string; status: string; detail?: string
  }
  interface LynisSection {
    name: string; checks: LynisCheck[]
  }
  interface LynisReport {
    datetime_start: string; datetime_end: string; lynis_version: string
    os_name: string; os_version: string; os_fullname: string; hostname: string
    hardening_index: number | null; tests_performed: number
    warnings: LynisWarning[]; suggestions: LynisSuggestion[]
    categories: Record<string, { score?: number }>
    installed_packages: number; kernel_version: string
    firewall_active: boolean; malware_scanner: boolean
    sections: LynisSection[]
  }
  const [lynisAuditRunning, setLynisAuditRunning] = useState(false)
  const [lynisReport, setLynisReport] = useState<LynisReport | null>(null)
  const [lynisReportLoading, setLynisReportLoading] = useState(false)
  const [lynisShowReport, setLynisShowReport] = useState(false)
  const [lynisActiveTab, setLynisActiveTab] = useState<"overview" | "warnings" | "suggestions" | "checks">("overview")

  // Fail2Ban detailed state
  interface BannedIp {
    ip: string
    type: "local" | "external" | "unknown"
  }
  interface JailDetail {
    name: string
    currently_failed: number
    total_failed: number
    currently_banned: number
    total_banned: number
    banned_ips: BannedIp[]
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
  const [f2bEditingJail, setF2bEditingJail] = useState<string | null>(null)
  const [f2bJailConfig, setF2bJailConfig] = useState<{maxretry: string; bantime: string; findtime: string; permanent: boolean}>({
    maxretry: "", bantime: "", findtime: "", permanent: false,
  })
  const [f2bSavingConfig, setF2bSavingConfig] = useState(false)
  const [f2bApplyingJails, setF2bApplyingJails] = useState(false)

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

  const handleApplyMissingJails = async () => {
    setF2bApplyingJails(true)
    setError("")
    setSuccess("")
    try {
      const data = await fetchApi("/api/security/fail2ban/apply-jails", {
        method: "POST",
      })
      if (data.success) {
        setSuccess(data.message || "Missing jails applied successfully")
        // Reload to see the new jails
        await loadFail2banDetails()
        loadSecurityTools()
      } else {
        setError(data.message || "Failed to apply missing jails")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to apply missing jails")
    } finally {
      setF2bApplyingJails(false)
    }
  }

  // --- Lynis audit handlers ---
  const handleRunLynisAudit = async () => {
    setLynisAuditRunning(true)
    setError("")
    setSuccess("")
    try {
      const data = await fetchApi("/api/security/lynis/run", { method: "POST" })
      if (data.success) {
        // Poll for completion
        const pollInterval = setInterval(async () => {
          try {
            const status = await fetchApi("/api/security/lynis/status")
            if (!status.running) {
              clearInterval(pollInterval)
              setLynisAuditRunning(false)
              if (status.progress === "completed") {
                setSuccess("Security audit completed successfully")
                loadSecurityTools()
                loadLynisReport()
              } else {
                setError(status.progress || "Audit failed")
              }
            }
          } catch {
            clearInterval(pollInterval)
            setLynisAuditRunning(false)
          }
        }, 3000)
      } else {
        setError(data.message || "Failed to start audit")
        setLynisAuditRunning(false)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start audit")
      setLynisAuditRunning(false)
    }
  }

  const loadLynisReport = async () => {
    setLynisReportLoading(true)
    try {
      const data = await fetchApi("/api/security/lynis/report")
      if (data.success && data.report) {
        setLynisReport(data.report)
      }
    } catch {
      // ignore
    } finally {
      setLynisReportLoading(false)
    }
  }

  // Load report on mount if lynis is installed
  useEffect(() => {
    if (lynisInfo?.installed && lynisInfo?.last_scan) {
      loadLynisReport()
    }
  }, [lynisInfo?.installed, lynisInfo?.last_scan])

  const openJailConfig = (jail: JailDetail) => {
    const bt = parseInt(jail.bantime, 10)
    const isPermanent = bt === -1
    setF2bEditingJail(jail.name)
    setF2bJailConfig({
      maxretry: jail.maxretry,
      bantime: isPermanent ? "" : jail.bantime,
      findtime: jail.findtime,
      permanent: isPermanent,
    })
  }

  const handleSaveJailConfig = async () => {
    if (!f2bEditingJail) return
    setF2bSavingConfig(true)
    setError("")
    setSuccess("")
    try {
      const payload: Record<string, string | number> = { jail: f2bEditingJail }
      if (f2bJailConfig.maxretry) payload.maxretry = parseInt(f2bJailConfig.maxretry, 10)
      if (f2bJailConfig.permanent) {
        payload.bantime = -1
      } else if (f2bJailConfig.bantime) {
        payload.bantime = parseInt(f2bJailConfig.bantime, 10)
      }
      if (f2bJailConfig.findtime) payload.findtime = parseInt(f2bJailConfig.findtime, 10)

      const data = await fetchApi("/api/security/fail2ban/jail/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (data.success) {
        setSuccess(data.message || "Jail configuration updated")
        setF2bEditingJail(null)
        loadFail2banDetails()
      } else {
        setError(data.message || "Failed to update jail config")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update jail config")
    } finally {
      setF2bSavingConfig(false)
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
    if (s === -1) return "Permanent"
    if (isNaN(s) || s <= 0) return seconds
    if (s < 60) return `${s}s`
    if (s < 3600) return `${Math.floor(s / 60)}m`
    if (s < 86400) return `${Math.floor(s / 3600)}h`
    return `${Math.floor(s / 86400)}d`
  }

  const handleAddRule = async () => {
    if (!newRule.dport && !newRule.source) {
      setError("Please specify at least a destination port or source address")
      return
    }
    setAddingRule(true)
    setError("")
    setSuccess("")
    try {
      const data = await fetchApi("/api/security/firewall/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newRule),
      })
      if (data.success) {
        setSuccess(data.message || "Rule added successfully")
        setShowAddRule(false)
        setNewRule({ direction: "IN", action: "ACCEPT", protocol: "tcp", dport: "", sport: "", source: "", iface: "", comment: "", level: "host" })
        loadFirewallStatus()
      } else {
        setError(data.message || "Failed to add rule")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add rule")
    } finally {
      setAddingRule(false)
    }
  }

  const handleDeleteRule = async (ruleIndex: number, level: string) => {
    setDeletingRuleIdx(ruleIndex)
    setError("")
    setSuccess("")
    try {
      const data = await fetchApi("/api/security/firewall/rules", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rule_index: ruleIndex, level }),
      })
      if (data.success) {
        setSuccess(data.message || "Rule deleted")
        loadFirewallStatus()
      } else {
        setError(data.message || "Failed to delete rule")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete rule")
    } finally {
      setDeletingRuleIdx(null)
    }
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

  const generatePrintableReport = (report: LynisReport) => {
    const scoreColor = report.hardening_index === null ? "#888"
      : report.hardening_index >= 70 ? "#16a34a"
      : report.hardening_index >= 50 ? "#ca8a04"
      : "#dc2626"
    const scoreLabel = report.hardening_index === null ? "N/A"
      : report.hardening_index >= 70 ? "GOOD"
      : report.hardening_index >= 50 ? "MODERATE"
      : "CRITICAL"
    const now = new Date().toLocaleString()
    const logoUrl = `${window.location.origin}/images/proxmenux-logo.png`

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Security Audit Report - ${report.hostname || "ProxMenux"}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #1a1a2e; background: #fff; font-size: 13px; line-height: 1.5; }

  /* Page setup for print */
  @page { margin: 15mm 15mm 20mm 15mm; size: A4; }
  @media print {
    .no-print { display: none !important; }
    .page-break { page-break-before: always; }
    body { font-size: 11px; }
  }

  /* Header */
  .report-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 20px 0; border-bottom: 3px solid #0f172a; margin-bottom: 24px;
  }
  .report-header-left { display: flex; align-items: center; gap: 16px; }
  .report-header-left img { height: 48px; width: auto; }
  .report-header-left h1 { font-size: 22px; font-weight: 700; color: #0f172a; }
  .report-header-left p { font-size: 11px; color: #64748b; }
  .report-header-right { text-align: right; font-size: 11px; color: #64748b; }
  .report-header-right .report-id { font-family: monospace; font-size: 10px; color: #94a3b8; }

  /* Sections */
  .section { margin-bottom: 24px; page-break-inside: avoid; }
  .section-title {
    font-size: 14px; font-weight: 700; color: #0f172a; text-transform: uppercase;
    letter-spacing: 0.05em; padding-bottom: 6px; border-bottom: 2px solid #e2e8f0; margin-bottom: 12px;
  }

  /* Score box */
  .score-section { display: flex; align-items: center; gap: 24px; padding: 20px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 24px; }
  .score-circle {
    width: 100px; height: 100px; border-radius: 50%; display: flex; flex-direction: column;
    align-items: center; justify-content: center; border: 4px solid; flex-shrink: 0;
  }
  .score-number { font-size: 32px; font-weight: 800; line-height: 1; }
  .score-label { font-size: 9px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; }
  .score-details { flex: 1; }
  .score-details h3 { font-size: 16px; margin-bottom: 4px; }
  .score-details p { font-size: 12px; color: #64748b; }

  /* Info grid */
  .info-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 8px; }
  .info-card { padding: 10px 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; }
  .info-label { font-size: 10px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 2px; }
  .info-value { font-size: 13px; font-weight: 600; color: #0f172a; }

  /* Status grid */
  .status-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 8px; }
  .status-card { padding: 12px; text-align: center; border-radius: 6px; border: 1px solid #e2e8f0; }
  .status-value { font-size: 20px; font-weight: 800; }
  .status-label { font-size: 10px; color: #64748b; text-transform: uppercase; margin-top: 2px; }

  /* Findings */
  .finding { padding: 10px 12px; margin-bottom: 6px; border-left: 4px solid; border-radius: 0 4px 4px 0; background: #fafafa; }
  .finding-warning { border-color: #dc2626; background: #fef2f2; }
  .finding-suggestion { border-color: #ca8a04; background: #fefce8; }
  .finding-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
  .finding-id { font-family: 'Courier New', monospace; font-size: 10px; background: #e2e8f0; padding: 1px 6px; border-radius: 3px; font-weight: 600; }
  .finding-severity { font-size: 10px; font-weight: 700; text-transform: uppercase; color: #dc2626; }
  .finding-desc { font-size: 12px; color: #1e293b; }
  .finding-solution { font-size: 11px; color: #64748b; margin-top: 3px; }
  .finding-solution strong { color: #475569; }
  .finding-details { font-size: 10px; font-family: 'Courier New', monospace; color: #94a3b8; margin-top: 2px; }

  /* Table of contents summary */
  .summary-bar { display: flex; gap: 16px; margin-bottom: 16px; }
  .summary-item { display: flex; align-items: center; gap: 6px; font-size: 12px; }
  .summary-dot { width: 10px; height: 10px; border-radius: 50%; }

  /* Footer */
  .report-footer {
    margin-top: 32px; padding-top: 12px; border-top: 1px solid #e2e8f0;
    display: flex; justify-content: space-between; font-size: 10px; color: #94a3b8;
  }

  /* Print button */
  .print-bar {
    position: fixed; top: 0; left: 0; right: 0; background: #0f172a; color: #fff;
    padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; z-index: 100;
  }
  .print-bar button {
    background: #06b6d4; color: #fff; border: none; padding: 8px 20px; border-radius: 6px;
    font-size: 13px; font-weight: 600; cursor: pointer;
  }
  .print-bar button:hover { background: #0891b2; }
  @media print { .print-bar { display: none; } body { padding-top: 0; } }
  @media screen { body { padding-top: 56px; max-width: 800px; margin: 0 auto; padding-left: 24px; padding-right: 24px; } }
</style>
</head>
<body>

<div class="print-bar no-print">
  <div style="display:flex;align-items:center;gap:12px;">
    <strong>ProxMenux Security Audit Report</strong>
    <span style="font-size:11px;opacity:0.7;">Use Print / Save as PDF to download</span>
  </div>
  <button onclick="window.print()">Print / Save as PDF</button>
</div>

<!-- Report Header -->
<div class="report-header">
  <div class="report-header-left">
    <img src="${logoUrl}" alt="ProxMenux" onerror="this.style.display='none'" />
    <div>
      <h1>Security Audit Report</h1>
      <p>ProxMenux Monitor - Lynis System Audit</p>
    </div>
  </div>
  <div class="report-header-right">
    <div><strong>Report Date:</strong> ${now}</div>
    <div><strong>Auditor:</strong> Lynis ${report.lynis_version || ""}</div>
    <div class="report-id">ID: PMXA-${Date.now().toString(36).toUpperCase()}</div>
  </div>
</div>

<!-- Executive Summary -->
<div class="section">
  <div class="section-title">1. Executive Summary</div>
  <div class="score-section">
    <div class="score-circle" style="border-color: ${scoreColor}; color: ${scoreColor};">
      <div class="score-number">${report.hardening_index ?? "N/A"}</div>
      <div class="score-label">${scoreLabel}</div>
    </div>
    <div class="score-details">
      <h3>System Hardening Assessment</h3>
      <p>
        This automated security audit was performed on host <strong>${report.hostname || "Unknown"}</strong>
        running <strong>${report.os_fullname || `${report.os_name} ${report.os_version}`.trim() || "Unknown OS"}</strong>.
        A total of <strong>${report.tests_performed}</strong> tests were executed,
        resulting in <strong style="color:#dc2626;">${report.warnings.length} warning(s)</strong>
        and <strong style="color:#ca8a04;">${report.suggestions.length} suggestion(s)</strong> for improvement.
      </p>
    </div>
  </div>
</div>

<!-- System Information -->
<div class="section">
  <div class="section-title">2. System Information</div>
  <div class="info-grid">
    <div class="info-card">
      <div class="info-label">Hostname</div>
      <div class="info-value">${report.hostname || "N/A"}</div>
    </div>
    <div class="info-card">
      <div class="info-label">Operating System</div>
      <div class="info-value">${report.os_fullname || `${report.os_name} ${report.os_version}`.trim() || "N/A"}</div>
    </div>
    <div class="info-card">
      <div class="info-label">Kernel</div>
      <div class="info-value">${report.kernel_version || "N/A"}</div>
    </div>
    <div class="info-card">
      <div class="info-label">Lynis Version</div>
      <div class="info-value">${report.lynis_version || "N/A"}</div>
    </div>
    <div class="info-card">
      <div class="info-label">Report Date</div>
      <div class="info-value">${report.datetime_start ? report.datetime_start.replace("T", " ").substring(0, 16) : "N/A"}</div>
    </div>
    <div class="info-card">
      <div class="info-label">Tests Performed</div>
      <div class="info-value">${report.tests_performed}</div>
    </div>
  </div>
</div>

<!-- Quick Status -->
<div class="section">
  <div class="section-title">3. Security Posture Overview</div>
  <div class="status-grid">
    <div class="status-card">
      <div class="status-value" style="color:${scoreColor};">${report.hardening_index ?? "N/A"}<span style="font-size:12px;color:#64748b;">/100</span></div>
      <div class="status-label">Hardening Score (${scoreLabel})</div>
    </div>
    <div class="status-card">
      <div class="status-value" style="color:${report.warnings.length > 0 ? "#dc2626" : "#16a34a"};">${report.warnings.length}</div>
      <div class="status-label">Warnings</div>
    </div>
    <div class="status-card">
      <div class="status-value" style="color:${report.suggestions.length > 0 ? "#ca8a04" : "#16a34a"};">${report.suggestions.length}</div>
      <div class="status-label">Suggestions</div>
    </div>
    <div class="status-card">
      <div class="status-value">${report.tests_performed}</div>
      <div class="status-label">Tests Performed</div>
    </div>
  </div>
  <div class="info-grid" style="grid-template-columns: repeat(3, 1fr);">
    <div class="info-card" style="text-align:center;">
      <div class="info-label">Firewall</div>
      <div class="info-value" style="color:${report.firewall_active ? "#16a34a" : "#dc2626"};">${report.firewall_active ? "Active" : "Inactive"}</div>
    </div>
    <div class="info-card" style="text-align:center;">
      <div class="info-label">Malware Scanner</div>
      <div class="info-value" style="color:${report.malware_scanner ? "#16a34a" : "#ca8a04"};">${report.malware_scanner ? "Installed" : "Not Found"}</div>
    </div>
    <div class="info-card" style="text-align:center;">
      <div class="info-label">Installed Packages</div>
      <div class="info-value">${report.installed_packages || "N/A"}</div>
    </div>
  </div>
</div>

<!-- Warnings -->
<div class="section page-break">
  <div class="section-title">4. Warnings (${report.warnings.length})</div>
  <p style="font-size:11px;color:#64748b;margin-bottom:12px;">Issues that require immediate attention and may represent security vulnerabilities.</p>
  ${report.warnings.length === 0 ?
    '<div style="padding:16px;text-align:center;color:#16a34a;background:#f0fdf4;border-radius:6px;border:1px solid #bbf7d0;">No warnings detected. System appears to be well-configured.</div>' :
    report.warnings.map((w, i) => `
    <div class="finding finding-warning">
      <div class="finding-header">
        <span style="font-size:10px;color:#94a3b8;font-weight:700;">#${i + 1}</span>
        <span class="finding-id">${w.test_id}</span>
        ${w.severity ? `<span class="finding-severity">${w.severity}</span>` : ""}
      </div>
      <div class="finding-desc">${w.description}</div>
      ${w.solution ? `<div class="finding-solution"><strong>Recommendation:</strong> ${w.solution}</div>` : ""}
    </div>`).join("")}
</div>

<!-- Suggestions -->
<div class="section page-break">
  <div class="section-title">5. Suggestions (${report.suggestions.length})</div>
  <p style="font-size:11px;color:#64748b;margin-bottom:12px;">Recommended improvements to strengthen your system's security posture.</p>
  ${report.suggestions.length === 0 ?
    '<div style="padding:16px;text-align:center;color:#16a34a;background:#f0fdf4;border-radius:6px;border:1px solid #bbf7d0;">No suggestions. System is fully hardened.</div>' :
    report.suggestions.map((s, i) => `
    <div class="finding finding-suggestion">
      <div class="finding-header">
        <span style="font-size:10px;color:#94a3b8;font-weight:700;">#${i + 1}</span>
        <span class="finding-id">${s.test_id}</span>
      </div>
      <div class="finding-desc">${s.description}</div>
      ${s.solution ? `<div class="finding-solution"><strong>Recommendation:</strong> ${s.solution}</div>` : ""}
      ${s.details ? `<div class="finding-details">${s.details}</div>` : ""}
    </div>`).join("")}
</div>

<!-- Detailed Checks -->
${(report.sections && report.sections.length > 0) ? `
<div class="section page-break">
  <div class="section-title">6. Detailed Security Checks (${report.sections.length} categories)</div>
  <p style="font-size:11px;color:#64748b;margin-bottom:16px;">Complete list of all security checks performed during the audit, organized by category.</p>
  ${report.sections.map((section, sIdx) => `
  <div style="margin-bottom:16px;page-break-inside:avoid;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;padding:6px 10px;background:#f1f5f9;border-radius:4px;">
      <span style="font-size:10px;font-weight:700;color:#0891b2;background:#ecfeff;padding:2px 6px;border-radius:3px;">${sIdx + 1}</span>
      <span style="font-size:12px;font-weight:700;color:#0f172a;">${section.name}</span>
      <span style="font-size:10px;color:#94a3b8;margin-left:auto;">${section.checks.length} checks</span>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:11px;">
      <thead>
        <tr style="background:#f8fafc;">
          <th style="text-align:left;padding:4px 8px;font-size:10px;color:#64748b;font-weight:600;border-bottom:1px solid #e2e8f0;">Check</th>
          <th style="text-align:right;padding:4px 8px;font-size:10px;color:#64748b;font-weight:600;border-bottom:1px solid #e2e8f0;width:120px;">Status</th>
        </tr>
      </thead>
      <tbody>
        ${section.checks.map(check => {
          const st = check.status.toUpperCase()
          const isWarn = ["WARNING", "UNSAFE", "WEAK", "DIFFERENT", "DISABLED"].includes(st)
          const isSugg = ["SUGGESTION", "PARTIALLY HARDENED", "MEDIUM", "NON DEFAULT"].includes(st)
          const isOk = ["OK", "FOUND", "DONE", "ENABLED", "ACTIVE", "YES", "HARDENED", "PROTECTED"].includes(st)
          const color = isWarn ? "#dc2626" : isSugg ? "#ca8a04" : isOk ? "#16a34a" : "#64748b"
          const bg = isWarn ? "#fef2f2" : isSugg ? "#fefce8" : "transparent"
          return `<tr style="background:${bg};border-bottom:1px solid #f1f5f9;">
            <td style="padding:3px 8px;color:#1e293b;">${check.name}${check.detail ? ` <span style="color:#94a3b8;font-size:10px;">(${check.detail})</span>` : ""}</td>
            <td style="padding:3px 8px;text-align:right;font-weight:700;color:${color};font-size:10px;">${check.status}</td>
          </tr>`
        }).join("")}
      </tbody>
    </table>
  </div>`).join("")}
</div>` : ""}

<!-- Footer -->
<div class="report-footer">
  <div>Generated by ProxMenux Monitor using Lynis ${report.lynis_version || ""}</div>
  <div>Report Date: ${now}</div>
  <div style="font-style:italic;">Confidential - For authorized personnel only</div>
</div>

</body>
</html>`
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
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Flame className="h-5 w-5 text-orange-500" />
              <CardTitle>Proxmox Firewall</CardTitle>
            </div>
            {firewallData?.pve_firewall_installed && (
              <Button
                variant="ghost"
                size="sm"
                onClick={loadFirewallStatus}
                className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
              >
                <RefreshCw className="h-3 w-3 mr-1" />
                Refresh
              </Button>
            )}
          </div>
          <CardDescription>
            Manage the Proxmox VE built-in firewall: enable/disable, configure rules, and protect your services
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
                        {firewallData.cluster_fw_enabled ? "Active - Required for host rules to work" : "Disabled - Must be enabled first"}
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
                        {firewallData.host_fw_enabled ? "Active - Rules are being enforced" : "Disabled"}
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

              {!firewallData.cluster_fw_enabled && (
                <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-start gap-2">
                  <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-blue-500">
                    The Cluster Firewall must be enabled for any host-level firewall rules to take effect. Enable it first, then configure your host rules.
                  </p>
                </div>
              )}

              {/* Quick Presets */}
              <div className="space-y-2">
                <h3 className="text-sm font-semibold text-muted-foreground">Quick Access Rules</h3>
                <div className="grid gap-2 sm:grid-cols-2">
                  {/* Monitor Port 8008 */}
                  <div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg border border-border">
                    <div className="flex items-center gap-2.5">
                      <div className={`w-2.5 h-2.5 rounded-full ${firewallData.monitor_port_open ? "bg-green-500" : "bg-yellow-500"}`} />
                      <div>
                        <p className="text-sm font-medium">ProxMenux Monitor</p>
                        <p className="text-xs text-muted-foreground">Port 8008/TCP</p>
                      </div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={firewallAction}
                      onClick={() => handleMonitorPortToggle(!firewallData.monitor_port_open)}
                      className={`h-7 text-xs ${firewallData.monitor_port_open
                        ? "text-red-500 border-red-500/30 hover:bg-red-500/10 bg-transparent"
                        : "text-green-500 border-green-500/30 hover:bg-green-500/10 bg-transparent"
                      }`}
                    >
                      {firewallData.monitor_port_open ? "Remove" : "Allow"}
                    </Button>
                  </div>

                  {/* Proxmox Web UI hint */}
                  <div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg border border-border">
                    <div className="flex items-center gap-2.5">
                      <div className="w-2.5 h-2.5 rounded-full bg-green-500" />
                      <div>
                        <p className="text-sm font-medium">Proxmox Web UI</p>
                        <p className="text-xs text-muted-foreground">Port 8006/TCP (always allowed)</p>
                      </div>
                    </div>
                    <span className="text-xs text-muted-foreground px-2 py-1 bg-muted/50 rounded">Built-in</span>
                  </div>
                </div>

                {!firewallData.monitor_port_open && (firewallData.cluster_fw_enabled || firewallData.host_fw_enabled) && (
                  <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3 flex items-start gap-2">
                    <AlertTriangle className="h-5 w-5 text-yellow-500 flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-yellow-500">
                      The firewall is active but port 8008 is not allowed. ProxMenux Monitor may be inaccessible from other devices.
                    </p>
                  </div>
                )}
              </div>

              {/* Firewall Rules */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-muted-foreground">
                    Firewall Rules ({firewallData.rules_count})
                  </h3>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowAddRule(!showAddRule)}
                    className="h-7 text-xs text-orange-500 border-orange-500/30 hover:bg-orange-500/10 bg-transparent"
                  >
                    <Plus className="h-3 w-3 mr-1" />
                    Add Rule
                  </Button>
                </div>

                {/* Add Rule Form */}
                {showAddRule && (
                  <div className="border border-orange-500/30 rounded-lg p-4 bg-orange-500/5 space-y-4">
                    <div className="flex items-center gap-2 mb-1">
                      <Plus className="h-4 w-4 text-orange-500" />
                      <p className="text-sm font-semibold text-orange-500">New Firewall Rule</p>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-3">
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Direction</Label>
                        <select
                          value={newRule.direction}
                          onChange={(e) => setNewRule({...newRule, direction: e.target.value})}
                          className="w-full h-9 rounded-md border border-border bg-card px-3 text-sm"
                        >
                          <option value="IN">IN (incoming)</option>
                          <option value="OUT">OUT (outgoing)</option>
                        </select>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Action</Label>
                        <select
                          value={newRule.action}
                          onChange={(e) => setNewRule({...newRule, action: e.target.value})}
                          className="w-full h-9 rounded-md border border-border bg-card px-3 text-sm"
                        >
                          <option value="ACCEPT">ACCEPT (allow)</option>
                          <option value="DROP">DROP (block silently)</option>
                          <option value="REJECT">REJECT (block with response)</option>
                        </select>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Protocol</Label>
                        <select
                          value={newRule.protocol}
                          onChange={(e) => setNewRule({...newRule, protocol: e.target.value})}
                          className="w-full h-9 rounded-md border border-border bg-card px-3 text-sm"
                        >
                          <option value="tcp">TCP</option>
                          <option value="udp">UDP</option>
                          <option value="icmp">ICMP (ping)</option>
                        </select>
                      </div>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Destination Port</Label>
                        <Input
                          placeholder="e.g. 80, 443, 8000:9000"
                          value={newRule.dport}
                          onChange={(e) => setNewRule({...newRule, dport: e.target.value})}
                          className="h-9 text-sm"
                        />
                        <p className="text-[10px] text-muted-foreground">Single port, comma-separated, or range (8000:9000)</p>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Source Address (optional)</Label>
                        <Input
                          placeholder="e.g. 192.168.1.0/24"
                          value={newRule.source}
                          onChange={(e) => setNewRule({...newRule, source: e.target.value})}
                          className="h-9 text-sm"
                        />
                        <p className="text-[10px] text-muted-foreground">IP, CIDR, or leave empty for any source</p>
                      </div>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Interface (optional)</Label>
                        <Input
                          placeholder="e.g. vmbr0"
                          value={newRule.iface}
                          onChange={(e) => setNewRule({...newRule, iface: e.target.value})}
                          className="h-9 text-sm"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">Apply to</Label>
                        <select
                          value={newRule.level}
                          onChange={(e) => setNewRule({...newRule, level: e.target.value})}
                          className="w-full h-9 rounded-md border border-border bg-card px-3 text-sm"
                        >
                          <option value="host">Host firewall (this node)</option>
                          <option value="cluster">Cluster firewall (all nodes)</option>
                        </select>
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">Comment (optional)</Label>
                      <Input
                        placeholder="e.g. Allow web traffic"
                        value={newRule.comment}
                        onChange={(e) => setNewRule({...newRule, comment: e.target.value})}
                        className="h-9 text-sm"
                      />
                    </div>

                    <div className="flex gap-2 justify-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setShowAddRule(false)}
                        className="text-muted-foreground"
                      >
                        Cancel
                      </Button>
                      <Button
                        size="sm"
                        disabled={addingRule}
                        onClick={handleAddRule}
                        className="bg-orange-600 hover:bg-orange-700 text-white"
                      >
                        {addingRule ? (
                          <div className="animate-spin h-3.5 w-3.5 border-2 border-white border-t-transparent rounded-full mr-1" />
                        ) : (
                          <Plus className="h-3.5 w-3.5 mr-1" />
                        )}
                        Add Rule
                      </Button>
                    </div>
                  </div>
                )}

                {/* Rules List */}
                {firewallData.rules.length > 0 ? (
                  <div className="border border-border rounded-lg overflow-hidden">
                    {/* Table header */}
                    <div className="grid grid-cols-[auto_1fr_auto_auto_auto_auto_auto] gap-2 p-2.5 bg-muted/50 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                      <span className="w-14">Action</span>
                      <span>Direction</span>
                      <span className="w-12">Proto</span>
                      <span className="w-20">Port</span>
                      <span className="w-28 hidden sm:block">Source</span>
                      <span className="w-14">Level</span>
                      <span className="w-8" />
                    </div>

                    <div className="divide-y divide-border max-h-64 overflow-y-auto">
                      {firewallData.rules.map((rule, idx) => (
                        <div key={idx} className="grid grid-cols-[auto_1fr_auto_auto_auto_auto_auto] gap-2 p-2.5 items-center hover:bg-muted/20 transition-colors">
                          <span className={`w-14 px-1.5 py-0.5 rounded text-[10px] font-bold text-center ${
                            rule.action === "ACCEPT" ? "bg-green-500/10 text-green-500" :
                            rule.action === "DROP" ? "bg-red-500/10 text-red-500" :
                            rule.action === "REJECT" ? "bg-orange-500/10 text-orange-500" :
                            "bg-gray-500/10 text-gray-500"
                          }`}>
                            {rule.action || "?"}
                          </span>
                          <span className="text-xs text-muted-foreground font-mono">{rule.direction || "IN"}</span>
                          <span className="w-12 text-xs text-blue-400 font-mono">{rule.p || "-"}</span>
                          <span className="w-20 text-xs text-foreground font-mono">{rule.dport || "-"}</span>
                          <span className="w-28 text-xs text-muted-foreground font-mono hidden sm:block truncate">{rule.source || "any"}</span>
                          <span className={`w-14 text-[10px] px-1.5 py-0.5 rounded text-center ${
                            rule.source_file === "cluster" ? "bg-blue-500/10 text-blue-400" : "bg-purple-500/10 text-purple-400"
                          }`}>
                            {rule.source_file}
                          </span>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDeleteRule(rule.rule_index, rule.source_file)}
                            disabled={deletingRuleIdx === rule.rule_index}
                            className="w-8 h-7 p-0 text-red-500/50 hover:text-red-500 hover:bg-red-500/10"
                          >
                            {deletingRuleIdx === rule.rule_index ? (
                              <div className="animate-spin h-3 w-3 border-2 border-red-500 border-t-transparent rounded-full" />
                            ) : (
                              <Trash2 className="h-3.5 w-3.5" />
                            )}
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-6 border border-dashed border-border rounded-lg">
                    <Shield className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
                    <p className="text-sm text-muted-foreground">No firewall rules configured yet</p>
                    <p className="text-xs text-muted-foreground/60 mt-1">Click "Add Rule" above to create your first rule</p>
                  </div>
                )}
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
                    <p className="text-sm text-muted-foreground">Protect SSH, Proxmox web interface, and ProxMenux Monitor from brute force attacks</p>
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
                      <li>ProxMenux Monitor protection (port 8008 + reverse proxy, max 3 retries, 1h ban)</li>
                      <li>Global settings with nftables backend</li>
                    </ul>
                    <p className="text-xs text-blue-300/70 mt-1">All settings can be customized after installation. You can change retries, ban time, or set permanent bans.</p>
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

                  {/* Missing jails warning */}
                  {(() => {
                    const expectedJails = ["sshd", "proxmox", "proxmenux"]
                    const currentNames = f2bDetails.jails.map(j => j.name.toLowerCase())
                    const missing = expectedJails.filter(j => !currentNames.includes(j))
                    if (missing.length === 0) return null

                    const jailLabels: Record<string, string> = {
                      sshd: "SSH (sshd)",
                      proxmox: "Proxmox UI (port 8006)",
                      proxmenux: "ProxMenux Monitor (port 8008)",
                    }

                    return (
                      <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-start gap-3">
                            <AlertTriangle className="h-5 w-5 text-yellow-500 flex-shrink-0 mt-0.5" />
                            <div className="space-y-1">
                              <p className="text-sm font-medium text-yellow-500">Missing protections detected</p>
                              <p className="text-xs text-yellow-400/80">
                                The following jails are not configured:{" "}
                                {missing.map(j => jailLabels[j] || j).join(", ")}
                              </p>
                            </div>
                          </div>
                          <Button
                            size="sm"
                            disabled={f2bApplyingJails}
                            onClick={handleApplyMissingJails}
                            className="bg-yellow-600 hover:bg-yellow-700 text-white flex-shrink-0"
                          >
                            {f2bApplyingJails ? (
                              <div className="animate-spin h-3.5 w-3.5 border-2 border-white border-t-transparent rounded-full mr-1.5" />
                            ) : (
                              <Shield className="h-3.5 w-3.5 mr-1.5" />
                            )}
                            Apply Missing Jails
                          </Button>
                        </div>
                      </div>
                    )
                  })()}

                  {/* Tab switcher - redesigned with border on inactive */}
                  <div className="flex gap-0 rounded-lg border border-border overflow-hidden">
                    <button
                      onClick={() => setF2bActiveTab("jails")}
                      className={`flex-1 px-3 py-2.5 text-sm font-medium transition-all flex items-center justify-center gap-1.5 ${
                        f2bActiveTab === "jails"
                          ? "bg-red-500 text-white"
                          : "bg-muted/30 text-muted-foreground hover:text-foreground hover:bg-muted/50"
                      }`}
                    >
                      <Shield className="h-3.5 w-3.5" />
                      Jails & Banned IPs
                    </button>
                    <button
                      onClick={() => setF2bActiveTab("activity")}
                      className={`flex-1 px-3 py-2.5 text-sm font-medium transition-all flex items-center justify-center gap-1.5 border-l border-border ${
                        f2bActiveTab === "activity"
                          ? "bg-red-500 text-white"
                          : "bg-muted/30 text-muted-foreground hover:text-foreground hover:bg-muted/50"
                      }`}
                    >
                      <Clock className="h-3.5 w-3.5" />
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
                              <span className="text-[10px] text-muted-foreground">
                                {jail.name === "sshd" ? "SSH Remote Access" :
                                 jail.name === "proxmox" ? "Proxmox UI :8006" :
                                 jail.name === "proxmenux" ? "ProxMenux Monitor :8008" :
                                 ""}
                              </span>
                              {parseInt(jail.bantime, 10) === -1 && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-500/10 text-red-500">PERMANENT BAN</span>
                              )}
                            </div>
                            <div className="flex items-center gap-2">
                              <div className="hidden sm:flex items-center gap-3 text-xs text-muted-foreground mr-2">
                                <span title="Max retries before ban">
                                  Retries: <span className="text-foreground font-medium">{jail.maxretry}</span>
                                </span>
                                <span title="Ban duration">
                                  Ban: <span className="text-foreground font-medium">{parseInt(jail.bantime, 10) === -1 ? "Permanent" : formatBanTime(jail.bantime)}</span>
                                </span>
                                <span title="Time window for counting failures">
                                  Window: <span className="text-foreground font-medium">{formatBanTime(jail.findtime)}</span>
                                </span>
                              </div>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => f2bEditingJail === jail.name ? setF2bEditingJail(null) : openJailConfig(jail)}
                                className={`h-7 w-7 p-0 ${f2bEditingJail === jail.name ? "text-red-500 bg-red-500/10" : "text-muted-foreground hover:text-foreground"}`}
                                title="Configure jail settings"
                              >
                                <Settings className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </div>

                          {/* Jail config editor */}
                          {f2bEditingJail === jail.name && (
                            <div className="border-t border-border bg-muted/20 p-4 space-y-4">
                              <div className="flex items-center gap-2 mb-1">
                                <Settings className="h-4 w-4 text-red-500" />
                                <p className="text-sm font-semibold text-red-500">Configure {jail.name}</p>
                              </div>

                              <div className="grid gap-3 sm:grid-cols-3">
                                <div className="space-y-1.5">
                                  <Label className="text-xs text-muted-foreground">Max Retries</Label>
                                  <Input
                                    type="number"
                                    min="1"
                                    value={f2bJailConfig.maxretry}
                                    onChange={(e) => setF2bJailConfig({...f2bJailConfig, maxretry: e.target.value})}
                                    className="h-9 text-sm"
                                    placeholder="e.g. 3"
                                  />
                                  <p className="text-[10px] text-muted-foreground">Failed attempts before ban</p>
                                </div>
                                <div className="space-y-1.5">
                                  <Label className="text-xs text-muted-foreground">Ban Time (seconds)</Label>
                                  <Input
                                    type="number"
                                    min="60"
                                    value={f2bJailConfig.permanent ? "" : f2bJailConfig.bantime}
                                    onChange={(e) => setF2bJailConfig({...f2bJailConfig, bantime: e.target.value, permanent: false})}
                                    className="h-9 text-sm"
                                    placeholder={f2bJailConfig.permanent ? "Permanent" : "e.g. 3600 = 1h"}
                                    disabled={f2bJailConfig.permanent}
                                  />
                                  <div className="flex items-center gap-2 mt-1">
                                    <input
                                      type="checkbox"
                                      id={`permanent-${jail.name}`}
                                      checked={f2bJailConfig.permanent}
                                      onChange={(e) => setF2bJailConfig({...f2bJailConfig, permanent: e.target.checked, bantime: ""})}
                                      className="rounded border-border"
                                    />
                                    <label htmlFor={`permanent-${jail.name}`} className="text-[10px] text-red-500 font-medium cursor-pointer">
                                      Permanent ban (never expires)
                                    </label>
                                  </div>
                                </div>
                                <div className="space-y-1.5">
                                  <Label className="text-xs text-muted-foreground">Find Time (seconds)</Label>
                                  <Input
                                    type="number"
                                    min="60"
                                    value={f2bJailConfig.findtime}
                                    onChange={(e) => setF2bJailConfig({...f2bJailConfig, findtime: e.target.value})}
                                    className="h-9 text-sm"
                                    placeholder="e.g. 600 = 10m"
                                  />
                                  <p className="text-[10px] text-muted-foreground">Time window for counting retries</p>
                                </div>
                              </div>

                              <div className="bg-blue-500/10 border border-blue-500/20 rounded p-2.5 flex items-start gap-2">
                                <Info className="h-4 w-4 text-blue-500 flex-shrink-0 mt-0.5" />
                                <p className="text-[11px] text-blue-400">
                                  Common values: 600s = 10min, 3600s = 1h, 32400s = 9h, 86400s = 24h. Set ban to permanent if you want blocked IPs to stay blocked until you manually unban them.
                                </p>
                              </div>

                              <div className="flex gap-2 justify-end">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => setF2bEditingJail(null)}
                                  className="text-muted-foreground"
                                >
                                  Cancel
                                </Button>
                                <Button
                                  size="sm"
                                  disabled={f2bSavingConfig}
                                  onClick={handleSaveJailConfig}
                                  className="bg-red-600 hover:bg-red-700 text-white"
                                >
                                  {f2bSavingConfig ? (
                                    <div className="animate-spin h-3.5 w-3.5 border-2 border-white border-t-transparent rounded-full mr-1" />
                                  ) : (
                                    <CheckCircle className="h-3.5 w-3.5 mr-1" />
                                  )}
                                  Save Configuration
                                </Button>
                              </div>
                            </div>
                          )}

                          {/* Mobile config summary (visible only on small screens) */}
                          <div className="sm:hidden flex items-center justify-around p-2 bg-muted/20 border-t border-border text-xs text-muted-foreground">
                            <span>Retries: <span className="text-foreground font-medium">{jail.maxretry}</span></span>
                            <span>Ban: <span className="text-foreground font-medium">{parseInt(jail.bantime, 10) === -1 ? "Perm" : formatBanTime(jail.bantime)}</span></span>
                            <span>Window: <span className="text-foreground font-medium">{formatBanTime(jail.findtime)}</span></span>
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
                                  {jail.banned_ips.map((entry) => (
                                    <div key={entry.ip} className="flex items-center justify-between px-3 py-2 bg-card rounded-md border border-red-500/20">
                                      <div className="flex items-center gap-2.5">
                                        <div className="w-2 h-2 rounded-full bg-red-500" />
                                        <code className="text-sm font-mono">{entry.ip}</code>
                                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider ${
                                          entry.type === "local"
                                            ? "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                                            : entry.type === "external"
                                            ? "bg-orange-500/10 text-orange-400 border border-orange-500/20"
                                            : "bg-gray-500/10 text-gray-400 border border-gray-500/20"
                                        }`}>
                                          {entry.type === "local" ? "LAN" : entry.type === "external" ? "External" : "Unknown"}
                                        </span>
                                      </div>
                                      <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={() => handleUnbanIp(jail.name, entry.ip)}
                                        disabled={f2bUnbanning === `${jail.name}:${entry.ip}`}
                                        className="h-7 px-2.5 text-xs text-green-500 hover:text-green-400 hover:bg-green-500/10"
                                      >
                                        {f2bUnbanning === `${jail.name}:${entry.ip}` ? (
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
              {/* Status bar */}
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

              {/* Summary stats */}
              <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
                <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                  <p className="text-xs text-muted-foreground mb-1">Last Scan</p>
                  <p className="text-sm font-medium">
                    {lynisInfo.last_scan ? lynisInfo.last_scan.replace("T", " ").substring(0, 16) : "Never"}
                  </p>
                </div>
                <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                  <p className="text-xs text-muted-foreground mb-1">Hardening Index</p>
                  <p className={`text-xl font-bold ${
                    (lynisReport?.hardening_index ?? lynisInfo.hardening_index) === null ? "text-muted-foreground" :
                    (lynisReport?.hardening_index ?? lynisInfo.hardening_index ?? 0) >= 70 ? "text-green-500" :
                    (lynisReport?.hardening_index ?? lynisInfo.hardening_index ?? 0) >= 50 ? "text-yellow-500" :
                    "text-red-500"
                  }`}>
                    {(lynisReport?.hardening_index ?? lynisInfo.hardening_index) !== null
                      ? (lynisReport?.hardening_index ?? lynisInfo.hardening_index)
                      : "N/A"}
                  </p>
                </div>
                <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                  <p className="text-xs text-muted-foreground mb-1">Warnings</p>
                  <p className={`text-xl font-bold ${lynisReport && lynisReport.warnings.length > 0 ? "text-red-500" : "text-green-500"}`}>
                    {lynisReport ? lynisReport.warnings.length : "-"}
                  </p>
                </div>
                <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                  <p className="text-xs text-muted-foreground mb-1">Suggestions</p>
                  <p className={`text-xl font-bold ${lynisReport && lynisReport.suggestions.length > 0 ? "text-yellow-500" : "text-green-500"}`}>
                    {lynisReport ? lynisReport.suggestions.length : "-"}
                  </p>
                </div>
              </div>

              {/* Hardening bar */}
              {(() => {
                const score = lynisReport?.hardening_index ?? lynisInfo.hardening_index
                if (score === null || score === undefined) return null
                return (
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">Security Hardening Score</span>
                      <span className={`font-bold ${
                        score >= 70 ? "text-green-500" : score >= 50 ? "text-yellow-500" : "text-red-500"
                      }`}>
                        {score}/100
                      </span>
                    </div>
                    <div className="w-full h-3 bg-muted/50 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-1000 ${
                          score >= 70 ? "bg-green-500" : score >= 50 ? "bg-yellow-500" : "bg-red-500"
                        }`}
                        style={{ width: `${score}%` }}
                      />
                    </div>
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                      <span>Critical (0-49)</span>
                      <span>Moderate (50-69)</span>
                      <span>Good (70-100)</span>
                    </div>
                  </div>
                )
              })()}

              {/* Running indicator */}
              {lynisAuditRunning && (
                <div className="bg-cyan-500/10 border border-cyan-500/20 rounded-lg p-4">
                  <div className="flex items-center gap-3">
                    <div className="animate-spin h-5 w-5 border-2 border-cyan-500 border-t-transparent rounded-full" />
                    <div>
                      <p className="text-sm font-medium text-cyan-500">Security audit in progress...</p>
                      <p className="text-xs text-cyan-400/70">This may take 2-5 minutes. Lynis is scanning your system for vulnerabilities, misconfigurations, and hardening opportunities.</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Reports list */}
              {lynisReport && (
                <div className="space-y-2">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Audit Reports</p>

                  {/* Report row - clickable to expand */}
                  <div className="border border-border rounded-lg overflow-hidden">
                    <button
                      onClick={() => setLynisShowReport(!lynisShowReport)}
                      className="w-full flex items-center justify-between p-3 bg-muted/20 hover:bg-muted/40 transition-colors text-left"
                    >
                      <div className="flex items-center gap-3">
                        <FileText className="h-4 w-4 text-cyan-500 flex-shrink-0" />
                        <div>
                          <p className="text-sm font-medium">
                            Security Audit - {lynisReport.datetime_start
                              ? lynisReport.datetime_start.replace("T", " ").substring(0, 16)
                              : lynisInfo.last_scan?.replace("T", " ").substring(0, 16) || "Unknown date"}
                          </p>
                          <p className="text-[11px] text-muted-foreground">
                            {lynisReport.hostname || "System"} - {lynisReport.tests_performed} tests - Score: {lynisReport.hardening_index ?? "N/A"}/100 - {lynisReport.warnings.length} warnings - {lynisReport.suggestions.length} suggestions
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation()
                            const printWindow = window.open("", "_blank")
                            if (printWindow) {
                              printWindow.document.write(generatePrintableReport(lynisReport))
                              printWindow.document.close()
                            }
                          }}
                          className="h-7 px-2 text-xs text-cyan-500 hover:text-cyan-400 hover:bg-cyan-500/10"
                          title="Print / Save as PDF"
                        >
                          <Printer className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation()
                            if (confirm("Delete this audit report? The report file will be removed from the server.")) {
                              fetchApi("/api/security/lynis/report", { method: "DELETE" })
                                .then(() => {
                                  setLynisReport(null)
                                  setLynisShowReport(false)
                                  setSuccess("Report deleted")
                                  loadSecurityTools()
                                })
                                .catch(() => setError("Failed to delete report"))
                            }
                          }}
                          className="h-7 px-2 text-xs text-red-500 hover:text-red-400 hover:bg-red-500/10"
                          title="Delete report"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                        <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${lynisShowReport ? "rotate-180" : ""}`} />
                      </div>
                    </button>

                    {/* Expanded report details */}
                    {lynisShowReport && (
                      <div className="border-t border-border">
                        {/* System info strip */}
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-border">
                          <div className="p-2.5 bg-card text-center">
                            <p className="text-[10px] text-muted-foreground uppercase">Hostname</p>
                            <p className="text-xs font-medium truncate">{lynisReport.hostname || "N/A"}</p>
                          </div>
                          <div className="p-2.5 bg-card text-center">
                            <p className="text-[10px] text-muted-foreground uppercase">OS</p>
                            <p className="text-xs font-medium truncate">{lynisReport.os_fullname || `${lynisReport.os_name} ${lynisReport.os_version}`.trim() || "N/A"}</p>
                          </div>
                          <div className="p-2.5 bg-card text-center">
                            <p className="text-[10px] text-muted-foreground uppercase">Kernel</p>
                            <p className="text-xs font-medium truncate">{lynisReport.kernel_version || "N/A"}</p>
                          </div>
                          <div className="p-2.5 bg-card text-center">
                            <p className="text-[10px] text-muted-foreground uppercase">Tests</p>
                            <p className="text-xs font-medium">{lynisReport.tests_performed}</p>
                          </div>
                        </div>

                        {/* Report tabs */}
                        <div className="flex gap-0 border-t border-border">
                          {(["overview", "checks", "warnings", "suggestions"] as const).map((tab) => (
                            <button
                              key={tab}
                              onClick={() => setLynisActiveTab(tab)}
                              className={`flex-1 px-3 py-2 text-xs font-medium transition-all flex items-center justify-center gap-1.5 border-r last:border-r-0 border-border ${
                                lynisActiveTab === tab
                                  ? "bg-cyan-500 text-white"
                                  : "bg-muted/20 text-muted-foreground hover:text-foreground hover:bg-muted/40"
                              }`}
                            >
                              {tab === "overview" && <BarChart3 className="h-3 w-3" />}
                              {tab === "checks" && <Search className="h-3 w-3" />}
                              {tab === "warnings" && <TriangleAlert className="h-3 w-3" />}
                              {tab === "suggestions" && <Info className="h-3 w-3" />}
                              {tab === "overview" ? "Overview"
                                : tab === "checks" ? `Checks (${lynisReport.sections?.length || 0})`
                                : tab === "warnings" ? `Warnings (${lynisReport.warnings.length})`
                                : `Suggestions (${lynisReport.suggestions.length})`}
                            </button>
                          ))}
                        </div>

                        {/* Overview tab */}
                        {lynisActiveTab === "overview" && (
                          <div className="p-4 space-y-3">
                            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                              <div className="p-3 rounded-lg border border-border bg-muted/20 text-center">
                                <p className="text-[10px] text-muted-foreground uppercase mb-1">Packages</p>
                                <p className="text-lg font-bold">{lynisReport.installed_packages || "N/A"}</p>
                              </div>
                              <div className="p-3 rounded-lg border border-border bg-muted/20 text-center">
                                <p className="text-[10px] text-muted-foreground uppercase mb-1">Firewall</p>
                                <p className={`text-lg font-bold ${lynisReport.firewall_active ? "text-green-500" : "text-red-500"}`}>
                                  {lynisReport.firewall_active ? "Active" : "Inactive"}
                                </p>
                              </div>
                              <div className="p-3 rounded-lg border border-border bg-muted/20 text-center">
                                <p className="text-[10px] text-muted-foreground uppercase mb-1">Malware Scanner</p>
                                <p className={`text-lg font-bold ${lynisReport.malware_scanner ? "text-green-500" : "text-yellow-500"}`}>
                                  {lynisReport.malware_scanner ? "Installed" : "Not Found"}
                                </p>
                              </div>
                            </div>

                            {/* Security checklist */}
                            <div className="space-y-1.5">
                              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Quick Status</p>
                              {[
                                {
                                  label: "Firewall",
                                  ok: lynisReport.firewall_active,
                                  passText: "Active",
                                  failText: "Inactive",
                                },
                                {
                                  label: "Malware Scanner",
                                  ok: lynisReport.malware_scanner,
                                  passText: "Installed",
                                  failText: "Not Installed",
                                  isWarning: true,
                                },
                                {
                                  label: "Warnings",
                                  ok: lynisReport.warnings.length === 0,
                                  passText: "None",
                                  failText: `${lynisReport.warnings.length} found`,
                                  isWarning: lynisReport.warnings.length > 0 && lynisReport.warnings.length <= 10,
                                },
                                {
                                  label: "Hardening Score",
                                  ok: (lynisReport.hardening_index || 0) >= 70,
                                  passText: `${lynisReport.hardening_index || 0}/100`,
                                  failText: `${lynisReport.hardening_index || 0}/100 (< 70)`,
                                  isWarning: (lynisReport.hardening_index || 0) >= 50,
                                },
                              ].map((item) => {
                                const color = item.ok ? "green" : item.isWarning ? "yellow" : "red"
                                return (
                                <div key={item.label} className="flex items-center gap-2 px-3 py-1.5 rounded bg-muted/20">
                                  <div className={`w-2 h-2 rounded-full ${color === "green" ? "bg-green-500" : color === "yellow" ? "bg-yellow-500" : "bg-red-500"}`} />
                                  <span className="text-xs">{item.label}</span>
                                  <span className={`ml-auto text-[10px] font-bold ${color === "green" ? "text-green-500" : color === "yellow" ? "text-yellow-500" : "text-red-500"}`}>
                                    {item.ok ? item.passText : item.failText}
                                  </span>
                                </div>
                              )})}
                            </div>
                          </div>
                        )}

                        {/* Checks tab */}
                        {lynisActiveTab === "checks" && (
                          <div className="max-h-[500px] overflow-y-auto">
                            {(!lynisReport.sections || lynisReport.sections.length === 0) ? (
                              <div className="p-6 text-center text-sm text-muted-foreground">
                                No check details available. Run an audit to generate detailed results.
                              </div>
                            ) : (
                              <div className="divide-y divide-border">
                                {lynisReport.sections.map((section, sIdx) => (
                                  <div key={sIdx}>
                                    <div className="px-3 py-2 bg-muted/30 flex items-center gap-2">
                                      <span className="text-[10px] font-bold text-cyan-500 bg-cyan-500/10 px-1.5 py-0.5 rounded">{sIdx + 1}</span>
                                      <span className="text-xs font-semibold">{section.name}</span>
                                      <span className="text-[10px] text-muted-foreground ml-auto">{section.checks.length} checks</span>
                                    </div>
                                    <div className="divide-y divide-border/50">
                                      {section.checks.map((check, cIdx) => {
                                        const st = check.status.toUpperCase()
                                        const isOk = ["OK", "FOUND", "DONE", "ENABLED", "ACTIVE", "YES", "HARDENED", "PROTECTED", "NONE", "NOT FOUND", "NOT RUNNING", "NOT ACTIVE", "NOT ENABLED", "DEFAULT", "NO"].includes(st)
                                        const isWarn = ["WARNING", "UNSAFE", "WEAK", "DIFFERENT", "DISABLED"].includes(st)
                                        const isSugg = ["SUGGESTION", "PARTIALLY HARDENED", "MEDIUM", "NON DEFAULT"].includes(st)
                                        const dotColor = isWarn ? "bg-red-500" : isSugg ? "bg-yellow-500" : isOk ? "bg-green-500" : "bg-muted-foreground"
                                        const textColor = isWarn ? "text-red-500" : isSugg ? "text-yellow-500" : isOk ? "text-green-500" : "text-muted-foreground"
                                        return (
                                          <div key={cIdx} className="flex items-center gap-2 px-3 py-1.5 hover:bg-muted/10">
                                            <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColor}`} />
                                            <span className="text-[11px] flex-1 min-w-0 truncate">{check.name}</span>
                                            {check.detail && <span className="text-[10px] text-muted-foreground/70 truncate max-w-[150px]">{check.detail}</span>}
                                            <span className={`text-[10px] font-bold flex-shrink-0 ${textColor}`}>{check.status}</span>
                                          </div>
                                        )
                                      })}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}

                        {/* Warnings tab */}
                        {lynisActiveTab === "warnings" && (
                          <div className="max-h-96 overflow-y-auto">
                            {lynisReport.warnings.length === 0 ? (
                              <div className="p-6 text-center text-sm text-muted-foreground">
                                No warnings found. Your system is well configured.
                              </div>
                            ) : (
                              <div className="divide-y divide-border">
                                {lynisReport.warnings.map((w, idx) => (
                                  <div key={idx} className="p-3 hover:bg-muted/20 transition-colors">
                                    <div className="flex items-start gap-2">
                                      <div className="w-2 h-2 rounded-full bg-red-500 flex-shrink-0 mt-1.5" />
                                      <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-0.5">
                                          <code className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-500 font-mono">{w.test_id}</code>
                                          {w.severity && (
                                            <span className="text-[10px] text-red-400">{w.severity}</span>
                                          )}
                                        </div>
                                        <p className="text-sm text-foreground">{w.description}</p>
                                        {w.solution && (
                                          <p className="text-xs text-muted-foreground mt-1">
                                            Solution: {w.solution}
                                          </p>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}

                        {/* Suggestions tab */}
                        {lynisActiveTab === "suggestions" && (
                          <div className="max-h-96 overflow-y-auto">
                            {lynisReport.suggestions.length === 0 ? (
                              <div className="p-6 text-center text-sm text-muted-foreground">
                                No suggestions. System is fully hardened.
                              </div>
                            ) : (
                              <div className="divide-y divide-border">
                                {lynisReport.suggestions.map((s, idx) => (
                                  <div key={idx} className="p-3 hover:bg-muted/20 transition-colors">
                                    <div className="flex items-start gap-2">
                                      <div className="w-2 h-2 rounded-full bg-yellow-500 flex-shrink-0 mt-1.5" />
                                      <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-0.5">
                                          <code className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/10 text-yellow-500 font-mono">{s.test_id}</code>
                                        </div>
                                        <p className="text-sm text-foreground">{s.description}</p>
                                        {s.solution && (
                                          <p className="text-xs text-muted-foreground mt-1">
                                            Solution: {s.solution}
                                          </p>
                                        )}
                                        {s.details && (
                                          <p className="text-[10px] text-muted-foreground/70 mt-0.5 font-mono">{s.details}</p>
                                        )}
                                      </div>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Run audit button - at the bottom */}
              <Button
                onClick={handleRunLynisAudit}
                disabled={lynisAuditRunning}
                className="w-full bg-cyan-600 hover:bg-cyan-700 text-white"
              >
                {lynisAuditRunning ? (
                  <>
                    <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full mr-2" />
                    Running Audit...
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4 mr-2" />
                    Run Security Audit
                  </>
                )}
              </Button>
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
