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
import { OnboardingCarousel } from "./onboarding-carousel"
import { HealthStatusModal } from "./health-status-modal"
import { getApiUrl } from "../lib/api-config"
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
  Box,
  Cpu,
  FileText,
  SettingsIcon,
} from "lucide-react"
import Image from "next/image"
import { ThemeToggle } from "./theme-toggle"
import { Sheet, SheetContent, SheetTrigger } from "./ui/sheet"

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
  const [showNavigation, setShowNavigation] = useState(true)
  const [lastScrollY, setLastScrollY] = useState(0)
  const [showHealthModal, setShowHealthModal] = useState(false)

  const fetchSystemData = useCallback(async () => {
    const apiUrl = getApiUrl("/api/system-info")

    try {
      const response = await fetch(apiUrl, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
        cache: "no-store",
      })

      if (!response.ok) {
        throw new Error(`Server responded with status: ${response.status}`)
      }

      const data: FlaskSystemInfo = await response.json()

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
      console.error("[v0] Failed to fetch system data from Flask server:", error)

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

    // En overview: cada 30 segundos para actualización frecuente del estado de salud
    // En otras tabs: cada 60 segundos para reducir carga
    let interval: ReturnType<typeof setInterval> | null = null
    if (activeTab === "overview") {
      interval = setInterval(fetchSystemData, 30000) // 30 segundos
    } else {
      interval = setInterval(fetchSystemData, 60000) // 60 segundos
    }

    return () => {
      if (interval) clearInterval(interval)
    }
  }, [fetchSystemData, activeTab])

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
      case "overview":
        return "Overview"
      case "storage":
        return "Storage"
      case "network":
        return "Network"
      case "vms":
        return "VMs & LXCs"
      case "hardware":
        return "Hardware"
      case "logs":
        return "System Logs"
      case "settings":
        return "Settings"
      default:
        return "Navigation Menu"
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <OnboardingCarousel />

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
                  src="/images/proxmenux-logo.png"
                  alt="ProxMenux Logo"
                  width={64}
                  height={64}
                  className="object-contain md:w-10 md:h-10"
                  priority
                  onError={(e) => {
                    console.log("[v0] Logo failed to load, using fallback icon")
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

              <Badge variant="outline" className={statusColor}>
                {statusIcon}
                <span className="ml-1 capitalize">{systemStatus.status}</span>
              </Badge>

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
            </div>

            {/* Mobile Actions */}
            <div className="flex lg:hidden items-center gap-2">
              <Badge variant="outline" className={`${statusColor} text-xs px-2`}>
                {statusIcon}
                <span className="ml-1 capitalize hidden sm:inline">{systemStatus.status}</span>
              </Badge>

              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation()
                  refreshData()
                }}
                disabled={isRefreshing}
                className="h-8 w-8 p-0"
              >
                <RefreshCw className={`h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} />
              </Button>

              <div onClick={(e) => e.stopPropagation()}>
                <ThemeToggle />
              </div>
            </div>
          </div>

          {/* Mobile Server Info */}
          <div className="lg:hidden mt-2 flex items-center justify-end text-xs text-muted-foreground">
            <span className="whitespace-nowrap">Uptime: {systemStatus.uptime || "N/A"}</span>
          </div>
        </div>
      </header>

      <div
        className={`sticky z-40 bg-background
          top-[120px] md:top-[76px]
          transition-all duration-700 ease-[cubic-bezier(0.4,0,0.2,1)]
          ${showNavigation ? "translate-y-0 opacity-100" : "-translate-y-[120%] opacity-0 pointer-events-none"}
        `}
      >
        <div className="container mx-auto px-4 md:px-6 pt-4 md:pt-6">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-0">
            <TabsList className="hidden md:grid w-full grid-cols-7 bg-card border border-border">
              <TabsTrigger
                value="overview"
                className="data-[state=active]:bg-blue-500 data-[state=active]:text-white data-[state=active]:rounded-md"
              >
                Overview
              </TabsTrigger>
              <TabsTrigger
                value="storage"
                className="data-[state=active]:bg-blue-500 data-[state=active]:text-white data-[state=active]:rounded-md"
              >
                Storage
              </TabsTrigger>
              <TabsTrigger
                value="network"
                className="data-[state=active]:bg-blue-500 data-[state=active]:text-white data-[state=active]:rounded-md"
              >
                Network
              </TabsTrigger>
              <TabsTrigger
                value="vms"
                className="data-[state=active]:bg-blue-500 data-[state=active]:text-white data-[state=active]:rounded-md"
              >
                VMs & LXCs
              </TabsTrigger>
              <TabsTrigger
                value="hardware"
                className="data-[state=active]:bg-blue-500 data-[state=active]:text-white data-[state=active]:rounded-md"
              >
                Hardware
              </TabsTrigger>
              <TabsTrigger
                value="logs"
                className="data-[state=active]:bg-blue-500 data-[state=active]:text-white data-[state=active]:rounded-md"
              >
                System Logs
              </TabsTrigger>
              <TabsTrigger
                value="settings"
                className="data-[state=active]:bg-blue-500 data-[state=active]:text-white data-[state=active]:rounded-md"
              >
                Settings
              </TabsTrigger>
            </TabsList>

            <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
              <div className="md:hidden">
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
                <div className="flex flex-col gap-2 mt-4">
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setActiveTab("overview")
                      setMobileMenuOpen(false)
                    }}
                    className={`w-full justify-start gap-3 ${
                      activeTab === "overview"
                        ? "bg-blue-500/10 text-blue-500 border-l-4 border-blue-500 rounded-l-none"
                        : ""
                    }`}
                  >
                    <LayoutDashboard className="h-5 w-5" />
                    <span>Overview</span>
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setActiveTab("storage")
                      setMobileMenuOpen(false)
                    }}
                    className={`w-full justify-start gap-3 ${
                      activeTab === "storage"
                        ? "bg-blue-500/10 text-blue-500 border-l-4 border-blue-500 rounded-l-none"
                        : ""
                    }`}
                  >
                    <HardDrive className="h-5 w-5" />
                    <span>Storage</span>
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setActiveTab("network")
                      setMobileMenuOpen(false)
                    }}
                    className={`w-full justify-start gap-3 ${
                      activeTab === "network"
                        ? "bg-blue-500/10 text-blue-500 border-l-4 border-blue-500 rounded-l-none"
                        : ""
                    }`}
                  >
                    <NetworkIcon className="h-5 w-5" />
                    <span>Network</span>
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setActiveTab("vms")
                      setMobileMenuOpen(false)
                    }}
                    className={`w-full justify-start gap-3 ${
                      activeTab === "vms"
                        ? "bg-blue-500/10 text-blue-500 border-l-4 border-blue-500 rounded-l-none"
                        : ""
                    }`}
                  >
                    <Box className="h-5 w-5" />
                    <span>VMs & LXCs</span>
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setActiveTab("hardware")
                      setMobileMenuOpen(false)
                    }}
                    className={`w-full justify-start gap-3 ${
                      activeTab === "hardware"
                        ? "bg-blue-500/10 text-blue-500 border-l-4 border-blue-500 rounded-l-none"
                        : ""
                    }`}
                  >
                    <Cpu className="h-5 w-5" />
                    <span>Hardware</span>
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setActiveTab("logs")
                      setMobileMenuOpen(false)
                    }}
                    className={`w-full justify-start gap-3 ${
                      activeTab === "logs"
                        ? "bg-blue-500/10 text-blue-500 border-l-4 border-blue-500 rounded-l-none"
                        : ""
                    }`}
                  >
                    <FileText className="h-5 w-5" />
                    <span>System Logs</span>
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setActiveTab("settings")
                      setMobileMenuOpen(false)
                    }}
                    className={`w-full justify-start gap-3 ${
                      activeTab === "settings"
                        ? "bg-blue-500/10 text-blue-500 border-l-4 border-blue-500 rounded-l-none"
                        : ""
                    }`}
                  >
                    <SettingsIcon className="h-5 w-5" />
                    <span>Settings</span>
                  </Button>
                </div>
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

          <TabsContent value="settings" className="space-y-4 md:space-y-6 mt-0">
            <Settings />
          </TabsContent>
        </Tabs>

        <footer className="mt-8 md:mt-12 pt-4 md:pt-6 border-t border-border text-center text-xs md:text-sm text-muted-foreground">
          <p className="font-medium mb-2">ProxMenux Monitor v1.0.1</p>
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
