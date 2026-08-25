"use client"

import { useState, useEffect, useRef } from "react"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import {
  Shield, Lock, User, AlertCircle, CheckCircle, Info, Key, Copy, Eye, EyeOff,
  Trash2, RefreshCw, Clock, ShieldCheck, Globe, FileKey, AlertTriangle,
  Flame, Bug, Search, Download, Power, PowerOff, Plus, Minus, Activity, Settings, Ban,
  FileText, Printer, Play, BarChart3, TriangleAlert, ChevronDown, ArrowDownLeft, ArrowUpRight,
  ChevronRight, Network, Zap, Pencil, Check, X, ExternalLink,
} from "lucide-react"
import { getApiUrl, fetchApi } from "../lib/api-config"
import { TwoFactorSetup } from "./two-factor-setup"
import { ScriptTerminalModal } from "./script-terminal-modal"
import { SecureGatewaySetup } from "./secure-gateway-setup"
import { useI18n } from "../lib/i18n/provider"

interface ApiTokenEntry {
  id: string
  name: string
  token_prefix: string
  created_at: string
  expires_at: string
  revoked: boolean
  /** Backend flag: `true` when JWT verifies under the current jwt_secret,
   *  `false` when the secret has been rotated since this token was minted
   *  (token returns 401 even though it looks stored), `null` for legacy
   *  rows that pre-date the tracking field. */
  valid?: boolean | null
  /** Human reason populated when `valid === false`. */
  invalidation_reason?: string
}

// Replaces the previous `password.length < 6` check. Bumped the minimum
// floor and require at least 3 of the 4 character categories so a brute-
// force on the password hash isn't trivial. Also screens the few obvious
// strings that real users still type. Server-side enforces the same floor
// in auth_manager.setup_auth.
const _OBVIOUS_PASSWORDS = new Set([
  "password", "password1", "password123",
  "12345678", "123456789", "1234567890",
  "qwerty", "qwertyuiop", "letmein", "welcome",
  "admin", "administrator", "root", "proxmox", "proxmenux",
  "changeme", "abcdefgh",
])
function validatePasswordStrength(pw: string, t: (key: string) => string): string | null {
  if (pw.length < 10) {
    return t("securityPage.errors.passwordMinLength")
  }
  const categories = [
    /[a-z]/.test(pw),
    /[A-Z]/.test(pw),
    /\d/.test(pw),
    /[^A-Za-z0-9]/.test(pw),
  ].filter(Boolean).length
  if (categories < 3) {
    return t("securityPage.errors.passwordComplexity")
  }
  if (_OBVIOUS_PASSWORDS.has(pw.toLowerCase())) {
    return t("securityPage.errors.passwordCommon")
  }
  return null
}

