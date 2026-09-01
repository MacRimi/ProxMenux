"use client"

import { useState, useEffect } from "react"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Checkbox } from "./ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog"
import {
  ShieldCheck, Globe, ExternalLink, Loader2, CheckCircle, XCircle,
  Play, Square, RotateCw, Trash2, FileText, ChevronRight, ChevronDown,
  AlertTriangle, Info, Network, Eye, EyeOff, Settings, Wifi, Key,
  ArrowUpCircle,
} from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

interface NetworkInfo {
  interface: string
  type?: string
  address?: string
  ip?: string
  subnet: string
  prefixlen?: number
  recommended?: boolean
}

interface StorageInfo {
  name: string
  type: string
  total: number
  used: number
  avail: number
  active: boolean
  enabled: boolean
  recommended: boolean
}

interface AppStatus {
  state: "not_installed" | "running" | "stopped" | "error"
  health: string
  uptime_seconds: number
  last_check: string
}

interface ConfigSchema {
  [key: string]: {
    type: string
    label: string
    description: string
    placeholder?: string
    default?: any
    required?: boolean
    sensitive?: boolean
    env_var?: string
    help_url?: string
    help_text?: string
    options?: Array<{ value: string; label: string; description?: string }>
    depends_on?: { field: string; values: string[] }
    flag?: string
    warning?: string
    validation?: { pattern?: string; max_length?: number; message?: string }
  }
}

interface WizardStep {
  id: string
  title: string
  description: string
  fields?: string[]
}

