"use client"

import type React from "react"

import { useState, useEffect, useCallback } from "react"
import { getAuthToken } from "@/lib/api-config"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Info,
  Activity,
  Cpu,
  MemoryStick,
  HardDrive,
  Disc,
  Network,
  Box,
  Settings,
  FileText,
  RefreshCw,
  Shield,
  Download,
  X,
  Clock,
  BellOff,
  ChevronRight,
  Settings2,
  HelpCircle,
} from "lucide-react"
import { ScriptTerminalModal } from "./script-terminal-modal"
import { useT } from "@/lib/i18n/provider"

interface CategoryCheck {
  status: string
  reason?: string
  details?: any
  checks?: Record<string, { status: string; detail: string; [key: string]: any }>
  dismissable?: boolean
  [key: string]: any
}

  interface DismissedError {
  error_key: string
  category: string
  severity: string
  reason: string
  dismissed: boolean
  permanent?: boolean
  suppression_remaining_hours: number
  suppression_hours?: number
  resolved_at: string
  }

  interface CustomSuppression {
  key: string
  label: string
  category: string
  icon: string
  hours: number
  }

interface HealthDetails {
  overall: string
  summary: string
  details: {
    cpu: CategoryCheck
    memory: CategoryCheck
    storage: CategoryCheck
    disks: CategoryCheck
    network: CategoryCheck
    vms: CategoryCheck
    services: CategoryCheck
    logs: CategoryCheck
    updates: CategoryCheck
    security: CategoryCheck
  }
  timestamp: string
}

 interface FullHealthData {
  health: HealthDetails
  active_errors: any[]
  dismissed: DismissedError[]
  custom_suppressions: CustomSuppression[]
  timestamp: string
  }

interface HealthStatusModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  getApiUrl: (path: string) => string
}

const CATEGORIES = [
  { key: "cpu", category: "temperature", Icon: Cpu },
  { key: "memory", category: "memory", Icon: MemoryStick },
  { key: "storage", category: "storage", Icon: HardDrive },
  { key: "disks", category: "disks", Icon: Disc },
  { key: "network", category: "network", Icon: Network },
  { key: "vms", category: "vms", Icon: Box },
  { key: "services", category: "pve_services", Icon: Settings },
  { key: "logs", category: "logs", Icon: FileText },
  { key: "updates", category: "updates", Icon: RefreshCw },
  { key: "security", category: "security", Icon: Shield },
]

