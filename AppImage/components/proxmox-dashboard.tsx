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
import { AuthSetup } from "./auth-setup"
import { Login } from "./login"
import { Settings } from "./settings"
import { getApiUrl, getApiBaseUrl } from "../lib/api-config"
import { HealthStatusModal } from "./health-status-modal"
import {
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

console.log("[v0] ========================================")
console.log("[v0] ProxmoxDashboard component file loaded!")
console.log("[v0] Timestamp:", new Date().toISOString())
console.log("[v0] ========================================")

export function ProxmoxDashboard() {
  console.log("[v0] ========================================")
  console.log("[v0] ProxmoxDashboard component MOUNTING")
  console.log("[v0] Window location:", typeof window !== "undefined" ? window.location.href : "SSR")
  console.log("[v0] API Base URL:", typeof window !== "undefined" ? getApiBaseUrl() : "SSR")
  console.log("[v0] ========================================")

  const [systemStatus, setSystemStatus] = useState<SystemStatus>({
    status: "healthy",
    uptime: "Loading...",
    lastUpdate: new Date().toLocaleTimeString(),
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
  const [authChecked, setAuthChecked] = useState(false)
  const [authRequired, setAuthRequired] = useState(false)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [authDeclined, setAuthDeclined] = useState(false)
  const [showHealthModal, setShowHealthModal] = useState(false)

  const fetchSystemData = useCallback(async () => {
    console.log("[v0] Fetching system data from Flask server...")
    console.log("[v0] Current window location:", window.location.href)

    const apiUrl = getApiUrl("/api/system")

    console.log("[v0] API URL:", apiUrl)

    try {
      const response = await fetch(apiUrl, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
        cache: "no-store",
      })
      console.log("[v0] Response status:", response.status)

      if (!response.ok) {
        throw new Error(`Server responded with status: ${response.status}`)
      }

      const data: FlaskSystemData = await response.json()
      console.log("[v0] System data received:", data)

      let status: "healthy" | "warning" | "critical" = "healthy"
      if (data.cpu_usage > 90 || data.memory_usage > 90) {
        status = "critical"
      } else if (data.cpu_usage > 75 || data.memory_usage > 75) {
        status = "warning"
      }

      setSystemStatus({
        status,
        uptime: data.uptime,
        lastUpdate: new Date().toLocaleTimeString(),
        serverName: data.hostname,
        nodeId: data.node_id,
      })
      setIsServerConnected(true)
    } catch (error) {
      console.error("[v0] Failed to fetch system data from Flask server:", error)
      console.error("[v0] Error details:", {
        message: error instanceof Error ? error.message : "Unknown error",
        apiUrl,
        windowLocation: window.location.href,
      })

      setIsServerConnected(false)
      setSystemStatus((prev) => ({
        ...prev,
        status: "critical",
        serverName: "Server Offline",
        nodeId: "Server Offline",
        uptime: "N/A",
        lastUpdate: new Date().toLocaleTimeString(),
      }))
    }
  }, [])

  useEffect(() => {
    fetchSystemData()
    const interval = setInterval(fetchSystemData, 10000)
    return () => clearInterval(interval)
  }, [fetchSystemData])

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

  const setupTokenRefresh = () => {
    let refreshTimeout: ReturnType<typeof setTimeout>

    const refreshToken = async () => {
      const token = localStorage.getItem("proxmenux-auth-token")
      if (!token) return

      try {
        const response = await fetch(getApiUrl("/api/auth/refresh"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
        })

        if (response.ok) {
          const data = await response.json()
          localStorage.setItem("proxmenux-auth-token", data.token)
          console.log("[v0] Token refreshed successfully")
        }
      } catch (error) {
        console.error("[v0] Failed to refresh token:", error)
      }
    }

    const resetRefreshTimer = () => {
      clearTimeout(refreshTimeout)
      // Refresh token every 25 minutes (before 30 min expiry)
      refreshTimeout = setTimeout(refreshToken, 25 * 60 * 1000)
    }

    // Refresh on user activity
    const events = ["mousedown", "keydown", "scroll", "touchstart"]
    events.forEach((event) => {
      window.addEventListener(event, resetRefreshTimer, { passive: true })
    })

    resetRefreshTimer()

    return () => {
      clearTimeout(refreshTimeout)
      events.forEach((event) => {
        window.removeEventListener(event, resetRefreshTimer)
      })
    }
  }

  const handleAuthSetupComplete = () => {
    setAuthDeclined(true)
    setIsAuthenticated(true)
  }

  const handleLoginSuccess = () => {
    setIsAuthenticated(true)
    setupTokenRefresh()
  }

  const handleLogout = () => {
    localStorage.removeItem("proxmenux-auth-token")
    setIsAuthenticated(false)
  }

  useEffect(() => {
    const checkAuth = async () => {
      console.log("[v0] ===== AUTH CHECK START =====")
      console.log("[v0] Current URL:", window.location.href)
      console.log("[v0] Window origin:", window.location.origin)

      try {
        const token = localStorage.getItem("proxmenux-auth-token")
        const headers: HeadersInit = { "Content-Type": "application/json" }

        if (token) {
          headers["Authorization"] = `Bearer ${token}`
          console.log("[v0] Token found in localStorage")
        } else {
          console.log("[v0] No token in localStorage")
        }

        const apiUrl = getApiUrl("/api/auth/status")
        console.log("[v0] Auth status API URL:", apiUrl)

        const response = await fetch(apiUrl, { headers })
        console.log("[v0] Auth status response status:", response.status)
        console.log("[v0] Auth status response ok:", response.ok)

        if (!response.ok) {
          throw new Error(`Auth status check failed with status: ${response.status}`)
        }

        const data = await response.json()
        console.log("[v0] Auth status response data:", JSON.stringify(data, null, 2))

        console.log("[v0] Setting authRequired to:", data.auth_enabled)
        console.log("[v0] Setting isAuthenticated to:", data.authenticated)
        console.log("[v0] auth_configured value:", data.auth_configured)

        setAuthRequired(data.auth_enabled)
        setIsAuthenticated(data.authenticated)

        // auth_configured will be true if user either set up auth OR declined it
        const shouldShowModal = !data.auth_configured
        console.log("[v0] Should show modal:", shouldShowModal)
        console.log("[v0] Setting authDeclined to:", data.auth_configured)

        setAuthDeclined(data.auth_configured) // If configured (either way), don't show modal
        setAuthChecked(true)

        if (data.authenticated && token) {
          setupTokenRefresh()
        }

        console.log("[v0] ===== AUTH CHECK SUCCESS =====")
      } catch (error) {
        console.error("[v0] ===== AUTH CHECK FAILED =====")
        console.error("[v0] Failed to check auth status:", error)
        console.error("[v0] Error message:", error instanceof Error ? error.message : "Unknown error")

        console.log("[v0] Setting authDeclined to false (show modal on error)")
        console.log("[v0] Setting authRequired to false (don't require login on error)")

        setAuthDeclined(false) // Show modal when API fails
        setAuthRequired(false) // Don't require login on error
        setAuthChecked(true)

        console.log("[v0] ===== AUTH CHECK ERROR HANDLED =====")
      }
    }

    checkAuth()
  }, [])

  if (!authChecked) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto" />
          <p className="text-muted-foreground">Loading...</p>
        </div>
      </div>
    )
  }

  if (authRequired && !isAuthenticated) {
    return <Login onLogin={handleLoginSuccess} />
  }

  return (
    <div className="min-h-screen bg-background">
      <HealthStatusModal open={showHealthModal} onOpenChange={setShowHealthModal} getApiUrl={getApiUrl} />

      <header
        className="border-b bg-card cursor-pointer hover:bg-muted/50 transition-colors"
        onClick={() => setShowHealthModal(true)}
      >
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Server className="h-6 w-6 text-primary" />
                <h1 className="text-2xl font-bold">ProxMenuX</h1>
              </div>
              <Badge
                variant={
                  systemStatus.status === "healthy"
                    ? "default"
                    : systemStatus.status === "warning"
                      ? "secondary"
                      : "destructive"
                }
                className="cursor-pointer"
              >
                {systemStatus.status === "healthy" && "Healthy"}
                {systemStatus.status === "warning" && "Warning"}
                {systemStatus.status === "critical" && "Critical"}
                {systemStatus.serverName === "Loading..." && "Loading..."}
              </Badge>
            </div>
            <div className="flex items-center gap-4">
              <ThemeToggle />
              {isAuthenticated && (
                <Button variant="outline" size="sm" onClick={handleLogout}>
                  Logout
                </Button>
              )}
            </div>
          </div>
        </div>
      </header>

      {!authDeclined && !authRequired && <AuthSetup onComplete={handleAuthSetupComplete} />}

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
            <Settings key={`settings-${componentKey}`} />
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
    </div>
  )
}