export function SecureGatewaySetup() {
  const t = useT()
  const sg = (key: string, params?: Record<string, string | number>) => t(`securityPage.secureGateway.${key}`, params)
  const maybeSg = (key: string, fallback?: string) => {
    const fullKey = `securityPage.secureGateway.${key}`
    const value = t(fullKey)
    return value === fullKey ? fallback || "" : value
  }
  const fieldText = (fieldName: string, part: string, fallback?: string) =>
    maybeSg(`schema.${fieldName}.${part}`, fallback)
  const optionText = (fieldName: string, value: string, part: string, fallback?: string) =>
    maybeSg(`schema.${fieldName}.options.${value}.${part}`, fallback)
  const stepText = (step: WizardStep, part: "title" | "description") =>
    maybeSg(`steps.${step.id}.${part}`, step[part])

  // State
  const [loading, setLoading] = useState(true)
  const [runtimeAvailable, setRuntimeAvailable] = useState(false)
  const [runtimeInfo, setRuntimeInfo] = useState<{ runtime: string; version: string } | null>(null)
  // Surface initial-data load failures. Wizard rendering depends on
  // wizardSteps being populated; if loadInitialData throws, we previously
  // ended up with `loading=false` and an empty wizard, which read as a
  // broken UI. Keep the error message so we can show a retry button.
  const [loadError, setLoadError] = useState<string | null>(null)
  const [appStatus, setAppStatus] = useState<AppStatus>({ state: "not_installed", health: "unknown", uptime_seconds: 0, last_check: "" })
  const [configSchema, setConfigSchema] = useState<ConfigSchema | null>(null)
  const [wizardSteps, setWizardSteps] = useState<WizardStep[]>([])
  const [networks, setNetworks] = useState<NetworkInfo[]>([])
  const [storages, setStorages] = useState<StorageInfo[]>([])
  
  // Wizard state
  const [showWizard, setShowWizard] = useState(false)
  const [currentStep, setCurrentStep] = useState(0)
  const [config, setConfig] = useState<Record<string, any>>({})
  const [deploying, setDeploying] = useState(false)
  const [deployProgress, setDeployProgress] = useState("")
  const [deployError, setDeployError] = useState("")
  
  // Installed state
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [showLogs, setShowLogs] = useState(false)
  const [logs, setLogs] = useState("")
  const [logsLoading, setLogsLoading] = useState(false)
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false)
  const [showAuthKey, setShowAuthKey] = useState(false)
  
  // Post-deploy confirmation
  const [showPostDeployInfo, setShowPostDeployInfo] = useState(false)
  const [deployedConfig, setDeployedConfig] = useState<Record<string, any>>({})
  
  // Host IP for "Host Only" mode
  const [hostIp, setHostIp] = useState("")
  
  // Update Auth Key
  const [showUpdateAuthKey, setShowUpdateAuthKey] = useState(false)
  const [newAuthKey, setNewAuthKey] = useState("")
  const [updateAuthKeyLoading, setUpdateAuthKeyLoading] = useState(false)
  const [updateAuthKeyError, setUpdateAuthKeyError] = useState("")

  // Sprint 14.6: Tailscale / Alpine package update flow.
  //   `updateInfo`: result of GET /api/oci/installed/<id>/update-check.
  //                 `null` until the first probe lands.
  //   `updateApplying`: true while POST /update is running. Long op
  //                     (apk upgrade can take 1-3 min on slow links).
  //   `updateError` / `updateResultMsg`: surfaced as a small banner
  //                 so the user gets explicit feedback.
  const [updateInfo, setUpdateInfo] = useState<{
    available: boolean
    current_version?: string | null
    latest_version?: string | null
    packages?: Array<{ name: string; current: string; latest: string }>
    last_checked_iso?: string
    error?: string | null
  } | null>(null)
  const [updateApplying, setUpdateApplying] = useState(false)
  const [updateError, setUpdateError] = useState<string | null>(null)
  const [updateResultMsg, setUpdateResultMsg] = useState<string | null>(null)
  
  // Password visibility
  const [visiblePasswords, setVisiblePasswords] = useState<Set<string>>(new Set())

  useEffect(() => {
    loadInitialData()
  }, [])

  const loadInitialData = async () => {
    setLoading(true)
    setLoadError(null)
    try {
      // Secure Gateway uses standard LXC, not OCI containers
      // So we don't require PVE 9.1+ - it works on any Proxmox version
      setRuntimeAvailable(true)
      
      // Still load runtime info for reference
      const runtimeRes = await fetchApi("/api/oci/runtime")
      if (runtimeRes.success) {
        setRuntimeInfo({ runtime: runtimeRes.runtime || "proxmox-lxc", version: runtimeRes.version || "unknown" })
      }

      // Load app definition
      const catalogRes = await fetchApi("/api/oci/catalog/secure-gateway")
      if (catalogRes.success && catalogRes.app) {
        setConfigSchema(catalogRes.app.config_schema || {})
        setWizardSteps(catalogRes.app.ui?.wizard_steps || [])
        
        // Set defaults
        const defaults: Record<string, any> = {}
        for (const [key, field] of Object.entries(catalogRes.app.config_schema || {})) {
          if (field.default !== undefined) {
            defaults[key] = field.default
          }
        }
        setConfig(defaults)
      }

      // Load status
      await loadStatus()

      // Load networks
      const networksRes = await fetchApi("/api/oci/networks")
      if (networksRes.success) {
        setNetworks(networksRes.networks || [])
        // Get host IP for "Host Only" mode
        const primaryNetwork = networksRes.networks?.find((n: NetworkInfo) => n.recommended) || networksRes.networks?.[0]
        // Backend returns "ip" field with the host IP address
        const hostIpValue = primaryNetwork?.ip || primaryNetwork?.address
        if (hostIpValue) {
          // Remove CIDR notation if present (e.g., "192.168.0.55/24" -> "192.168.0.55")
          const ip = hostIpValue.split("/")[0]
          setHostIp(ip)
        }
      }

      // Load available storages
      const storagesRes = await fetchApi("/api/oci/storages")
      if (storagesRes.success && storagesRes.storages?.length > 0) {
        setStorages(storagesRes.storages)
        // Set default storage (first recommended one)
        const recommended = storagesRes.storages.find((s: StorageInfo) => s.recommended) || storagesRes.storages[0]
        if (recommended) {
          setConfig(prev => ({ ...prev, storage: recommended.name }))
        }
      }
    } catch (err) {
      console.error("Failed to load data:", err)
      setLoadError(err instanceof Error ? err.message : sg("errors.loadWizardFailed"))
    } finally {
      setLoading(false)
    }
  }

  const loadStatus = async () => {
    try {
      const statusRes = await fetchApi("/api/oci/status/secure-gateway")
      if (statusRes.success) {
        setAppStatus(statusRes.status)
        // Once we know the gateway is installed, kick off the update
        // probe in the background. It hits the 24h-cached endpoint, so
        // repeating this on every status reload is essentially free.
        if (statusRes.status?.state && statusRes.status.state !== "not_installed") {
          loadUpdateInfo()
        }
      }
    } catch (err) {
      // Not installed is ok
    }
  }

  // Pull the cached update-check from the backend. The server-side
  // cache is 24h, so this is cheap to call on mount. After applying
  // an update we pass `force=true` so the panel doesn't keep
  // rendering the pre-update "available" state from a stale cache
  // entry.
  const loadUpdateInfo = async (force = false) => {
    try {
      const url = force
        ? "/api/oci/installed/secure-gateway/update-check?force=1"
        : "/api/oci/installed/secure-gateway/update-check"
      const res: any = await fetchApi(url)
      if (res?.success) {
        setUpdateInfo({
          available: !!res.available,
          current_version: res.current_version,
          latest_version: res.latest_version,
          packages: res.packages,
          last_checked_iso: res.last_checked_iso,
          error: res.error || null,
        })
      }
    } catch {
      // Silent — the panel just won't show the update line.
    }
  }

  const handleApplyUpdate = async () => {
    setUpdateApplying(true)
    setUpdateError(null)
    setUpdateResultMsg(null)
    try {
      const res: any = await fetchApi("/api/oci/installed/secure-gateway/update", {
        method: "POST",
      })
      if (res?.success) {
        setUpdateResultMsg(res.message || sg("messages.updateApplied"))
        // Re-probe with force=true so the panel flips back to "No
        // updates available" immediately, bypassing the 24h server
        // cache which may still hold the pre-apply "available" entry.
        await loadUpdateInfo(true)
        // Status may briefly show "stopped" if tailscale was restarted —
        // refresh that too so the action buttons render the right state.
        await loadStatus()
      } else {
        setUpdateError(res?.message || sg("errors.updateFailed"))
      }
    } catch (err) {
      setUpdateError(err instanceof Error ? err.message : sg("errors.networkUpdateFailed"))
    } finally {
      setUpdateApplying(false)
    }
  }

  const handleDeploy = async () => {
    // Concurrency guard. The button is also `disabled={deploying}`, but
    // a screen reader, a fast double-tap on a high-latency link, or an
    // automated test can fire two clicks before React re-renders the
    // disabled state. The handler-level guard makes it impossible to
    // submit a second deploy while one is still in flight. Audit Tier 6
    // — `secure-gateway-setup.tsx` action buttons sin guard.
    if (deploying) return
    setDeploying(true)
    setDeployError("")
    setDeployProgress(sg("messages.preparingDeployment"))

    try {
      // Validate required fields
      const step = wizardSteps[currentStep]
      if (step?.fields) {
        for (const fieldName of step.fields) {
          const field = configSchema?.[fieldName]
          if (field?.required && !config[fieldName]) {
            setDeployError(sg("errors.fieldRequired", { field: fieldText(fieldName, "label", field.label) }))
            setDeploying(false)
            return
          }
        }
      }

      // Prepare config based on access_mode
      const deployConfig = { ...config }
      
      if (config.access_mode === "host_only" && hostIp) {
        // Host only: just the host IP
        deployConfig.advertise_routes = [`${hostIp}/32`]
      } else if (config.access_mode === "proxmox_network") {
        // Proxmox network: use the recommended network (should already be set)
        if (!deployConfig.advertise_routes?.length) {
          const recommendedNetwork = networks.find((n) => n.recommended) || networks[0]
          if (recommendedNetwork) {
            deployConfig.advertise_routes = [recommendedNetwork.subnet]
          }
        }
      }
      // For "custom", the user has already selected networks manually

      setDeployProgress(sg("messages.creatingLxc"))
      
      const result = await fetchApi("/api/oci/deploy", {
        method: "POST",
        body: JSON.stringify({
          app_id: "secure-gateway",
          config: deployConfig
        })
      })

      if (!result.success) {
        // Make runtime errors more user-friendly
        let errorMsg = result.message || sg("errors.deploymentFailed")
        if (errorMsg.includes("9.1") || errorMsg.includes("OCI") || errorMsg.includes("not supported")) {
          errorMsg = sg("errors.ociRequiresPve")
        }
        setDeployError(errorMsg)
        setDeploying(false)
        return
      }

      setDeployProgress(sg("messages.gatewayDeployed"))

      // Wipe the Tailscale auth_key from React state so it's no longer
      // reachable from a future XSS / state-inspection. The key only needs
      // to live in memory for the duration of the deploy POST. Audit
      // residual #11 — secure-gateway auth_key persistence.
      setConfig((prev) => ({ ...prev, auth_key: "" }))

      // Wait and reload status, then show post-deploy info
      setTimeout(async () => {
        await loadStatus()
        setShowWizard(false)
        setDeploying(false)
        setCurrentStep(0)
        
        // Show post-deploy confirmation - always show when access mode is set (routes need approval)
        const needsApproval = deployConfig.access_mode && deployConfig.access_mode !== "none"
        if (needsApproval) {
          // Ensure advertise_routes is set for the dialog
          const finalConfig = { ...deployConfig }
          if (deployConfig.access_mode === "host_only" && hostIp) {
            finalConfig.advertise_routes = [`${hostIp}/32`]
          }
          setDeployedConfig(finalConfig)
          setShowPostDeployInfo(true)
        }
      }, 2000)

    } catch (err: any) {
      setDeployError(err.message || sg("errors.deploymentFailed"))
      setDeploying(false)
    }
  }

  const handleAction = async (action: "start" | "stop" | "restart") => {
    if (actionLoading) return
    setActionLoading(action)
    try {
      const result = await fetchApi(`/api/oci/installed/secure-gateway/${action}`, {
        method: "POST"
      })
      if (result.success) {
        await loadStatus()
      }
    } catch (err) {
      console.error(`Failed to ${action}:`, err)
    } finally {
      setActionLoading(null)
    }
  }

  const handleUpdateAuthKey = async () => {
    if (!newAuthKey.trim()) {
      setUpdateAuthKeyError(sg("errors.authKeyRequired"))
      return
    }
    
    if (updateAuthKeyLoading) return
    setUpdateAuthKeyLoading(true)
    setUpdateAuthKeyError("")

    try {
      const result = await fetchApi("/api/oci/installed/secure-gateway/update-auth-key", {
        method: "POST",
        body: JSON.stringify({
          auth_key: newAuthKey.trim()
        })
      })
      
      if (!result.success) {
        setUpdateAuthKeyError(result.message || sg("errors.updateAuthKeyFailed"))
        setUpdateAuthKeyLoading(false)
        return
      }
      
      // Success - close dialog and reload status
      setShowUpdateAuthKey(false)
      setNewAuthKey("")
      await loadStatus()
    } catch (err: any) {
      setUpdateAuthKeyError(err.message || sg("errors.updateAuthKeyFailed"))
    } finally {
      setUpdateAuthKeyLoading(false)
    }
  }

  const handleRemove = async () => {
    if (actionLoading) return
    setActionLoading("remove")
    try {
      const result = await fetchApi("/api/oci/installed/secure-gateway?remove_data=false", {
        method: "DELETE"
      })
      if (result.success) {
        setAppStatus({ state: "not_installed", health: "unknown", uptime_seconds: 0, last_check: "" })
        setShowRemoveConfirm(false)
      }
    } catch (err) {
      console.error("Failed to remove:", err)
    } finally {
      setActionLoading(null)
    }
  }

  const loadLogs = async () => {
    setLogsLoading(true)
    try {
      const result = await fetchApi("/api/oci/installed/secure-gateway/logs?lines=100")
      if (result.success) {
        setLogs(result.logs || sg("logs.empty"))
      }
    } catch (err) {
      setLogs(sg("logs.failed"))
    } finally {
      setLogsLoading(false)
    }
  }

  const formatUptime = (seconds: number): string => {
    if (seconds < 60) return `${seconds}s`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
    return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`
  }

  // Format an ISO timestamp as a friendly "HH:MM" / "yesterday HH:MM" /
  // date-only string. Used in the Updates panel — the user wants to know
  // "how stale is this number" without seeing the raw 2026-05-09T10:23Z.
  const formatLastChecked = (iso?: string): string => {
    if (!iso) return sg("values.never")
    const d = new Date(iso)
    if (isNaN(d.getTime())) return t("common.unknown")
    const now = Date.now()
    const ageMs = now - d.getTime()
    const sameDay = new Date(now).toDateString() === d.toDateString()
    const yesterday = new Date(now - 86_400_000).toDateString() === d.toDateString()
    const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    if (sameDay) return time
    if (yesterday) return sg("values.yesterdayAt", { time })
    if (ageMs < 7 * 86_400_000) {
      return d.toLocaleDateString([], { weekday: "short" }) + " " + time
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" })
  }

  const renderField = (fieldName: string) => {
    const field = configSchema?.[fieldName]
    if (!field) return null
    const translatedLabel = fieldText(fieldName, "label", field.label)
    const translatedDescription = fieldText(fieldName, "description", field.description)
    const translatedPlaceholder = fieldText(fieldName, "placeholder", field.placeholder)
    const translatedWarning = fieldText(fieldName, "warning", field.warning)
    const translatedHelpText = fieldText(fieldName, "helpText", field.help_text)

    // Check depends_on
    if (field.depends_on) {
      const depValue = config[field.depends_on.field]
      if (!field.depends_on.values.includes(depValue)) {
        return null
      }
    }

    const isVisible = visiblePasswords.has(fieldName)

    switch (field.type) {
      case "password":
        return (
          <div key={fieldName} className="space-y-2">
            <Label htmlFor={fieldName} className="text-sm font-medium">
              {translatedLabel}
              {field.required && <span className="text-red-500 ml-1">*</span>}
            </Label>
            <div className="relative">
              <Input
                id={fieldName}
                type={isVisible ? "text" : "password"}
                value={config[fieldName] || ""}
                onChange={(e) => setConfig({ ...config, [fieldName]: e.target.value })}
                placeholder={translatedPlaceholder}
                className="pr-10 bg-background border-border"
              />
              <button
                type="button"
                onClick={() => {
                  const newSet = new Set(visiblePasswords)
                  if (isVisible) newSet.delete(fieldName)
                  else newSet.add(fieldName)
                  setVisiblePasswords(newSet)
                }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                {isVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <p className="text-xs text-muted-foreground">{translatedDescription}</p>
            {field.help_url && (
              <a
                href={field.help_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-cyan-500 hover:text-cyan-400 inline-flex items-center gap-1"
              >
                {translatedHelpText || sg("learnMore")} <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        )

      case "text":
        return (
          <div key={fieldName} className="space-y-2">
            <Label htmlFor={fieldName} className="text-sm font-medium">
              {translatedLabel}
              {field.required && <span className="text-red-500 ml-1">*</span>}
            </Label>
            <Input
              id={fieldName}
              type="text"
              value={config[fieldName] || ""}
              onChange={(e) => setConfig({ ...config, [fieldName]: e.target.value })}
              placeholder={translatedPlaceholder}
              className="bg-background border-border"
            />
            <p className="text-xs text-muted-foreground">{translatedDescription}</p>
          </div>
        )

      case "select":
        // Special handling for access_mode to auto-select networks
        const handleSelectChange = (value: string) => {
          const newConfig = { ...config, [fieldName]: value }
          
          // When access_mode changes to proxmox_network, auto-select the recommended network
          if (fieldName === "access_mode" && value === "proxmox_network") {
            const recommendedNetwork = networks.find((n) => n.recommended) || networks[0]
            if (recommendedNetwork) {
              newConfig.advertise_routes = [recommendedNetwork.subnet]
            }
          }
          // Clear routes when switching to host_only
          if (fieldName === "access_mode" && value === "host_only") {
            newConfig.advertise_routes = []
          }
          // Clear routes when switching to custom (user will select manually)
          if (fieldName === "access_mode" && value === "custom") {
            newConfig.advertise_routes = []
          }
          
          setConfig(newConfig)
        }
        
        return (
          <div key={fieldName} className="space-y-3">
            <Label className="text-sm font-medium">
              {translatedLabel}
              {field.required && <span className="text-red-500 ml-1">*</span>}
            </Label>
            <div className="space-y-2">
              {field.options?.map((opt) => (
                <div
                  key={opt.value}
                  onClick={() => handleSelectChange(opt.value)}
                  className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                    config[fieldName] === opt.value
                      ? "border-cyan-500 bg-cyan-500/10"
                      : "border-border hover:border-muted-foreground/50"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                      config[fieldName] === opt.value ? "border-cyan-500" : "border-muted-foreground"
                    }`}>
                      {config[fieldName] === opt.value && (
                        <div className="w-2 h-2 rounded-full bg-cyan-500" />
                      )}
                    </div>
                    <div className="flex-1">
                      <p className="font-medium text-sm">{optionText(fieldName, opt.value, "label", opt.label)}</p>
                      {opt.description && (
                        <p className="text-xs text-muted-foreground">{optionText(fieldName, opt.value, "description", opt.description)}</p>
                      )}
                      {/* Show selected network for proxmox_network */}
                      {fieldName === "access_mode" && opt.value === "proxmox_network" && config[fieldName] === "proxmox_network" && (
                        <p className="text-xs text-cyan-400 mt-1 flex items-center gap-1">
                          <Network className="h-3 w-3" />
                          {networks.find((n) => n.recommended)?.subnet || networks[0]?.subnet || sg("noNetworkDetected")}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )

      case "networks":
        return (
          <div key={fieldName} className="space-y-3">
            <Label className="text-sm font-medium">
              {translatedLabel}
            </Label>
            <p className="text-xs text-muted-foreground">{translatedDescription}</p>
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {networks.length === 0 ? (
                <p className="text-sm text-muted-foreground p-3 bg-muted/30 rounded">
                  {sg("noNetworksDetected")}
                </p>
              ) : (
                networks.map((net) => {
                  const selected = (config[fieldName] || []).includes(net.subnet)
                  return (
                    <div
                      key={net.subnet}
                      onClick={() => {
                        const current = config[fieldName] || []
                        const updated = selected
                          ? current.filter((s: string) => s !== net.subnet)
                          : [...current, net.subnet]
                        setConfig({ ...config, [fieldName]: updated })
                      }}
                      className={`p-3 rounded-lg border cursor-pointer transition-colors flex items-center gap-3 ${
                        selected
                          ? "border-cyan-500 bg-cyan-500/10"
                          : "border-border hover:border-muted-foreground/50"
                      }`}
                    >
                      <Checkbox checked={selected} className="pointer-events-none" />
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <Network className="h-4 w-4 text-muted-foreground" />
                          <span className="font-mono text-sm">{net.subnet}</span>
                          {net.recommended && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/10 text-green-500">
                              {sg("recommended")}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {net.interface} ({net.type})
                        </p>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        )

      case "boolean":
        return (
          <div key={fieldName} className="space-y-2">
            <div
              onClick={() => setConfig({ ...config, [fieldName]: !config[fieldName] })}
              className={`p-3 rounded-lg border cursor-pointer transition-colors flex items-start gap-3 ${
                config[fieldName]
                  ? "border-cyan-500 bg-cyan-500/10"
                  : "border-border hover:border-muted-foreground/50"
              }`}
            >
              <Checkbox checked={config[fieldName] || false} className="pointer-events-none mt-0.5" />
              <div>
                <p className="font-medium text-sm">{translatedLabel}</p>
                <p className="text-xs text-muted-foreground">{translatedDescription}</p>
                {field.warning && config[fieldName] && (
                  <p className="text-xs text-cyan-400 mt-2 flex items-start gap-1.5 bg-cyan-500/10 p-2 rounded">
                    <Info className="h-3 w-3 mt-0.5 flex-shrink-0" />
                    {translatedWarning}
                  </p>
                )}
              </div>
            </div>
          </div>
        )

      default:
        return null
    }
  }

  const renderWizardContent = () => {
    const step = wizardSteps[currentStep]
    if (!step) return null

    if (step.id === "intro") {
      return (
        <div className="space-y-6">
          <div className="flex justify-center">
            <div className="w-20 h-20 rounded-full bg-cyan-500/10 flex items-center justify-center">
              <ShieldCheck className="h-10 w-10 text-cyan-500" />
            </div>
          </div>
          <div className="text-center space-y-2">
            <h3 className="text-lg font-semibold">{sg("wizard.introTitle")}</h3>
            <p className="text-sm text-muted-foreground max-w-md mx-auto">
              {sg("wizard.introDescription")}
            </p>
          </div>
          <div className="bg-muted/30 rounded-lg p-4 space-y-3">
            <h4 className="text-sm font-medium">{sg("wizard.whatYouGet")}</h4>
            <ul className="space-y-2 text-sm text-muted-foreground">
              <li className="flex items-center gap-2">
                <CheckCircle className="h-4 w-4 text-green-500 flex-shrink-0" />
                {sg("wizard.benefitMonitorAnywhere")}
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="h-4 w-4 text-green-500 flex-shrink-0" />
                {sg("wizard.benefitProxmoxUi")}
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="h-4 w-4 text-green-500 flex-shrink-0" />
                {sg("wizard.benefitVmLxc")}
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="h-4 w-4 text-green-500 flex-shrink-0" />
                {sg("wizard.benefitEncryption")}
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle className="h-4 w-4 text-green-500 flex-shrink-0" />
                {sg("wizard.benefitNoPorts")}
              </li>
            </ul>
          </div>
          <div className="bg-cyan-500/10 border border-cyan-500/20 rounded-lg p-3">
            <p className="text-xs text-cyan-400 flex items-start gap-2">
              <Info className="h-4 w-4 flex-shrink-0 mt-0.5" />
              {sg("wizard.tailscaleAccountBefore")}{" "}
              <a href="https://tailscale.com" target="_blank" rel="noopener noreferrer" className="underline hover:text-cyan-300">
                tailscale.com
              </a>
            </p>
          </div>
        </div>
      )
    }

    if (step.id === "deploy") {
      return (
        <div className="space-y-6">
          <div className="text-center space-y-2">
            <h3 className="text-lg font-semibold">{sg("wizard.reviewDeploy")}</h3>
            <p className="text-sm text-muted-foreground">
              {sg("wizard.reviewDescription")}
            </p>
          </div>
          
          {/* Storage selector */}
          {storages.length > 1 && (
            <div className="space-y-3">
              <Label className="text-sm font-medium">{sg("wizard.storageLocation")}</Label>
              <p className="text-xs text-muted-foreground">{sg("wizard.storageDescription")}</p>
              <div className="space-y-2">
                {storages.filter(s => s.active && s.enabled).map((storage) => (
                  <div
                    key={storage.name}
                    onClick={() => setConfig({ ...config, storage: storage.name })}
                    className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                      config.storage === storage.name
                        ? "border-cyan-500 bg-cyan-500/10"
                        : "border-border hover:border-muted-foreground/50"
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                        config.storage === storage.name ? "border-cyan-500" : "border-muted-foreground"
                      }`}>
                        {config.storage === storage.name && (
                          <div className="w-2 h-2 rounded-full bg-cyan-500" />
                        )}
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm">{storage.name}</span>
                          <span className="text-xs text-muted-foreground">({storage.type})</span>
                          {storage.recommended && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/10 text-green-500">
                              {sg("recommended")}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {sg("wizard.gbAvailable", { amount: (storage.avail / 1024 / 1024 / 1024).toFixed(1) })}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="bg-muted/30 rounded-lg p-4 space-y-3">
            <h4 className="text-sm font-medium">{sg("wizard.configurationSummary")}</h4>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">{sg("wizard.hostname")}:</span>
                <span className="font-mono">{config.hostname || "proxmox-gateway"}</span>
              </div>
              {storages.length > 1 && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{sg("wizard.storage")}:</span>
                  <span className="font-mono">{config.storage || storages[0]?.name}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-muted-foreground">{sg("wizard.accessMode")}:</span>
                <span>{config.access_mode === "host_only" ? sg("wizard.accessModes.hostOnly") : config.access_mode === "proxmox_network" ? sg("wizard.accessModes.proxmoxNetwork") : sg("wizard.accessModes.customNetworks")}</span>
              </div>
              {config.access_mode === "host_only" && hostIp && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{sg("wizard.hostAccess")}:</span>
                  <span className="text-right font-mono text-xs">{hostIp}/32</span>
                </div>
              )}
              {(config.access_mode === "proxmox_network" || config.access_mode === "custom") && config.advertise_routes?.length > 0 && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{sg("wizard.networks")}:</span>
                  <span className="text-right font-mono text-xs">{config.advertise_routes.join(", ")}</span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-muted-foreground">{sg("wizard.exitNode")}:</span>
                <span>{config.exit_node ? sg("values.yes") : sg("values.no")}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">{sg("wizard.acceptRoutes")}:</span>
                <span>{config.accept_routes ? sg("values.yes") : sg("values.no")}</span>
              </div>
            </div>
          </div>

          {/* Approval notice */}
          {(config.access_mode && config.access_mode !== "none") && !deploying && (
            <div className="bg-cyan-500/10 border border-cyan-500/20 rounded-lg p-3 space-y-2">
              <p className="text-xs text-cyan-400 flex items-start gap-2">
                <Info className="h-4 w-4 flex-shrink-0 mt-0.5" />
                <span>
                  <strong>{sg("wizard.important")}:</strong> {sg("wizard.approvalRequired")}
                  {config.exit_node && <span> {sg("wizard.exitNodeApprovalRequired")}</span>}
                </span>
              </p>
              <p className="text-xs text-muted-foreground ml-6">
                {sg("wizard.showAfterDeploy")}
              </p>
            </div>
          )}

          {deploying && (
            <div className="bg-cyan-500/10 border border-cyan-500/20 rounded-lg p-4">
              <div className="flex items-center gap-3">
                <Loader2 className="h-5 w-5 text-cyan-500 animate-spin" />
                <span className="text-sm">{deployProgress}</span>
              </div>
            </div>
          )}

          {deployError && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3">
              <p className="text-sm text-red-500 flex items-center gap-2">
                <XCircle className="h-4 w-4" />
                {deployError}
              </p>
            </div>
          )}
        </div>
      )
    }

    // Regular step with fields
    return (
      <div className="space-y-6">
        <div className="text-center space-y-2">
          <h3 className="text-lg font-semibold">{stepText(step, "title")}</h3>
          <p className="text-sm text-muted-foreground">{stepText(step, "description")}</p>
        </div>
        <div className="space-y-4">
          {step.fields?.map((fieldName) => renderField(fieldName))}
        </div>
      </div>
    )
  }

  // Loading state
  if (loading) {
    return (
      <Card className="border-border bg-card">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-cyan-500" />
            <CardTitle className="text-base">{sg("title")}</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    )
  }

  // Initial data load failed — show the error and a retry button instead
  // of an empty wizard. Without this, a transient network error or 401
  // dropped the user into a wizard with zero steps and no signal.
  if (loadError) {
    return (
      <Card className="border-border bg-card">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-cyan-500" />
            <CardTitle className="text-base">{sg("title")}</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 py-2">
            <p className="text-sm text-red-500">{sg("errors.couldNotLoadSetupData")} {loadError}</p>
            <Button size="sm" variant="outline" onClick={() => loadInitialData()}>
              {sg("retry")}
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  // Installed state
  if (appStatus.state !== "not_installed") {
    const isRunning = appStatus.state === "running"
    const isStopped = appStatus.state === "stopped"
    const isError = appStatus.state === "error"

    return (
      <>
        <Card className="border-border bg-card">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-5 w-5 text-cyan-500" />
                <CardTitle className="text-base">{sg("title")}</CardTitle>
              </div>
              <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium ${
                isRunning ? "bg-green-500/10 text-green-500" :
                isStopped ? "bg-yellow-500/10 text-yellow-500" :
                "bg-red-500/10 text-red-500"
              }`}>
                {isRunning ? <Wifi className="h-3 w-3" /> :
                 isStopped ? <Square className="h-3 w-3" /> :
                 <XCircle className="h-3 w-3" />}
                {isRunning ? sg("status.connected") : isStopped ? sg("status.stopped") : sg("status.error")}
              </div>
            </div>
            <CardDescription>{sg("installed.description")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Status info */}
            {isRunning && appStatus.uptime_seconds > 0 && (
              <div className="text-xs text-muted-foreground">
                {sg("installed.uptime")}: {formatUptime(appStatus.uptime_seconds)}
              </div>
            )}

            {/* Actions */}
            <div className="flex flex-wrap gap-2">
              {isStopped && (
                <Button
                  size="sm"
                  onClick={() => handleAction("start")}
                  disabled={actionLoading !== null}
                  className="bg-green-600 hover:bg-green-700"
                >
                  {actionLoading === "start" ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-1" />
                  ) : (
                    <Play className="h-4 w-4 mr-1" />
                  )}
                  {sg("actions.start")}
                </Button>
              )}
              {isRunning && (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleAction("stop")}
                    disabled={actionLoading !== null}
                  >
                    {actionLoading === "stop" ? (
                      <Loader2 className="h-4 w-4 animate-spin mr-1" />
                    ) : (
                      <Square className="h-4 w-4 mr-1" />
                    )}
                    {sg("actions.stop")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleAction("restart")}
                    disabled={actionLoading !== null}
                  >
                    {actionLoading === "restart" ? (
                      <Loader2 className="h-4 w-4 animate-spin mr-1" />
                    ) : (
                      <RotateCw className="h-4 w-4 mr-1" />
                    )}
                    {sg("actions.restart")}
                  </Button>
                </>
              )}
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setShowLogs(true)
                  loadLogs()
                }}
              >
                <FileText className="h-4 w-4 mr-1" />
                {sg("actions.logs")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="text-red-500 hover:text-red-400 hover:bg-red-500/10"
                onClick={() => setShowRemoveConfirm(true)}
                disabled={actionLoading !== null}
              >
                <Trash2 className="h-4 w-4 mr-1" />
                {sg("actions.remove")}
              </Button>
            </div>

            {/* Updates panel — only when we have a probe result. The
                cached 24h backend means this stays cheap; the user
                doesn't see anything during the very first load. */}
            {updateInfo && !updateInfo.error && (
              <div className="pt-2 border-t border-border space-y-2">
                {updateInfo.available ? (
                  <>
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs text-muted-foreground">
                        {sg("updates.lastChecked")}: {formatLastChecked(updateInfo.last_checked_iso)} ·{" "}
                        <span className="text-purple-400 font-medium">
                          {sg("updates.tailscaleAvailable", { version: updateInfo.latest_version || "" })}
                        </span>
                      </div>
                    </div>
                    <Button
                      size="sm"
                      onClick={handleApplyUpdate}
                      disabled={updateApplying || actionLoading !== null}
                      className="bg-purple-600/15 hover:bg-purple-600/25 border border-purple-500/40 text-purple-300 hover:text-purple-200"
                    >
                      {updateApplying ? (
                        <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                      ) : (
                        <ArrowUpCircle className="h-4 w-4 mr-1.5" />
                      )}
                      {updateApplying
                        ? sg("updates.updating")
                        : sg("updates.updateToVersion", { version: updateInfo.latest_version || "" })}
                    </Button>
                    {updateInfo.packages && updateInfo.packages.length > 1 && (
                      <div className="text-[11px] text-muted-foreground">
                        {sg("updates.otherPackagesPending", { count: updateInfo.packages.length - 1 })}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="text-xs text-muted-foreground">
                    {sg("updates.lastChecked")}: {formatLastChecked(updateInfo.last_checked_iso)}
                    {updateInfo.current_version
                      ? ` · Tailscale v${updateInfo.current_version}`
                      : ""}
                    {" · "}
                    <span className="text-green-500/80">{sg("updates.noneAvailable")}</span>
                  </div>
                )}
                {updateError && (
                  <div className="text-xs text-red-400 flex items-start gap-1.5">
                    <XCircle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                    {updateError}
                  </div>
                )}
                {updateResultMsg && !updateError && (
                  <div className="text-xs text-green-400 flex items-start gap-1.5">
                    <CheckCircle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                    {updateResultMsg}
                  </div>
                )}
              </div>
            )}

            {/* Update Auth Key button */}
            <div className="pt-2 border-t border-border flex items-center justify-between">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowUpdateAuthKey(true)}
                disabled={actionLoading !== null}
                className="text-xs h-7 px-2"
              >
                <Key className="h-3 w-3 mr-1" />
                {sg("authKey.update")}
              </Button>
              <a
                href="https://login.tailscale.com/admin/machines"
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-cyan-500 hover:text-cyan-400 inline-flex items-center gap-1"
              >
                {sg("tailscale.openAdmin")} <ExternalLink className="h-3 w-3" />
              </a>
            </div>
          </CardContent>
        </Card>

        {/* Logs Dialog */}
        <Dialog open={showLogs} onOpenChange={setShowLogs}>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{sg("logs.title")}</DialogTitle>
              <DialogDescription>{sg("logs.description")}</DialogDescription>
            </DialogHeader>
            <div className="bg-black/50 rounded-lg p-4 max-h-96 overflow-auto">
              {logsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <pre className="text-xs font-mono text-green-400 whitespace-pre-wrap">
                  {logs || sg("logs.empty")}
                </pre>
              )}
            </div>
            <div className="flex justify-end">
              <Button variant="outline" size="sm" onClick={loadLogs}>
                <RotateCw className="h-4 w-4 mr-1" />
                {t("actions.refresh")}
              </Button>
            </div>
          </DialogContent>
        </Dialog>

        {/* Remove Confirm Dialog */}
        <Dialog open={showRemoveConfirm} onOpenChange={setShowRemoveConfirm}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{sg("remove.title")}</DialogTitle>
              <DialogDescription>
                {sg("remove.description")}
              </DialogDescription>
            </DialogHeader>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setShowRemoveConfirm(false)}>
                {t("actions.cancel")}
              </Button>
              <Button
                variant="destructive"
                onClick={handleRemove}
                disabled={actionLoading === "remove"}
              >
                {actionLoading === "remove" ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-1" />
                ) : (
                  <Trash2 className="h-4 w-4 mr-1" />
                )}
                {sg("actions.remove")}
              </Button>
            </div>
          </DialogContent>
        </Dialog>

        {/* Update Auth Key Dialog */}
        <Dialog open={showUpdateAuthKey} onOpenChange={(open) => {
          setShowUpdateAuthKey(open)
          if (!open) {
            setNewAuthKey("")
            setUpdateAuthKeyError("")
          }
        }}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Key className="h-5 w-5 text-cyan-500" />
                {sg("authKey.update")}
              </DialogTitle>
              <DialogDescription>
                {sg("authKey.description")}
              </DialogDescription>
            </DialogHeader>
            
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">{sg("authKey.newKey")}</label>
                <Input
                  type="password"
                  value={newAuthKey}
                  onChange={(e) => setNewAuthKey(e.target.value)}
                  placeholder="tskey-auth-..."
                  className="font-mono text-sm"
                />
                <p className="text-xs text-muted-foreground">
                  {sg("authKey.generateAt")}{" "}
                  <a
                    href="https://login.tailscale.com/admin/settings/keys"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-cyan-500 hover:text-cyan-400 underline"
                  >
                    {sg("authKey.adminKeys")}
                  </a>
                </p>
              </div>
              
              {updateAuthKeyError && (
                <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3">
                  <p className="text-xs text-red-500">{updateAuthKeyError}</p>
                </div>
              )}
            </div>
            
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowUpdateAuthKey(false)}>
                {t("actions.cancel")}
              </Button>
              <Button
                onClick={handleUpdateAuthKey}
                disabled={updateAuthKeyLoading || !newAuthKey.trim()}
                className="bg-cyan-600 hover:bg-cyan-700"
              >
                {updateAuthKeyLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <Key className="h-4 w-4 mr-2" />
                )}
                {sg("authKey.updateKey")}
              </Button>
            </div>
          </DialogContent>
        </Dialog>

        {/* Post-Deploy Info Dialog */}
        <Dialog open={showPostDeployInfo} onOpenChange={setShowPostDeployInfo}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <CheckCircle className="h-5 w-5 text-green-500" />
                {sg("postDeploy.title")}
              </DialogTitle>
              <DialogDescription>
                {sg("postDeploy.description")}
              </DialogDescription>
            </DialogHeader>
            
            <div className="space-y-4">
              <div className="bg-cyan-500/10 border border-cyan-500/20 rounded-lg p-4">
                <p className="text-sm font-medium text-cyan-400 flex items-center gap-2 mb-2">
                  <Info className="h-4 w-4" />
                  {sg("postDeploy.nextStep")}
                </p>
                <p className="text-sm text-muted-foreground mb-3">
                  {sg("postDeploy.approveDescription")}
                </p>
                <ul className="space-y-2 text-sm">
                  {deployedConfig.advertise_routes?.length > 0 && (
                    <li className="flex items-start gap-2">
                      <Network className="h-4 w-4 text-cyan-500 mt-0.5 flex-shrink-0" />
                      <div>
                        <span className="font-medium">{sg("postDeploy.subnetRoutes")}:</span>
                        <span className="text-muted-foreground ml-1">
                          {deployedConfig.advertise_routes.join(", ")}
                        </span>
                      </div>
                    </li>
                  )}
                  {deployedConfig.exit_node && (
                    <li className="flex items-start gap-2">
                      <Globe className="h-4 w-4 text-cyan-500 mt-0.5 flex-shrink-0" />
                      <div>
                        <span className="font-medium">{sg("postDeploy.exitNode")}:</span>
                        <span className="text-muted-foreground ml-1">
                          {sg("postDeploy.routeAllTraffic")}
                        </span>
                      </div>
                    </li>
                  )}
                </ul>
              </div>
              
              <div className="bg-muted/30 rounded-lg p-4 space-y-2">
                <p className="text-sm font-medium">{sg("postDeploy.howToApprove")}</p>
                <ol className="text-sm text-muted-foreground space-y-2 list-decimal list-inside">
                  <li>{sg("postDeploy.stepOpenAdmin")}</li>
                  <li>{sg("postDeploy.stepFindBefore")} <span className="font-mono text-cyan-400">{deployedConfig.hostname || "proxmox-gateway"}</span> {sg("postDeploy.stepFindAfter")}</li>
                  <li>{sg("postDeploy.stepOpenDetails")}</li>
                  <li>{sg("postDeploy.stepSubnetsBefore")} <strong>Subnets</strong> {sg("postDeploy.stepSubnetsMiddle")} <strong>Edit</strong> {sg("postDeploy.stepSubnetsAfter")}</li>
                  {deployedConfig.exit_node && (
                    <li>{sg("postDeploy.stepRoutingBefore")} <strong>Routing Settings</strong>, {sg("postDeploy.stepRoutingMiddle")} <strong>Exit Node</strong></li>
                  )}
                </ol>
              </div>
              
              <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-3">
                <p className="text-xs text-green-400">
                  {sg("postDeploy.accessAfterApproval")}{" "}
                  <span className="font-mono">{deployedConfig.advertise_routes?.[0]?.replace("/32", "") || hostIp}:8006</span> (Proxmox UI) {sg("postDeploy.or")}{" "}
                  <span className="font-mono">{deployedConfig.advertise_routes?.[0]?.replace("/32", "") || hostIp}:8008</span> (ProxMenux Monitor) {sg("postDeploy.fromAnyDevice")}
                </p>
              </div>
            </div>
            
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowPostDeployInfo(false)}>
                {sg("postDeploy.doLater")}
              </Button>
              <Button
                onClick={() => {
                  window.open("https://login.tailscale.com/admin/machines", "_blank")
                  setShowPostDeployInfo(false)
                }}
                className="bg-cyan-600 hover:bg-cyan-700"
              >
                {sg("tailscale.openAdmin")}
                <ExternalLink className="h-4 w-4 ml-2" />
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </>
    )
  }

  // Not installed state
  return (
    <>
      <Card className="border-border bg-card">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-cyan-500" />
            <CardTitle className="text-base">{sg("title")}</CardTitle>
          </div>
          <CardDescription>{sg("notInstalled.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            {sg("notInstalled.description")}
          </p>

          <Button
            onClick={() => setShowWizard(true)}
            className="bg-cyan-600 hover:bg-cyan-700"
          >
            <ShieldCheck className="h-4 w-4 mr-2" />
            {sg("notInstalled.deploy")}
          </Button>
        </CardContent>
      </Card>

      {/* Wizard Dialog */}
      <Dialog open={showWizard} onOpenChange={(open) => {
        if (!deploying) {
          setShowWizard(open)
          if (!open) {
            setCurrentStep(0)
            setDeployError("")
          }
        }
      }}>
        <DialogContent className="max-w-lg max-h-[90vh] sm:max-h-[85vh] flex flex-col p-0 gap-0">
          {/* Fixed Header */}
          <div className="shrink-0 px-6 pt-6 pb-4 border-b border-border">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <ShieldCheck className="h-5 w-5 text-cyan-500" />
                {sg("wizard.setupTitle")}
              </DialogTitle>
            </DialogHeader>

            {/* Progress indicator - filter out "options" step if using Proxmox Only */}
            <div className="flex items-center gap-1 mt-4">
              {wizardSteps
                .filter((step) => !(config.access_mode === "host_only" && step.id === "options"))
                .map((step, idx) => {
                  // Recalculate the actual step index accounting for skipped steps
                  const actualIdx = wizardSteps.findIndex((s) => s.id === step.id)
                  const adjustedCurrentStep = config.access_mode === "host_only" 
                    ? (currentStep > wizardSteps.findIndex((s) => s.id === "options") ? currentStep - 1 : currentStep)
                    : currentStep
                  return (
                    <div
                      key={step.id}
                      className={`flex-1 h-1 rounded-full transition-colors ${
                        idx < adjustedCurrentStep ? "bg-cyan-500" :
                        idx === adjustedCurrentStep ? "bg-cyan-500" :
                        "bg-muted"
                      }`}
                    />
                  )
                })}
            </div>
          </div>

          {/* Scrollable Content */}
          <div className="flex-1 overflow-y-auto px-6 py-4 min-h-0">
            {renderWizardContent()}
          </div>

          {/* Fixed Footer with Navigation */}
          <div className="shrink-0 flex justify-between px-6 py-4 border-t border-border bg-background">
            <Button
              variant="outline"
              onClick={() => {
                // Skip "options" step when going back if using "Proxmox Only"
                let prevStep = currentStep - 1
                if (config.access_mode === "host_only" && wizardSteps[prevStep]?.id === "options") {
                  prevStep = prevStep - 1
                }
                setCurrentStep(Math.max(0, prevStep))
              }}
              disabled={currentStep === 0 || deploying}
            >
              {sg("actions.back")}
            </Button>
            
            {currentStep < wizardSteps.length - 1 ? (
              <Button
                onClick={() => {
                  // Skip "options" step when using "Proxmox Only"
                  let nextStep = currentStep + 1
                  if (config.access_mode === "host_only" && wizardSteps[nextStep]?.id === "options") {
                    nextStep = nextStep + 1
                  }
                  setCurrentStep(nextStep)
                }}
                className="bg-cyan-600 hover:bg-cyan-700"
              >
                {sg("actions.continue")}
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            ) : (
              <Button
                onClick={handleDeploy}
                disabled={deploying}
                className="bg-cyan-600 hover:bg-cyan-700"
              >
                {deploying ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                    {sg("actions.deploying")}
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4 mr-2" />
                    {sg("actions.deployGateway")}
                  </>
                )}
              </Button>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
