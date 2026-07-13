"use client"

import { useState, useEffect, useMemo, useCallback } from "react"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs"
import { SystemOverview } from "./system-overview"
import { StorageOverview } from "./storage-overview"
import { NetworkMetrics } from "./network-metrics"
import { VirtualMachines } from "./virtual-machines"
import Hardware from "./hardware"
import { SystemLogs } from "./system-logs"
import { Settings } from "./settings"
import { Security } from "./security"
import { Profile } from "./profile"
import { About } from "./about"
import { HostBackup } from "./host-backup"
import { OnboardingCarousel } from "./onboarding-carousel"
import { HealthStatusModal } from "./health-status-modal"
import { ReleaseNotesModal, useVersionCheck } from "./release-notes-modal"
import { getApiUrl, fetchApi } from "../lib/api-config"
import { TerminalPanel } from "./terminal-panel"
import { AvatarMenu } from "./avatar-menu"
import {
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Server,
  Menu,
  LayoutDashboard,
  HardDrive,
  NetworkIcon,
  Boxes,
  Cpu,
  ScrollText,
  SettingsIcon,
  Settings2,
  Terminal,
  ShieldCheck,
  Info,
  DatabaseBackup,
  ChevronDown,
} from "lucide-react"
import Image from "next/image"
import { ThemeToggle } from "./theme-toggle"
import { Sheet, SheetContent, SheetTrigger } from "./ui/sheet"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu"

interface SystemStatus {
  status: "healthy" | "warning" | "critical"
  uptime: string
  lastUpdate: string
  serverName: string
  nodeId: string
}

interface FlaskSystemData {
  hostname: string
  node_id: string
  uptime: string
  cpu_usage: number
  memory_usage: number
  temperature: number
  load_average: number[]
}

interface FlaskSystemInfo {
  hostname: string
  node_id: string
  uptime: string
  health: {
    status: "healthy" | "warning" | "critical"
  }
}