export function Security() {
  const { language, t } = useI18n()
  const st = (key: string, params?: Record<string, string | number>) => t(`securityPage.${key}`, params)
  const interfaceTypeLabel = (type: string) =>
    ["physical", "bridge", "bond", "vlan", "virtual"].includes(type)
      ? t(`network.interfaceTypes.${type}`)
      : type
  const authErrorText = (message: unknown, fallbackKey: string) => {
    const raw = typeof message === "string" ? message : ""
    const normalized = raw.toLowerCase()
    if (normalized.includes("authentication is already configured")) {
      return st("errors.authAlreadyConfigured")
    }
    if (normalized.includes("invalid 2fa code")) {
      return st("errors.invalid2faCode")
    }
    if (normalized.includes("invalid password")) {
      return st("errors.invalidPassword")
    }
    return raw || st(fallbackKey)
  }
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
  const [disable2FATotpCode, setDisable2FATotpCode] = useState("")

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
  const [tokenName, setTokenName] = useState("")

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
  const [expandedRuleKey, setExpandedRuleKey] = useState<string | null>(null)
  const [editingRuleKey, setEditingRuleKey] = useState<string | null>(null)
  const [editRule, setEditRule] = useState({
    direction: "IN", action: "ACCEPT", protocol: "tcp",
    dport: "", sport: "", source: "", iface: "", comment: "", level: "host",
  })
  const [savingRule, setSavingRule] = useState(false)
  const [networkInterfaces, setNetworkInterfaces] = useState<{name: string, type: string, status: string}[]>([])

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
  const [uninstallingFail2ban, setUninstallingFail2ban] = useState(false)
  const [uninstallingLynis, setUninstallingLynis] = useState(false)
  const [showFail2banUninstallConfirm, setShowFail2banUninstallConfirm] = useState(false)
  const [showLynisUninstallConfirm, setShowLynisUninstallConfirm] = useState(false)

  // Lynis audit state
  interface LynisWarning { test_id: string; severity: string; description: string; solution: string; proxmox_context?: string; proxmox_expected?: boolean; proxmox_severity?: string }
  interface LynisSuggestion { test_id: string; description: string; solution: string; details: string; proxmox_context?: string; proxmox_expected?: boolean; proxmox_severity?: string }
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
    proxmox_adjusted_score?: number | null
    proxmox_expected_warnings?: number
    proxmox_expected_suggestions?: number
    proxmox_context_applied?: boolean
    is_complete?: boolean
    parse_issue?: string
  }
  const [lynisAuditRunning, setLynisAuditRunning] = useState(false)
  const [lynisReport, setLynisReport] = useState<LynisReport | null>(null)
  const [lynisReportLoading, setLynisReportLoading] = useState(false)
  const [lynisShowReport, setLynisShowReport] = useState(false)
  const [lynisActiveTab, setLynisActiveTab] = useState<"overview" | "warnings" | "suggestions" | "checks">("overview")
  // Tracks the active Lynis poll so a component unmount mid-audit clears
  // the setInterval. Without this the timer kept firing every 3s and
  // calling setState on an unmounted component, which logs a React
  // warning and leaks the closure.
  const lynisPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  useEffect(() => () => {
    if (lynisPollRef.current) {
      clearInterval(lynisPollRef.current)
      lynisPollRef.current = null
    }
  }, [])

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
  const [f2bTrustedNetworks, setF2bTrustedNetworks] = useState<Array<{value: string; protected: boolean}>>([])
  const [f2bDetectedIp, setF2bDetectedIp] = useState("")
  const [f2bTrustedInput, setF2bTrustedInput] = useState("")
  const [f2bSavingTrusted, setF2bSavingTrusted] = useState(false)
  const [f2bRemovingTrusted, setF2bRemovingTrusted] = useState<string | null>(null)
  const [f2bShowTrustedForm, setF2bShowTrustedForm] = useState(false)
  const [f2bEditingTrusted, setF2bEditingTrusted] = useState<string | null>(null)
  const [f2bTrustedEditInput, setF2bTrustedEditInput] = useState("")
  const [f2bTrustedNotice, setF2bTrustedNotice] = useState<{type: "success" | "error"; text: string} | null>(null)

  // SSL/HTTPS state
  const [sslEnabled, setSslEnabled] = useState(false)
  const [sslSource, setSslSource] = useState<"none" | "proxmox" | "custom">("none")
  const [sslCertPath, setSslCertPath] = useState("")
  const [sslKeyPath, setSslKeyPath] = useState("")
  const [proxmoxCertAvailable, setProxmoxCertAvailable] = useState(false)
  const [proxmoxCertInfo, setProxmoxCertInfo] = useState<{subject?: string; expires?: string; issuer?: string; is_self_signed?: boolean} | null>(null)
  const [loadingSsl, setLoadingSsl] = useState(true)
  const [configuringSsl, setConfiguringSsl] = useState(false)
  const [reloadingSsl, setReloadingSsl] = useState(false)
  const [sslRestarting, setSslRestarting] = useState(false)
  const [showCustomCertForm, setShowCustomCertForm] = useState(false)
  const [customCertPath, setCustomCertPath] = useState("")
  const [customKeyPath, setCustomKeyPath] = useState("")

  useEffect(() => {
    checkAuthStatus()
    loadApiTokens()
    loadSslStatus()
    loadFirewallStatus()
    loadNetworkInterfaces()
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
    } catch (err) {
      // Was a silent catch — left the user staring at "0 firewall rules" when
      // the request 401'd or the backend was down. At minimum surface the
      // failure in the browser console so devtools shows what went wrong.
      console.error("[security] Failed to load firewall status:", err)
    } finally {
      setFirewallLoading(false)
    }
  }

  const loadNetworkInterfaces = async () => {
    try {
      const data = await fetchApi("/api/network")
      // The API returns interfaces in separate arrays: physical_interfaces, bridge_interfaces, etc.
      // The generic "interfaces" array only holds uncategorized types and is usually empty.
      const all = [
        ...(data.physical_interfaces || []),
        ...(data.bridge_interfaces || []),
        ...(data.interfaces || []),
      ].sort((a: any, b: any) => a.name.localeCompare(b.name))
      setNetworkInterfaces(all)
    } catch {
      // Silently fail - select will just show "Any interface"
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
    } catch (err) {
      console.error("[security] Failed to load security tools (fail2ban/lynis):", err)
    } finally {
      setToolsLoading(false)
    }
  }

  const handleUninstallFail2ban = async () => {
    setUninstallingFail2ban(true)
    setError("")
    setSuccess("")
    setShowFail2banUninstallConfirm(false)
    try {
      const data = await fetchApi("/api/security/fail2ban/uninstall", {
        method: "POST",
      })
      if (data.success) {
        setSuccess(st("messages.fail2banUninstalled"))
        loadSecurityTools()
        setF2bDetails(null)
      } else {
        setError(data.message || st("errors.fail2banUninstallFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.fail2banUninstallFailed"))
    } finally {
      setUninstallingFail2ban(false)
    }
  }

  const handleUninstallLynis = async () => {
    setUninstallingLynis(true)
    setError("")
    setSuccess("")
    setShowLynisUninstallConfirm(false)
    try {
      const data = await fetchApi("/api/security/lynis/uninstall", {
        method: "POST",
      })
      if (data.success) {
        setSuccess(st("messages.lynisUninstalled"))
        loadSecurityTools()
        setLynisReport(null)
      } else {
        setError(data.message || st("errors.lynisUninstallFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.lynisUninstallFailed"))
    } finally {
      setUninstallingLynis(false)
    }
  }

  const loadFail2banDetails = async () => {
    try {
      setF2bDetailsLoading(true)
      const [detailsRes, activityRes, trustedRes] = await Promise.all([
        fetchApi("/api/security/fail2ban/details"),
        fetchApi("/api/security/fail2ban/activity"),
        fetchApi("/api/security/fail2ban/trusted-networks"),
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
      if (trustedRes.success) {
        setF2bTrustedNetworks(trustedRes.entries || [])
        setF2bDetectedIp(trustedRes.detected_ip || "")
      }
    } catch {
      // Silently fail
    } finally {
      setF2bDetailsLoading(false)
    }
  }

  const trustedNetworkError = (message?: string) => {
    if (message?.includes("already trusted")) return st("errors.trustedNetworkExists")
    if (message?.includes("Invalid IP") || message?.includes("Enter one IP")) return st("errors.invalidTrustedNetwork")
    return st("errors.updateTrustedNetworksFailed")
  }

  const handleAddTrustedNetwork = async (value?: string) => {
    const candidate = (value || f2bTrustedInput).trim()
    if (!candidate) {
      setF2bTrustedNotice({ type: "error", text: st("errors.invalidTrustedNetwork") })
      return
    }
    setF2bSavingTrusted(true)
    setF2bTrustedNotice(null)
    try {
      const data = await fetchApi("/api/security/fail2ban/trusted-networks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: candidate }),
      })
      if (data.success) {
        setF2bTrustedNotice({ type: "success", text: st("messages.trustedNetworkAdded", { value: data.value || candidate }) })
        setF2bTrustedInput("")
        setF2bShowTrustedForm(false)
        await loadFail2banDetails()
      } else {
        setF2bTrustedNotice({ type: "error", text: trustedNetworkError(data.message) })
      }
    } catch (err) {
      setF2bTrustedNotice({ type: "error", text: trustedNetworkError(err instanceof Error ? err.message : undefined) })
    } finally {
      setF2bSavingTrusted(false)
    }
  }

  const handleRemoveTrustedNetwork = async (value: string) => {
    setF2bRemovingTrusted(value)
    setF2bTrustedNotice(null)
    try {
      const data = await fetchApi("/api/security/fail2ban/trusted-networks", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value }),
      })
      if (data.success) {
        setF2bTrustedNotice({ type: "success", text: st("messages.trustedNetworkRemoved", { value }) })
        await loadFail2banDetails()
      } else {
        setF2bTrustedNotice({ type: "error", text: st("errors.updateTrustedNetworksFailed") })
      }
    } catch {
      setF2bTrustedNotice({ type: "error", text: st("errors.updateTrustedNetworksFailed") })
    } finally {
      setF2bRemovingTrusted(null)
    }
  }

  const handleUpdateTrustedNetwork = async () => {
    if (!f2bEditingTrusted || !f2bTrustedEditInput.trim()) return
    setF2bSavingTrusted(true)
    setF2bTrustedNotice(null)
    try {
      const data = await fetchApi("/api/security/fail2ban/trusted-networks", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ old_value: f2bEditingTrusted, new_value: f2bTrustedEditInput.trim() }),
      })
      if (data.success) {
        setF2bTrustedNotice({ type: "success", text: st("messages.trustedNetworkUpdated", { value: data.value }) })
        setF2bEditingTrusted(null)
        setF2bTrustedEditInput("")
        await loadFail2banDetails()
      }
    } catch (err) {
      setF2bTrustedNotice({ type: "error", text: trustedNetworkError(err instanceof Error ? err.message : undefined) })
    } finally {
      setF2bSavingTrusted(false)
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
        setSuccess(st("messages.ipUnbanned", { ip, jail: fail2banProtectionLabel(jail) }))
        loadFail2banDetails()
        loadSecurityTools()
      } else {
        setError(data.message || st("errors.unbanIpFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.unbanIpFailed"))
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
        setSuccess(st("messages.missingJailsApplied"))
        // Reload to see the new jails
        await loadFail2banDetails()
        loadSecurityTools()
      } else {
        setError(data.message || st("errors.applyMissingJailsFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.applyMissingJailsFailed"))
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
        // Poll for completion. Stash the interval id in a ref so the
        // component unmount cleanup (above) can clear it if the user
        // navigates away while the audit is still running.
        if (lynisPollRef.current) clearInterval(lynisPollRef.current)
        lynisPollRef.current = setInterval(async () => {
          try {
            const status = await fetchApi("/api/security/lynis/status")
            if (!status.running) {
              if (lynisPollRef.current) {
                clearInterval(lynisPollRef.current)
                lynisPollRef.current = null
              }
              setLynisAuditRunning(false)
              if (status.progress === "completed") {
                setSuccess(st("messages.auditCompleted"))
                loadSecurityTools()
                loadLynisReport()
              } else {
                setError(status.progress || st("errors.auditFailed"))
              }
            }
          } catch {
            if (lynisPollRef.current) {
              clearInterval(lynisPollRef.current)
              lynisPollRef.current = null
            }
            setLynisAuditRunning(false)
          }
        }, 3000)
      } else {
        setError(data.message || st("errors.startAuditFailed"))
        setLynisAuditRunning(false)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.startAuditFailed"))
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
    } catch (err) {
      console.error("[security] Failed to load Lynis report:", err)
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
        setSuccess(st("messages.jailConfigUpdated"))
        setF2bEditingJail(null)
        loadFail2banDetails()
      } else {
        setError(data.message || st("errors.updateJailConfigFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.updateJailConfigFailed"))
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
    if (s === -1) return st("values.permanent")
    if (isNaN(s) || s <= 0) return seconds
    if (s < 60) return `${s}s`
    if (s < 3600) return `${Math.floor(s / 60)}m`
    if (s < 86400) return `${Math.floor(s / 3600)}h`
    return `${Math.floor(s / 86400)}d`
  }

  const fail2banProtectionLabel = (name: string) => {
    const normalized = name.toLowerCase()
    if (normalized === "sshd" || normalized === "proxmox" || normalized === "proxmenux") {
      return st(`fail2ban.jailLabels.${normalized}`)
    }
    return name
  }

  const fail2banProtectionDescription = (name: string) => {
    const normalized = name.toLowerCase()
    if (normalized === "sshd" || normalized === "proxmox" || normalized === "proxmenux") {
      return st(`fail2ban.jailDescriptions.${normalized}`)
    }
    return ""
  }

  const fail2banActivityLabel = (action: string) => {
    const normalized = action.toLowerCase()
    if (normalized === "ban") return st("fail2ban.activity.ban")
    if (normalized === "unban") return st("fail2ban.activity.unban")
    if (normalized === "fail") return st("fail2ban.activity.fail")
    return action
  }

  const handleAddRule = async () => {
    if (!newRule.dport && !newRule.source) {
      setError(st("errors.ruleNeedsPortOrSource"))
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
        setSuccess(st("messages.ruleAdded"))
        setShowAddRule(false)
        setNewRule({ direction: "IN", action: "ACCEPT", protocol: "tcp", dport: "", sport: "", source: "", iface: "", comment: "", level: "host" })
        loadFirewallStatus()
      } else {
        setError(data.message || st("errors.addRuleFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.addRuleFailed"))
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
        setSuccess(st("messages.ruleDeleted"))
        loadFirewallStatus()
      } else {
        setError(data.message || st("errors.deleteRuleFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.deleteRuleFailed"))
    } finally {
      setDeletingRuleIdx(null)
    }
  }

  const startEditRule = (rule: any) => {
    const ruleKey = `${rule.source_file}-${rule.rule_index}`
    const comment = rule.raw?.includes("#") ? rule.raw.split("#").slice(1).join("#").trim() : ""
    setEditingRuleKey(ruleKey)
    setEditRule({
      direction: rule.direction || "IN",
      action: rule.action || "ACCEPT",
      protocol: rule.p || "tcp",
      dport: rule.dport || "",
      sport: "",
      source: rule.source || "",
      iface: rule.i || "",
      comment,
      level: rule.source_file || "host",
    })
  }

  const handleSaveEditRule = async (oldRuleIndex: number, oldLevel: string) => {
    setSavingRule(true)
    setError("")
    setSuccess("")
    try {
      const data = await fetchApi("/api/security/firewall/rules/edit", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rule_index: oldRuleIndex,
          level: oldLevel,
          new_rule: editRule,
        }),
      })
      if (data.success) {
        setSuccess(st("messages.ruleUpdated"))
        setEditingRuleKey(null)
        loadFirewallStatus()
      } else {
        setError(data.message || st("errors.updateRuleFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.updateRuleFailed"))
    } finally {
      setSavingRule(false)
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
        setSuccess(st("messages.firewallUpdated", {
          state: enable ? st("values.enabledLower") : st("values.disabledLower"),
          level: level === "cluster" ? st("values.clusterLower") : st("values.hostLower"),
        }))
        loadFirewallStatus()
      } else {
        setError(data.message || st("errors.updateFirewallFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.updateFirewallFailed"))
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
        setSuccess(st(add ? "messages.monitorPortAdded" : "messages.monitorPortRemoved"))
        loadFirewallStatus()
      } else {
        setError(data.message || st("errors.updateMonitorPortFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.updateMonitorPortFailed"))
    } finally {
      setFirewallAction(false)
    }
  }

  const checkAuthStatus = async () => {
    try {
      const response = await fetch(getApiUrl("/api/auth/status"))
      
      // Check if response is valid JSON before parsing
      if (!response.ok) return
      
      const contentType = response.headers.get("content-type")
      if (!contentType || !contentType.includes("application/json")) return
      
      const data = await response.json()
      setAuthEnabled(data.auth_enabled || false)
      setTotpEnabled(data.totp_enabled || false)
    } catch {
      // API not available (preview environment)
    }
  }

  const handleEnableAuth = async () => {
    setError("")
    setSuccess("")

    if (!username || !password) {
      setError(st("errors.fillAllFields"))
      return
    }

    if (password !== confirmPassword) {
      setError(st("errors.passwordsDoNotMatch"))
      return
    }

    const pwError = validatePasswordStrength(password, t)
    if (pwError) {
      setError(pwError)
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
        throw new Error(authErrorText(data.error || data.message, "errors.enableAuthFailed"))
      }

      localStorage.setItem("proxmenux-auth-token", data.token)
      localStorage.setItem("proxmenux-auth-setup-complete", "true")

      setSuccess(st("messages.authEnabled"))
      setAuthEnabled(true)
      setShowSetupForm(false)
      setUsername("")
      setPassword("")
      setConfirmPassword("")
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.enableAuthFailed"))
    } finally {
      setLoading(false)
    }
  }

  const handleDisableAuth = async () => {
    if (
      !confirm(
        st("confirm.disableAuth"),
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
        throw new Error(authErrorText(data.message || data.error, "errors.disableAuthFailed"))
      }

      localStorage.removeItem("proxmenux-auth-token")
      localStorage.removeItem("proxmenux-auth-setup-complete")

      setSuccess(st("messages.authDisabledReloading"))

      setTimeout(() => {
        window.location.reload()
      }, 1000)
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.disableAuthRetry"))
    } finally {
      setLoading(false)
    }
  }

  const handleChangePassword = async () => {
    setError("")
    setSuccess("")

    if (!currentPassword || !newPassword) {
      setError(st("errors.fillAllFields"))
      return
    }

    if (newPassword !== confirmNewPassword) {
      setError(st("errors.newPasswordsDoNotMatch"))
      return
    }

    const pwError = validatePasswordStrength(newPassword, t)
    if (pwError) {
      setError(pwError)
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
        throw new Error(authErrorText(data.error || data.message, "errors.changePasswordFailed"))
      }

      if (data.token) {
        localStorage.setItem("proxmenux-auth-token", data.token)
      }

      setSuccess(st("messages.passwordChanged"))
      setShowChangePassword(false)
      setCurrentPassword("")
      setNewPassword("")
      setConfirmNewPassword("")
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.changePasswordFailed"))
    } finally {
      setLoading(false)
    }
  }

  const handleDisable2FA = async () => {
    setError("")
    setSuccess("")

    if (!disable2FAPassword) {
      setError(st("errors.enterPassword"))
      return
    }
    // Mirror backend hardening (auth_manager.disable_totp): turning 2FA off must
    // require the second factor — otherwise an attacker who phished the password
    // could strip the protection. Accepts a 6-digit TOTP code or a backup code.
    if (!disable2FATotpCode) {
      setError(st("errors.enter2faOrBackup"))
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
        body: JSON.stringify({
          password: disable2FAPassword,
          totp_code: disable2FATotpCode.trim(),
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(authErrorText(data.message || data.error, "errors.disable2faFailed"))
      }

      setSuccess(st("messages.twoFactorDisabled"))
      setTotpEnabled(false)
      setShow2FADisable(false)
      setDisable2FAPassword("")
      setDisable2FATotpCode("")
      checkAuthStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.disable2faFailed"))
    } finally {
      setLoading(false)
    }
  }

  // handleLogout removed: the session-end action lives in the header's
  // AvatarMenu now (Fase 1, v1.2.2). See `components/avatar-menu.tsx`.

  const loadApiTokens = async () => {
    try {
      setLoadingTokens(true)
      const data = await fetchApi("/api/auth/api-tokens")
      if (data.success) {
        setExistingTokens(data.tokens || [])
      }
    } catch (err) {
      console.error("[security] Failed to load API tokens:", err)
    } finally {
      setLoadingTokens(false)
    }
  }

  const handleRevokeToken = async (tokenId: string) => {
    if (!confirm(st("confirm.revokeToken"))) {
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
        setSuccess(st("messages.tokenRevoked"))
        setExistingTokens((prev) => prev.filter((t) => t.id !== tokenId))
      } else {
        setError(data.message || st("errors.revokeTokenFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.revokeTokenFailed"))
    } finally {
      setRevokingTokenId(null)
    }
  }

  const handleGenerateApiToken = async () => {
    setError("")
    setSuccess("")

    if (!tokenPassword) {
      setError(st("errors.enterPassword"))
      return
    }

    if (totpEnabled && !tokenTotpCode) {
      setError(st("errors.enter2fa"))
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
          token_name: tokenName || st("apiTokens.defaultName"),
        }),
      })

      if (!data.success) {
        setError(authErrorText(data.message || data.error, "errors.generateTokenFailed"))
        return
      }

      if (!data.token) {
        setError(st("errors.noTokenReceived"))
        return
      }

      setApiToken(data.token)
      setSuccess(st("messages.apiTokenGenerated"))
      setTokenPassword("")
      setTokenTotpCode("")
      setTokenName("")
      loadApiTokens()
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.generateTokenRetry"))
    } finally {
      setGeneratingToken(false)
    }
  }

  const copyToClipboard = async (text: string) => {
    // Preferred path (HTTPS / localhost). On plain HTTP the Promise rejects,
    // so we catch and fall through to the textarea fallback.
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text)
        return true
      }
    } catch {
      // fall through to execCommand fallback
    }

    try {
      const textarea = document.createElement("textarea")
      textarea.value = text
      textarea.style.position = "fixed"
      textarea.style.left = "-9999px"
      textarea.style.top = "-9999px"
      textarea.style.opacity = "0"
      textarea.readOnly = true
      document.body.appendChild(textarea)
      textarea.focus()
      textarea.select()
      const ok = document.execCommand("copy")
      document.body.removeChild(textarea)
      return ok
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

  const isNumber = (value: unknown): value is number => (
    typeof value === "number" && Number.isFinite(value)
  )

  const getLynisScoreState = (report: LynisReport | null | undefined, fallbackScore?: number | null) => {
    const rawScore = report ? report.hardening_index : fallbackScore
    const adjustedScore = report?.proxmox_adjusted_score
    const reportHasScore = isNumber(rawScore) || isNumber(adjustedScore)
    const reportComplete = report
      ? report.is_complete !== false && report.tests_performed > 0 && reportHasScore
      : isNumber(fallbackScore)
    const displayScore = reportComplete ? (isNumber(adjustedScore) ? adjustedScore : rawScore) : null
    const hasAdjustment = reportComplete && isNumber(adjustedScore) && isNumber(rawScore) && adjustedScore !== rawScore

    return { rawScore, adjustedScore, displayScore, reportComplete, hasAdjustment }
  }

  const getActionableCount = (total: number, expected = 0) => Math.max(0, total - expected)

  const getPluralForm = (count: number) => {
    const value = Math.abs(count)
    if (language === "sk") {
      if (value === 1) return "one"
      if (value >= 2 && value <= 4) return "few"
      return "many"
    }
    return value === 1 ? "one" : "many"
  }

  const lynisCountText = (
    key: "tests" | "warnings" | "suggestions" | "testsExecuted" | "actionableWarnings" | "actionableSuggestions",
    count: number,
  ) => st(`lynis.counts.${key}.${getPluralForm(count)}`, { count })

  const generatePrintableReport = (report: LynisReport) => {
    // Escape user/server-controlled strings before they land in the printable
    // HTML. Without this, any Lynis check name / description / solution that
    // contained `<script>` or `<img onerror=...>` would execute in the admin's
    // browser when the report is opened — a stored XSS path. Numbers, CSS
    // colors and our static markup are safe; only dynamic strings are escaped.
    // See audit Tier 2 #14.
    const esc = (raw: unknown): string => {
      const s = raw == null ? "" : String(raw)
      return s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
    }

    const { rawScore, adjustedScore: adjScore, displayScore, reportComplete, hasAdjustment } = getLynisScoreState(report)
    const scoreColor = displayScore == null ? "#64748b"
      : displayScore >= 70 ? "#16a34a"
      : displayScore >= 50 ? "#ca8a04"
      : "#dc2626"
    const scoreLabel = displayScore == null ? st("lynis.report.scoreUnavailable")
      : displayScore >= 70 ? st("lynis.report.scoreGood")
      : displayScore >= 50 ? st("lynis.report.scoreModerate")
      : st("lynis.report.scoreCritical")
    const now = new Date().toLocaleString()
    const logoUrl = `${window.location.origin}/images/proxmenux-logo.png`
    const reportLang = document.documentElement.lang || "en"

    const actionableWarnings = getActionableCount(report.warnings.length, report.proxmox_expected_warnings ?? 0)
    const actionableSuggestions = getActionableCount(report.suggestions.length, report.proxmox_expected_suggestions ?? 0)
    const totalExpected = (report.proxmox_expected_warnings ?? 0) + (report.proxmox_expected_suggestions ?? 0)

    return `<!DOCTYPE html>
<html lang="${esc(reportLang)}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${st("lynis.report.title")} - ${esc(report.hostname || "ProxMenux")}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1a1a2e; background: #fff; font-size: 13px; line-height: 1.5; }
  @page { margin: 10mm; size: A4; }
  @media print {
    html, body { margin: 0 !important; padding: 0 !important; }
    .no-print { display: none !important; }
    .page-break { page-break-before: always; }
    * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
    body { font-size: 11px; padding-top: 0; }
    .section { margin-bottom: 16px; }
    /* Darken light grays for PDF readability */
    .rpt-header-left p, .rpt-header-right { color: #374151; }
    .rpt-header-right .rid { color: #4b5563; }
    .exec-text p { color: #374151; }
    .score-bar-labels { color: #4b5563; }
    .card-label { color: #4b5563; }
    .card-sub { color: #374151; }
    .f-num { color: #4b5563; }
    .f-sol { color: #374151; }
    .f-sol strong { color: #1e293b; }
    .f-det { color: #4b5563; }
    .cat-cnt { color: #4b5563; }
    .chk-tbl th { color: #374151; }
    .chk-det { color: #4b5563; }
    .rpt-footer { color: #4b5563; }
    /* Force inline style overrides for print */
    [style*="color:#64748b"] { color: #374151 !important; }
    [style*="color:#94a3b8"] { color: #4b5563 !important; }
    [style*="color: #64748b"] { color: #374151 !important; }
    [style*="color: #94a3b8"] { color: #4b5563 !important; }
    /* Ensure all greens are exactly the same shade in print */
    [style*="color:#16a34a"], [style*="color: #16a34a"] { color: #16a34a !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    [style*="border-color:#16a34a"], [style*="border-color: #16a34a"] { border-color: #16a34a !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    [style*="background:#16a34a"], [style*="background: #16a34a"] { background: #16a34a !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .score-ring, .score-bar-fill, .card-value, .chk-tbl td { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    /* Ensure red and yellow consistency too */
    [style*="color:#dc2626"] { color: #dc2626 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    [style*="color:#ca8a04"] { color: #ca8a04 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    [style*="color:#0891b2"] { color: #0891b2 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
  @media screen {
    body { max-width: 1000px; margin: 0 auto; padding: 24px 32px; padding-top: 64px; }
  }
  
  /* Top bar for screen only */
  .top-bar {
    position: fixed; top: 0; left: 0; right: 0; background: #0f172a; color: #e2e8f0;
    padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; z-index: 100;
    font-size: 13px;
  }
  .top-bar-left { display: flex; align-items: center; gap: 12px; }
  .top-bar-title { font-weight: 600; }
  .top-bar-subtitle { font-size: 11px; color: #94a3b8; display: none; }
  .top-bar button {
    background: #06b6d4; color: #fff; border: none; padding: 10px 20px; border-radius: 6px;
    font-size: 14px; font-weight: 600; cursor: pointer;
  }
  .top-bar button:hover { background: #0891b2; }
  .hide-mobile { }
  @media (min-width: 640px) {
    .top-bar { padding: 12px 24px; }
    .top-bar-subtitle { display: block; }
  }
  @media (max-width: 639px) {
    .hide-mobile { display: none !important; }
  }
  @media print { .top-bar { display: none; } body { padding-top: 0; } }

  /* Header */
  .rpt-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 0; border-bottom: 3px solid #0f172a; margin-bottom: 22px;
  }
  .rpt-header-left { display: flex; align-items: center; gap: 14px; }
  .rpt-header-left img { height: 44px; width: auto; }
  .rpt-header-left h1 { font-size: 22px; font-weight: 700; color: #0f172a; }
  .rpt-header-left p { font-size: 11px; color: #64748b; }
  .rpt-header-right { text-align: right; font-size: 11px; color: #64748b; line-height: 1.6; }
  .rpt-header-right .rid { font-family: monospace; font-size: 10px; color: #94a3b8; }

  /* Sections */
  .section { margin-bottom: 22px; }
  .section-title {
    font-size: 14px; font-weight: 700; color: #0f172a; text-transform: uppercase;
    letter-spacing: 0.05em; padding-bottom: 5px; border-bottom: 2px solid #e2e8f0; margin-bottom: 12px;
  }

  /* Executive summary */
  .exec-box {
    display: flex; align-items: center; gap: 24px; padding: 20px;
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 16px;
  }
  .score-ring {
    width: 96px; height: 96px; border-radius: 50%; display: flex; flex-direction: column;
    align-items: center; justify-content: center; border: 4px solid; flex-shrink: 0;
  }
  .score-num { font-size: 32px; font-weight: 800; line-height: 1; }
  .score-lbl { font-size: 9px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; }
  .exec-text { flex: 1; }
  .exec-text h3 { font-size: 16px; margin-bottom: 4px; }
  .exec-text p { font-size: 12px; color: #64748b; line-height: 1.5; }

  /* Score bar */
  .score-bar-wrap { margin: 10px 0 6px; }
  .score-bar-bg { height: 10px; background: #e2e8f0; border-radius: 5px; position: relative; overflow: hidden; }
  .score-bar-fill { height: 100%; border-radius: 5px; }
  .score-bar-labels { display: flex; justify-content: space-between; font-size: 9px; color: #94a3b8; margin-top: 3px; }

  /* Grids */
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .grid-4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .card { padding: 10px 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; }
  .card-label { font-size: 10px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 2px; }
  .card-value { font-size: 13px; font-weight: 600; color: #0f172a; }
  .card-c { text-align: center; }
  .card-c .card-value { font-size: 20px; font-weight: 800; }
  .card-c .card-label { margin-top: 3px; margin-bottom: 0; }
  .card-sub { font-size: 9px; color: #64748b; margin-top: 2px; }
  .card-sub.pve { color: #0891b2; }

  /* Findings */
  .finding { padding: 10px 12px; margin-bottom: 6px; border-left: 4px solid; border-radius: 0 4px 4px 0; page-break-inside: avoid; }
  .f-warn { border-color: #dc2626; background: #fef2f2; }
  .f-sugg { border-color: #ca8a04; background: #fefce8; }
  .f-pve { border-color: #06b6d4; background: #ecfeff; opacity: 0.85; }
  .f-hdr { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap; }
  .f-num { font-size: 10px; color: #94a3b8; font-weight: 700; }
  .f-id { font-family: 'Courier New', monospace; font-size: 10px; background: #e2e8f0; padding: 1px 6px; border-radius: 3px; font-weight: 600; }
  .f-id.pve { background: #ecfeff; color: #0891b2; }
  .f-tag { font-size: 9px; padding: 2px 6px; border-radius: 4px; font-weight: 600; }
  .f-tag-pve { background: #ecfeff; color: #0891b2; }
  .f-tag-low { background: #fefce8; color: #a16207; }
  .f-tag-sev { color: #dc2626; font-weight: 700; text-transform: uppercase; }
  .f-desc { font-size: 12px; color: #1e293b; }
  .f-ctx { font-size: 10px; color: #0891b2; margin-top: 3px; }
  .f-ctx strong { font-weight: 700; }
  .f-sol { font-size: 11px; color: #64748b; margin-top: 3px; }
  .f-sol strong { color: #475569; }
  .f-det { font-size: 10px; font-family: 'Courier New', monospace; color: #94a3b8; margin-top: 2px; }

  /* Category tables */
  .cat-head { display: flex; align-items: center; gap: 8px; padding: 6px 10px; background: #f1f5f9; border-radius: 4px; margin-bottom: 6px; }
  .cat-num { font-size: 10px; font-weight: 700; color: #0891b2; background: #ecfeff; padding: 2px 6px; border-radius: 3px; }
  .cat-name { font-size: 12px; font-weight: 700; color: #0f172a; }
  .cat-cnt { font-size: 10px; color: #94a3b8; margin-left: auto; }
  .chk-tbl { width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 14px; }
  .chk-tbl th { text-align: left; padding: 4px 8px; font-size: 10px; color: #64748b; font-weight: 600; border-bottom: 1px solid #e2e8f0; }
  .chk-tbl th:last-child { text-align: right; width: 120px; }
  .chk-tbl td { padding: 3px 8px; border-bottom: 1px solid #f1f5f9; color: #1e293b; }
  .chk-tbl td:last-child { text-align: right; font-weight: 700; font-size: 10px; }
  .chk-tbl tr.warn { background: #fef2f2; }
  .chk-tbl tr.sugg { background: #fefce8; }
  .chk-det { color: #94a3b8; font-size: 10px; }

  /* Footer */
  .rpt-footer {
    margin-top: 32px; padding-top: 12px; border-top: 1px solid #e2e8f0;
    display: flex; justify-content: space-between; font-size: 10px; color: #94a3b8;
  }
</style>
</head>
<body>

<script>
function pmxPrint(){
  try { window.print(); }
  catch(e) {
    // Fallback hint
    var isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
    var el = document.getElementById('pmx-print-hint');
    if(el) el.textContent = isMac ? ${JSON.stringify(st("lynis.report.useCmdP"))} : ${JSON.stringify(st("lynis.report.useCtrlP"))};
  }
}
</script>
<div class="top-bar no-print">
  <div style="display:flex;align-items:center;gap:12px;">
    <strong>${st("lynis.report.brandTitle")}</strong>
    <span id="pmx-print-hint" class="hide-mobile" style="font-size:11px;opacity:0.7;">${st("lynis.report.reviewHint")}</span>
  </div>
  <button onclick="pmxPrint()">${st("lynis.printSavePdf")}</button>
</div>

<!-- Header -->
<div class="rpt-header">
  <div class="rpt-header-left">
    <img src="${logoUrl}" alt="ProxMenux" onerror="this.style.display='none'" />
    <div>
      <h1>${st("lynis.report.title")}</h1>
      <p>${st("lynis.report.subtitle")}</p>
    </div>
  </div>
  <div class="rpt-header-right">
    <div><strong>${st("lynis.report.date")}:</strong> ${esc(now)}</div>
    <div><strong>${st("lynis.report.auditor")}:</strong> Lynis ${esc(report.lynis_version || "")}</div>
    <div class="rid">ID: PMXA-${Date.now().toString(36).toUpperCase()}</div>
  </div>
</div>

<!-- 1. Executive Summary -->
<div class="section">
  <div class="section-title">1. ${st("lynis.report.executiveSummary")}</div>
  <div class="exec-box">
    <div class="score-ring" style="border-color:${scoreColor};color:${scoreColor};">
      <div class="score-num">${displayScore ?? "N/A"}</div>
      <div class="score-lbl">${scoreLabel}</div>
    </div>
    <div class="exec-text">
      <h3>${st("lynis.report.hardeningAssessment")}${hasAdjustment ? ` ${st("lynis.proxmoxAdjustedParen")}` : ""}</h3>
      ${reportComplete ? `
      <p>
        ${st("lynis.report.auditOf")} <strong>${esc(report.hostname || t("common.unknown"))}</strong>
        ${st("lynis.report.running")} <strong>${esc(report.os_fullname || `${report.os_name} ${report.os_version}`.trim() || st("lynis.report.unknownOs"))}</strong> (Proxmox VE).
        ${lynisCountText("testsExecuted", report.tests_performed)}
        ${actionableWarnings > 0 ? `<strong style="color:#dc2626;">${lynisCountText("actionableWarnings", actionableWarnings)}</strong>` : `<strong style="color:#16a34a;">${st("lynis.report.noActionableWarnings")}</strong>`}
        ${st("lynis.report.and")} <strong style="color:${actionableSuggestions > 0 ? '#ca8a04' : '#16a34a'};">${lynisCountText("actionableSuggestions", actionableSuggestions)}</strong>.
        ${totalExpected > 0 ? `<span style="color:#0891b2;">${st("lynis.report.expectedBehavior", { count: totalExpected })}</span>` : ""}
      </p>` : `
      <p style="color:#ca8a04;">
        ${st("lynis.report.incompleteDescription")}
      </p>`}
      ${hasAdjustment ? `
      <div class="score-bar-wrap">
        <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:3px;">
          <span style="color:#64748b;">${st("lynis.report.lynisRaw")}: ${rawScore}/100</span>
          <span style="color:${scoreColor};font-weight:700;">${st("lynis.report.pveAdjusted")}: ${displayScore}/100</span>
        </div>
        <div class="score-bar-bg">
          <div class="score-bar-fill" style="width:${displayScore}%;background:${scoreColor};"></div>
        </div>
        <div class="score-bar-labels"><span>${st("lynis.report.rangeCritical")}</span><span>${st("lynis.report.rangeModerate")}</span><span>${st("lynis.report.rangeGood")}</span><span>100</span></div>
      </div>` : ""}
    </div>
  </div>
</div>

<!-- 2. System Information -->
<div class="section">
  <div class="section-title">2. ${st("lynis.report.systemInformation")}</div>
  <div class="grid-3">
    <div class="card"><div class="card-label">${st("lynis.hostname")}</div><div class="card-value">${esc(report.hostname || "N/A")}</div></div>
    <div class="card"><div class="card-label">${st("lynis.report.operatingSystem")}</div><div class="card-value">${esc(report.os_fullname || `${report.os_name} ${report.os_version}`.trim() || "N/A")}</div></div>
    <div class="card"><div class="card-label">${esc(st("lynis.kernel"))}</div><div class="card-value">${esc(report.kernel_version || "N/A")}</div></div>
    <div class="card"><div class="card-label">${st("lynis.report.lynisVersion")}</div><div class="card-value">${esc(report.lynis_version || "N/A")}</div></div>
    <div class="card"><div class="card-label">${st("lynis.report.reportDate")}</div><div class="card-value">${esc(report.datetime_start ? report.datetime_start.replace("T", " ").substring(0, 16) : "N/A")}</div></div>
    <div class="card"><div class="card-label">${st("lynis.report.testsPerformed")}</div><div class="card-value">${reportComplete ? report.tests_performed : "N/A"}</div></div>
  </div>
</div>

<!-- 3. Security Posture -->
<div class="section">
  <div class="section-title">3. ${st("lynis.report.securityPosture")}</div>
  <div class="grid-4">
    <div class="card card-c">
      <div class="card-value" style="color:${scoreColor};">${displayScore ?? "N/A"}${displayScore == null ? "" : `<span style="font-size:10px;color:#64748b;">/100</span>`}</div>
      <div class="card-label">${st("lynis.report.proxmoxScoreWithLabel", { label: scoreLabel })}</div>
      ${hasAdjustment ? `<div class="card-sub">${st("lynis.report.lynisRaw")}: ${rawScore}</div>` : ""}
    </div>
    <div class="card card-c">
      <div class="card-value" style="color:${actionableWarnings > 0 ? "#dc2626" : "#16a34a"};">${actionableWarnings}</div>
      <div class="card-label">${st("lynis.report.actionableWarningsLabel")}</div>
      ${(report.proxmox_expected_warnings ?? 0) > 0 ? `<div class="card-sub pve">${st("lynis.pveExpectedPlus", { count: report.proxmox_expected_warnings ?? 0 })}</div>` : ""}
    </div>
    <div class="card card-c">
      <div class="card-value" style="color:${actionableSuggestions > 0 ? "#ca8a04" : "#16a34a"};">${actionableSuggestions}</div>
      <div class="card-label">${st("lynis.report.actionableSuggestionsLabel")}</div>
      ${(report.proxmox_expected_suggestions ?? 0) > 0 ? `<div class="card-sub pve">${st("lynis.pveExpectedPlus", { count: report.proxmox_expected_suggestions ?? 0 })}</div>` : ""}
    </div>
    <div class="card card-c">
      <div class="card-value">${reportComplete ? report.tests_performed : "N/A"}</div>
      <div class="card-label">${st("lynis.report.testsPerformed")}</div>
    </div>
  </div>
  <div class="grid-3">
    <div class="card card-c">
      <div class="card-label">${st("lynis.firewall")}</div>
      <div class="card-value" style="color:${report.firewall_active ? "#16a34a" : "#dc2626"};font-size:13px;">${report.firewall_active ? st("values.active") : st("values.inactive")}</div>
    </div>
    <div class="card card-c">
      <div class="card-label">${st("lynis.malwareScanner")}</div>
      <div class="card-value" style="color:${report.malware_scanner ? "#16a34a" : "#ca8a04"};font-size:13px;">${report.malware_scanner ? st("values.installed") : st("lynis.malwareScannerNotInstalled")}</div>
    </div>
    <div class="card card-c">
      <div class="card-label">${st("lynis.packages")}</div>
      <div class="card-value" style="font-size:13px;">${esc(report.installed_packages || "N/A")}</div>
    </div>
  </div>
</div>

<!-- Warnings -->
<div class="section page-break">
  <div class="section-title">4. ${st("lynis.warnings")} (${report.warnings.length}${(report.proxmox_expected_warnings ?? 0) > 0 ? ` - ${st("lynis.actionableCount", { count: actionableWarnings })}` : ""})</div>
  <p style="font-size:11px;color:#64748b;margin-bottom:10px;">${st("lynis.report.warningsDescription")}</p>
  ${report.warnings.length === 0 ?
    `<div style="padding:16px;text-align:center;color:#16a34a;background:#f0fdf4;border-radius:6px;border:1px solid #bbf7d0;">${st("lynis.report.noWarningsDetected")}</div>` :
    report.warnings.map((w, i) => `
    <div class="finding ${w.proxmox_expected ? 'f-pve' : 'f-warn'}">
      <div class="f-hdr">
        <span class="f-num">#${i + 1}</span>
        <span class="f-id${w.proxmox_expected ? ' pve' : ''}">${esc(w.test_id)}</span>
        ${w.proxmox_expected ? `<span class="f-tag f-tag-pve">${st("lynis.pveExpected")}</span>` : ''}
        ${!w.proxmox_expected && w.proxmox_severity === "low" ? `<span class="f-tag f-tag-low">${st("lynis.lowRisk")}</span>` : ''}
        ${!w.proxmox_expected && !w.proxmox_severity && w.severity ? `<span class="f-tag f-tag-sev">${esc(w.severity)}</span>` : ""}
      </div>
      <div class="f-desc">${esc(w.description)}</div>
      ${w.proxmox_context ? `<div class="f-ctx"><strong>Proxmox:</strong> ${esc(w.proxmox_context)}</div>` : ""}
      ${w.solution ? `<div class="f-sol"><strong>${st("lynis.report.recommendation")}:</strong> ${esc(w.solution)}</div>` : ""}
    </div>`).join("")}
</div>

<!-- Suggestions -->
<div class="section page-break">
  <div class="section-title">5. ${st("lynis.suggestions")} (${report.suggestions.length}${(report.proxmox_expected_suggestions ?? 0) > 0 ? ` - ${st("lynis.actionableCount", { count: actionableSuggestions })}` : ""})</div>
  <p style="font-size:11px;color:#64748b;margin-bottom:10px;">${st("lynis.report.suggestionsDescription")}${(report.proxmox_expected_suggestions ?? 0) > 0 ? ` <span style="color:#0891b2;">${st("lynis.report.expectedBehavior", { count: report.proxmox_expected_suggestions ?? 0 })}</span>` : ""}</p>
  ${report.suggestions.length === 0 ?
    `<div style="padding:16px;text-align:center;color:#16a34a;background:#f0fdf4;border-radius:6px;border:1px solid #bbf7d0;">${st("lynis.noSuggestions")}</div>` :
    report.suggestions.map((s, i) => `
    <div class="finding ${s.proxmox_expected ? 'f-pve' : 'f-sugg'}">
      <div class="f-hdr">
        <span class="f-num">#${i + 1}</span>
        <span class="f-id${s.proxmox_expected ? ' pve' : ''}">${esc(s.test_id)}</span>
        ${s.proxmox_expected ? `<span class="f-tag f-tag-pve">${st("lynis.pveExpected")}</span>` : ''}
        ${!s.proxmox_expected && s.proxmox_severity === "low" ? `<span class="f-tag f-tag-low">${st("lynis.lowPriority")}</span>` : ''}
      </div>
      <div class="f-desc">${esc(s.description)}</div>
      ${s.proxmox_context ? `<div class="f-ctx"><strong>Proxmox:</strong> ${esc(s.proxmox_context)}</div>` : ""}
      ${s.solution ? `<div class="f-sol"><strong>${st("lynis.report.recommendation")}:</strong> ${esc(s.solution)}</div>` : ""}
      ${s.details ? `<div class="f-det">${esc(s.details)}</div>` : ""}
    </div>`).join("")}
</div>

<!-- Detailed Checks -->
${(report.sections && report.sections.length > 0) ? `
<div class="section page-break">
  <div class="section-title">6. ${st("lynis.report.detailedChecks")} (${st("lynis.report.categoriesCount", { count: report.sections.length })})</div>
  <p style="font-size:11px;color:#64748b;margin-bottom:12px;">${st("lynis.report.detailedChecksDescription")}</p>
  ${report.sections.map((section, sIdx) => `
  <div style="margin-bottom:10px;page-break-inside:avoid;">
    <div class="cat-head">
      <span class="cat-num">${sIdx + 1}</span>
      <span class="cat-name">${esc(section.name)}</span>
      <span class="cat-cnt">${st("lynis.checksCount", { count: section.checks.length })}</span>
    </div>
    <table class="chk-tbl">
      <thead><tr><th>${st("lynis.report.check")}</th><th>${st("lynis.report.status")}</th></tr></thead>
      <tbody>
        ${section.checks.map(check => {
          const st = check.status.toUpperCase()
          const isWarn = ["WARNING", "UNSAFE", "WEAK", "DIFFERENT", "DISABLED"].includes(st)
          const isSugg = ["SUGGESTION", "PARTIALLY HARDENED", "MEDIUM", "NON DEFAULT"].includes(st)
          const isOk = ["OK", "FOUND", "DONE", "ENABLED", "ACTIVE", "YES", "HARDENED", "PROTECTED"].includes(st)
          const color = isWarn ? "#dc2626" : isSugg ? "#ca8a04" : isOk ? "#16a34a" : "#64748b"
          const cls = isWarn ? ' class="warn"' : isSugg ? ' class="sugg"' : ""
          return `<tr${cls}>
            <td>${esc(check.name)}${check.detail ? ` <span class="chk-det">(${esc(check.detail)})</span>` : ""}</td>
            <td style="color:${color};">${esc(check.status)}</td>
          </tr>`
        }).join("")}
      </tbody>
    </table>
  </div>`).join("")}
</div>` : ""}

<!-- Footer -->
<div class="rpt-footer">
  <div>${st("lynis.report.generatedBy")} ProxMenux Monitor / Lynis ${esc(report.lynis_version || "")}</div>
  <div>${esc(now)}</div>
  <div style="font-style:italic;">${st("lynis.report.confidential")}</div>
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
    } catch (err) {
      console.error("[security] Failed to load SSL status:", err)
    } finally {
      setLoadingSsl(false)
    }
  }

  // Wait for the monitor service to come back on the new protocol, then redirect
  const waitForServiceAndRedirect = async (newProtocol: "https" | "http") => {
    const host = window.location.hostname
    const port = window.location.port || "8008"
    const newUrl = `${newProtocol}://${host}:${port}${window.location.pathname}`
    
    // Wait for service to restart (try up to 30 seconds)
    const maxAttempts = 15
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise(r => setTimeout(r, 2000))
      try {
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 3000)
        const resp = await fetch(`${newProtocol}://${host}:${port}/api/ssl/status`, {
          signal: controller.signal,
          // For self-signed certs, we need to handle rejection
          mode: "no-cors"
        }).catch(() => null)
        clearTimeout(timeout)
        
        // For HTTPS with self-signed certs, even a failed CORS request means the server is up
        if (resp || newProtocol === "https") {
          // Give it one more second to fully stabilize
          await new Promise(r => setTimeout(r, 1000))
          window.location.href = newUrl
          return
        }
      } catch {
        // Server not ready yet, keep waiting
      }
    }
    
    // Fallback: redirect anyway after timeout
    window.location.href = newUrl
  }

  const handleEnableSsl = async (source: "proxmox" | "custom", certPath?: string, keyPath?: string) => {
    setConfiguringSsl(true)
    setError("")
    setSuccess("")

    try {
      const body: Record<string, string | boolean> = { source, auto_restart: true }
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
        setSslEnabled(true)
        setSslSource(source)
        setShowCustomCertForm(false)
        setCustomCertPath("")
        setCustomKeyPath("")
        setConfiguringSsl(false)
        setSslRestarting(true)
        setSuccess(st("messages.sslEnabledRestarting"))
        await waitForServiceAndRedirect("https")
      } else {
        setError(data.message || st("errors.configureSslFailed"))
        setConfiguringSsl(false)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.configureSslFailed"))
      setConfiguringSsl(false)
    }
  }

  const handleDisableSsl = async () => {
    if (!confirm(st("confirm.disableHttps"))) {
      return
    }

    setConfiguringSsl(true)
    setError("")
    setSuccess("")

    try {
      const data = await fetchApi("/api/ssl/disable", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auto_restart: true }),
      })

      if (data.success) {
        setSslEnabled(false)
        setSslSource("none")
        setSslCertPath("")
        setSslKeyPath("")
        setConfiguringSsl(false)
        setSslRestarting(true)
        setSuccess(st("messages.sslDisabledRestarting"))
        await waitForServiceAndRedirect("http")
      } else {
        setError(data.message || st("errors.disableSslFailed"))
        setConfiguringSsl(false)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.disableSslFailed"))
      setConfiguringSsl(false)
    }
  }

  const handleReloadSsl = async () => {
    setReloadingSsl(true)
    setError("")
    setSuccess("")

    try {
      const data = await fetchApi("/api/ssl/reload", {
        method: "POST",
      })

      if (data.success) {
        setSslCertPath(data.cert_path || sslCertPath)
        setSslKeyPath(data.key_path || sslKeyPath)
        if (data.cert_info) {
          setProxmoxCertInfo(data.cert_info)
        }
        setSuccess(data.changed
          ? st("messages.sslCertificateReloaded")
          : st("messages.sslCertificateUnchanged"))
      } else {
        setError(data.message || st("errors.reloadSslFailed"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : st("errors.reloadSslFailed"))
    } finally {
      setReloadingSsl(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">{st("title")}</h1>
        <p className="text-muted-foreground mt-2">{st("description")}</p>
      </div>

      {/* ── ProxMenux Monitor Security Group ── */}
      <div className="flex items-center gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-cyan-500">ProxMenux Monitor</h2>
        <div className="flex-1 h-px bg-cyan-500/20" />
      </div>

      {/* Authentication Settings */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-blue-500" />
            <CardTitle>{st("auth.title")}</CardTitle>
          </div>
          <CardDescription>{st("auth.description")}</CardDescription>
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
                <p className="font-medium">{st("auth.statusTitle")}</p>
                <p className="text-sm text-muted-foreground">
                  {authEnabled ? st("auth.passwordEnabled") : st("auth.noPasswordProtection")}
                </p>
              </div>
            </div>
            <div
              className={`px-3 py-1 rounded-full text-sm font-medium ${authEnabled ? "bg-green-500/10 text-green-500" : "bg-gray-500/10 text-gray-500"}`}
            >
              {authEnabled ? st("values.enabled") : st("values.disabled")}
            </div>
          </div>

          {!authEnabled && !showSetupForm && (
            <div className="space-y-3">
              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-start gap-2">
                <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                <p className="text-sm text-blue-500">
                  {st("auth.enableHint")}
                </p>
              </div>
              <Button onClick={() => setShowSetupForm(true)} className="bg-blue-500 hover:bg-blue-600">
                <Shield className="h-4 w-4 mr-2" />
                {st("auth.enable")}
              </Button>
            </div>
          )}

          {!authEnabled && showSetupForm && (
            <div className="space-y-4 border border-border rounded-lg p-4">
              <h3 className="font-semibold">{st("auth.setupTitle")}</h3>

              <div className="space-y-2">
                <Label htmlFor="setup-username">{st("auth.username")}</Label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="setup-username"
                    type="text"
                    placeholder={st("auth.usernamePlaceholder")}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="pl-10"
                    disabled={loading}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="setup-password">{st("auth.password")}</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="setup-password"
                    type="password"
                    placeholder={st("auth.passwordPlaceholder")}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-10"
                    disabled={loading}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="setup-confirm-password">{st("auth.confirmPassword")}</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="setup-confirm-password"
                    type="password"
                    placeholder={st("auth.confirmPasswordPlaceholder")}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="pl-10"
                    disabled={loading}
                  />
                </div>
              </div>

              <div className="flex gap-2">
                <Button onClick={handleEnableAuth} className="flex-1 bg-blue-500 hover:bg-blue-600" disabled={loading}>
                  {loading ? st("auth.enabling") : st("auth.enableShort")}
                </Button>
                <Button onClick={() => setShowSetupForm(false)} variant="outline" className="flex-1" disabled={loading}>
                  {t("actions.cancel")}
                </Button>
              </div>
            </div>
          )}

          {authEnabled && (
            <div className="space-y-3">
              {/* Logout moved to the header AvatarMenu (Fase 1, v1.2.2)
                  so the session-end action lives in one consistent place
                  on every page. The Security panel keeps the actions
                  that affect the *account* itself (password, 2FA, disable
                  auth), not the session. */}

              {!showChangePassword && (
                <Button onClick={() => setShowChangePassword(true)} variant="outline">
                  <Lock className="h-4 w-4 mr-2" />
                  {st("auth.changePassword")}
                </Button>
              )}

              {showChangePassword && (
                <div className="space-y-4 border border-border rounded-lg p-4">
                  <h3 className="font-semibold">{st("auth.changePassword")}</h3>

                  <div className="space-y-2">
                    <Label htmlFor="current-password">{st("auth.currentPassword")}</Label>
                    <div className="relative">
                      <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="current-password"
                        type="password"
                        placeholder={st("auth.currentPasswordPlaceholder")}
                        value={currentPassword}
                        onChange={(e) => setCurrentPassword(e.target.value)}
                        className="pl-10"
                        disabled={loading}
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="new-password">{st("auth.newPassword")}</Label>
                    <div className="relative">
                      <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="new-password"
                        type="password"
                        placeholder={st("auth.newPasswordPlaceholder")}
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        className="pl-10"
                        disabled={loading}
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="confirm-new-password">{st("auth.confirmNewPassword")}</Label>
                    <div className="relative">
                      <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="confirm-new-password"
                        type="password"
                        placeholder={st("auth.confirmNewPasswordPlaceholder")}
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
                      {loading ? st("auth.changing") : st("auth.changePassword")}
                    </Button>
                    <Button
                      onClick={() => setShowChangePassword(false)}
                      variant="outline"
                      className="flex-1"
                      disabled={loading}
                    >
                      {t("actions.cancel")}
                    </Button>
                  </div>
                </div>
              )}

              {!totpEnabled && (
                <div className="space-y-3">
                  <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-start gap-2">
                    <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                    <div className="text-sm text-blue-400">
                      <p className="font-medium mb-1">{st("twoFactor.title")}</p>
                      <p className="text-blue-300">
                        {st("twoFactor.hint")}
                      </p>
                    </div>
                  </div>

                  <Button onClick={() => setShow2FASetup(true)} variant="outline">
                    <Shield className="h-4 w-4 mr-2" />
                    {st("twoFactor.enable")}
                  </Button>
                </div>
              )}

              {totpEnabled && (
                <div className="space-y-3">
                  <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-3 flex items-center gap-2">
                    <CheckCircle className="h-5 w-5 text-green-500" />
                    <p className="text-sm text-green-500 font-medium">{st("twoFactor.enabled")}</p>
                  </div>

                  {!show2FADisable && (
                    <Button onClick={() => setShow2FADisable(true)} variant="outline">
                      <Shield className="h-4 w-4 mr-2" />
                      {st("twoFactor.disable")}
                    </Button>
                  )}

                  {show2FADisable && (
                    <div className="space-y-4 border border-border rounded-lg p-4">
                      <h3 className="font-semibold">{st("twoFactor.disableTitle")}</h3>
                      <p className="text-sm text-muted-foreground">
                        {st("twoFactor.disableDescription")}
                      </p>

                      <div className="space-y-2">
                        <Label htmlFor="disable-2fa-password">{st("auth.password")}</Label>
                        <div className="relative">
                          <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                          <Input
                            id="disable-2fa-password"
                            type="password"
                            placeholder={st("auth.enterYourPassword")}
                            value={disable2FAPassword}
                            onChange={(e) => setDisable2FAPassword(e.target.value)}
                            className="pl-10"
                            disabled={loading}
                          />
                        </div>
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="disable-2fa-totp">{st("twoFactor.codeOrBackup")}</Label>
                        <Input
                          id="disable-2fa-totp"
                          type="text"
                          inputMode="numeric"
                          autoComplete="one-time-code"
                          placeholder={st("twoFactor.codeOrBackupPlaceholder")}
                          value={disable2FATotpCode}
                          onChange={(e) => setDisable2FATotpCode(e.target.value)}
                          disabled={loading}
                        />
                      </div>

                      <div className="flex gap-2">
                        <Button onClick={handleDisable2FA} variant="destructive" className="flex-1" disabled={loading}>
                          {loading ? st("twoFactor.disabling") : st("twoFactor.disable")}
                        </Button>
                        <Button
                          onClick={() => {
                            setShow2FADisable(false)
                            setDisable2FAPassword("")
                            setDisable2FATotpCode("")
                            setError("")
                          }}
                          variant="outline"
                          className="flex-1"
                          disabled={loading}
                        >
                          {t("actions.cancel")}
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              <Button onClick={handleDisableAuth} variant="destructive" disabled={loading}>
                {st("auth.disable")}
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
            <CardTitle>{st("ssl.title")}</CardTitle>
          </div>
          <CardDescription>
            {st("ssl.description")}
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
                      {sslEnabled ? st("ssl.httpsEnabled") : st("ssl.httpNoSsl")}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {sslEnabled
                        ? st("ssl.usingCertificate", { source: sslSource === "proxmox" ? st("ssl.proxmoxHost") : st("ssl.custom") })
                        : st("ssl.unencryptedHttp")}
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
                    {st("ssl.activeCertificate")}
                  </div>
                  <div className="grid gap-1 text-sm text-muted-foreground">
                    <p><span className="font-medium text-foreground">{st("ssl.cert")}:</span> <code className="text-xs">{sslCertPath}</code></p>
                    <p><span className="font-medium text-foreground">{st("ssl.key")}:</span> <code className="text-xs">{sslKeyPath}</code></p>
                  </div>
                  <div className="flex flex-wrap gap-2 pt-2">
                    <Button
                      onClick={handleReloadSsl}
                      variant="outline"
                      size="sm"
                      disabled={configuringSsl || reloadingSsl || sslRestarting}
                    >
                      <RefreshCw className={`h-4 w-4 mr-2 ${reloadingSsl ? "animate-spin" : ""}`} />
                      {reloadingSsl ? st("ssl.updatingCertificate") : st("ssl.updateCertificate")}
                    </Button>
                    <Button
                      onClick={handleDisableSsl}
                      variant="outline"
                      size="sm"
                      disabled={configuringSsl || reloadingSsl || sslRestarting}
                      className="text-red-500 border-red-500/30 hover:bg-red-500/10 bg-transparent"
                    >
                      {configuringSsl ? st("ssl.disabling") : sslRestarting ? st("ssl.restarting") : st("ssl.disableHttps")}
                    </Button>
                  </div>
                </div>
              )}

              {/* Proxmox certificate detection */}
              {!sslEnabled && proxmoxCertAvailable && (
                <div className="space-y-3 p-4 border border-border rounded-lg">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-green-500" />
                    <h3 className="font-semibold text-sm">{st("ssl.proxmoxCertDetected")}</h3>
                  </div>

                  {proxmoxCertInfo && (
                    <div className="grid gap-1 text-sm text-muted-foreground bg-muted/50 p-3 rounded">
                      {proxmoxCertInfo.subject && (
                        <p><span className="font-medium text-foreground">{st("ssl.subject")}:</span> {proxmoxCertInfo.subject}</p>
                      )}
                      {proxmoxCertInfo.issuer && (
                        <p><span className="font-medium text-foreground">{st("ssl.issuer")}:</span> {proxmoxCertInfo.issuer}</p>
                      )}
                      {proxmoxCertInfo.expires && (
                        <p><span className="font-medium text-foreground">{st("ssl.expires")}:</span> {proxmoxCertInfo.expires}</p>
                      )}
                      {proxmoxCertInfo.is_self_signed && (
                        <div className="flex items-center gap-1.5 mt-1 text-yellow-500">
                          <AlertTriangle className="h-3.5 w-3.5" />
                          <span className="text-xs">{st("ssl.selfSignedWarning")}</span>
                        </div>
                      )}
                    </div>
                  )}

                  <Button
                    onClick={() => handleEnableSsl("proxmox")}
                    className="bg-green-600 hover:bg-green-700 text-white"
                    disabled={configuringSsl || sslRestarting}
                  >
                    {configuringSsl ? (
                      <div className="flex items-center gap-2">
                        <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                        {st("ssl.configuring")}
                      </div>
                    ) : (
                      <>
                        <ShieldCheck className="h-4 w-4 mr-2" />
                        {st("ssl.useProxmoxCertificate")}
                      </>
                    )}
                  </Button>
                </div>
              )}

              {!sslEnabled && !proxmoxCertAvailable && (
                <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3 flex items-start gap-2">
                  <AlertTriangle className="h-5 w-5 text-yellow-500 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-yellow-500">
                    {st("ssl.noProxmoxCertificate")}
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
                    >
                      <FileKey className="h-4 w-4 mr-2" />
                      {st("ssl.useCustomCertificate")}
                    </Button>
                  ) : (
                    <div className="space-y-4 border border-border rounded-lg p-4">
                      <h3 className="font-semibold text-sm">{st("ssl.customPaths")}</h3>
                      <p className="text-xs text-muted-foreground">
                        {st("ssl.customPathsDescription")}
                      </p>

                      <div className="space-y-2">
                        <Label htmlFor="ssl-cert-path">{st("ssl.certificatePath")}</Label>
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
                        <Label htmlFor="ssl-key-path">{st("ssl.privateKeyPath")}</Label>
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
                        disabled={configuringSsl || sslRestarting || !customCertPath || !customKeyPath}
                        >
                          {configuringSsl ? st("ssl.configuring") : st("ssl.enableHttps")}
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
                          {t("actions.cancel")}
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Restarting overlay or info note */}
              {sslRestarting ? (
                <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-4 flex items-center gap-3">
                  <div className="h-5 w-5 border-2 border-amber-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-amber-500">
                      {st("ssl.restartTitle")}
                    </p>
                    <p className="text-xs text-amber-400 mt-0.5">
                      {st("ssl.restartDescription")}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-start gap-2">
                  <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-blue-500">
                    {st("ssl.changesRestart")}
                  </p>
                </div>
              )}
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
              <CardTitle>{st("apiTokens.title")}</CardTitle>
            </div>
            <CardDescription>
              {st("apiTokens.description")}
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
                  <p className="font-medium">{st("apiTokens.aboutTitle")}</p>
                  <ul className="list-disc list-inside space-y-1 text-blue-300">
                    <li>{st("apiTokens.validFor")}</li>
                    <li>{st("apiTokens.externalServices")}</li>
                    <li>{st("apiTokens.authorizationHeader")}</li>
                    <li>
                      {st("apiTokens.seeGuideBefore")}{" "}
                      <a
                        href="https://proxmenux.com/docs/monitor/integrations"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-blue-200 hover:text-blue-100 underline underline-offset-2"
                      >
                        {st("apiTokens.integrationsGuide")}
                        <ExternalLink className="h-3 w-3" />
                      </a>{" "}
                      {st("apiTokens.seeGuideAfter")}
                    </li>
                  </ul>
                </div>
              </div>
            </div>

            {!showApiTokenSection && !apiToken && (
              <Button onClick={() => setShowApiTokenSection(true)} className="bg-purple-500 hover:bg-purple-600">
                <Key className="h-4 w-4 mr-2" />
                {st("apiTokens.generateNew")}
              </Button>
            )}

            {showApiTokenSection && !apiToken && (
              <div className="space-y-4 border border-border rounded-lg p-4">
                <h3 className="font-semibold">{st("apiTokens.generateTitle")}</h3>
                <p className="text-sm text-muted-foreground">
                  {st("apiTokens.generateDescription")}
                </p>

                <div className="space-y-2">
                  <Label htmlFor="token-name">{st("apiTokens.tokenName")}</Label>
                  <div className="relative">
                    <Key className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="token-name"
                      type="text"
                      placeholder={st("apiTokens.tokenNamePlaceholder")}
                      value={tokenName}
                      onChange={(e) => setTokenName(e.target.value)}
                      className="pl-10"
                      disabled={generatingToken}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="token-password">{st("auth.password")}</Label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      id="token-password"
                      type="password"
                      placeholder={st("auth.enterYourPassword")}
                      value={tokenPassword}
                      onChange={(e) => setTokenPassword(e.target.value)}
                      className="pl-10"
                      disabled={generatingToken}
                    />
                  </div>
                </div>

                {totpEnabled && (
                  <div className="space-y-2">
                    <Label htmlFor="token-totp">{st("twoFactor.code")}</Label>
                    <div className="relative">
                      <Shield className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                      <Input
                        id="token-totp"
                        type="text"
                        placeholder={st("twoFactor.codePlaceholder")}
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
                    {generatingToken ? st("apiTokens.generating") : st("apiTokens.generate")}
                  </Button>
                  <Button
                    onClick={() => {
                      setShowApiTokenSection(false)
                      setTokenPassword("")
                      setTokenTotpCode("")
                      setTokenName("")
                      setError("")
                    }}
                    variant="outline"
                    className="flex-1"
                    disabled={generatingToken}
                  >
                    {t("actions.cancel")}
                  </Button>
                </div>
              </div>
            )}

            {apiToken && (
              <div className="space-y-4 border border-green-500/20 bg-green-500/5 rounded-lg p-4">
                <div className="flex items-center gap-2 text-green-500">
                  <CheckCircle className="h-5 w-5" />
                  <h3 className="font-semibold">{st("apiTokens.yourToken")}</h3>
                </div>

                <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-3 flex items-start gap-2">
                  <AlertCircle className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <p className="text-sm text-amber-600 dark:text-amber-400 font-semibold">
                      {st("apiTokens.saveTokenNow")}
                    </p>
                    <p className="text-xs text-amber-600/80 dark:text-amber-400/80">
                      {st("apiTokens.tokenOnlyShownOnce")}
                    </p>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>{st("apiTokens.token")}</Label>
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
                      {st("apiTokens.copied")}
                    </p>
                  )}
                </div>

                <div className="space-y-2">
                  <p className="text-sm font-medium">{st("apiTokens.howToUse")}</p>
                  <div className="bg-muted/50 rounded p-3 text-xs font-mono">
                    <p className="text-muted-foreground mb-2"># {st("apiTokens.addToHeaders")}</p>
                    <p>{st("apiTokens.authorizationHeaderExample")}</p>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {st("apiTokens.readmeExamples")}
                  </p>
                </div>

                <Button
                  onClick={() => {
                    setApiToken("")
                  setShowApiTokenSection(false)
                }}
                variant="outline"
              >
                  {st("apiTokens.done")}
                </Button>
              </div>
            )}

            {/* Existing Tokens List */}
            {!loadingTokens && existingTokens.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-muted-foreground">{st("apiTokens.activeTokens")}</h3>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={loadApiTokens}
                    className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                  >
                    <RefreshCw className="h-3 w-3 mr-1" />
                    {t("actions.refresh")}
                  </Button>
                </div>

                <div className="space-y-2">
                  {existingTokens.map((token) => {
                    // `valid === false` → JWT signature broken by a
                    // jwt_secret rotation, every request returns 401
                    // even though the entry still appears here. The
                    // operator needs to revoke and regenerate.
                    const isInvalid = token.valid === false
                    const isLegacy = token.valid === null || token.valid === undefined
                    const containerClass = isInvalid
                      ? "flex items-center justify-between p-3 bg-red-500/5 rounded-lg border border-red-500/30"
                      : "flex items-center justify-between p-3 bg-muted/50 rounded-lg border border-border"
                    return (
                    <div key={token.id} className={containerClass}>
                      <div className="flex items-center gap-3 min-w-0">
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                          isInvalid ? "bg-red-500/10" : "bg-blue-500/10"
                        }`}>
                          <Key className={`h-4 w-4 ${isInvalid ? "text-red-500" : "text-blue-500"}`} />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="text-sm font-medium truncate">{token.name}</p>
                            {isInvalid && (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-500/15 text-red-500 border border-red-500/30 whitespace-nowrap">
                                {st("apiTokens.invalidRegenerate")}
                              </span>
                            )}
                            {isLegacy && (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-500 border border-amber-500/30 whitespace-nowrap">
                                {st("apiTokens.legacy")}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
                            <code className="font-mono">{token.token_prefix}</code>
                            <span className="flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              {token.created_at
                                ? new Date(token.created_at).toLocaleDateString()
                                : t("common.unknown")}
                            </span>
                          </div>
                          {isInvalid && token.invalidation_reason && (
                            <p className="text-[11px] text-red-500/90 mt-1 leading-snug">
                              {token.invalidation_reason}
                            </p>
                          )}
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
                        <span className="ml-1 text-xs hidden sm:inline">{st("apiTokens.revoke")}</span>
                      </Button>
                    </div>
                    )
                  })}
                </div>
              </div>
            )}

            {loadingTokens && (
              <div className="flex items-center justify-center py-4">
                <div className="animate-spin h-5 w-5 border-2 border-blue-500 border-t-transparent rounded-full" />
                <span className="ml-2 text-sm text-muted-foreground">{st("apiTokens.loading")}</span>
              </div>
            )}

            {!loadingTokens && existingTokens.length === 0 && !showApiTokenSection && !apiToken && (
              <div className="text-center py-4 text-sm text-muted-foreground">
                {st("apiTokens.empty")}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ── Proxmox VE Security Group ── */}
      <div className="flex items-center gap-3 mt-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-orange-500">Proxmox VE</h2>
        <div className="flex-1 h-px bg-orange-500/20" />
      </div>

      {/* Proxmox Firewall */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Flame className="h-5 w-5 text-orange-500" />
              <CardTitle>{st("firewall.title")}</CardTitle>
            </div>
            {firewallData?.pve_firewall_installed && (
              <Button
                variant="ghost"
                size="sm"
                onClick={loadFirewallStatus}
                className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
              >
                <RefreshCw className="h-3 w-3 mr-1" />
                {t("actions.refresh")}
              </Button>
            )}
          </div>
          <CardDescription>
            {st("firewall.description")}
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
                <p className="text-sm font-medium text-yellow-500">{st("firewall.notDetectedTitle")}</p>
                <p className="text-sm text-muted-foreground mt-1">
                  {st("firewall.notDetectedDescription")}
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
                      <p className="font-medium text-sm">{st("firewall.clusterTitle")}</p>
                      <p className="text-xs text-muted-foreground">
                        {firewallData.cluster_fw_enabled ? st("firewall.clusterActive") : st("firewall.clusterDisabled")}
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
                      <><PowerOff className="h-3.5 w-3.5 mr-1" /> {st("values.disable")}</>
                    ) : (
                      <><Power className="h-3.5 w-3.5 mr-1" /> {st("values.enable")}</>
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
                      <p className="font-medium text-sm">{st("firewall.hostTitle")}</p>
                      <p className="text-xs text-muted-foreground">
                        {firewallData.host_fw_enabled ? st("firewall.hostActive") : st("values.disabled")}
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
                      <><PowerOff className="h-3.5 w-3.5 mr-1" /> {st("values.disable")}</>
                    ) : (
                      <><Power className="h-3.5 w-3.5 mr-1" /> {st("values.enable")}</>
                    )}
                  </Button>
                </div>
              </div>

              {!firewallData.cluster_fw_enabled && (
                <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 flex items-start gap-2">
                  <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-blue-500">
                    {st("firewall.clusterRequiredHint")}
                  </p>
                </div>
              )}

              {/* Quick Presets */}
              <div className="space-y-2">
                <h3 className="text-sm font-semibold text-muted-foreground">{st("firewall.quickAccessRules")}</h3>
                <div className="grid gap-2 sm:grid-cols-2">
                  {/* Monitor Port 8008 */}
                  <div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg border border-border">
                    <div className="flex items-center gap-2.5">
                      <div className={`w-2.5 h-2.5 rounded-full ${firewallData.monitor_port_open ? "bg-green-500" : "bg-yellow-500"}`} />
                      <div>
                        <p className="text-sm font-medium">ProxMenux Monitor</p>
                        <p className="text-xs text-muted-foreground">{st("firewall.port8008")}</p>
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
                      {firewallData.monitor_port_open ? st("values.remove") : st("values.allow")}
                    </Button>
                  </div>

                  {/* Proxmox Web UI hint */}
                  <div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg border border-border">
                    <div className="flex items-center gap-2.5">
                      <div className="w-2.5 h-2.5 rounded-full bg-green-500" />
                      <div>
                        <p className="text-sm font-medium">Proxmox Web UI</p>
                        <p className="text-xs text-muted-foreground">{st("firewall.port8006AlwaysAllowed")}</p>
                      </div>
                    </div>
                    <span className="text-xs text-muted-foreground px-2 py-1 bg-muted/50 rounded">{st("firewall.builtIn")}</span>
                  </div>
                </div>

                {!firewallData.monitor_port_open && (firewallData.cluster_fw_enabled || firewallData.host_fw_enabled) && (
                  <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3 flex items-start gap-2">
                    <AlertTriangle className="h-5 w-5 text-yellow-500 flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-yellow-500">
                      {st("firewall.monitorPortWarning")}
                    </p>
                  </div>
                )}
              </div>

              {/* Rules Summary Dashboard */}
              {firewallData.rules.length > 0 && (() => {
                const acceptCount = firewallData.rules.filter(r => r.action === "ACCEPT").length
                const dropCount = firewallData.rules.filter(r => r.action === "DROP").length
                const rejectCount = firewallData.rules.filter(r => r.action === "REJECT").length
                const blockCount = dropCount + rejectCount
                const total = firewallData.rules.length
                const clusterCount = firewallData.rules.filter(r => r.source_file === "cluster").length
                const hostCount = firewallData.rules.filter(r => r.source_file === "host").length
                const inCount = firewallData.rules.filter(r => (r.direction || "IN") === "IN").length
                const outCount = firewallData.rules.filter(r => r.direction === "OUT").length
                // Collect unique protected ports
                const protectedPorts = new Set<string>()
                firewallData.rules.forEach(r => {
                  if (r.dport) r.dport.split(",").forEach(p => protectedPorts.add(p.trim()))
                })

                return (
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold text-muted-foreground">{st("firewall.rulesOverview")}</h3>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      <div className="p-3 bg-muted/50 rounded-lg border border-border text-center">
                        <p className="text-lg font-bold text-foreground">{total}</p>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{st("firewall.totalRules")}</p>
                      </div>
                      <div className="p-3 bg-green-500/5 rounded-lg border border-green-500/20 text-center">
                        <p className="text-lg font-bold text-green-500">{acceptCount}</p>
                        <p className="text-[10px] text-green-500/70 uppercase tracking-wider">{st("firewall.accept")}</p>
                      </div>
                      <div className="p-3 bg-red-500/5 rounded-lg border border-red-500/20 text-center">
                        <p className="text-lg font-bold text-red-500">{blockCount}</p>
                        <p className="text-[10px] text-red-500/70 uppercase tracking-wider">{st("firewall.blockReject")}</p>
                      </div>
                      <div className="p-3 bg-muted/50 rounded-lg border border-border text-center">
                        <p className="text-lg font-bold text-foreground">{protectedPorts.size}</p>
                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{st("firewall.portsCovered")}</p>
                      </div>
                    </div>
                    {/* Visual bar */}
                    <div className="space-y-1.5 sm:space-y-0">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden flex">
                          {acceptCount > 0 && (
                            <div className="h-full bg-green-500 transition-all" style={{ width: `${(acceptCount / total) * 100}%` }} />
                          )}
                          {dropCount > 0 && (
                            <div className="h-full bg-red-500 transition-all" style={{ width: `${(dropCount / total) * 100}%` }} />
                          )}
                          {rejectCount > 0 && (
                            <div className="h-full bg-orange-500 transition-all" style={{ width: `${(rejectCount / total) * 100}%` }} />
                          )}
                        </div>
                        <div className="hidden sm:flex items-center gap-3 text-[10px] text-muted-foreground flex-shrink-0">
                          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500" />{st("firewall.accept")}</span>
                          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500" />{st("firewall.drop")}</span>
                          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-orange-500" />{st("firewall.reject")}</span>
                        </div>
                      </div>
                      <div className="flex sm:hidden items-center gap-3 text-[10px] text-muted-foreground">
                        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500" />{st("firewall.accept")}</span>
                        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500" />{st("firewall.drop")}</span>
                        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-orange-500" />{st("firewall.reject")}</span>
                      </div>
                    </div>
                    {/* Scope breakdown */}
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1.5">
                        <Globe className="h-3 w-3 text-blue-400" /> {st("firewall.cluster")}: {clusterCount}
                      </span>
                      <span className="flex items-center gap-1.5">
                        <Shield className="h-3 w-3 text-purple-400" /> {st("firewall.host")}: {hostCount}
                      </span>
                      <span className="text-border">|</span>
                      <span className="flex items-center gap-1.5">
                        <ArrowDownLeft className="h-3 w-3" /> IN: {inCount}
                      </span>
                      <span className="flex items-center gap-1.5">
                        <ArrowUpRight className="h-3 w-3" /> OUT: {outCount}
                      </span>
                    </div>
                  </div>
                )
              })()}

              {/* Firewall Rules */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-muted-foreground">
                    {st("firewall.rules", { count: firewallData.rules_count })}
                  </h3>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowAddRule(!showAddRule)}
                    className="h-7 text-xs text-orange-500 border-orange-500/30 hover:bg-orange-500/10 bg-transparent"
                  >
                    <Plus className="h-3 w-3 mr-1" />
                    {st("firewall.addRule")}
                  </Button>
                </div>

                {/* Add Rule Form */}
                {showAddRule && (
                  <div className="border border-orange-500/30 rounded-lg p-4 bg-orange-500/5 space-y-4">
                    <div className="flex items-center gap-2 mb-1">
                      <Plus className="h-4 w-4 text-orange-500" />
                      <p className="text-sm font-semibold text-orange-500">{st("firewall.newRule")}</p>
                    </div>

                    {/* Service Presets */}
                    <div className="space-y-1.5">
                      <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{st("firewall.quickPresets")}</p>
                      <div className="flex flex-wrap gap-1.5">
                        {[
                          { label: "HTTP", port: "80", proto: "tcp", comment: st("firewall.presets.httpWeb") },
                          { label: "HTTPS", port: "443", proto: "tcp", comment: st("firewall.presets.httpsWeb") },
                          { label: "SSH", port: "22", proto: "tcp", comment: st("firewall.presets.sshRemoteAccess") },
                          { label: "DNS", port: "53", proto: "udp", comment: "DNS" },
                          { label: "SMTP", port: "25", proto: "tcp", comment: st("firewall.presets.smtpMail") },
                          { label: "NFS", port: "2049", proto: "tcp", comment: "NFS" },
                          { label: "SMB", port: "445", proto: "tcp", comment: "SMB/CIFS" },
                          { label: "Ping", port: "", proto: "icmp", comment: st("firewall.presets.icmpPing") },
                        ].map((preset) => (
                          <Button
                            key={preset.label}
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => setNewRule({
                              ...newRule,
                              dport: preset.port,
                              protocol: preset.proto,
                              comment: preset.comment,
                              direction: "IN",
                              action: "ACCEPT",
                            })}
                            className="h-6 text-[10px] px-2 text-muted-foreground border-border hover:text-orange-500 hover:border-orange-500/30 bg-transparent"
                          >
                            <Zap className="h-2.5 w-2.5 mr-1" />
                            {preset.label}
                          </Button>
                        ))}
                      </div>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-3">
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">{st("firewall.fields.direction")}</Label>
                        <select
                          value={newRule.direction}
                          onChange={(e) => setNewRule({...newRule, direction: e.target.value})}
                          className="w-full h-9 rounded-md border border-border bg-card px-3 text-sm"
                        >
                          <option value="IN">IN ({st("firewall.incomingLower")})</option>
                          <option value="OUT">OUT ({st("firewall.outgoingLower")})</option>
                        </select>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">{st("firewall.fields.action")}</Label>
                        <select
                          value={newRule.action}
                          onChange={(e) => setNewRule({...newRule, action: e.target.value})}
                          className="w-full h-9 rounded-md border border-border bg-card px-3 text-sm"
                        >
                          <option value="ACCEPT">ACCEPT ({st("firewall.allowLower")})</option>
                          <option value="DROP">DROP ({st("firewall.blockSilentlyLower")})</option>
                          <option value="REJECT">REJECT ({st("firewall.blockWithResponseLower")})</option>
                        </select>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">{st("firewall.fields.protocol")}</Label>
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
                        <Label className="text-xs text-muted-foreground">{st("firewall.fields.destinationPort")}</Label>
                        <Input
                          placeholder={st("firewall.placeholders.destinationPort")}
                          value={newRule.dport}
                          onChange={(e) => setNewRule({...newRule, dport: e.target.value})}
                          className="h-9 text-sm"
                        />
                        <p className="text-[10px] text-muted-foreground">{st("firewall.destinationPortHint")}</p>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">{st("firewall.fields.sourceAddress")}</Label>
                        <Input
                          placeholder={st("firewall.placeholders.sourceAddress")}
                          value={newRule.source}
                          onChange={(e) => setNewRule({...newRule, source: e.target.value})}
                          className="h-9 text-sm"
                        />
                        <p className="text-[10px] text-muted-foreground">{st("firewall.sourceAddressHint")}</p>
                      </div>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">{st("firewall.fields.interfaceOptional")}</Label>
                        <select
                          value={newRule.iface}
                          onChange={(e) => setNewRule({...newRule, iface: e.target.value})}
                          className="w-full h-9 rounded-md border border-border bg-card px-3 text-sm"
                        >
                          <option value="">{st("firewall.anyInterface")}</option>
                          {networkInterfaces.map((iface) => (
                            <option key={iface.name} value={iface.name}>
                              {iface.name} ({interfaceTypeLabel(iface.type)}{iface.status === "up" ? `, ${st("values.up")}` : `, ${st("values.down")}`})
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs text-muted-foreground">{st("firewall.fields.applyTo")}</Label>
                        <select
                          value={newRule.level}
                          onChange={(e) => setNewRule({...newRule, level: e.target.value})}
                          className="w-full h-9 rounded-md border border-border bg-card px-3 text-sm"
                        >
                          <option value="host">{st("firewall.hostFirewallThisNode")}</option>
                          <option value="cluster">{st("firewall.clusterFirewallAllNodes")}</option>
                        </select>
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">{st("firewall.fields.commentOptional")}</Label>
                      <Input
                        placeholder={st("firewall.placeholders.comment")}
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
                        {t("actions.cancel")}
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
                        {st("firewall.addRule")}
                      </Button>
                    </div>
                  </div>
                )}

                {/* Rules List */}
                {firewallData.rules.length > 0 ? (
                  <div className="border border-border rounded-lg overflow-hidden">
                    {/* Table header */}
                    <div className="hidden sm:grid grid-cols-[2rem_4.5rem_2rem_3rem_5rem_1fr_3.5rem_2rem] gap-2 px-3 py-2 bg-muted/50 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider items-center">
                      <span />
                      <span>{st("firewall.fields.action")}</span>
                      <span />
                      <span>{st("firewall.fields.proto")}</span>
                      <span>{st("firewall.fields.port")}</span>
                      <span>{st("firewall.fields.source")}</span>
                      <span>{st("firewall.fields.level")}</span>
                      <span />
                    </div>

                    <div className="divide-y divide-border max-h-80 overflow-y-auto">
                      {firewallData.rules.map((rule, idx) => {
                        const ruleKey = `${rule.source_file}-${rule.rule_index}`
                        const isExpanded = expandedRuleKey === ruleKey
                        const direction = rule.direction || "IN"
                        const comment = rule.raw?.includes("#") ? rule.raw.split("#").slice(1).join("#").trim() : ""
                        
                        return (
                          <div key={ruleKey}>
                            {/* Main row */}
                            <div
                              className="grid grid-cols-[2rem_4.5rem_1fr_2rem] sm:grid-cols-[2rem_4.5rem_2rem_3rem_5rem_1fr_3.5rem_2rem] gap-2 px-3 py-2.5 items-center hover:bg-white/5 transition-colors cursor-pointer"
                              onClick={() => setExpandedRuleKey(isExpanded ? null : ruleKey)}
                            >
                              {/* Direction icon */}
                              <div className="flex items-center justify-center">
                                {direction === "IN" ? (
                                  <ArrowDownLeft className="h-4 w-4 text-blue-400" />
                                ) : (
                                  <ArrowUpRight className="h-4 w-4 text-amber-400" />
                                )}
                              </div>
                              {/* Action badge */}
                              <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold text-center ${
                                rule.action === "ACCEPT" ? "bg-green-500/10 text-green-500" :
                                rule.action === "DROP" ? "bg-red-500/10 text-red-500" :
                                rule.action === "REJECT" ? "bg-orange-500/10 text-orange-500" :
                                "bg-gray-500/10 text-gray-500"
                              }`}>
                                {rule.action || "?"}
                              </span>
                              {/* Mobile: combined info on two lines */}
                              <div className="sm:hidden min-w-0">
                                <div className="flex items-center gap-1.5">
                                  <span className="text-xs text-blue-400 font-mono flex-shrink-0">{rule.p || "*"}</span>
                                  <span className="text-xs text-muted-foreground flex-shrink-0">:</span>
                                  <span className="text-xs text-foreground font-mono font-medium">{rule.dport || "*"}</span>
                                  <span className={`text-[10px] px-1 py-0 rounded flex-shrink-0 ${
                                    rule.source_file === "cluster" ? "bg-blue-500/10 text-blue-400" : "bg-purple-500/10 text-purple-400"
                                  }`}>{rule.source_file}</span>
                                </div>
                                {comment && (
                                  <p className="text-[10px] text-muted-foreground truncate mt-0.5">{comment}</p>
                                )}
                              </div>
                              {/* Desktop: direction label */}
                              <span className="hidden sm:block text-xs text-muted-foreground font-mono">{direction}</span>
                              {/* Protocol */}
                              <span className="hidden sm:block text-xs text-blue-400 font-mono">{rule.p || "*"}</span>
                              {/* Port */}
                              <span className="hidden sm:block text-xs text-foreground font-mono font-medium">{rule.dport || "*"}</span>
                              {/* Source */}
                              <span className="hidden sm:block text-xs text-muted-foreground font-mono truncate">{rule.source || "any"}</span>
                              {/* Level badge */}
                              <span className={`hidden sm:block text-[10px] px-1.5 py-0.5 rounded text-center ${
                                rule.source_file === "cluster" ? "bg-blue-500/10 text-blue-400" : "bg-purple-500/10 text-purple-400"
                              }`}>
                                {rule.source_file}
                              </span>
                              {/* Expand/Delete */}
                              <div className="flex items-center justify-end">
                                <ChevronRight className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${isExpanded ? "rotate-90" : ""}`} />
                              </div>
                            </div>
                            
                            {/* Expanded details */}
                            {isExpanded && (
                              <div className="px-3 pb-3 pt-0 border-t border-border/50 bg-muted/10">
                                {editingRuleKey === ruleKey ? (
                                  /* ── Inline Edit Form ── */
                                  <div className="py-3 space-y-3">
                                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                                      <div>
                                        <Label className="text-[10px] text-muted-foreground uppercase">{st("firewall.fields.direction")}</Label>
                                        <select value={editRule.direction} onChange={(e) => setEditRule({ ...editRule, direction: e.target.value })}
                                          className="w-full h-8 text-xs rounded-md border border-border bg-background px-2 mt-0.5">
                                          <option value="IN">IN</option>
                                          <option value="OUT">OUT</option>
                                        </select>
                                      </div>
                                      <div>
                                        <Label className="text-[10px] text-muted-foreground uppercase">{st("firewall.fields.action")}</Label>
                                        <select value={editRule.action} onChange={(e) => setEditRule({ ...editRule, action: e.target.value })}
                                          className="w-full h-8 text-xs rounded-md border border-border bg-background px-2 mt-0.5">
                                          <option value="ACCEPT">ACCEPT</option>
                                          <option value="DROP">DROP</option>
                                          <option value="REJECT">REJECT</option>
                                        </select>
                                      </div>
                                      <div>
                                        <Label className="text-[10px] text-muted-foreground uppercase">{st("firewall.fields.protocol")}</Label>
                                        <select value={editRule.protocol} onChange={(e) => setEditRule({ ...editRule, protocol: e.target.value })}
                                          className="w-full h-8 text-xs rounded-md border border-border bg-background px-2 mt-0.5">
                                          <option value="tcp">TCP</option>
                                          <option value="udp">UDP</option>
                                          <option value="icmp">ICMP</option>
                                        </select>
                                      </div>
                                      <div>
                                        <Label className="text-[10px] text-muted-foreground uppercase">{st("firewall.fields.port")}</Label>
                                        <Input value={editRule.dport} onChange={(e) => setEditRule({ ...editRule, dport: e.target.value })}
                                          placeholder={st("firewall.placeholders.shortPort")} className="h-8 text-xs mt-0.5" />
                                      </div>
                                    </div>
                                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                                      <div>
                                        <Label className="text-[10px] text-muted-foreground uppercase">{st("firewall.fields.source")}</Label>
                                        <Input value={editRule.source} onChange={(e) => setEditRule({ ...editRule, source: e.target.value })}
                                          placeholder={st("firewall.placeholders.ipOrCidr")} className="h-8 text-xs mt-0.5" />
                                      </div>
                                      <div>
                                        <Label className="text-[10px] text-muted-foreground uppercase">{st("firewall.fields.interface")}</Label>
                                        <select value={editRule.iface} onChange={(e) => setEditRule({ ...editRule, iface: e.target.value })}
                                          className="w-full h-8 text-xs rounded-md border border-border bg-background px-2 mt-0.5">
                                          <option value="">{st("firewall.any")}</option>
                                          {networkInterfaces.map((iface) => (
                                            <option key={iface.name} value={iface.name}>
                                              {iface.name} ({interfaceTypeLabel(iface.type)})
                                            </option>
                                          ))}
                                        </select>
                                      </div>
                                      <div className="col-span-2 sm:col-span-1">
                                        <Label className="text-[10px] text-muted-foreground uppercase">{st("firewall.fields.comment")}</Label>
                                        <Input value={editRule.comment} onChange={(e) => setEditRule({ ...editRule, comment: e.target.value })}
                                          placeholder={st("firewall.placeholders.description")} className="h-8 text-xs mt-0.5" />
                                      </div>
                                    </div>
                                    <div className="flex items-center justify-end gap-2 pt-1">
                                      <Button variant="ghost" size="sm"
                                        onClick={(e) => { e.stopPropagation(); setEditingRuleKey(null) }}
                                        className="h-7 text-xs text-muted-foreground">
                                        <X className="h-3 w-3 mr-1" /> {t("actions.cancel")}
                                      </Button>
                                      <Button variant="outline" size="sm"
                                        onClick={(e) => { e.stopPropagation(); handleSaveEditRule(rule.rule_index, rule.source_file || "host") }}
                                        disabled={savingRule}
                                        className="h-7 text-xs text-green-500 border-green-500/30 hover:bg-green-500/10 bg-transparent">
                                        {savingRule ? (
                                          <div className="animate-spin h-3 w-3 border-2 border-green-500 border-t-transparent rounded-full mr-1" />
                                        ) : (
                                          <Check className="h-3 w-3 mr-1" />
                                        )}
                                        {st("firewall.saveChanges")}
                                      </Button>
                                    </div>
                                  </div>
                                ) : (
                                  /* ── Read-only Details ── */
                                  <>
                                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 py-3">
                                      <div>
                                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">{st("firewall.fields.direction")}</p>
                                        <p className="text-xs font-medium flex items-center gap-1">
                                          {direction === "IN" ? <ArrowDownLeft className="h-3 w-3 text-blue-400" /> : <ArrowUpRight className="h-3 w-3 text-amber-400" />}
                                          {direction === "IN" ? st("firewall.incoming") : st("firewall.outgoing")}
                                        </p>
                                      </div>
                                      <div>
                                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">{st("firewall.fields.protocol")}</p>
                                        <p className="text-xs font-medium font-mono">{rule.p || st("firewall.anyLower")}</p>
                                      </div>
                                      <div>
                                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">{st("firewall.fields.port")}</p>
                                        <p className="text-xs font-medium font-mono">{rule.dport || st("firewall.anyLower")}</p>
                                      </div>
                                      <div>
                                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">{st("firewall.fields.source")}</p>
                                        <p className="text-xs font-medium font-mono">{rule.source || st("firewall.anyLower")}</p>
                                      </div>
                                      {rule.i && (
                                        <div>
                                          <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">{st("firewall.fields.interface")}</p>
                                          <p className="text-xs font-medium font-mono">{rule.i}</p>
                                        </div>
                                      )}
                                      <div>
                                        <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">{st("firewall.fields.scope")}</p>
                                        <p className="text-xs font-medium flex items-center gap-1">
                                          {rule.source_file === "cluster" ? <Globe className="h-3 w-3 text-blue-400" /> : <Shield className="h-3 w-3 text-purple-400" />}
                                          {rule.source_file === "cluster" ? st("firewall.cluster") : st("firewall.host")}
                                        </p>
                                      </div>
                                      {comment && (
                                        <div className="col-span-2">
                                          <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-0.5">{st("firewall.fields.comment")}</p>
                                          <p className="text-xs text-muted-foreground">{comment}</p>
                                        </div>
                                      )}
                                    </div>
                                    <div className="flex items-center justify-between pt-2 border-t border-border/50">
                                      <code className="text-[10px] text-muted-foreground/60 font-mono truncate max-w-[50%]">{rule.raw}</code>
                                      <div className="flex items-center gap-2">
                                        <Button
                                          variant="outline"
                                          size="sm"
                                          onClick={(e) => { e.stopPropagation(); startEditRule(rule) }}
                                          className="h-7 text-xs text-blue-400 border-blue-400/30 hover:bg-blue-400/10 bg-transparent"
                                        >
                                          <Pencil className="h-3 w-3 mr-1" />
                                          {t("actions.edit")}
                                        </Button>
                                        <Button
                                          variant="outline"
                                          size="sm"
                                          onClick={(e) => { e.stopPropagation(); handleDeleteRule(rule.rule_index, rule.source_file) }}
                                          disabled={deletingRuleIdx === rule.rule_index}
                                          className="h-7 text-xs text-red-500 border-red-500/30 hover:bg-red-500/10 bg-transparent"
                                        >
                                          {deletingRuleIdx === rule.rule_index ? (
                                            <div className="animate-spin h-3 w-3 border-2 border-red-500 border-t-transparent rounded-full mr-1" />
                                          ) : (
                                            <Trash2 className="h-3 w-3 mr-1" />
                                          )}
                                          {st("values.delete")}
                                        </Button>
                                      </div>
                                    </div>
                                  </>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-6 border border-dashed border-border rounded-lg">
                    <Shield className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
                    <p className="text-sm text-muted-foreground">{st("firewall.noRules")}</p>
                    <p className="text-xs text-muted-foreground/60 mt-1">{st("firewall.noRulesHint")}</p>
                  </div>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Secure Gateway */}
      <SecureGatewaySetup />

      {/* Fail2Ban */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bug className="h-5 w-5 text-red-500" />
              <CardTitle>Fail2Ban</CardTitle>
            </div>
            {fail2banInfo?.installed && (
              <div className="flex items-center gap-1">
                {fail2banInfo?.active && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => { loadFail2banDetails(); loadSecurityTools(); }}
                    className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
                  >
                    <RefreshCw className="h-3 w-3 mr-1" />
                    {t("actions.refresh")}
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowFail2banUninstallConfirm(true)}
                  disabled={uninstallingFail2ban}
                  className="h-8 px-3 text-xs border-red-500/30 text-red-500 hover:bg-red-500/10 hover:text-red-400 hover:border-red-500/50"
                >
                  {uninstallingFail2ban ? (
                    <div className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full mr-2" />
                  ) : (
                    <Trash2 className="h-4 w-4 mr-2" />
                  )}
                  {st("values.uninstall")}
                </Button>
              </div>
            )}
          </div>
          <CardDescription>
            {st("fail2ban.description")}
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
  <div className="flex items-center gap-3 p-4 bg-muted/50 rounded-lg">
  <div className="w-10 h-10 rounded-full bg-gray-500/10 flex items-center justify-center shrink-0">
  <Bug className="h-5 w-5 text-gray-500" />
  </div>
  <div>
  <p className="font-medium">{st("fail2ban.notInstalled")}</p>
  <p className="text-sm text-muted-foreground">{st("fail2ban.notInstalledDescription")}</p>
  </div>
  </div>

              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
                <div className="flex items-start gap-3">
                  <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <div className="space-y-2 text-sm text-blue-400">
                    <p className="font-medium">{st("fail2ban.configureTitle")}</p>
                    <ul className="list-disc list-inside space-y-1 text-blue-300">
                      <li>{st("fail2ban.configureSsh")}</li>
                      <li>{st("fail2ban.configureProxmox")}</li>
                      <li>{st("fail2ban.configureMonitor")}</li>
                      <li>{st("fail2ban.configureGlobal")}</li>
                    </ul>
                    <p className="text-xs text-blue-300/70 mt-1">{st("fail2ban.customizeAfterInstall")}</p>
                  </div>
                </div>
              </div>

              <Button
                onClick={() => setShowFail2banInstaller(true)}
                className="bg-red-600 hover:bg-red-700 text-white"
              >
                <Download className="h-4 w-4 mr-2" />
                {st("fail2ban.installConfigure")}
              </Button>
            </div>
          ) : (
            /* --- INSTALLED --- */
            <div className="space-y-4">
              {/* Status bar */}
              <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center ${fail2banInfo.active ? "bg-green-500/10" : "bg-yellow-500/10"}`}>
                    <Bug className={`h-5 w-5 ${fail2banInfo.active ? "text-green-500" : "text-yellow-500"}`} />
                  </div>
                  <div>
                    <p className="font-medium">{fail2banInfo.version}</p>
                    <p className="text-sm text-muted-foreground">
                      {fail2banInfo.active ? st("values.serviceRunning") : st("values.serviceNotRunning")}
                    </p>
                  </div>
                </div>
                <div className={`px-3 py-1 rounded-full text-sm font-medium ${fail2banInfo.active ? "bg-green-500/10 text-green-500" : "bg-yellow-500/10 text-yellow-500"}`}>
                  {fail2banInfo.active ? st("values.active") : st("values.inactive")}
                </div>
              </div>

              {fail2banInfo.active && f2bDetails && (
                <>
                  {/* Global Fail2Ban allowlist */}
                  <div className="rounded-lg border border-green-500/15 overflow-hidden shadow-sm">
                    <div className="flex items-start justify-between gap-3 p-3 bg-gradient-to-r from-green-500/[0.07] via-green-500/[0.03] to-transparent border-l-2 border-green-500/60">
                      <div className="flex items-start gap-2.5 min-w-0">
                        <div className="w-8 h-8 rounded-md bg-green-500/10 flex items-center justify-center shrink-0">
                          <Network className="h-4 w-4 text-green-500" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-semibold">{st("fail2ban.trustedNetworks.title")}</p>
                          <p className="text-xs text-muted-foreground mt-0.5">{st("fail2ban.trustedNetworks.description")}</p>
                        </div>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => { setF2bShowTrustedForm(!f2bShowTrustedForm); setF2bTrustedNotice(null) }}
                        className="h-7 text-xs text-orange-500 border-orange-500/30 hover:bg-orange-500/10 bg-transparent shrink-0"
                      >
                        <Plus className="h-3 w-3 mr-1" />
                        {st("fail2ban.trustedNetworks.addRule")}
                      </Button>
                    </div>

                    {f2bTrustedNotice && (
                      <div className={`mx-3 mt-3 rounded-md border px-3 py-2 text-xs ${f2bTrustedNotice.type === "success" ? "border-green-500/20 bg-green-500/10 text-green-500" : "border-red-500/20 bg-red-500/10 text-red-500"}`}>
                        {f2bTrustedNotice.text}
                      </div>
                    )}

                    {f2bShowTrustedForm && (
                      <div className="m-3 rounded-lg border border-border bg-muted/20 p-3 space-y-3">
                        <div>
                          <Label className="text-[10px] text-muted-foreground uppercase">{st("fail2ban.trustedNetworks.addressOrNetwork")}</Label>
                          <Input
                            value={f2bTrustedInput}
                            onChange={(event) => setF2bTrustedInput(event.target.value)}
                            onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); handleAddTrustedNetwork() } }}
                            placeholder={st("fail2ban.trustedNetworks.placeholder")}
                            className="h-8 font-mono text-xs mt-1"
                          />
                          <p className="mt-1.5 text-[10px] text-muted-foreground">{st("fail2ban.trustedNetworks.example")}</p>
                        </div>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          {f2bDetectedIp && !f2bTrustedNetworks.some((entry) => entry.value === f2bDetectedIp) ? (
                            <Button variant="ghost" size="sm" onClick={() => setF2bTrustedInput(f2bDetectedIp)} className="h-7 text-xs text-blue-400">
                              {st("fail2ban.trustedNetworks.useCurrent", { ip: f2bDetectedIp })}
                            </Button>
                          ) : <span />}
                          <div className="flex gap-2 ml-auto">
                            <Button variant="ghost" size="sm" onClick={() => { setF2bShowTrustedForm(false); setF2bTrustedInput("") }} className="h-7 text-xs text-muted-foreground">
                              {t("actions.cancel")}
                            </Button>
                            <Button size="sm" onClick={() => handleAddTrustedNetwork()} disabled={f2bSavingTrusted || !f2bTrustedInput.trim()} className="h-7 text-xs bg-orange-600 hover:bg-orange-700 text-white">
                              {f2bSavingTrusted ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent mr-1" /> : <Plus className="h-3 w-3 mr-1" />}
                              {st("fail2ban.trustedNetworks.add")}
                            </Button>
                          </div>
                        </div>
                      </div>
                    )}

                    <div className="hidden sm:grid grid-cols-[1.1fr_0.65fr_2fr_1.5fr] gap-3 border-t border-border bg-muted/20 px-3 py-2 text-[9px] font-medium uppercase tracking-wider text-muted-foreground">
                      <span>{st("fail2ban.trustedNetworks.columns.status")}</span>
                      <span>{st("fail2ban.trustedNetworks.columns.type")}</span>
                      <span>{st("fail2ban.trustedNetworks.columns.address")}</span>
                      <span className="text-right">{st("fail2ban.trustedNetworks.columns.actions")}</span>
                    </div>

                    <div className="divide-y divide-border border-t border-border sm:border-t-0">
                      {f2bTrustedNetworks.map((entry) => (
                        <div key={entry.value} className="px-3 py-2.5 transition-colors hover:bg-muted/20">
                          {f2bEditingTrusted === entry.value ? (
                            <div className="flex flex-col sm:flex-row gap-2 items-end">
                              <div className="flex-1 w-full">
                                <Label className="text-[10px] text-muted-foreground uppercase">{st("fail2ban.trustedNetworks.addressOrNetwork")}</Label>
                                <Input value={f2bTrustedEditInput} onChange={(event) => setF2bTrustedEditInput(event.target.value)} className="h-8 font-mono text-xs mt-1" />
                              </div>
                              <Button variant="ghost" size="sm" onClick={() => setF2bEditingTrusted(null)} className="h-7 text-xs text-muted-foreground">{t("actions.cancel")}</Button>
                              <Button variant="outline" size="sm" onClick={handleUpdateTrustedNetwork} disabled={f2bSavingTrusted || !f2bTrustedEditInput.trim()} className="h-7 text-xs text-green-500 border-green-500/30 hover:bg-green-500/10 bg-transparent">
                                <Check className="h-3 w-3 mr-1" />{st("fail2ban.trustedNetworks.save")}
                              </Button>
                            </div>
                          ) : (
                            <div className="grid grid-cols-1 sm:grid-cols-[1.1fr_0.65fr_2fr_1.5fr] gap-2 sm:gap-3 items-center">
                              <div className="flex items-center gap-2">
                                <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ${entry.protected ? "bg-slate-500/15 text-slate-400 border border-slate-500/20" : "bg-green-500/15 text-green-500 border border-green-500/20"}`}>
                                  {entry.protected ? st("fail2ban.trustedNetworks.system") : st("fail2ban.trustedNetworks.trusted")}
                                </span>
                              </div>
                              <div>
                                <span className={`inline-flex rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${entry.value.includes("/") ? "bg-purple-500/15 text-purple-400" : "bg-blue-500/15 text-blue-400"}`}>
                                  {entry.value.includes("/") ? "CIDR" : "IP"}
                                </span>
                              </div>
                              <code className="text-xs text-muted-foreground font-mono break-all">{entry.value}</code>
                              <div className="flex gap-2 sm:justify-end shrink-0">
                                {!entry.protected ? (
                                  <>
                                  <Button variant="outline" size="sm" onClick={() => { setF2bEditingTrusted(entry.value); setF2bTrustedEditInput(entry.value); setF2bTrustedNotice(null) }} className="h-7 text-xs text-blue-400 border-blue-400/30 hover:bg-blue-400/10 bg-transparent">
                                    <Pencil className="h-3 w-3 mr-1" />{st("fail2ban.trustedNetworks.edit")}
                                  </Button>
                                  <Button variant="outline" size="sm" onClick={() => handleRemoveTrustedNetwork(entry.value)} disabled={f2bRemovingTrusted === entry.value} className="h-7 text-xs text-red-500 border-red-500/30 hover:bg-red-500/10 bg-transparent">
                                    {f2bRemovingTrusted === entry.value ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent mr-1" /> : <Trash2 className="h-3 w-3 mr-1" />}
                                    {st("fail2ban.trustedNetworks.delete")}
                                  </Button>
                                  </>
                                ) : (
                                  <span className="inline-flex items-center text-[10px] text-muted-foreground"><Lock className="h-3 w-3 mr-1" />{st("fail2ban.trustedNetworks.required")}</span>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>

                    <div className="flex items-start gap-2 border-t border-border bg-amber-500/5 px-3 py-2 text-[11px] text-amber-500">
                      <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                      <p>{st("fail2ban.trustedNetworks.warning")}</p>
                    </div>
                  </div>

                  {/* Summary stats */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <div className="p-3 bg-muted/50 rounded-lg border border-border text-center">
                      <p className="text-lg font-bold text-foreground">{f2bDetails.jails.length}</p>
                      <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{st("fail2ban.jails")}</p>
                    </div>
                    <div className={`p-3 rounded-lg border text-center ${f2bDetails.jails.reduce((a, j) => a + j.currently_banned, 0) > 0 ? "bg-red-500/5 border-red-500/20" : "bg-muted/50 border-border"}`}>
                      <p className={`text-lg font-bold ${f2bDetails.jails.reduce((a, j) => a + j.currently_banned, 0) > 0 ? "text-red-500" : "text-foreground"}`}>
                        {f2bDetails.jails.reduce((a, j) => a + j.currently_banned, 0)}
                      </p>
                      <p className={`text-[10px] uppercase tracking-wider ${f2bDetails.jails.reduce((a, j) => a + j.currently_banned, 0) > 0 ? "text-red-500/70" : "text-muted-foreground"}`}>{st("fail2ban.bannedIps")}</p>
                    </div>
                    <div className="p-3 bg-orange-500/5 rounded-lg border border-orange-500/20 text-center">
                      <p className="text-lg font-bold text-orange-500">{f2bDetails.jails.reduce((a, j) => a + j.total_banned, 0)}</p>
                      <p className="text-[10px] text-orange-500/70 uppercase tracking-wider">{st("fail2ban.totalBans")}</p>
                    </div>
                    <div className="p-3 bg-yellow-500/5 rounded-lg border border-yellow-500/20 text-center">
                      <p className="text-lg font-bold text-yellow-500">{f2bDetails.jails.reduce((a, j) => a + j.total_failed, 0)}</p>
                      <p className="text-[10px] text-yellow-500/70 uppercase tracking-wider">{st("fail2ban.failedAttempts")}</p>
                    </div>
                  </div>

                  {/* Missing protections warning */}
                  {(() => {
                    const expectedJails = ["sshd", "proxmox", "proxmenux"]
                    const currentNames = f2bDetails.jails.map(j => j.name.toLowerCase())
                    const missing = expectedJails.filter(j => !currentNames.includes(j))
                    if (missing.length === 0) return null

                    return (
                      <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-start gap-3">
                            <AlertTriangle className="h-5 w-5 text-yellow-500 flex-shrink-0 mt-0.5" />
                            <div className="space-y-1">
                              <p className="text-sm font-medium text-yellow-500">{st("fail2ban.missingProtectionsTitle")}</p>
                              <p className="text-xs text-yellow-400/80">
                                {st("fail2ban.missingProtectionsBefore")}{" "}
                                {missing.map(j => fail2banProtectionLabel(j)).join(", ")}
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
                            {st("fail2ban.applyMissingJails")}
                          </Button>
                        </div>
                      </div>
                    )
                  })()}

                  {/* Tab switcher */}
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
                      {st("fail2ban.tabs.jails")}
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
                      {st("fail2ban.tabs.activity")}
                    </button>
                  </div>

                  {/* PROTECTIONS TAB */}
                  {f2bActiveTab === "jails" && (
                    <div className="space-y-3">
                      {f2bDetails.jails.map((jail) => (
                        <div key={jail.name} className="border border-border rounded-lg overflow-hidden">
                          {/* Protection header */}
                          <div className="flex items-center justify-between p-3 bg-muted/40">
                            <div className="flex items-center gap-2.5">
                              <div className={`w-2.5 h-2.5 rounded-full ${jail.currently_banned > 0 ? "bg-red-500 animate-pulse" : "bg-green-500"}`} />
                              <span className="font-semibold text-sm">{fail2banProtectionLabel(jail.name)}</span>
                              {fail2banProtectionLabel(jail.name) !== jail.name && (
                                <span className="text-[10px] text-muted-foreground font-mono">{jail.name}</span>
                              )}
                              <span className="text-[10px] text-muted-foreground">
                                {fail2banProtectionDescription(jail.name)}
                              </span>
                              {parseInt(jail.bantime, 10) === -1 && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-500/10 text-red-500">{st("fail2ban.permanentBan")}</span>
                              )}
                            </div>
                            <div className="flex items-center gap-2">
                              <div className="hidden sm:flex items-center gap-3 text-xs text-muted-foreground mr-2">
                                <span title={st("fail2ban.maxRetriesTitle")}>
                                  {st("fail2ban.retries")}: <span className="text-foreground font-medium">{jail.maxretry}</span>
                                </span>
                                <span title={st("fail2ban.banDurationTitle")}>
                                  {st("fail2ban.ban")}: <span className="text-foreground font-medium">{parseInt(jail.bantime, 10) === -1 ? st("values.permanent") : formatBanTime(jail.bantime)}</span>
                                </span>
                                <span title={st("fail2ban.findTimeTitle")}>
                                  {st("fail2ban.window")}: <span className="text-foreground font-medium">{formatBanTime(jail.findtime)}</span>
                                </span>
                              </div>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => f2bEditingJail === jail.name ? setF2bEditingJail(null) : openJailConfig(jail)}
                                className={`h-7 w-7 p-0 ${f2bEditingJail === jail.name ? "text-red-500 bg-red-500/10" : "text-muted-foreground hover:text-foreground"}`}
                                title={st("fail2ban.configureJailSettings")}
                              >
                                <Settings className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </div>

                          {/* Protection config editor */}
                          {f2bEditingJail === jail.name && (
                            <div className="border-t border-border bg-muted/20 p-4 space-y-4">
                              <div className="flex items-center gap-2 mb-1">
                                <Settings className="h-4 w-4 text-red-500" />
                                <p className="text-sm font-semibold text-red-500">
                                  {st("fail2ban.configureJail", { jail: fail2banProtectionLabel(jail.name) })}
                                </p>
                              </div>

                              <div className="grid gap-3 sm:grid-cols-3">
                                <div className="space-y-1.5">
                                  <Label className="text-xs text-muted-foreground">{st("fail2ban.maxRetries")}</Label>
                                  <Input
                                    type="number"
                                    min="1"
                                    value={f2bJailConfig.maxretry}
                                    onChange={(e) => setF2bJailConfig({...f2bJailConfig, maxretry: e.target.value})}
                                    className="h-9 text-sm"
                                    placeholder={st("fail2ban.placeholders.maxRetries")}
                                  />
                                  <p className="text-[10px] text-muted-foreground">{st("fail2ban.failedAttemptsBeforeBan")}</p>
                                </div>
                                <div className="space-y-1.5">
                                  <Label className="text-xs text-muted-foreground">{st("fail2ban.banTimeSeconds")}</Label>
                                  <Input
                                    type="number"
                                    min="60"
                                    value={f2bJailConfig.permanent ? "" : f2bJailConfig.bantime}
                                    onChange={(e) => setF2bJailConfig({...f2bJailConfig, bantime: e.target.value, permanent: false})}
                                    className="h-9 text-sm"
                                    placeholder={f2bJailConfig.permanent ? st("values.permanent") : st("fail2ban.placeholders.banTime")}
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
                                      {st("fail2ban.permanentBanNeverExpires")}
                                    </label>
                                  </div>
                                </div>
                                <div className="space-y-1.5">
                                  <Label className="text-xs text-muted-foreground">{st("fail2ban.findTimeSeconds")}</Label>
                                  <Input
                                    type="number"
                                    min="60"
                                    value={f2bJailConfig.findtime}
                                    onChange={(e) => setF2bJailConfig({...f2bJailConfig, findtime: e.target.value})}
                                    className="h-9 text-sm"
                                    placeholder={st("fail2ban.placeholders.findTime")}
                                  />
                                  <p className="text-[10px] text-muted-foreground">{st("fail2ban.timeWindowHint")}</p>
                                </div>
                              </div>

                              <div className="bg-blue-500/10 border border-blue-500/20 rounded p-2.5 flex items-start gap-2">
                                <Info className="h-4 w-4 text-blue-500 flex-shrink-0 mt-0.5" />
                                <p className="text-[11px] text-blue-400">
                                  {st("fail2ban.commonValuesHint")}
                                </p>
                              </div>

                              <div className="flex gap-2 justify-end">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => setF2bEditingJail(null)}
                                  className="text-muted-foreground"
                                >
                                  {t("actions.cancel")}
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
                                  {st("fail2ban.saveConfiguration")}
                                </Button>
                              </div>
                            </div>
                          )}

                          {/* Mobile config summary (visible only on small screens) */}
                          <div className="sm:hidden flex items-center justify-around p-2 bg-muted/20 border-t border-border text-xs text-muted-foreground">
                            <span>{st("fail2ban.retries")}: <span className="text-foreground font-medium">{jail.maxretry}</span></span>
                            <span>{st("fail2ban.ban")}: <span className="text-foreground font-medium">{parseInt(jail.bantime, 10) === -1 ? st("values.perm") : formatBanTime(jail.bantime)}</span></span>
                            <span>{st("fail2ban.window")}: <span className="text-foreground font-medium">{formatBanTime(jail.findtime)}</span></span>
                          </div>

                          {/* Protection stats - inline */}
                          <div className="flex items-center gap-4 flex-wrap px-3 py-2 border-t border-border">
                            <div className="flex items-center gap-1.5 text-sm">
                              <span className="text-muted-foreground">{st("fail2ban.banned")}:</span>
                              <span className={`font-bold ${jail.currently_banned > 0 ? "text-red-500" : "text-green-500"}`}>
                                {jail.currently_banned}
                              </span>
                            </div>
                            <div className="w-px h-4 bg-border" />
                            <div className="flex items-center gap-1.5 text-sm">
                              <span className="text-muted-foreground">{st("fail2ban.totalBans")}:</span>
                              <span className="font-bold text-orange-500">{jail.total_banned}</span>
                            </div>
                            <div className="w-px h-4 bg-border" />
                            <div className="flex items-center gap-1.5 text-sm">
                              <span className="text-muted-foreground">{st("fail2ban.failedNow")}:</span>
                              <span className="font-bold text-yellow-500">{jail.currently_failed}</span>
                            </div>
                            <div className="w-px h-4 bg-border" />
                            <div className="flex items-center gap-1.5 text-sm">
                              <span className="text-muted-foreground">{st("fail2ban.totalFailed")}:</span>
                              <span className="font-bold text-muted-foreground">{jail.total_failed}</span>
                            </div>
                          </div>

                          {/* Blocked IPs list */}
                          {jail.banned_ips.length > 0 && (
                            <div className="border-t border-border">
                              <div className="px-3 py-2 bg-red-500/5">
                                <p className="text-xs font-semibold text-red-500 mb-2">
                                  {st("fail2ban.bannedIpsWithCount", { count: jail.banned_ips.length })}
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
                                          {entry.type === "local" ? "LAN" : entry.type === "external" ? st("values.external") : t("common.unknown")}
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
                                            {st("fail2ban.unban")}
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
                            <div className="px-3 py-2 border-t border-border text-center">
                              <p className="text-xs text-muted-foreground">{st("fail2ban.noBannedIps")}</p>
                            </div>
                          )}
                        </div>
                      ))}

                      {f2bDetails.jails.length === 0 && (
                        <div className="text-center py-6 text-muted-foreground text-sm">
                          {st("fail2ban.noJails")}
                        </div>
                      )}
                    </div>
                  )}

                  {/* ACTIVITY TAB */}
                  {f2bActiveTab === "activity" && (
                    <div className="space-y-1.5 max-h-80 overflow-y-auto">
                      {f2bActivity.length === 0 ? (
                        <div className="text-center py-6 text-muted-foreground text-sm">
                          {st("fail2ban.noActivity")}
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
                              {fail2banActivityLabel(event.action)}
                            </div>
                            <code className="text-xs font-mono text-foreground flex-shrink-0">{event.ip}</code>
                            <span className="text-xs text-muted-foreground">{fail2banProtectionLabel(event.jail)}</span>
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
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Search className="h-5 w-5 text-cyan-500" />
              <CardTitle>{st("lynis.title")}</CardTitle>
            </div>
            {lynisInfo?.installed && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowLynisUninstallConfirm(true)}
                disabled={uninstallingLynis}
                className="h-8 px-3 text-xs border-red-500/30 text-red-500 hover:bg-red-500/10 hover:text-red-400 hover:border-red-500/50"
              >
                {uninstallingLynis ? (
                  <div className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full mr-2" />
                ) : (
                  <Trash2 className="h-4 w-4 mr-2" />
                )}
                {st("values.uninstall")}
              </Button>
            )}
          </div>
          <CardDescription>
            {st("lynis.description")}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {toolsLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin h-8 w-8 border-4 border-cyan-500 border-t-transparent rounded-full" />
            </div>
          ) : !lynisInfo?.installed ? (
            <div className="space-y-4">
  <div className="flex items-center gap-3 p-4 bg-muted/50 rounded-lg">
  <div className="w-10 h-10 rounded-full bg-gray-500/10 flex items-center justify-center shrink-0">
  <Search className="h-5 w-5 text-gray-500" />
  </div>
  <div>
  <p className="font-medium">{st("lynis.notInstalled")}</p>
  <p className="text-sm text-muted-foreground">{st("lynis.notInstalledDescription")}</p>
  </div>
  </div>

              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
                <div className="flex items-start gap-3">
                  <Info className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
                  <div className="space-y-2 text-sm text-blue-400">
                    <p className="font-medium">{st("lynis.featuresTitle")}</p>
                    <ul className="list-disc list-inside space-y-1 text-blue-300">
                      <li>{st("lynis.featureScoring")}</li>
                      <li>{st("lynis.featureVulnerabilities")}</li>
                      <li>{st("lynis.featureCompliance")}</li>
                      <li>{st("lynis.featureGithub")}</li>
                    </ul>
                  </div>
                </div>
              </div>

              <Button
                onClick={() => setShowLynisInstaller(true)}
                className="bg-cyan-600 hover:bg-cyan-700 text-white"
              >
                <Download className="h-4 w-4 mr-2" />
                {st("lynis.install")}
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
                    <p className="text-sm text-muted-foreground">{st("lynis.installedDescription")}</p>
                  </div>
                </div>
                <div className="px-3 py-1 rounded-full text-sm font-medium bg-green-500/10 text-green-500">
                  {st("values.installed")}
                </div>
              </div>

              {/* Summary stats */}
              <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
                <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                  <p className="text-xs text-muted-foreground mb-1">{st("lynis.lastScan")}</p>
                  <p className="text-sm font-medium">
                    {lynisInfo.last_scan ? lynisInfo.last_scan.replace("T", " ").substring(0, 16) : st("values.never")}
                  </p>
                </div>
                <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                  <p className="text-xs text-muted-foreground mb-1">{st("lynis.hardeningIndex")}</p>
                  {(() => {
                    const { rawScore, adjustedScore: adjScore, displayScore, reportComplete, hasAdjustment } = getLynisScoreState(lynisReport, lynisInfo.hardening_index)
                    const scoreColorClass = displayScore === null || displayScore === undefined ? "text-muted-foreground" :
                      displayScore >= 70 ? "text-green-500" :
                      displayScore >= 50 ? "text-yellow-500" : "text-red-500"
                    return (
                      <div>
                        <p className={`text-xl font-bold ${scoreColorClass}`}>
                          {displayScore !== null && displayScore !== undefined ? displayScore : "—"}
                        </p>
                        {hasAdjustment && (
                          <p className="text-[10px] text-muted-foreground mt-0.5">
                            {st("lynis.scoreBreakdown", { raw: rawScore ?? "N/A", adjusted: adjScore ?? "N/A" })}
                          </p>
                        )}
                        {!reportComplete && lynisReport && (
                          <p className="text-[10px] text-yellow-500 mt-0.5">
                            {st("lynis.reportIncompleteShort")}
                          </p>
                        )}
                      </div>
                    )
                  })()}
                </div>
                <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                  <p className="text-xs text-muted-foreground mb-1">{st("lynis.warnings")}</p>
                  {(() => {
                    if (!lynisReport) return <p className="text-xl font-bold text-muted-foreground">-</p>
                    const total = lynisReport.warnings.length
                    const expected = lynisReport.proxmox_expected_warnings ?? 0
                    const real = getActionableCount(total, expected)
                    return (
                      <div>
                        <p className={`text-xl font-bold ${real > 0 ? "text-red-500" : total > 0 ? "text-yellow-500" : "text-green-500"}`}>
                          {real > 0 ? real : total}
                        </p>
                        {expected > 0 && (
                          <p className="text-[10px] text-muted-foreground mt-0.5">
                            {st("lynis.pveExpectedPlus", { count: expected })}
                          </p>
                        )}
                      </div>
                    )
                  })()}
                </div>
                <div className="p-3 bg-muted/30 rounded-lg border border-border text-center">
                  <p className="text-xs text-muted-foreground mb-1">{st("lynis.suggestions")}</p>
                  {(() => {
                    if (!lynisReport) return <p className="text-xl font-bold text-muted-foreground">-</p>
                    const total = lynisReport.suggestions.length
                    const expected = lynisReport.proxmox_expected_suggestions ?? 0
                    const real = getActionableCount(total, expected)
                    return (
                      <div>
                        <p className={`text-xl font-bold ${real > 0 ? "text-yellow-500" : "text-green-500"}`}>
                          {real > 0 ? real : total}
                        </p>
                        {expected > 0 && (
                          <p className="text-[10px] text-muted-foreground mt-0.5">
                            {st("lynis.pveExpectedPlus", { count: expected })}
                          </p>
                        )}
                      </div>
                    )
                  })()}
                </div>
              </div>

              {/* Hardening bar */}
              {(() => {
                const { rawScore, displayScore, reportComplete, hasAdjustment } = getLynisScoreState(lynisReport, lynisInfo.hardening_index)
                if (!reportComplete || displayScore === null || displayScore === undefined || rawScore === null || rawScore === undefined) {
                  if (!lynisReport) return null
                  return (
                    <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-3 text-sm text-yellow-200">
                      <p className="font-medium">{st("lynis.reportIncompleteTitle")}</p>
                      <p className="text-xs text-yellow-200/80 mt-1">{st("lynis.reportIncompleteDescription")}</p>
                    </div>
                  )
                }
                return (
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">
                        {st("lynis.securityHardeningScore")} {hasAdjustment && <span className="text-cyan-400/70">{st("lynis.proxmoxAdjustedParen")}</span>}
                      </span>
                      <span className={`font-bold ${
                        displayScore >= 70 ? "text-green-500" : displayScore >= 50 ? "text-yellow-500" : "text-red-500"
                      }`}>
                        {displayScore}/100
                      </span>
                    </div>
                    {hasAdjustment ? (
                      <div className="relative w-full h-3 bg-muted/50 rounded-full overflow-hidden">
                        {/* Raw score bar (dimmed) */}
                        <div
                          className="absolute inset-y-0 left-0 rounded-full bg-yellow-500/30"
                          style={{ width: `${rawScore}%` }}
                        />
                        {/* Adjusted score bar */}
                        <div
                          className={`absolute inset-y-0 left-0 rounded-full transition-all duration-1000 ${
                            displayScore >= 70 ? "bg-green-500" : displayScore >= 50 ? "bg-yellow-500" : "bg-red-500"
                          }`}
                          style={{ width: `${displayScore}%` }}
                        />
                      </div>
                    ) : (
                      <div className="w-full h-3 bg-muted/50 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-1000 ${
                            displayScore >= 70 ? "bg-green-500" : displayScore >= 50 ? "bg-yellow-500" : "bg-red-500"
                          }`}
                          style={{ width: `${displayScore}%` }}
                        />
                      </div>
                    )}
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                      <span>{st("lynis.scoreCritical")}</span>
                      <span>{st("lynis.scoreModerate")}</span>
                      <span>{st("lynis.scoreGood")}</span>
                    </div>
                    {hasAdjustment && (
                      <p className="text-[10px] text-cyan-400/70 text-center">
                        {st("lynis.rawScorePrefix")} {rawScore}/100 | {st("lynis.expectedFindings", { count: (lynisReport?.proxmox_expected_warnings ?? 0) + (lynisReport?.proxmox_expected_suggestions ?? 0) })}
                      </p>
                    )}
                  </div>
                )
              })()}

              {/* Running indicator */}
              {lynisAuditRunning && (
                <div className="bg-cyan-500/10 border border-cyan-500/20 rounded-lg p-4">
                  <div className="flex items-center gap-3">
                    <div className="animate-spin h-5 w-5 border-2 border-cyan-500 border-t-transparent rounded-full" />
                    <div>
                      <p className="text-sm font-medium text-cyan-500">{st("lynis.auditInProgress")}</p>
                      <p className="text-xs text-cyan-400/70">{st("lynis.auditInProgressDescription")}</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Reports list */}
              {lynisReport && (
                <div className="space-y-2">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{st("lynis.auditReports")}</p>

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
                            {st("lynis.auditReportTitle")} - {lynisReport.datetime_start
                              ? lynisReport.datetime_start.replace("T", " ").substring(0, 16)
                              : lynisInfo.last_scan?.replace("T", " ").substring(0, 16) || st("values.unknownDate")}
                          </p>
                          <p className="text-[11px] text-muted-foreground">
                            {(() => {
                              const { displayScore, reportComplete } = getLynisScoreState(lynisReport)
                              if (!reportComplete) return st("lynis.reportIncompleteShort")
                              return st("lynis.reportSummary", {
                                host: lynisReport.hostname || st("values.system"),
                                tests: lynisCountText("tests", lynisReport.tests_performed),
                                score: displayScore ?? "N/A",
                                warnings: lynisCountText("warnings", getActionableCount(lynisReport.warnings.length, lynisReport.proxmox_expected_warnings ?? 0)),
                                suggestions: lynisCountText("suggestions", getActionableCount(lynisReport.suggestions.length, lynisReport.proxmox_expected_suggestions ?? 0)),
                              })
                            })()}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {(() => {
                          const { reportComplete } = getLynisScoreState(lynisReport)
                          return (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation()
                            if (!reportComplete) return
                            const html = generatePrintableReport(lynisReport)
                            // Use Blob URL for Safari-safe preview (avoids document.write issues)
                            const blob = new Blob([html], { type: "text/html" })
                            const url = URL.createObjectURL(blob)
                            const w = window.open(url, "_blank")
                            // Revoke after a delay so it loads first
                            if (w) setTimeout(() => URL.revokeObjectURL(url), 60000)
                          }}
                          disabled={!reportComplete}
                          className="h-7 gap-1.5 px-2.5 text-xs border-cyan-500/30 text-cyan-500 hover:text-cyan-400 hover:bg-cyan-500/10"
                          title={reportComplete ? st("lynis.printSavePdf") : st("lynis.reportIncompleteShort")}
                        >
                          <Printer className="h-3.5 w-3.5" />
                          <span className="hidden sm:inline">PDF</span>
                        </Button>
                          )
                        })()}
                        <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${lynisShowReport ? "rotate-180" : ""}`} />
                        {/* Delete button separated with divider to prevent accidental clicks */}
                        <div className="hidden sm:block w-px h-5 bg-border mx-1" />
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation()
                            if (confirm(st("confirm.deleteAuditReport"))) {
                              fetchApi("/api/security/lynis/report", { method: "DELETE" })
                                .then(() => {
                                  setLynisReport(null)
                                  setLynisShowReport(false)
                                  setSuccess(st("messages.reportDeleted"))
                                  loadSecurityTools()
                                })
                                .catch(() => setError(st("errors.deleteReportFailed")))
                            }
                          }}
                          className="h-7 px-2 text-xs text-red-500 hover:text-red-400 hover:bg-red-500/10 ml-2 sm:ml-0"
                          title={st("lynis.deleteReport")}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </button>

                    {/* Expanded report details */}
                    {lynisShowReport && (
                      <div className="border-t border-border">
                        {/* System info strip */}
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-border">
                          <div className="p-2.5 bg-card text-center">
                            <p className="text-[10px] text-muted-foreground uppercase">{st("lynis.hostname")}</p>
                            <p className="text-xs font-medium truncate">{lynisReport.hostname || "N/A"}</p>
                          </div>
                          <div className="p-2.5 bg-card text-center">
                            <p className="text-[10px] text-muted-foreground uppercase">OS</p>
                            <p className="text-xs font-medium truncate">{lynisReport.os_fullname || `${lynisReport.os_name} ${lynisReport.os_version}`.trim() || "N/A"}</p>
                          </div>
                          <div className="p-2.5 bg-card text-center">
                            <p className="text-[10px] text-muted-foreground uppercase">{st("lynis.kernel")}</p>
                            <p className="text-xs font-medium truncate">{lynisReport.kernel_version || "N/A"}</p>
                          </div>
                          <div className="p-2.5 bg-card text-center">
                            <p className="text-[10px] text-muted-foreground uppercase">{st("lynis.tests")}</p>
                            <p className="text-xs font-medium">{lynisReport.tests_performed}</p>
                          </div>
                        </div>

                        {/* Report tabs - responsive with shorter labels on mobile */}
                        <div className="flex gap-0 border-t border-border overflow-x-auto">
                          {(["overview", "checks", "warnings", "suggestions"] as const).map((tab) => (
                            <button
                              key={tab}
                              onClick={() => setLynisActiveTab(tab)}
                              className={`flex-1 min-w-0 px-2 sm:px-3 py-2 text-xs font-medium transition-all flex items-center justify-center gap-1 sm:gap-1.5 border-r last:border-r-0 border-border ${
                                lynisActiveTab === tab
                                  ? "bg-cyan-500 text-white"
                                  : "bg-muted/20 text-muted-foreground hover:text-foreground hover:bg-muted/40"
                              }`}
                            >
                              {tab === "overview" && <BarChart3 className="h-3 w-3 shrink-0" />}
                              {tab === "checks" && <Search className="h-3 w-3 shrink-0" />}
                              {tab === "warnings" && <TriangleAlert className="h-3 w-3 shrink-0" />}
                              {tab === "suggestions" && <Info className="h-3 w-3 shrink-0" />}
                              <span className="hidden sm:inline">
                                {tab === "overview" ? st("lynis.tabs.overview")
                                  : tab === "checks" ? st("lynis.tabs.checksWithCount", { count: lynisReport.sections?.length || 0 })
                                  : tab === "warnings" ? st("lynis.tabs.warningsWithCount", { count: lynisReport.warnings.length })
                                  : st("lynis.tabs.suggestionsWithCount", { count: lynisReport.suggestions.length })}
                              </span>
                              <span className="sm:hidden">
                                {tab === "overview" ? ""
                                  : tab === "checks" ? `(${lynisReport.sections?.length || 0})`
                                  : tab === "warnings" ? `(${lynisReport.warnings.length})`
                                  : `(${lynisReport.suggestions.length})`}
                              </span>
                            </button>
                          ))}
                        </div>

                        {/* Overview tab */}
                        {lynisActiveTab === "overview" && (
                          <div className="p-4 space-y-3">
                            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                              <div className="p-3 rounded-lg border border-border bg-muted/20 text-center">
                                <p className="text-[10px] text-muted-foreground uppercase mb-1">{st("lynis.packages")}</p>
                                <p className="text-lg font-bold">{lynisReport.installed_packages || "N/A"}</p>
                              </div>
                              <div className="p-3 rounded-lg border border-border bg-muted/20 text-center">
                                <p className="text-[10px] text-muted-foreground uppercase mb-1">{st("lynis.firewall")}</p>
                                <p className={`text-lg font-bold ${lynisReport.firewall_active ? "text-green-500" : "text-red-500"}`}>
                                  {lynisReport.firewall_active ? st("values.active") : st("values.inactive")}
                                </p>
                              </div>
                              <div className="p-3 rounded-lg border border-border bg-muted/20 text-center">
                                <p className="text-[10px] text-muted-foreground uppercase mb-1">{st("lynis.malwareScanner")}</p>
                                <p className={`text-lg font-bold ${lynisReport.malware_scanner ? "text-green-500" : "text-yellow-500"}`}>
                                  {lynisReport.malware_scanner ? st("values.installed") : st("lynis.malwareScannerNotInstalled")}
                                </p>
                              </div>
                            </div>

                            {/* Security checklist */}
                            <div className="space-y-1.5">
                              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{st("lynis.quickStatus")}</p>
                              {(() => {
                                const { displayScore, reportComplete } = getLynisScoreState(lynisReport)
                                const adjScore = displayScore ?? 0
                                const realWarnings = getActionableCount(lynisReport.warnings.length, lynisReport.proxmox_expected_warnings ?? 0)
                                return [
                                {
                                  label: st("lynis.firewall"),
                                  ok: lynisReport.firewall_active,
                                  passText: st("values.active"),
                                  failText: st("values.inactive"),
                                },
                                {
                                  label: st("lynis.malwareScanner"),
                                  ok: lynisReport.malware_scanner,
                                  passText: st("values.installed"),
                                  failText: st("values.notInstalled"),
                                  isWarning: true,
                                },
                                {
                                  label: st("lynis.warnings"),
                                  ok: realWarnings <= 0,
                                  passText: lynisReport.warnings.length === 0 ? st("values.none") : st("lynis.allPveExpected", { count: lynisReport.warnings.length }),
                                  failText: st("lynis.actionableCount", { count: realWarnings }) + (lynisReport.proxmox_expected_warnings ? ` ${st("lynis.expectedWarningsSuffix", { count: lynisReport.proxmox_expected_warnings })}` : ""),
                                  isWarning: realWarnings > 0 && realWarnings <= 5,
                                },
                                {
                                  label: st("lynis.hardeningScorePve"),
                                  ok: reportComplete && adjScore >= 70,
                                  passText: `${adjScore}/100`,
                                  failText: reportComplete ? `${adjScore}/100 (< 70)` : st("lynis.reportIncompleteShort"),
                                  isWarning: !reportComplete || adjScore >= 50,
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
                              )})
                              })()}
                            </div>
                          </div>
                        )}

                        {/* Checks tab */}
                        {lynisActiveTab === "checks" && (
                          <div className="max-h-[500px] overflow-y-auto">
                            {(!lynisReport.sections || lynisReport.sections.length === 0) ? (
                              <div className="p-6 text-center text-sm text-muted-foreground">
                                {st("lynis.noCheckDetails")}
                              </div>
                            ) : (
                              <div className="divide-y divide-border">
                                {lynisReport.sections.map((section, sIdx) => (
                                  <div key={sIdx}>
                                    <div className="px-3 py-2 bg-muted/30 flex items-center gap-2">
                                      <span className="text-[10px] font-bold text-cyan-500 bg-cyan-500/10 px-1.5 py-0.5 rounded">{sIdx + 1}</span>
                                      <span className="text-xs font-semibold">{section.name}</span>
                                      <span className="text-[10px] text-muted-foreground ml-auto">{st("lynis.checksCount", { count: section.checks.length })}</span>
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
                                {st("lynis.noWarnings")}
                              </div>
                            ) : (
                              <div className="divide-y divide-border">
                                {lynisReport.warnings.map((w, idx) => (
                                  <div key={idx} className={`p-3 hover:bg-muted/20 transition-colors ${w.proxmox_expected ? "opacity-60" : ""}`}>
                                    <div className="flex items-start gap-2">
                                      <div className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${
                                        w.proxmox_expected ? "bg-cyan-500" :
                                        w.proxmox_severity === "low" ? "bg-yellow-500" : "bg-red-500"
                                      }`} />
                                      <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                                          <code className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                                            w.proxmox_expected ? "bg-cyan-500/10 text-cyan-400" : "bg-red-500/10 text-red-500"
                                          }`}>{w.test_id}</code>
                                          {w.proxmox_expected && (
                                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400">{st("lynis.pveExpected")}</span>
                                          )}
                                          {!w.proxmox_expected && w.proxmox_severity === "low" && (
                                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/10 text-yellow-500">{st("lynis.lowRisk")}</span>
                                          )}
                                          {!w.proxmox_expected && !w.proxmox_severity && w.severity && (
                                            <span className="text-[10px] text-red-400">{w.severity}</span>
                                          )}
                                        </div>
                                        <p className="text-sm text-foreground">{w.description}</p>
                                        {w.proxmox_context && (
                                          <p className="text-xs text-cyan-400/70 mt-1 flex items-start gap-1">
                                            <span className="shrink-0">Proxmox:</span> {w.proxmox_context}
                                          </p>
                                        )}
                                        {w.solution && (
                                          <p className="text-xs text-muted-foreground mt-1">
                                            {st("lynis.solution")}: {w.solution}
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
                                {st("lynis.noSuggestions")}
                              </div>
                            ) : (
                              <div className="divide-y divide-border">
                                {lynisReport.suggestions.map((s, idx) => (
                                  <div key={idx} className={`p-3 hover:bg-muted/20 transition-colors ${s.proxmox_expected ? "opacity-60" : ""}`}>
                                    <div className="flex items-start gap-2">
                                      <div className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${
                                        s.proxmox_expected ? "bg-cyan-500" :
                                        s.proxmox_severity === "low" ? "bg-muted-foreground" : "bg-yellow-500"
                                      }`} />
                                      <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                                          <code className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                                            s.proxmox_expected ? "bg-cyan-500/10 text-cyan-400" : "bg-yellow-500/10 text-yellow-500"
                                          }`}>{s.test_id}</code>
                                          {s.proxmox_expected && (
                                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400">{st("lynis.pveExpected")}</span>
                                          )}
                                          {!s.proxmox_expected && s.proxmox_severity === "low" && (
                                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{st("lynis.lowPriority")}</span>
                                          )}
                                        </div>
                                        <p className="text-sm text-foreground">{s.description}</p>
                                        {s.proxmox_context && (
                                          <p className="text-xs text-cyan-400/70 mt-1 flex items-start gap-1">
                                            <span className="shrink-0">Proxmox:</span> {s.proxmox_context}
                                          </p>
                                        )}
                                        {s.solution && (
                                          <p className="text-xs text-muted-foreground mt-1">
                                            {st("lynis.solution")}: {s.solution}
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
                className="bg-cyan-600 hover:bg-cyan-700 text-white"
              >
                {lynisAuditRunning ? (
                  <>
                    <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full mr-2" />
                    {st("lynis.runningAudit")}
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4 mr-2" />
                    {st("lynis.runAudit")}
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
        title={st("fail2ban.installationTitle")}
        description={st("fail2ban.installationDescription")}
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
        title={st("lynis.installationTitle")}
        description={st("lynis.installationDescription")}
      />

      {/* Uninstall Confirmation Dialogs */}
      {showFail2banUninstallConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-background border border-border rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center">
                <AlertTriangle className="h-5 w-5 text-red-500" />
              </div>
              <div>
                <h3 className="font-semibold text-lg">{st("fail2ban.uninstallConfirmTitle")}</h3>
                <p className="text-sm text-muted-foreground">{st("confirm.cannotBeUndone")}</p>
              </div>
            </div>
            <p className="text-sm text-muted-foreground mb-6">
              {st("fail2ban.uninstallConfirmDescription")}
            </p>
            <ul className="text-sm text-muted-foreground mb-6 list-disc list-inside space-y-1">
              <li>{st("fail2ban.removeSshJail")}</li>
              <li>{st("fail2ban.removeProxmoxProtection")}</li>
              <li>{st("fail2ban.removeMonitorProtection")}</li>
              <li>{st("fail2ban.removeCustomJails")}</li>
              <li>{st("fail2ban.removeAuthLogger")}</li>
            </ul>
            <div className="flex justify-end gap-3">
              <Button
                variant="outline"
                onClick={() => setShowFail2banUninstallConfirm(false)}
              >
                {t("actions.cancel")}
              </Button>
              <Button
                variant="destructive"
                onClick={handleUninstallFail2ban}
                disabled={uninstallingFail2ban}
              >
                {uninstallingFail2ban ? (
                  <>
                    <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full mr-2" />
                    {st("values.uninstalling")}
                  </>
                ) : (
                  <>
                    <Trash2 className="h-4 w-4 mr-2" />
                    {st("values.uninstall")}
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      )}

      {showLynisUninstallConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-background border border-border rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center">
                <AlertTriangle className="h-5 w-5 text-red-500" />
              </div>
              <div>
                <h3 className="font-semibold text-lg">{st("lynis.uninstallConfirmTitle")}</h3>
                <p className="text-sm text-muted-foreground">{st("confirm.cannotBeUndone")}</p>
              </div>
            </div>
            <p className="text-sm text-muted-foreground mb-6">
              {st("lynis.uninstallConfirmDescription")}
            </p>
            <ul className="text-sm text-muted-foreground mb-6 list-disc list-inside space-y-1">
              <li>{st("lynis.removeInstallation")}</li>
              <li>{st("lynis.removeWrapper")}</li>
              <li>{st("lynis.removeReports")}</li>
            </ul>
            <div className="flex justify-end gap-3">
              <Button
                variant="outline"
                onClick={() => setShowLynisUninstallConfirm(false)}
              >
                {t("actions.cancel")}
              </Button>
              <Button
                variant="destructive"
                onClick={handleUninstallLynis}
                disabled={uninstallingLynis}
              >
                {uninstallingLynis ? (
                  <>
                    <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full mr-2" />
                    {st("values.uninstalling")}
                  </>
                ) : (
                  <>
                    <Trash2 className="h-4 w-4 mr-2" />
                    {st("values.uninstall")}
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      )}

      <TwoFactorSetup
        open={show2FASetup}
        onClose={() => setShow2FASetup(false)}
        onSuccess={() => {
          setSuccess(st("messages.twoFactorEnabled"))
          checkAuthStatus()
        }}
      />
    </div>
  )
}