export function HealthStatusModal({ open, onOpenChange, getApiUrl }: HealthStatusModalProps) {
  const t = useT()
  const [loading, setLoading] = useState(true)
  const [healthData, setHealthData] = useState<HealthDetails | null>(null)
  const [dismissedItems, setDismissedItems] = useState<DismissedError[]>([])
  const [customSuppressions, setCustomSuppressions] = useState<CustomSuppression[]>([])
  const [error, setError] = useState<string | null>(null)
  const [dismissingKey, setDismissingKey] = useState<string | null>(null)
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())
  const [showUpdateTerminal, setShowUpdateTerminal] = useState(false)

  const fetchHealthDetails = useCallback(async (force = false) => {
    setLoading(true)
    setError(null)

    try {
      let newOverallStatus = "OK"

      // Use the new combined endpoint for fewer round-trips
      const token = getAuthToken()
      const authHeaders: Record<string, string> = {}
      if (token) {
        authHeaders["Authorization"] = `Bearer ${token}`
      }

      const response = await fetch(getApiUrl(force ? "/api/health/full?refresh=1" : "/api/health/full"), { headers: authHeaders })
      let infoCount = 0
      
      if (!response.ok) {
        // Fallback to legacy endpoint
        const legacyResponse = await fetch(getApiUrl("/api/health/details"), { headers: authHeaders })
        if (!legacyResponse.ok) throw new Error(t("healthStatus.errors.fetchFailed"))
        const data = await legacyResponse.json()
        setHealthData(data)
        setDismissedItems([])
        setCustomSuppressions([])
        newOverallStatus = data?.overall || "OK"
        
        // Count INFO categories from legacy data
        if (data?.details) {
          CATEGORIES.forEach(({ key }) => {
            const cat = data.details[key as keyof typeof data.details]
            if (cat && cat.status?.toUpperCase() === "INFO") {
              infoCount++
            }
          })
        }
      } else {
        const fullData: FullHealthData = await response.json()
        setHealthData(fullData.health)
        setDismissedItems(fullData.dismissed || [])
        setCustomSuppressions(fullData.custom_suppressions || [])
        newOverallStatus = fullData.health?.overall || "OK"
        
        // Get categories that have dismissed items (these become INFO)
        const customCats = new Set((fullData.custom_suppressions || []).map((cs: { category: string }) => cs.category))
        const filteredDismissed = (fullData.dismissed || []).filter((item: { category: string }) => !customCats.has(item.category))
        const categoriesWithDismissed = new Set<string>()
        filteredDismissed.forEach((item: { category: string }) => {
          const catMeta = CATEGORIES.find(c => c.category === item.category || c.key === item.category)
          if (catMeta) {
            categoriesWithDismissed.add(catMeta.key)
          }
        })
        
        // Count effective INFO categories (original INFO + OK categories with dismissed)
        if (fullData.health?.details) {
          CATEGORIES.forEach(({ key }) => {
            const cat = fullData.health.details[key as keyof typeof fullData.health.details]
            if (cat) {
              const originalStatus = cat.status?.toUpperCase()
              // Count as INFO if: originally INFO OR (originally OK and has dismissed items)
              if (originalStatus === "INFO" || (originalStatus === "OK" && categoriesWithDismissed.has(key))) {
                infoCount++
              }
            }
          })
        }
      }
      
      const totalInfoCount = infoCount
      
      // Emit event with the FRESH data from the response, not the stale state
      const event = new CustomEvent("healthStatusUpdated", {
        detail: { status: newOverallStatus, infoCount: totalInfoCount },
      })
      window.dispatchEvent(event)
    } catch (err) {
      setError(err instanceof Error ? err.message : t("healthStatus.errors.unknown"))
    } finally {
      setLoading(false)
    }
  }, [getApiUrl, t])

  // Tick counter to force re-render every 30s so "X minutes ago" stays current
  const [, setTick] = useState(0)
  
  useEffect(() => {
    if (!open) return
    const tickInterval = setInterval(() => setTick(t => t + 1), 30000)
    return () => clearInterval(tickInterval)
  }, [open])

  useEffect(() => {
    if (open) {
      fetchHealthDetails()
      // Auto-refresh every 5 minutes while modal is open
      const refreshInterval = setInterval(() => fetchHealthDetails(), 300000)
      return () => clearInterval(refreshInterval)
    }
  }, [open, fetchHealthDetails])

  // Auto-expand non-OK categories when data loads
  useEffect(() => {
    if (healthData?.details) {
      const nonOkCategories = new Set<string>()
      CATEGORIES.forEach(({ key }) => {
        const cat = healthData.details[key as keyof typeof healthData.details]
        if (cat && cat.status?.toUpperCase() !== "OK") {
          // Updates section: only auto-expand on WARNING+, not INFO
          if (key === "updates" && cat.status?.toUpperCase() === "INFO") {
            return
          }
          nonOkCategories.add(key)
        }
      })
      setExpandedCategories(nonOkCategories)
    }
  }, [healthData])

  const toggleCategory = (key: string) => {
    setExpandedCategories(prev => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  const getStatusIcon = (status: string, size: "sm" | "md" = "md") => {
    const statusUpper = status?.toUpperCase()
    const cls = size === "sm" ? "h-4 w-4" : "h-5 w-5"
    switch (statusUpper) {
      case "OK":
        return <CheckCircle2 className={`${cls} text-green-500`} />
      case "INFO":
        return <Info className={`${cls} text-blue-500`} />
      case "WARNING":
        return <AlertTriangle className={`${cls} text-yellow-500`} />
      case "CRITICAL":
        return <XCircle className={`${cls} text-red-500`} />
      case "UNKNOWN":
        return <HelpCircle className={`${cls} text-amber-400`} />
      default:
        return <Activity className={`${cls} text-muted-foreground`} />
    }
  }

  const getStatusBadge = (status: string) => {
    const statusUpper = status?.toUpperCase()
    switch (statusUpper) {
      case "OK":
        return <Badge className="bg-green-500 text-white hover:bg-green-500">{t("healthStatus.status.ok")}</Badge>
      case "INFO":
        return <Badge className="bg-blue-500 text-white hover:bg-blue-500">{t("healthStatus.status.info")}</Badge>
      case "WARNING":
        return <Badge className="bg-yellow-500 text-white hover:bg-yellow-500">{t("healthStatus.status.warning")}</Badge>
      case "CRITICAL":
        return <Badge className="bg-red-500 text-white hover:bg-red-500">{t("healthStatus.status.critical")}</Badge>
      case "UNKNOWN":
        return <Badge className="bg-amber-500 text-white hover:bg-amber-500">{t("healthStatus.status.unknown")}</Badge>
      default:
        return <Badge>{t("healthStatus.status.unknown")}</Badge>
    }
  }

  const formatStatus = (status: string) => {
    const key = status?.toLowerCase()
    return ["ok", "info", "warning", "critical", "unknown"].includes(key)
      ? t(`healthStatus.status.${key}`)
      : status
  }

  const translateHealthText = (value?: string): string => {
    if (!value) return ""
    const exact: Record<string, string> = {
      "All systems operational": t("healthStatus.details.allOperational"),
      "Normal": t("healthStatus.details.normal"),
      "No I/O errors in dmesg": t("healthStatus.details.noIoErrors"),
      "Mounted read-write, space OK": t("healthStatus.details.rootFilesystemOk"),
      "No SMART warnings in journal": t("healthStatus.details.noSmartWarnings"),
      "No critical errors": t("healthStatus.details.noCriticalErrors"),
      "No cascading errors": t("healthStatus.details.noCascadingErrors"),
      "No error spikes": t("healthStatus.details.noErrorSpikes"),
      "No persistent patterns": t("healthStatus.details.noPersistentPatterns"),
      "Certificate valid": t("healthStatus.details.certificateValid"),
      "Cluster detected (corosync.conf present)": t("healthStatus.details.clusterDetected"),
      "Active": t("healthStatus.details.active"),
      "UP": t("healthStatus.details.up"),
      "Kernel/PVE up to date": t("healthStatus.details.kernelUpToDate"),
      "Proxmox VE is up to date": t("healthStatus.details.proxmoxUpToDate"),
      "No security updates pending": t("healthStatus.details.noSecurityUpdates"),
      "No container startup errors": t("healthStatus.details.noContainerErrors"),
      "No OOM events detected": t("healthStatus.details.noOomEvents"),
      "No QMP timeouts detected": t("healthStatus.details.noQmpTimeouts"),
      "No VM startup failures": t("healthStatus.details.noVmFailures"),
      "Dismissed by user": t("healthStatus.details.dismissedByUser"),
    }
    if (exact[value]) return exact[value]

    let match = value.match(/^Latency ([\d.]+)ms to gateway$/)
    if (match) return t("healthStatus.details.gatewayLatency", { latency: match[1] })
    match = value.match(/^(\d+) failed login attempts in 24h$/)
    if (match) return t("healthStatus.details.failedLogins", { count: match[1] })
    match = value.match(/^(\d+) IP\(s\) currently banned by Fail2Ban \(jails: (.+)\)$/)
    if (match) return t("healthStatus.details.fail2banBannedIps", { count: match[1], jails: match[2] })
    match = value.match(/^Uptime (\d+) days?$/)
    if (match) return t("healthStatus.details.uptimeDays", { count: match[1] })
    match = value.match(/^(\d+) package\(s\) pending$/)
    if (match) return t("healthStatus.details.pendingPackages", { count: match[1] })
    match = value.match(/^Last updated (\d+) day\(s\) ago$/)
    if (match) return t("healthStatus.details.updatedDaysAgo", { count: match[1] })
    match = value.match(/^(.+) storage available$/)
    if (match) return t("healthStatus.details.storageAvailable", { type: match[1] })
    match = value.match(/^(.+) mount reachable$/)
    if (match) return t("healthStatus.details.mountReachable", { type: match[1] })
    match = value.match(/^rootfs ([\d.]+)% used \((.+)\)$/)
    if (match) return t("healthStatus.details.rootfsUsed", { percent: match[1], size: match[2] })
    match = value.match(/^(\d+) running CT\(s\) within safe rootfs usage$/)
    if (match) return t("healthStatus.details.runningCtsSafe", { count: match[1] })
    match = value.match(/^(\d+) PVE block storage\(s\) within safe usage$/)
    if (match) return t("healthStatus.details.pveStorageSafe", { count: match[1] })
    match = value.match(/^(\d+) remote mount\(s\) healthy$/)
    if (match) return t("healthStatus.details.remoteMountsHealthy", { count: match[1] })
    return value
  }

  const formatDuration = (hours: number) => {
    if (hours === -1) return t("healthStatus.permanent")
    if (hours >= 8760) return t("healthStatus.duration.years", { count: Math.floor(hours / 8760) })
    if (hours >= 720) return t("healthStatus.duration.months", { count: Math.floor(hours / 720) })
    if (hours >= 168) return t("healthStatus.duration.weeks", { count: Math.floor(hours / 168) })
    if (hours >= 24) return t("healthStatus.duration.days", { count: Math.floor(hours / 24) })
    return t("healthStatus.duration.hours", { count: Math.round(hours) })
  }

  // Get categories that have dismissed items (to show as INFO)
  const getCategoriesWithDismissed = () => {
    const customCats = new Set(customSuppressions.map(cs => cs.category))
    const filteredDismissed = dismissedItems.filter(item => !customCats.has(item.category))
    const categoriesWithDismissed = new Set<string>()
    filteredDismissed.forEach(item => {
      // Map dismissed category to our CATEGORIES keys
      const catMeta = CATEGORIES.find(c => c.category === item.category || c.key === item.category)
      if (catMeta) {
        categoriesWithDismissed.add(catMeta.key)
      }
    })
    return categoriesWithDismissed
  }

  const categoriesWithDismissed = getCategoriesWithDismissed()

  // Get effective status for a category (considers dismissed items)
  const getEffectiveStatus = (key: string, originalStatus: string) => {
    // If category has dismissed items and original status is OK, show as INFO
    if (categoriesWithDismissed.has(key) && originalStatus?.toUpperCase() === "OK") {
      return "INFO"
    }
    return originalStatus?.toUpperCase() || "UNKNOWN"
  }

  const getHealthStats = () => {
    if (!healthData?.details) return { total: 0, healthy: 0, info: 0, warnings: 0, critical: 0, unknown: 0 }

    let healthy = 0
    let info = 0
    let warnings = 0
    let critical = 0
    let unknown = 0

    CATEGORIES.forEach(({ key }) => {
      const categoryData = healthData.details[key as keyof typeof healthData.details]
      if (categoryData) {
        const effectiveStatus = getEffectiveStatus(key, categoryData.status)
        if (effectiveStatus === "OK") healthy++
        else if (effectiveStatus === "INFO") info++
        else if (effectiveStatus === "WARNING") warnings++
        else if (effectiveStatus === "CRITICAL") critical++
        else if (effectiveStatus === "UNKNOWN") unknown++
      }
    })

    return { total: CATEGORIES.length, healthy, info, warnings, critical, unknown }
  }

  const stats = getHealthStats()

  const handleCategoryClick = (categoryKey: string, status: string) => {
    if (status === "OK" || status === "INFO") return

    onOpenChange(false)

    const categoryToTab: Record<string, string> = {
      storage: "storage",
      disks: "storage",
      network: "network",
      vms: "vms",
      logs: "logs",
      hardware: "hardware",
      services: "hardware",
    }

    const targetTab = categoryToTab[categoryKey]
    if (targetTab) {
      const event = new CustomEvent("changeTab", { detail: { tab: targetTab } })
      window.dispatchEvent(event)
    }
  }

  // `suppressionHours` overrides the category default for this dismiss:
  //   - undefined → backend uses the category's configured suppression
  //   - 24, 168 (7 days)  → silence for that many hours
  //   - -1               → permanent dismiss; only revertible from
  //                        Settings → Active Suppressions
  const handleAcknowledge = async (
    errorKey: string,
    suppressionHours?: number,
  ) => {
    setDismissingKey(errorKey)

    try {
      const url = getApiUrl("/api/health/acknowledge")
      const token = getAuthToken()
      const headers: Record<string, string> = { "Content-Type": "application/json" }
      if (token) {
        headers["Authorization"] = `Bearer ${token}`
      }

      const body: Record<string, unknown> = { error_key: errorKey }
      if (suppressionHours !== undefined) {
        body.suppression_hours = suppressionHours
      }

      const response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      })

      const responseData = await response.json().catch(() => ({}))

      if (!response.ok) {
        throw new Error(responseData.error || `Failed to dismiss error (${response.status})`)
      }

      // Optimistically update local state to avoid slow re-fetch
      // Add the dismissed item to the local list immediately
      if (responseData.result || responseData.success) {
        const dismissedItem = {
          error_key: errorKey,
          category: responseData.result?.category || responseData.category || '',
          severity: responseData.result?.original_severity || 'WARNING',
          reason: 'Dismissed by user',
          dismissed: true,
          // Surface the chosen duration so the row shows the right badge
          // (countdown vs. "Permanent") without waiting for the refetch.
          permanent: suppressionHours === -1,
          suppression_remaining_hours: suppressionHours === -1 ? -1 : undefined,
          suppression_hours: suppressionHours,
          acknowledged_at: new Date().toISOString(),
        }
        setDismissedItems(prev => [...prev, dismissedItem])
      }

      // Fetch fresh data in background (non-blocking)
      fetchHealthDetails().catch(() => {})

      // Notify other mounted views (e.g. Settings → Active Suppressions
      // panel) that the suppression set has changed so they can refresh.
      try {
        window.dispatchEvent(new CustomEvent("health-suppression-changed"))
      } catch {}
    } catch (err) {
      console.error("Error dismissing:", err)
    } finally {
      setDismissingKey(null)
    }
  }

  const getTimeSinceCheck = () => {
    if (!healthData?.timestamp) return null
    const checkTime = new Date(healthData.timestamp)
    const now = new Date()
    const diffMs = now.getTime() - checkTime.getTime()
    const diffMin = Math.floor(diffMs / 60000)
    if (diffMin < 1) return t("healthStatus.time.justNow")
    if (diffMin === 1) return t("healthStatus.time.oneMinuteAgo")
    if (diffMin < 60) return t("healthStatus.time.minutesAgo", { count: diffMin })
    const diffHours = Math.floor(diffMin / 60)
    return t("healthStatus.time.hoursMinutesAgo", { hours: diffHours, minutes: diffMin % 60 })
  }

  const getCategoryRowStyle = (status: string) => {
    const s = status?.toUpperCase()
    if (s === "CRITICAL") return "bg-red-500/5 border-red-500/20 hover:bg-red-500/10 cursor-pointer"
    if (s === "WARNING") return "bg-yellow-500/5 border-yellow-500/20 hover:bg-yellow-500/10 cursor-pointer"
    if (s === "UNKNOWN") return "bg-amber-500/5 border-amber-500/20 hover:bg-amber-500/10 cursor-pointer"
    if (s === "INFO") return "bg-blue-500/5 border-blue-500/20 hover:bg-blue-500/10"
    return "bg-card border-border hover:bg-muted/30"
  }
  
  const getOutlineBadgeStyle = (status: string) => {
    const s = status?.toUpperCase()
    if (s === "OK") return "border-green-500 text-green-500 bg-transparent"
    if (s === "INFO") return "border-blue-500 text-blue-500 bg-blue-500/5"
    if (s === "WARNING") return "border-yellow-500 text-yellow-500 bg-yellow-500/5"
    if (s === "CRITICAL") return "border-red-500 text-red-500 bg-red-500/5"
    if (s === "UNKNOWN") return "border-amber-400 text-amber-400 bg-amber-500/5"
    return ""
  }

  const formatCheckLabel = (key: string): string => {
    const knownKeys = new Set([
      "cpu_usage", "cpu_temperature", "ram_usage", "swap_usage", "root_filesystem",
      "smart_health", "io_errors", "zfs_pools", "lvm_volumes", "lvm_check", "connectivity",
      "qmp_communication", "container_startup", "vm_startup", "oom_killer", "cluster_mode",
      "log_error_cascade", "log_error_spike", "log_persistent_errors", "log_critical_errors",
      "pve_version", "security_updates", "system_age", "pending_updates", "kernel_pve", "uptime",
      "certificates", "login_attempts", "fail2ban", "proxmox_storages",
    ])
    if (knownKeys.has(key)) return t(`healthStatus.checks.${key}`)
    // Convert snake_case or camelCase to Title Case
    return key
      .replace(/_/g, " ")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/\b\w/g, (c) => c.toUpperCase())
  }

  const renderChecks = (
    checks: Record<string, { status: string; detail: string; dismissable?: boolean; [key: string]: any }>,
    categoryKey: string
  ) => {
    if (!checks || Object.keys(checks).length === 0) return null

    return (
      <div className="mt-2 space-y-0.5">
        {Object.entries(checks)
          .filter(([, checkData]) => checkData.installed !== false)
          .map(([checkKey, checkData]) => {
          const isDismissable = checkData.dismissable === true
          const checkStatus = checkData.status?.toUpperCase() || "OK"

          return (
            <div
              key={checkKey}
              className="flex items-center justify-between gap-1.5 sm:gap-2 text-[10px] sm:text-xs py-1.5 px-2 sm:px-3 rounded-md hover:bg-muted/40 transition-colors"
            >
              <div className="flex items-start gap-1.5 sm:gap-2 min-w-0 flex-1">
                <span className="mt-0.5 shrink-0">{getStatusIcon(checkData.dismissed ? "INFO" : checkData.status, "sm")}</span>
                <span className="font-medium shrink-0">{formatCheckLabel(checkKey)}</span>
                <span className="text-muted-foreground break-words whitespace-pre-wrap min-w-0">{translateHealthText(checkData.detail)}</span>
                {checkData.dismissed && (
                  checkData.permanent ? (
                    <Badge variant="outline" className="text-[9px] px-1 py-0 h-4 shrink-0 text-amber-400 border-amber-400/40">
                      {t("healthStatus.permanent")}
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-[9px] px-1 py-0 h-4 shrink-0 text-blue-400 border-blue-400/30">
                      {t("healthStatus.dismissed")}
                    </Badge>
                  )
                )}
              </div>
              <div className="flex items-center gap-1 sm:gap-1.5 shrink-0">
                {(checkStatus === "WARNING" || checkStatus === "CRITICAL" || checkStatus === "UNKNOWN") && isDismissable && !checkData.dismissed && (
                  <DismissDropdown
                    onSelect={(hours) =>
                      handleAcknowledge(checkData.error_key || checkKey, hours)
                    }
                    busy={dismissingKey === (checkData.error_key || checkKey)}
                    t={t}
                  />
                )}
              </div>
            </div>
          )
        })}
      </div>
    )
  }



  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl w-[calc(100vw-2rem)] sm:w-[95vw] max-h-[85vh] overflow-y-auto overflow-x-hidden p-4 sm:p-6">
        <DialogHeader>
          <div className="flex items-center justify-between gap-3">
            <DialogTitle className="flex items-center gap-2 flex-1 min-w-0">
              <Activity className="h-5 w-5 sm:h-6 sm:w-6 shrink-0" />
              <span className="truncate text-base sm:text-lg">{t("healthStatus.title")}</span>
              {healthData && <div className="shrink-0">{getStatusBadge(healthData.overall)}</div>}
            </DialogTitle>
          </div>
          <DialogDescription className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs sm:text-sm">
            <span>{t("healthStatus.description")}</span>
            {getTimeSinceCheck() && (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <Clock className="h-3 w-3" />
                {getTimeSinceCheck()}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>

        {loading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:bg-red-950 dark:border-red-800 dark:text-red-200">
            <p className="font-medium">{t("healthStatus.errors.loading")}</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {healthData && !loading && (
          <div className="space-y-4">
            {/* Overall Stats Summary */}
            <div className={`grid gap-2 sm:gap-3 p-3 sm:p-4 rounded-lg bg-muted/30 border ${stats.info > 0 ? "grid-cols-5" : "grid-cols-4"}`}>
              <div className="text-center">
                <div className="text-lg sm:text-2xl font-bold">{stats.total}</div>
                <div className="text-[10px] sm:text-xs text-muted-foreground">{t("healthStatus.stats.total")}</div>
              </div>
              <div className="text-center">
                <div className="text-lg sm:text-2xl font-bold text-green-500">{stats.healthy}</div>
                <div className="text-[10px] sm:text-xs text-muted-foreground">{t("healthStatus.stats.healthy")}</div>
              </div>
              {stats.info > 0 && (
                <div className="text-center">
                  <div className="text-lg sm:text-2xl font-bold text-blue-500">{stats.info}</div>
                  <div className="text-[10px] sm:text-xs text-muted-foreground">{t("healthStatus.stats.info")}</div>
                </div>
              )}
              <div className="text-center">
                <div className="text-lg sm:text-2xl font-bold text-yellow-500">{stats.warnings}</div>
                <div className="text-[10px] sm:text-xs text-muted-foreground">{t("healthStatus.stats.warning")}</div>
              </div>
              <div className="text-center">
                <div className="text-lg sm:text-2xl font-bold text-red-500">{stats.critical}</div>
                <div className="text-[10px] sm:text-xs text-muted-foreground">{t("healthStatus.stats.critical")}</div>
              </div>
              {stats.unknown > 0 && (
              <div className="text-center">
                <div className="text-lg sm:text-2xl font-bold text-amber-400">{stats.unknown}</div>
                <div className="text-[10px] sm:text-xs text-muted-foreground">{t("healthStatus.stats.unknown")}</div>
              </div>
              )}
            </div>

            {healthData.summary && healthData.summary !== "All systems operational" && (
              <div className="text-xs sm:text-sm p-3 rounded-lg bg-muted/20 border overflow-hidden max-w-full">
                <p className="font-medium text-foreground break-words whitespace-pre-wrap">{translateHealthText(healthData.summary)}</p>
              </div>
            )}

            {/* Category List */}
            <div className="space-y-2">
              {CATEGORIES.map(({ key, Icon }) => {
                const categoryData = healthData.details[key as keyof typeof healthData.details]
                const originalStatus = categoryData?.status || "UNKNOWN"
                const status = getEffectiveStatus(key, originalStatus)
                const reason = translateHealthText(categoryData?.reason)
                const checks = categoryData?.checks
                const isExpanded = expandedCategories.has(key)
                const hasChecks = checks && Object.keys(checks).length > 0

                return (
                  <div
                    key={key}
                    className={`rounded-lg border transition-colors overflow-hidden ${getCategoryRowStyle(status)}`}
                  >
                    {/* Clickable header row */}
                    <div
                      className="flex items-center gap-2 sm:gap-3 p-2 sm:p-3 cursor-pointer select-none overflow-hidden"
                      onClick={() => toggleCategory(key)}
                    >
                      <div className="shrink-0 flex items-center gap-1.5 sm:gap-2">
                        <Icon className="h-4 w-4 text-blue-500 hidden sm:block" />
                        {getStatusIcon(status)}
                      </div>
                      <div className="flex-1 min-w-0 overflow-hidden">
                        <div className="flex items-center gap-1.5 sm:gap-2">
                          <p className="font-medium text-xs sm:text-sm truncate">{t(`healthStatus.categories.${key}`)}</p>
                          {hasChecks && (
                            <span className="text-[10px] text-muted-foreground shrink-0">
                              ({Object.values(checks).filter(c => c.installed !== false).length})
                            </span>
                          )}
                        </div>
                        {reason && !isExpanded && (
                          <p className="text-[10px] sm:text-xs text-muted-foreground mt-0.5 line-clamp-2 break-words">{reason}</p>
                        )}
                      </div>
                      <div className="flex items-center gap-1 sm:gap-2 shrink-0">
                        <Badge variant="outline" className={`text-[10px] sm:text-xs px-1.5 sm:px-2.5 ${getOutlineBadgeStyle(status)}`}>
                          {formatStatus(status)}
                        </Badge>
                        <ChevronRight
                          className={`h-3.5 w-3.5 sm:h-4 sm:w-4 text-muted-foreground transition-transform duration-200 ${
                            isExpanded ? "rotate-90" : ""
                          }`}
                        />
                      </div>
                    </div>

                    {/* Expandable checks section */}
                    {isExpanded && (
                      <div className="border-t border-border/50 bg-muted/5 px-1.5 sm:px-2 py-1.5 overflow-hidden">
                        {reason && (
                          <div className="flex items-center justify-between gap-2 px-3 py-1.5 mb-1">
                            <p className="text-xs text-muted-foreground break-words whitespace-pre-wrap flex-1">{reason}</p>
                            {/* Show dismiss button for UNKNOWN status at category level when dismissable */}
                            {status === "UNKNOWN" && categoryData?.dismissable && !hasChecks && (
                              <DismissDropdown
                                onSelect={(hours) =>
                                  handleAcknowledge(`category_${key}_unknown`, hours)
                                }
                                busy={dismissingKey === `category_${key}_unknown`}
                                t={t}
                              />
                            )}
                          </div>
                        )}
                        {hasChecks ? (
                          renderChecks(checks, key)
                        ) : (
                          <div className="flex items-center gap-2 text-xs text-muted-foreground px-3 py-2">
                            <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                            {t("healthStatus.noIssues")}
                          </div>
                        )}
                        {/* Only offer "Update Now" when the category is not
                            already OK — hiding it when there's nothing
                            pending prevents the operator from spawning a
                            terminal that would only report "System is
                            already up to date". */}
                        {key === "updates" && status?.toUpperCase() !== "OK" && (
                          <div className="flex justify-end px-3 py-2 pt-1">
                            <Button
                              size="sm"
                              onClick={() => setShowUpdateTerminal(true)}
                              className="bg-purple-600/15 hover:bg-purple-600/25 border border-purple-500/40 text-purple-300 hover:text-purple-200"
                            >
                              <Download className="h-4 w-4 mr-1.5" />
                              {t("healthStatus.updateNow")}
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Dismissed Items Section -- hide items whose category has custom suppression */}
            {(() => {
              const customCats = new Set(customSuppressions.map(cs => cs.category))
              const filteredDismissed = dismissedItems.filter(item => !customCats.has(item.category))
              if (filteredDismissed.length === 0) return null
              return (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs sm:text-sm font-medium text-muted-foreground pt-2">
                  <BellOff className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                  {t("healthStatus.dismissedItems", { count: filteredDismissed.length })}
                </div>
                {filteredDismissed.map((item) => {
                  const catMeta = CATEGORIES.find(c => c.category === item.category || c.key === item.category)
                  const CatIcon = catMeta?.Icon || BellOff
                  const catLabel = catMeta ? t(`healthStatus.categories.${catMeta.key}`) : item.category
                  const isPermanent = item.permanent || item.suppression_remaining_hours === -1
                  
                  return (
                    <div
                      key={item.error_key}
                      className="flex items-start gap-2 sm:gap-3 p-2 sm:p-3 rounded-lg border bg-muted/10 border-muted opacity-75"
                    >
                      <div className="mt-0.5 shrink-0 flex items-center gap-1.5 sm:gap-2">
                        <CatIcon className="h-3.5 w-3.5 sm:h-4 sm:w-4 text-muted-foreground" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-2 mb-1">
                          <div className="min-w-0 flex-1 overflow-hidden">
                            <p className="font-medium text-xs sm:text-sm text-muted-foreground truncate">{catLabel}</p>
                            <p className="text-[10px] sm:text-xs text-muted-foreground/70 break-words line-clamp-2">{translateHealthText(item.reason)}</p>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            {isPermanent ? (
                              <Badge variant="outline" className="text-[9px] sm:text-xs border-amber-500/50 text-amber-500/70 bg-transparent whitespace-nowrap">
                                {t("healthStatus.permanent")}
                              </Badge>
                            ) : (
                              <Badge variant="outline" className="text-[9px] sm:text-xs border-blue-500/50 text-blue-500/70 bg-transparent whitespace-nowrap">
                                {t("healthStatus.dismissed")}
                              </Badge>
                            )}
                            <Badge variant="outline" className={`text-[9px] sm:text-xs whitespace-nowrap ${getOutlineBadgeStyle(item.severity)}`}>
                              {t("healthStatus.wasStatus", { status: formatStatus(item.severity) })}
                            </Badge>
                          </div>
                        </div>
                        <p className="text-[10px] sm:text-xs text-muted-foreground flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {isPermanent
                            ? t("healthStatus.permanentlySuppressed")
                            : t("healthStatus.suppressedForMore", { duration: formatDuration(item.suppression_remaining_hours) })
                          }
                        </p>
                      </div>
                    </div>
                  )
                })}
              </div>
              )
            })()}

            {/* Custom Suppression Settings Summary */}
            {customSuppressions.length > 0 && (
              <div className="space-y-2 pt-2">
                <div className="flex items-center gap-2 text-xs sm:text-sm font-medium text-muted-foreground">
                  <Settings2 className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                  {t("healthStatus.customSuppressionSettings")}
                </div>
                <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-2.5 sm:p-3">
                  <div className="space-y-1.5">
                    {customSuppressions.map((cs) => {
                      const catMeta = CATEGORIES.find(c => c.category === cs.category || c.key === cs.category)
                      const CatIcon = catMeta?.Icon || Settings2
                      const durationLabel = formatDuration(cs.hours)
                      
                      return (
                        <div key={cs.key} className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <CatIcon className="h-3 w-3 sm:h-3.5 sm:w-3.5 text-blue-400/70 shrink-0" />
                            <span className="text-[11px] sm:text-xs text-blue-400/80 truncate">{catMeta ? t(`healthStatus.categories.${catMeta.key}`) : cs.label}</span>
                          </div>
                          <Badge variant="outline" className="text-[9px] sm:text-[10px] border-blue-500/30 text-blue-400/80 bg-transparent shrink-0">
                            {durationLabel}
                          </Badge>
                        </div>
                      )
                    })}
                  </div>
                  <p className="text-[10px] text-muted-foreground/60 mt-2 pt-1.5 border-t border-blue-500/10">
                    {t("healthStatus.autoSuppressedHint")}
                  </p>
                </div>
              </div>
            )}

            {healthData.timestamp && (
              <div className="text-xs text-muted-foreground text-center pt-2">
                {t("healthStatus.lastUpdated", { date: new Date(healthData.timestamp).toLocaleString(document.documentElement.lang) })}
              </div>
            )}
          </div>
        )}
      </DialogContent>
      <ScriptTerminalModal
        open={showUpdateTerminal}
        onClose={() => {
          setShowUpdateTerminal(false)
          // Force a fresh read (cache-busting via ?refresh=1) so the
          // "System Updates" row reflects the state right after the
          // update finished, instead of the pre-update cached value.
          fetchHealthDetails(true).catch(() => {})
        }}
        scriptPath="/usr/local/share/proxmenux/scripts/utilities/proxmox_update.sh"
        scriptName="proxmox_update"
        params={{
          EXECUTION_MODE: "web",
        }}
        title={t("healthStatus.updateTerminalTitle")}
        description={t("healthStatus.updateTerminalDescription")}
      />
    </Dialog>
  )
}

// Small split button: the visible click opens a 3-option menu so the user
// chooses how long this specific alert stays silenced. ``-1`` is the
// permanent sentinel — backend stores it as `suppression_hours = -1` and
// the alert can only be brought back from Settings → Active Suppressions.
function DismissDropdown({
  onSelect,
  busy,
  t,
}: {
  onSelect: (suppressionHours: number) => void
  busy: boolean
  t: ReturnType<typeof useT>
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="sm"
          variant="outline"
          className="h-5 px-1 sm:px-1.5 shrink-0 hover:bg-red-500/10 hover:border-red-500/50 bg-transparent text-[10px]"
          disabled={busy}
          onClick={(e) => e.stopPropagation()}
        >
          {busy ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <>
              <X className="h-3 w-3 sm:mr-0.5" />
              <span className="hidden sm:inline">{t("healthStatus.dismiss")}</span>
            </>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-44" onClick={(e) => e.stopPropagation()}>
        <DropdownMenuLabel className="text-[10px] uppercase tracking-wide text-muted-foreground">
          {t("healthStatus.silenceFor")}
        </DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => onSelect(24)} className="text-xs">
          <Clock className="h-3 w-3 mr-2 text-muted-foreground" /> {t("healthStatus.duration.24hours")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onSelect(168)} className="text-xs">
          <Clock className="h-3 w-3 mr-2 text-muted-foreground" /> {t("healthStatus.duration.7days")}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => onSelect(-1)}
          className="text-xs text-red-500 focus:text-red-500 focus:bg-red-500/10"
        >
          <BellOff className="h-3 w-3 mr-2" /> {t("healthStatus.permanently")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