export function ProxmoxDashboard() {
  const [systemStatus, setSystemStatus] = useState<SystemStatus>({
    status: "healthy",
    uptime: "Loading...",
    lastUpdate: new Date().toLocaleTimeString("en-US", { hour12: false }),
    serverName: "Loading...",
    nodeId: "Loading...",
  })
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isServerConnected, setIsServerConnected] = useState(true)
  const [componentKey, setComponentKey] = useState(0)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [activeTab, setActiveTab] = useState("overview")
  const [infoCount, setInfoCount] = useState(0)
  const [updateAvailable, setUpdateAvailable] = useState(false)
  const [showNavigation, setShowNavigation] = useState(true)
  const [lastScrollY, setLastScrollY] = useState(0)
  const [showHealthModal, setShowHealthModal] = useState(false)
  const { showReleaseNotes, setShowReleaseNotes } = useVersionCheck()

  // Category keys for health info count calculation
  const HEALTH_CATEGORY_KEYS = [
    { key: "cpu", category: "temperature" },
    { key: "memory", category: "memory" },
    { key: "storage", category: "storage" },
    { key: "disks", category: "disks" },
    { key: "network", category: "network" },
    { key: "vms", category: "vms" },
    { key: "services", category: "pve_services" },
    { key: "logs", category: "logs" },
    { key: "updates", category: "updates" },
    { key: "security", category: "security" },
  ]

  // Fetch ProxMenux update status
  const fetchUpdateStatus = useCallback(async () => {
    try {
      const response = await fetchApi("/api/proxmenux/update-status")
      if (response?.success && response?.update_available) {
        const { stable, beta } = response.update_available
        setUpdateAvailable(stable || beta)
      }
    } catch (error) {
      // Silently fail - updateAvailable will remain false
    }
  }, [])

  // Fetch health info count independently (for initial load and refresh)
  const fetchHealthInfoCount = useCallback(async () => {
    try {
      const response = await fetchApi("/api/health/full")
      let calculatedInfoCount = 0
      
      if (response && response.health?.details) {
        // Get categories that have dismissed items (these become INFO)
        const customCats = new Set((response.custom_suppressions || []).map((cs: { category: string }) => cs.category))
        const filteredDismissed = (response.dismissed || []).filter((item: { category: string }) => !customCats.has(item.category))
        const categoriesWithDismissed = new Set<string>()
        filteredDismissed.forEach((item: { category: string }) => {
          const catMeta = HEALTH_CATEGORY_KEYS.find(c => c.category === item.category || c.key === item.category)
          if (catMeta) {
            categoriesWithDismissed.add(catMeta.key)
          }
        })
        
        // Count effective INFO categories (original INFO + OK categories with dismissed)
        HEALTH_CATEGORY_KEYS.forEach(({ key }) => {
          const cat = response.health.details[key as keyof typeof response.health.details]
          if (cat) {
            const originalStatus = cat.status?.toUpperCase()
            // Count as INFO if: originally INFO OR (originally OK and has dismissed items)
            if (originalStatus === "INFO" || (originalStatus === "OK" && categoriesWithDismissed.has(key))) {
              calculatedInfoCount++
            }
          }
        })
      }
      
      setInfoCount(calculatedInfoCount)
    } catch (error) {
      // Silently fail - infoCount will remain at 0
    }
  }, [])

  const fetchSystemData = useCallback(async () => {
    try {
      const data: FlaskSystemInfo = await fetchApi("/api/system-info")

      const uptimeValue =
        data.uptime && typeof data.uptime === "string" && data.uptime.trim() !== "" ? data.uptime : "N/A"

      const backendStatus = data.health?.status?.toUpperCase() || "OK"
      let healthStatus: "healthy" | "warning" | "critical"

      if (backendStatus === "CRITICAL") {
        healthStatus = "critical"
      } else if (backendStatus === "WARNING") {
        healthStatus = "warning"
      } else {
        healthStatus = "healthy"
      }

      setSystemStatus({
        status: healthStatus,
        uptime: uptimeValue,
        lastUpdate: new Date().toLocaleTimeString("en-US", { hour12: false }),
        serverName: data.hostname || "Unknown",
        nodeId: data.node_id || "Unknown",
      })
      setIsServerConnected(true)
    } catch (error) {
      // Expected to fail in v0 preview (no Flask server)

      setIsServerConnected(false)
      setSystemStatus((prev) => ({
        ...prev,
        status: "critical",
        serverName: "Server Offline",
        nodeId: "Server Offline",
        uptime: "N/A",
        lastUpdate: new Date().toLocaleTimeString("en-US", { hour12: false }),
      }))
    }
  }, [])

  useEffect(() => {
  // Siempre fetch inicial
  fetchSystemData()
  fetchHealthInfoCount()
  fetchUpdateStatus()

    // En overview: cada 30 segundos para actualización frecuente del estado de salud
    // En otras tabs: cada 60 segundos para reducir carga
    let interval: ReturnType<typeof setInterval> | null = null
    let healthInterval: ReturnType<typeof setInterval> | null = null
    if (activeTab === "overview") {
      interval = setInterval(fetchSystemData, 30000) // 30 segundos
      healthInterval = setInterval(fetchHealthInfoCount, 30000) // Also refresh info count
    } else {
      interval = setInterval(fetchSystemData, 60000) // 60 segundos
      healthInterval = setInterval(fetchHealthInfoCount, 60000) // Also refresh info count
    }

    return () => {
      if (interval) clearInterval(interval)
      if (healthInterval) clearInterval(healthInterval)
    }
  }, [fetchSystemData, fetchHealthInfoCount, fetchUpdateStatus, activeTab])

  useEffect(() => {
    const handleChangeTab = (event: CustomEvent) => {
      const { tab } = event.detail
      if (tab) {
        setActiveTab(tab)
      }
    }

    window.addEventListener("changeTab", handleChangeTab as EventListener)
    return () => {
      window.removeEventListener("changeTab", handleChangeTab as EventListener)
    }
  }, [])
  
  // Auto-refresh terminal on mobile devices
  // This fixes the issue where terminal doesn't connect properly on mobile/VPN
  useEffect(() => {
    if (activeTab === "terminal") {
      const isMobileDevice = window.innerWidth < 768 || 
        ('ontouchstart' in window && navigator.maxTouchPoints > 0)
      
      if (isMobileDevice) {
        // Delay to allow initial connection attempt, then refresh to ensure proper connection
        const timeoutId = setTimeout(() => {
          setComponentKey(prev => prev + 1)
        }, 500)
        
        return () => clearTimeout(timeoutId)
      }
    }
  }, [activeTab])

  useEffect(() => {
    const handleHealthStatusUpdate = (event: CustomEvent) => {
      const { status, infoCount: newInfoCount } = event.detail
      let healthStatus: "healthy" | "warning" | "critical"

      if (status === "CRITICAL") {
        healthStatus = "critical"
      } else if (status === "WARNING") {
        healthStatus = "warning"
      } else {
        healthStatus = "healthy"
      }

      setSystemStatus((prev) => ({
        ...prev,
        status: healthStatus,
      }))
      
      // Update info count (INFO categories + dismissed items)
      if (typeof newInfoCount === "number") {
        setInfoCount(newInfoCount)
      }
    }

    window.addEventListener("healthStatusUpdated", handleHealthStatusUpdate as EventListener)
    return () => {
      window.removeEventListener("healthStatusUpdated", handleHealthStatusUpdate as EventListener)
    }
  }, [])

  useEffect(() => {
    if (
      systemStatus.serverName &&
      systemStatus.serverName !== "Loading..." &&
      systemStatus.serverName !== "Server Offline"
    ) {
      document.title = `${systemStatus.serverName} - ProxMenux Monitor`
    } else {
      document.title = "ProxMenux Monitor"
    }
  }, [systemStatus.serverName])

  useEffect(() => {
    let hideTimeout: ReturnType<typeof setTimeout> | null = null
    let lastPosition = window.scrollY

    const handleScroll = () => {
      const currentScrollY = window.scrollY
      const delta = currentScrollY - lastPosition

      if (currentScrollY < 50) {
        setShowNavigation(true)
      } else if (delta > 2) {
        if (hideTimeout) clearTimeout(hideTimeout)
        hideTimeout = setTimeout(() => setShowNavigation(false), 20)
      } else if (delta < -2) {
        if (hideTimeout) clearTimeout(hideTimeout)
        setShowNavigation(true)
      }

      lastPosition = currentScrollY
    }

    window.addEventListener("scroll", handleScroll, { passive: true })
    return () => {
      window.removeEventListener("scroll", handleScroll)
      if (hideTimeout) clearTimeout(hideTimeout)
    }
  }, [])

  const refreshData = async () => {
    setIsRefreshing(true)
    await fetchSystemData()
    setComponentKey((prev) => prev + 1)
    await new Promise((resolve) => setTimeout(resolve, 500))
    setIsRefreshing(false)
  }

  const statusIcon = useMemo(() => {
    switch (systemStatus.status) {
      case "healthy":
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case "warning":
        return <AlertTriangle className="h-4 w-4 text-yellow-500" />
      case "critical":
        return <XCircle className="h-4 w-4 text-red-500" />
    }
  }, [systemStatus.status])

  const statusColor = useMemo(() => {
    switch (systemStatus.status) {
      case "healthy":
        return "bg-green-500/10 text-green-500 border-green-500/20"
      case "warning":
        return "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
      case "critical":
        return "bg-red-500/10 text-red-500 border-red-500/20"
    }
  }, [systemStatus.status])

  const getActiveTabLabel = () => {
    switch (activeTab) {
      case "overview":  return "Overview"
      case "vms":       return "VMs & LXCs"
      case "storage":   return "Storage"
      case "network":   return "Network"
      case "hardware":  return "Hardware"
      case "backup":    return "Backup"
      case "terminal":  return "Terminal"
      case "logs":      return "System Logs"
      case "security":  return "Security"
      case "settings":  return "Settings"
      case "about":     return "About"
      case "profile":   return "Profile"
      default:          return "Navigation Menu"
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <OnboardingCarousel />
      <ReleaseNotesModal open={showReleaseNotes} onClose={() => setShowReleaseNotes(false)} />

      {!isServerConnected && (
        <div className="bg-red-500/10 border-b border-red-500/20 px-6 py-3">
          <div className="container mx-auto">
            <div className="flex items-center space-x-2 text-red-500 mb-2">
              <XCircle className="h-5 w-5" />
              <span className="font-medium">ProxMenux Server Connection Failed</span>
            </div>
            <div className="text-sm text-red-500/80 space-y-1 ml-7">
              <p>• Check that the monitor.service is running correctly.</p>
              <p>• The ProxMenux server should start automatically on port 8008</p>
              <p>
                • Try accessing:{" "}
                <a href={getApiUrl("/api/health")} target="_blank" rel="noopener noreferrer" className="underline">
                  {getApiUrl("/api/health")}
                </a>
              </p>
            </div>
          </div>
        </div>
      )}

      <header
        className="border-b border-border bg-card sticky top-0 z-50 shadow-sm cursor-pointer hover:bg-accent/5 transition-colors"
        onClick={() => setShowHealthModal(true)}
      >
        <div className="container mx-auto px-4 md:px-6 py-4 md:py-4">
          {/* Logo and Title */}
          <div className="flex items-start justify-between gap-3">
            {/* Logo and Title */}
            <div className="flex items-center space-x-2 md:space-x-3 min-w-0">
              <div className="w-16 h-16 md:w-10 md:h-10 relative flex items-center justify-center bg-primary/10 flex-shrink-0">
                <Image
                  src={updateAvailable ? "/images/proxmenux_update-logo.png" : "/images/proxmenux-logo.png"}
                  alt="ProxMenux Logo"
                  width={64}
                  height={64}
                  className="object-contain md:w-10 md:h-10"
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
                <Server className="h-8 w-8 md:h-6 md:w-6 text-primary absolute fallback-icon hidden" />
              </div>
              <div className="min-w-0">
                <h1 className="text-lg md:text-xl font-semibold text-foreground truncate">ProxMenux Monitor</h1>
                <p className="text-xs md:text-sm text-muted-foreground">Proxmox System Dashboard</p>
                <div className="lg:hidden flex items-center gap-1 text-xs text-muted-foreground mt-0.5">
                  <Server className="h-3 w-3" />
                  <span className="truncate">Node: {systemStatus.serverName}</span>
                </div>
              </div>
            </div>

            {/* Desktop Actions */}
            <div className="hidden lg:flex items-center space-x-4">
              <div className="flex items-center space-x-2">
                <Server className="h-4 w-4 text-muted-foreground" />
                <div className="text-sm">
                  <div className="font-medium text-foreground">Node: {systemStatus.serverName}</div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Badge variant="outline" className={statusColor}>
                  {statusIcon}
                  <span className="ml-1 capitalize">{systemStatus.status}</span>
                </Badge>
                {systemStatus.status === "healthy" && infoCount > 0 && (
                  <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">
                    <Info className="h-4 w-4" />
                    <span className="ml-1">{infoCount} info</span>
                  </Badge>
                )}
              </div>

              <div className="text-sm text-muted-foreground whitespace-nowrap">
                Uptime: {systemStatus.uptime || "N/A"}
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation()
                  refreshData()
                }}
                disabled={isRefreshing}
                className="border-border/50 bg-transparent hover:bg-secondary"
              >
                <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? "animate-spin" : ""}`} />
                Refresh
              </Button>

              <div onClick={(e) => e.stopPropagation()}>
                <ThemeToggle />
              </div>

              {/* User account dropdown — Fase 1 (v1.2.2). Self-hides
                  when auth isn't enabled on this install. */}
              <div onClick={(e) => e.stopPropagation()}>
                <AvatarMenu
                  size="lg"
                  onOpenProfile={() => setActiveTab("profile")}
                  onOpenSecurity={() => setActiveTab("security")}
                />
              </div>
            </div>

            {/* Mobile Actions — variant D approved in demo:
                 • Top-right: Refresh + Theme + Avatar (all with border)
                 • Bottom row (under Node line): badges left-aligned with
                   the Node text column, Uptime right-aligned in the same
                   horizontal line. No extra row for Uptime so the
                   header doesn't grow vertically. */}
            <div className="flex lg:hidden items-center gap-1.5 shrink-0">
              <Button
                variant="outline"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation()
                  refreshData()
                }}
                disabled={isRefreshing}
                className="h-8 w-8 p-0 border-border/50 bg-transparent hover:bg-secondary"
                aria-label="Refresh"
              >
                <RefreshCw className={`h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} />
              </Button>

              <div onClick={(e) => e.stopPropagation()}>
                <ThemeToggle />
              </div>

              <div onClick={(e) => e.stopPropagation()}>
                <AvatarMenu
                  size="lg"
                  onOpenProfile={() => setActiveTab("profile")}
                  onOpenSecurity={() => setActiveTab("security")}
                />
              </div>
            </div>
          </div>

          {/* Mobile bottom row — badges (left, aligned with the title
              column via pl-[3.25rem] = w-16 logo + space-x-2 gap-ish)
              and Uptime (right). The pl matches the mobile logo width
              + the parent flex gap so the badges sit visually under
              "Node: amd", not flush against the screen edge. */}
          <div className="lg:hidden mt-2 flex items-center justify-between gap-2 pl-[4.5rem]">
            <div className="flex items-center gap-1.5">
              <Badge variant="outline" className={`${statusColor} text-xs px-2`}>
                {statusIcon}
                <span className="ml-1 capitalize">{systemStatus.status}</span>
              </Badge>
              {systemStatus.status === "healthy" && infoCount > 0 && (
                <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20 text-xs px-2">
                  <Info className="h-3 w-3" />
                  <span className="ml-1">{infoCount}</span>
                </Badge>
              )}
            </div>
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              Uptime: {systemStatus.uptime || "N/A"}
            </span>
          </div>
        </div>
      </header>

      <div
        className={`sticky z-40 bg-background
          top-[120px] lg:top-[76px]
          transition-all duration-700 ease-in-out
          ${showNavigation ? "translate-y-0 opacity-100" : "-translate-y-[120%] opacity-0 pointer-events-none"}
        `}
      >
        <div className="container mx-auto px-4 lg:px-6 pt-4 lg:pt-6">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-0">
            {/* Sprint 13D nav redesign — 6 top-level slots in usage order:
                Overview · VMs & LXCs · Node ⌄ · Backup · Terminal · Admin ⌄
                Node groups Storage / Network / Hardware (3 sub-items).
                Admin groups System Logs / Security / Settings / About
                (will split when RBAC arrives in 1.5.0).
                Backup is direct now (only Host Backup); becomes a dropdown
                when VM/LXC centralised backup ships. */}
            {(() => {
              const triggerActiveClass =
                "data-[state=active]:bg-blue-500 data-[state=active]:text-white data-[state=active]:rounded-md"
              // Each dropdown lists its children in the order they
              // render. When one of them is the active tab, the dropdown
              // trigger swaps its label + icon to that child — same
              // pattern macOS Settings uses inside a category: the
              // crumb shows where you are, the chevron tells you the
              // siblings are one click away.
              const NODE_ITEMS = [
                { value: "storage",  label: "Storage",  Icon: HardDrive,   default: false },
                { value: "network",  label: "Network",  Icon: NetworkIcon, default: false },
                { value: "hardware", label: "Hardware", Icon: Cpu,         default: false },
              ]
              const ADMIN_ITEMS = [
                { value: "logs",     label: "System Logs", Icon: ScrollText,  default: false },
                { value: "security", label: "Security",    Icon: ShieldCheck, default: false },
                { value: "settings", label: "Settings",    Icon: SettingsIcon, default: false },
                { value: "about",    label: "About",       Icon: Info,        default: false },
              ]
              const activeNodeItem  = NODE_ITEMS.find(i => i.value === activeTab)
              const activeAdminItem = ADMIN_ITEMS.find(i => i.value === activeTab)
              const isNodeActive    = activeNodeItem !== undefined
              const isAdminActive   = activeAdminItem !== undefined
              // The trigger label + icon shown on the bar. When a child
              // is active we surface IT; otherwise the group default.
              const NodeTriggerIcon  = activeNodeItem ? activeNodeItem.Icon  : Server
              const NodeTriggerLabel = activeNodeItem ? activeNodeItem.label : "Node"
              const AdminTriggerIcon  = activeAdminItem ? activeAdminItem.Icon  : Settings2
              const AdminTriggerLabel = activeAdminItem ? activeAdminItem.label : "Admin"
              // Dropdown trigger styling: parity with TabsTrigger so the
              // parent visibly carries the "I'm the selected section"
              // signal when any of its children is the active tab —
              // same blue background + white text + rounded as a direct
              // tab. Without this the user lands on Storage and the
              // entire top bar looks idle.
              const dropdownBtnClass = (active: boolean) =>
                `inline-flex items-center justify-center whitespace-nowrap px-3 py-1.5 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 ${
                  active
                    ? "bg-blue-500 text-white rounded-md"
                    : "text-muted-foreground hover:text-foreground rounded-sm"
                }`

              return (
                <TabsList className="hidden lg:grid w-full grid-cols-6 bg-card border border-border">
                  {/* Direct: Overview */}
                  <TabsTrigger value="overview" className={triggerActiveClass}>
                    <LayoutDashboard className="mr-2 h-4 w-4" />
                    Overview
                  </TabsTrigger>

                  {/* Direct: VMs & LXCs — first-class because Proxmox IS
                      a hypervisor; workloads belong at top level. */}
                  <TabsTrigger value="vms" className={triggerActiveClass}>
                    <Boxes className="mr-2 h-4 w-4" />
                    VMs &amp; LXCs
                  </TabsTrigger>

                  {/* Dropdown: Node (Storage / Network / Hardware) */}
                  <DropdownMenu>
                    <DropdownMenuTrigger className={dropdownBtnClass(isNodeActive)}>
                      <NodeTriggerIcon className="mr-2 h-4 w-4" />
                      {NodeTriggerLabel}
                      <ChevronDown className="ml-1.5 h-3 w-3 opacity-70" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="center" className="min-w-[180px]">
                      {NODE_ITEMS.map(({ value, label, Icon }) => (
                        <DropdownMenuItem
                          key={value}
                          onClick={() => setActiveTab(value)}
                          className={activeTab === value ? "bg-blue-500/10 text-blue-500" : ""}
                        >
                          <Icon className="mr-2 h-4 w-4" />
                          {label}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>

                  {/* Direct: Backup (today: Host Backup only). When VM/LXC
                      backup ships this becomes a dropdown. */}
                  <TabsTrigger value="backup" className={triggerActiveClass}>
                    <DatabaseBackup className="mr-2 h-4 w-4" />
                    Backup
                  </TabsTrigger>

                  {/* Direct: Terminal */}
                  <TabsTrigger value="terminal" className={triggerActiveClass}>
                    <Terminal className="mr-2 h-4 w-4" />
                    Terminal
                  </TabsTrigger>

                  {/* Dropdown: Admin (System Logs / Security / Settings / About) */}
                  <DropdownMenu>
                    <DropdownMenuTrigger className={dropdownBtnClass(isAdminActive)}>
                      <AdminTriggerIcon className="mr-2 h-4 w-4" />
                      {AdminTriggerLabel}
                      <ChevronDown className="ml-1.5 h-3 w-3 opacity-70" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="center" className="min-w-[180px]">
                      {ADMIN_ITEMS.map(({ value, label, Icon }) => (
                        <DropdownMenuItem
                          key={value}
                          onClick={() => setActiveTab(value)}
                          className={activeTab === value ? "bg-blue-500/10 text-blue-500" : ""}
                        >
                          <Icon className="mr-2 h-4 w-4" />
                          {label}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TabsList>
              )
            })()}

            <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
              <div className="lg:hidden">
                <SheetTrigger asChild>
                  <Button
                    variant="outline"
                    className={`w-full justify-between border-border ${
                      activeTab ? "bg-blue-500/10 text-blue-500" : "bg-card"
                    }`}
                  >
                    <span>{getActiveTabLabel()}</span>
                    <Menu className="h-4 w-4" />
                  </Button>
                </SheetTrigger>
              </div>
              <SheetContent side="top" className="bg-card border-border">
                {(() => {
                  // Sheet items mirror the desktop layout: 6 sections,
                  // with two of them (Node, Admin) collapsing into a
                  // header + nested items. Direct tabs (Overview, VMs,
                  // Backup, Terminal) sit at the top level.
                  const select = (v: string) => {
                    setActiveTab(v)
                    setMobileMenuOpen(false)
                  }
                  const itemClass = (active: boolean) =>
                    `w-full justify-start gap-3 ${
                      active
                        ? "bg-blue-500/10 text-blue-500 border-l-4 border-blue-500 rounded-l-none"
                        : ""
                    }`
                  // Mobile sheet is a flat list (no section headers).
                  // The desktop layout uses dropdowns to express the
                  // Node/Admin grouping; here we just enumerate items
                  // in the same visual order.
                  return (
                    <div className="flex flex-col gap-1 mt-4">
                      <Button variant="ghost" onClick={() => select("overview")} className={itemClass(activeTab === "overview")}>
                        <LayoutDashboard className="h-5 w-5" />
                        <span>Overview</span>
                      </Button>
                      <Button variant="ghost" onClick={() => select("vms")} className={itemClass(activeTab === "vms")}>
                        <Boxes className="h-5 w-5" />
                        <span>VMs &amp; LXCs</span>
                      </Button>
                      <Button variant="ghost" onClick={() => select("storage")} className={itemClass(activeTab === "storage")}>
                        <HardDrive className="h-5 w-5" />
                        <span>Storage</span>
                      </Button>
                      <Button variant="ghost" onClick={() => select("network")} className={itemClass(activeTab === "network")}>
                        <NetworkIcon className="h-5 w-5" />
                        <span>Network</span>
                      </Button>
                      <Button variant="ghost" onClick={() => select("hardware")} className={itemClass(activeTab === "hardware")}>
                        <Cpu className="h-5 w-5" />
                        <span>Hardware</span>
                      </Button>
                      <Button variant="ghost" onClick={() => select("backup")} className={itemClass(activeTab === "backup")}>
                        <DatabaseBackup className="h-5 w-5" />
                        <span>Backup</span>
                      </Button>
                      <Button variant="ghost" onClick={() => select("terminal")} className={itemClass(activeTab === "terminal")}>
                        <Terminal className="h-5 w-5" />
                        <span>Terminal</span>
                      </Button>
                      <Button variant="ghost" onClick={() => select("logs")} className={itemClass(activeTab === "logs")}>
                        <ScrollText className="h-5 w-5" />
                        <span>System Logs</span>
                      </Button>
                      <Button variant="ghost" onClick={() => select("security")} className={itemClass(activeTab === "security")}>
                        <ShieldCheck className="h-5 w-5" />
                        <span>Security</span>
                      </Button>
                      <Button variant="ghost" onClick={() => select("settings")} className={itemClass(activeTab === "settings")}>
                        <SettingsIcon className="h-5 w-5" />
                        <span>Settings</span>
                      </Button>
                      <Button variant="ghost" onClick={() => select("about")} className={itemClass(activeTab === "about")}>
                        <Info className="h-5 w-5" />
                        <span>About</span>
                      </Button>
                    </div>
                  )
                })()}
              </SheetContent>
            </Sheet>
          </Tabs>
        </div>
      </div>

      <div className="container mx-auto px-4 md:px-6 py-4 md:py-6">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4 md:space-y-6">
          <TabsContent value="overview" className="space-y-4 md:space-y-6 mt-0">
            <SystemOverview key={`overview-${componentKey}`} />
          </TabsContent>

          <TabsContent value="storage" className="space-y-4 md:space-y-6 mt-0">
            <StorageOverview key={`storage-${componentKey}`} />
          </TabsContent>

          <TabsContent value="network" className="space-y-4 md:space-y-6 mt-0">
            <NetworkMetrics key={`network-${componentKey}`} />
          </TabsContent>

          <TabsContent value="vms" className="space-y-4 md:space-y-6 mt-0">
            <VirtualMachines key={`vms-${componentKey}`} />
          </TabsContent>

          <TabsContent value="hardware" className="space-y-4 md:space-y-6 mt-0">
            <Hardware key={`hardware-${componentKey}`} />
          </TabsContent>

          <TabsContent value="logs" className="space-y-4 md:space-y-6 mt-0">
            <SystemLogs key={`logs-${componentKey}`} />
          </TabsContent>

          <TabsContent value="backup" className="space-y-4 md:space-y-6 mt-0">
            <HostBackup key={`backup-${componentKey}`} />
          </TabsContent>

          <TabsContent value="terminal" className="mt-0">
            <TerminalPanel key={`terminal-${componentKey}`} />
          </TabsContent>

          <TabsContent value="security" className="space-y-4 md:space-y-6 mt-0">
            <Security key={`security-${componentKey}`} />
          </TabsContent>

          {/* Profile tab — not surfaced in the top tabs nav. The only
              entry point is the avatar dropdown in the header (View
              profile). v1.2.2 Fase 2. */}
          <TabsContent value="profile" className="space-y-4 md:space-y-6 mt-0">
            <Profile
              key={`profile-${componentKey}`}
              onOpenSecurity={() => setActiveTab("security")}
            />
          </TabsContent>

          <TabsContent value="settings" className="space-y-4 md:space-y-6 mt-0">
            <Settings />
          </TabsContent>

          <TabsContent value="about" className="space-y-4 md:space-y-6 mt-0">
            <About />
          </TabsContent>
        </Tabs>

        <footer className="mt-8 md:mt-12 pt-4 md:pt-6 border-t border-border text-center text-xs md:text-sm text-muted-foreground">
          <p className="font-medium mb-2">ProxMenux Monitor v1.2.3</p>
          <p>
            <a
              href="https://ko-fi.com/macrimi"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-500 hover:text-blue-600 hover:underline transition-colors"
            >
              Support and contribute to the project
            </a>
          </p>
        </footer>
      </div>

      <HealthStatusModal open={showHealthModal} onOpenChange={setShowHealthModal} getApiUrl={getApiUrl} />
    </div>
  )
}
