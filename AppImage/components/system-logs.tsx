"use client"

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { ScrollArea } from "./ui/scroll-area"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "./ui/sheet"
import {
  FileText,
  Search,
  Download,
  AlertTriangle,
  Info,
  CheckCircle,
  XCircle,
  Database,
  Activity,
  HardDrive,
  Calendar,
  RefreshCw,
  Bell,
  Mail,
  Menu,
  Terminal,
  CalendarDays,
} from "lucide-react"
import { useState, useEffect } from "react"

interface Log {
  timestamp: string
  level: string
  service: string
  message: string
  source: string
  pid?: string
  hostname?: string
}

interface Backup {
  volid: string
  storage: string
  vmid: string | null
  type: string | null
  size: number
  size_human: string
  created: string
  timestamp: number
}

interface Event {
  upid: string
  type: string
  status: string
  level: string
  node: string
  user: string
  vmid: string
  starttime: string
  endtime: string
  duration: string
}

interface Notification {
  timestamp: string
  type: string
  service: string
  message: string
  source: string
}

interface SystemLog {
  timestamp: string
  level: string
  service: string
  message: string
  source: string
  pid?: string
  hostname?: string
}

interface CombinedLogEntry {
  timestamp: string
  level: string
  service: string
  message: string
  source: string
  pid?: string
  hostname?: string
  isEvent: boolean
  eventData?: Event
  sortTimestamp: number
}

export function SystemLogs() {
  const [logs, setLogs] = useState<SystemLog[]>([])
  const [backups, setBackups] = useState<Backup[]>([])
  const [events, setEvents] = useState<Event[]>([])
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [searchTerm, setSearchTerm] = useState("")
  const [levelFilter, setLevelFilter] = useState("all")
  const [serviceFilter, setServiceFilter] = useState("all")
  const [activeTab, setActiveTab] = useState("logs")

  const [displayedLogsCount, setDisplayedLogsCount] = useState(500)

  const [selectedLog, setSelectedLog] = useState<SystemLog | null>(null)
  const [selectedEvent, setSelectedEvent] = useState<Event | null>(null)
  const [selectedBackup, setSelectedBackup] = useState<Backup | null>(null)
  const [selectedNotification, setSelectedNotification] = useState<Notification | null>(null) // Added
  const [isLogModalOpen, setIsLogModalOpen] = useState(false)
  const [isEventModalOpen, setIsEventModalOpen] = useState(false)
  const [isBackupModalOpen, setIsBackupModalOpen] = useState(false)
  const [isNotificationModalOpen, setIsNotificationModalOpen] = useState(false) // Added

  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)

  const [dateFilter, setDateFilter] = useState("1")
  const [customDays, setCustomDays] = useState("1")

  const getApiUrl = (endpoint: string) => {
    if (typeof window !== "undefined") {
      return `${window.location.protocol}//${window.location.hostname}:8008${endpoint}`
    }
    return `http://localhost:8008${endpoint}`
  }

  useEffect(() => {
    // Initial fetch might be redundant if dateFilter is not "now" anymore, but keeping for now
    // if (dateFilter === "now") {
    fetchAllData()
    // }
  }, [])

  useEffect(() => {
    console.log("[v0] Date filter changed:", dateFilter, "Custom days:", customDays)
    setLoading(true)
    fetchSystemLogs()
      .then((newLogs) => {
        console.log("[v0] Loaded logs for date filter:", dateFilter, "Count:", newLogs.length)
        console.log("[v0] First log:", newLogs[0])
        setLogs(newLogs)
        setLoading(false)
      })
      .catch((err) => {
        console.error("[v0] Error loading logs:", err)
        setLoading(false)
      })
  }, [dateFilter, customDays])

  useEffect(() => {
    console.log("[v0] Level or service filter changed:", levelFilter, serviceFilter)
    setLoading(true)
    fetchSystemLogs()
      .then((newLogs) => {
        console.log(
          "[v0] Loaded logs for filters - Level:",
          levelFilter,
          "Service:",
          serviceFilter,
          "Count:",
          newLogs.length,
        )
        setLogs(newLogs)
        setLoading(false)
      })
      .catch((err) => {
        console.error("[v0] Error loading logs:", err)
        setLoading(false)
      })
  }, [levelFilter, serviceFilter])

  const fetchAllData = async () => {
    try {
      setLoading(true)
      setError(null)

      // NOTE: Backend endpoints should filter data by current node only
      // When a node belongs to a cluster, only show data for that specific node:
      // - /api/logs - should return logs only from current node
      // - /api/backups - should return backups only from current node
      // - /api/events - should return events only from current node
      // - /api/notifications - should return notifications only from current node

      const [logsRes, backupsRes, eventsRes, notificationsRes] = await Promise.all([
        fetchSystemLogs(),
        fetch(getApiUrl("/api/backups")),
        fetch(getApiUrl("/api/events?limit=50")),
        fetch(getApiUrl("/api/notifications")),
      ])

      setLogs(logsRes)

      if (backupsRes.ok) {
        const backupsData = await backupsRes.json()
        setBackups(backupsData.backups || [])
      }

      if (eventsRes.ok) {
        const eventsData = await eventsRes.json()
        setEvents(eventsData.events || [])
      }

      if (notificationsRes.ok) {
        const notificationsData = await notificationsRes.json()
        setNotifications(notificationsData.notifications || [])
      }
    } catch (err) {
      console.error("[v0] Error fetching system logs data:", err)
      setError("Failed to connect to server")
    } finally {
      setLoading(false)
    }
  }

  const fetchSystemLogs = async (): Promise<SystemLog[]> => {
    try {
      let apiUrl = getApiUrl("/api/logs")
      const params = new URLSearchParams()

      const daysAgo = dateFilter === "custom" ? Number.parseInt(customDays) : Number.parseInt(dateFilter)
      params.append("since_days", daysAgo.toString())
      console.log("[v0] Fetching logs since_days:", daysAgo)

      if (levelFilter !== "all") {
        const priorityMap: Record<string, string> = {
          error: "3", // 0-3: emerg, alert, crit, err
          warning: "4", // 4: warning
          info: "6", // 5-7: notice, info, debug
        }
        const priority = priorityMap[levelFilter]
        if (priority) {
          params.append("priority", priority)
          console.log("[v0] Fetching logs with priority:", priority, "for level:", levelFilter)
        }
      }

      if (serviceFilter !== "all") {
        params.append("service", serviceFilter)
        console.log("[v0] Fetching logs for service:", serviceFilter)
      }

      params.append("limit", "5000")

      if (params.toString()) {
        apiUrl += `?${params.toString()}`
      }

      console.log("[v0] Making fetch request to:", apiUrl)
      const response = await fetch(apiUrl, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
        cache: "no-store",
        signal: AbortSignal.timeout(30000), // 30 second timeout
      })

      console.log("[v0] Response status:", response.status, "OK:", response.ok)

      if (!response.ok) {
        throw new Error(`Flask server responded with status: ${response.status}`)
      }

      const data = await response.json()
      console.log("[v0] Received logs data, count:", data.logs?.length || 0)

      const logsArray = Array.isArray(data) ? data : data.logs || []
      console.log("[v0] Returning logs array with length:", logsArray.length)
      return logsArray
    } catch (error) {
      console.error("[v0] Failed to fetch system logs:", error)
      if (error instanceof Error && error.name === "TimeoutError") {
        setError("Request timed out. Try selecting a more specific filter.")
      } else {
        setError("Failed to load logs. Please try again.")
      }
      return []
    }
  }

  const handleDownloadLogs = async () => {
    try {
      // Generate filename based on active filters
      const filters = []
      if (dateFilter !== "30") {
        const days = dateFilter === "custom" ? customDays : dateFilter
        filters.push(`${days}days`)
      }
      if (levelFilter !== "all") {
        filters.push(levelFilter)
      }
      if (serviceFilter !== "all") {
        filters.push(serviceFilter)
      }
      if (searchTerm) {
        filters.push("searched")
      }

      const filename = `proxmox_logs_${filters.length > 0 ? filters.join("_") + "_" : ""}${new Date().toISOString().split("T")[0]}.txt`

      // Generate log content
      const logContent = [
        `Proxmox System Logs & Events Export`,
        `Generated: ${new Date().toISOString()}`,
        `Total Entries: ${filteredCombinedLogs.length.toLocaleString()}`,
        ``,
        `Filters Applied:`,
        `- Date Range: ${dateFilter === "custom" ? `${customDays} days ago` : `${dateFilter} days ago`}`,
        `- Level: ${levelFilter === "all" ? "All Levels" : levelFilter}`,
        `- Service: ${serviceFilter === "all" ? "All Services" : serviceFilter}`,
        `- Search: ${searchTerm || "None"}`,
        ``,
        `${"=".repeat(80)}`,
        ``,
        ...filteredCombinedLogs.map((log) => {
          const lines = [
            `[${log.timestamp}] ${log.level.toUpperCase()} - ${log.service}${log.isEvent ? " [EVENT]" : ""}`,
            `Message: ${log.message}`,
            `Source: ${log.source}`,
          ]
          if (log.pid) lines.push(`PID: ${log.pid}`)
          if (log.hostname) lines.push(`Hostname: ${log.hostname}`)
          lines.push(`${"-".repeat(80)}`)
          return lines.join("\n")
        }),
      ].join("\n")

      // Create and download blob
      const blob = new Blob([logContent], { type: "text/plain" })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      console.error("Error exporting logs:", err)
    }
  }

  const extractUPID = (message: string): string | null => {
    const upidMatch = message.match(/UPID:[^\s:]+:[^\s:]+:[^\s:]+:[^\s:]+:[^\s:]+:[^\s:]*:[^\s:]*:?[^\s]*/)
    return upidMatch ? upidMatch[0] : null
  }

  const handleDownloadNotificationLog = async (notification: Notification) => {
    try {
      const upid = extractUPID(notification.message)

      if (upid) {
        // Try to fetch the complete task log from Proxmox
        try {
          const response = await fetch(getApiUrl(`/api/task-log/${encodeURIComponent(upid)}`))

          if (response.ok) {
            const taskLog = await response.text()

            // Download the complete task log
            const blob = new Blob(
              [
                `Proxmox Task Log\n`,
                `================\n\n`,
                `UPID: ${upid}\n`,
                `Timestamp: ${notification.timestamp}\n`,
                `Service: ${notification.service}\n`,
                `Source: ${notification.source}\n\n`,
                `Complete Task Log:\n`,
                `${"-".repeat(80)}\n`,
                `${taskLog}\n`,
              ],
              { type: "text/plain" },
            )

            const url = window.URL.createObjectURL(blob)
            const a = document.createElement("a")
            a.href = url
            a.download = `task_log_${upid.replace(/:/g, "_")}_${notification.timestamp.replace(/[:\s]/g, "_")}.txt`
            document.body.appendChild(a)
            a.click()
            window.URL.revokeObjectURL(url)
            document.body.removeChild(a)
            return
          }
        } catch (error) {
          console.error("[v0] Failed to fetch task log from Proxmox:", error)
          // Fall through to download notification message
        }
      }

      // If no UPID or failed to fetch task log, download the notification message
      const blob = new Blob(
        [
          `Notification Details\n`,
          `==================\n\n`,
          `Timestamp: ${notification.timestamp}\n`,
          `Type: ${notification.type}\n`,
          `Service: ${notification.service}\n`,
          `Source: ${notification.source}\n\n`,
          `Complete Message:\n`,
          `${notification.message}\n`,
        ],
        { type: "text/plain" },
      )

      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `notification_${notification.timestamp.replace(/[:\s]/g, "_")}.txt`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      console.error("[v0] Error downloading notification:", err)
    }
  }

  const combinedLogs: CombinedLogEntry[] = [
    ...logs.map((log) => ({ ...log, isEvent: false, sortTimestamp: new Date(log.timestamp).getTime() })),
    ...events.map((event) => ({
      timestamp: event.starttime,
      level: event.level,
      service: event.type,
      message: `${event.type}${event.vmid ? ` (VM/CT ${event.vmid})` : ""} - ${event.status}`,
      source: `Node: ${event.node} • User: ${event.user}`,
      isEvent: true,
      eventData: event,
      sortTimestamp: new Date(event.starttime).getTime(),
    })),
  ].sort((a, b) => b.sortTimestamp - a.sortTimestamp) // Sort by timestamp descending

  // Filter combined logs
  const filteredCombinedLogs = combinedLogs.filter((log) => {
    const matchesSearch =
      log.message.toLowerCase().includes(searchTerm.toLowerCase()) ||
      log.service.toLowerCase().includes(searchTerm.toLowerCase())
    const matchesLevel = levelFilter === "all" || log.level === levelFilter
    const matchesService = serviceFilter === "all" || log.service === serviceFilter

    return matchesSearch && matchesLevel && matchesService
  })

  const displayedLogs = filteredCombinedLogs.slice(0, displayedLogsCount)
  const hasMoreLogs = displayedLogsCount < filteredCombinedLogs.length

  const getLevelColor = (level: string) => {
    switch (level) {
      case "error":
      case "critical":
      case "emergency":
      case "alert":
        return "bg-red-500/10 text-red-500 border-red-500/20"
      case "warning":
        return "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
      case "info":
      case "notice":
        return "bg-blue-500/10 text-blue-500 border-blue-500/20"
      case "success":
        return "bg-green-500/10 text-green-500 border-green-500/20"
      default:
        return "bg-gray-500/10 text-gray-500 border-gray-500/20"
    }
  }

  const getLevelIcon = (level: string) => {
    switch (level) {
      case "error":
      case "critical":
      case "emergency":
      case "alert":
        return <XCircle className="h-3 w-3 mr-1" />
      case "warning":
        return <AlertTriangle className="h-3 w-3 mr-1" />
      case "info":
      case "notice":
        return <Info className="h-3 w-3 mr-1" />
      case "success":
        return <CheckCircle className="h-3 w-3 mr-1" />
      default:
        return <CheckCircle className="h-3 w-3 mr-1" />
    }
  }

  const getNotificationIcon = (type: string) => {
    switch (type) {
      case "email":
        return <Mail className="h-4 w-4 text-blue-500" />
      case "webhook":
        return <Activity className="h-4 w-4 text-purple-500" />
      case "alert":
        return <AlertTriangle className="h-4 w-4 text-yellow-500" />
      case "error":
        return <XCircle className="h-4 w-4 text-red-500" />
      case "success":
        return <CheckCircle className="h-4 w-4 text-green-500" />
      default:
        return <Bell className="h-4 w-4 text-gray-500" />
    }
  }

  const getNotificationTypeColor = (type: string) => {
    switch (type.toLowerCase()) {
      case "error":
        return "bg-red-500/10 text-red-500 border-red-500/20"
      case "warning":
        return "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
      case "info":
        return "bg-blue-500/10 text-blue-500 border-blue-500/20"
      case "success":
        return "bg-green-500/10 text-green-500 border-green-500/20"
      default:
        return "bg-gray-500/10 text-gray-500 border-gray-500/20"
    }
  }

  // ADDED: New function for notification source colors
  const getNotificationSourceColor = (source: string) => {
    switch (source.toLowerCase()) {
      case "task-log":
        return "bg-purple-500/10 text-purple-500 border-purple-500/20"
      case "journal":
        return "bg-cyan-500/10 text-cyan-500 border-cyan-500/20"
      case "system":
        return "bg-orange-500/10 text-orange-500 border-orange-500/20"
      default:
        return "bg-gray-500/10 text-gray-500 border-gray-500/20"
    }
  }

  const logCounts = {
    total: logs.length,
    error: logs.filter((log) => ["error", "critical", "emergency", "alert"].includes(log.level)).length,
    warning: logs.filter((log) => log.level === "warning").length,
    info: logs.filter((log) => ["info", "notice", "debug"].includes(log.level)).length,
  }

  const uniqueServices = [...new Set(logs.map((log) => log.service))]

  const getBackupType = (volid: string): "vm" | "lxc" => {
    if (volid.includes("/vm/") || volid.includes("vzdump-qemu")) {
      return "vm"
    }
    return "lxc"
  }

  const getBackupTypeColor = (volid: string) => {
    const type = getBackupType(volid)
    return type === "vm"
      ? "bg-cyan-500/10 text-cyan-500 border-cyan-500/20"
      : "bg-orange-500/10 text-orange-500 border-orange-500/20"
  }

  const getBackupTypeLabel = (volid: string) => {
    const type = getBackupType(volid)
    return type === "vm" ? "VM" : "LXC"
  }

  const getBackupStorageType = (volid: string): "pbs" | "pve" => {
    // PBS backups have format: storage:backup/type/vmid/timestamp
    // PVE backups have format: storage:backup/vzdump-type-vmid-timestamp.vma.zst
    if (volid.includes(":backup/vm/") || volid.includes(":backup/ct/")) {
      return "pbs"
    }
    return "pve"
  }

  const getBackupStorageColor = (volid: string) => {
    const type = getBackupStorageType(volid)
    return type === "pbs"
      ? "bg-purple-500/10 text-purple-500 border-purple-500/20"
      : "bg-blue-500/10 text-blue-500 border-blue-500/20"
  }

  const getBackupStorageLabel = (volid: string) => {
    const type = getBackupStorageType(volid)
    return type === "pbs" ? "PBS" : "PVE"
  }

  const backupStats = {
    total: backups.length,
    totalSize: backups.reduce((sum, b) => sum + b.size, 0),
    qemu: backups.filter((b) => {
      // Check if volid contains /vm/ for QEMU or vzdump-qemu for PVE
      return b.volid.includes("/vm/") || b.volid.includes("vzdump-qemu")
    }).length,
    lxc: backups.filter((b) => {
      // Check if volid contains /ct/ for LXC or vzdump-lxc for PVE
      return b.volid.includes("/ct/") || b.volid.includes("vzdump-lxc")
    }).length,
  }

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return "0 B"
    const k = 1024
    const sizes = ["B", "KB", "MB", "GB", "TB"]
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
  }

  const getSectionIcon = (section: string) => {
    switch (section) {
      case "logs":
        return <Terminal className="h-4 w-4" />
      case "events":
        return <CalendarDays className="h-4 w-4" />
      case "backups":
        return <Database className="h-4 w-4" />
      case "notifications":
        return <Bell className="h-4 w-4" />
      default:
        return <FileText className="h-4 w-4" />
    }
  }

  const getSectionLabel = (section: string) => {
    switch (section) {
      case "logs":
        return "Logs & Events"
      case "events":
        return "Recent Events"
      case "backups":
        return "Backups"
      case "notifications":
        return "Notifications"
      default:
        return section
    }
  }

  if (loading && logs.length === 0 && events.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {loading && (logs.length > 0 || events.length > 0) && (
        <div className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className="flex flex-col items-center gap-4 p-8 rounded-lg bg-card border border-border shadow-lg">
            <RefreshCw className="h-12 w-12 animate-spin text-primary" />
            <div className="text-lg font-medium text-foreground">Loading logs selected...</div>
            <div className="text-sm text-muted-foreground">Please wait while we fetch the logs</div>
          </div>
        </div>
      )}

      {/* Statistics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Entries</CardTitle>
            <FileText className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">
              {filteredCombinedLogs.length.toLocaleString("fr-FR")}
            </div>
            <p className="text-xs text-muted-foreground mt-2">Filtered</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Errors</CardTitle>
            <XCircle className="h-4 w-4 text-red-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-500">{logCounts.error.toLocaleString("fr-FR")}</div>
            <p className="text-xs text-muted-foreground mt-2">Requires attention</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Warnings</CardTitle>
            <AlertTriangle className="h-4 w-4 text-yellow-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-yellow-500">{logCounts.warning.toLocaleString("fr-FR")}</div>
            <p className="text-xs text-muted-foreground mt-2">Monitor closely</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Backups</CardTitle>
            <Database className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-500">{backupStats.total.toLocaleString("fr-FR")}</div>
            <p className="text-xs text-muted-foreground mt-2">{formatBytes(backupStats.totalSize)}</p>
          </CardContent>
        </Card>
      </div>

      {/* Main Content with Tabs */}
      <Card className="bg-card border-border">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-foreground flex items-center">
              <Activity className="h-5 w-5 mr-2" />
              System Logs & Events
            </CardTitle>
            <Button variant="outline" size="sm" onClick={fetchAllData} disabled={loading}>
              <RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="hidden md:grid w-full grid-cols-3">
              <TabsTrigger value="logs">
                <Terminal className="h-4 w-4 mr-2" />
                Logs & Events
              </TabsTrigger>
              <TabsTrigger value="backups">
                <Database className="h-4 w-4 mr-2" />
                Backups
              </TabsTrigger>
              <TabsTrigger value="notifications">
                <Bell className="h-4 w-4 mr-2" />
                Notifications
              </TabsTrigger>
            </TabsList>

            <div className="md:hidden mb-4">
              <Sheet open={isMobileMenuOpen} onOpenChange={setIsMobileMenuOpen}>
                <SheetTrigger asChild>
                  <Button variant="outline" className="w-full justify-start gap-2 bg-transparent">
                    <Menu className="h-4 w-4" />
                    {getSectionIcon(activeTab)}
                    <span>{getSectionLabel(activeTab)}</span>
                  </Button>
                </SheetTrigger>
                <SheetContent side="left" className="w-[280px]">
                  <SheetHeader>
                    <SheetTitle>Sections</SheetTitle>
                  </SheetHeader>
                  <div className="mt-6 space-y-2">
                    <Button
                      variant={activeTab === "logs" ? "default" : "ghost"}
                      className="w-full justify-start gap-3"
                      onClick={() => {
                        setActiveTab("logs")
                        setIsMobileMenuOpen(false)
                      }}
                    >
                      <Terminal className="h-4 w-4" />
                      Logs & Events
                    </Button>
                    <Button
                      variant={activeTab === "backups" ? "default" : "ghost"}
                      className="w-full justify-start gap-3"
                      onClick={() => {
                        setActiveTab("backups")
                        setIsMobileMenuOpen(false)
                      }}
                    >
                      <Database className="h-4 w-4" />
                      Backups
                    </Button>
                    <Button
                      variant={activeTab === "notifications" ? "default" : "ghost"}
                      className="w-full justify-start gap-3"
                      onClick={() => {
                        setActiveTab("notifications")
                        setIsMobileMenuOpen(false)
                      }}
                    >
                      <Bell className="h-4 w-4" />
                      Notifications
                    </Button>
                  </div>
                </SheetContent>
              </Sheet>
            </div>

            <TabsContent value="logs" className="space-y-4">
              <div className="flex flex-col sm:flex-row gap-4">
                <div className="flex-1">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Search logs & events..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="pl-10 bg-background border-border"
                    />
                  </div>
                </div>

                <Select value={dateFilter} onValueChange={setDateFilter}>
                  <SelectTrigger className="w-full sm:w-[180px] bg-background border-border">
                    <SelectValue placeholder="Time range" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">1 day ago</SelectItem>
                    <SelectItem value="3">3 days ago</SelectItem>
                    <SelectItem value="7">1 week ago</SelectItem>
                    <SelectItem value="14">2 weeks ago</SelectItem>
                    <SelectItem value="30">1 month ago</SelectItem>
                    <SelectItem value="90">3 months ago</SelectItem>
                    <SelectItem value="custom">Custom days</SelectItem>
                  </SelectContent>
                </Select>

                {dateFilter === "custom" && (
                  <Input
                    type="number"
                    placeholder="Days ago"
                    value={customDays}
                    onChange={(e) => setCustomDays(e.target.value)}
                    className="w-full sm:w-[120px] bg-background border-border"
                    min="1"
                  />
                )}

                <Select value={levelFilter} onValueChange={setLevelFilter}>
                  <SelectTrigger className="w-full sm:w-[180px] bg-background border-border">
                    <SelectValue placeholder="Filter by level" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Levels</SelectItem>
                    <SelectItem value="error">Error</SelectItem>
                    <SelectItem value="warning">Warning</SelectItem>
                    <SelectItem value="info">Info</SelectItem>
                  </SelectContent>
                </Select>

                <Select value={serviceFilter} onValueChange={setServiceFilter}>
                  <SelectTrigger className="w-full sm:w-[180px] bg-background border-border">
                    <SelectValue placeholder="Filter by service" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Services</SelectItem>
                    {uniqueServices.slice(0, 20).map((service) => (
                      <SelectItem key={service} value={service}>
                        {service}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Button variant="outline" className="border-border bg-transparent" onClick={handleDownloadLogs}>
                  <Download className="h-4 w-4 mr-2" />
                  Export Logs
                </Button>
              </div>

              <ScrollArea className="h-[600px] w-full rounded-md border border-border">
                <div className="space-y-2 p-4">
                  {displayedLogs.map((log, index) => (
                    <div
                      key={index}
                      className="flex flex-col md:flex-row md:items-start space-y-2 md:space-y-0 md:space-x-4 p-3 rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 transition-colors cursor-pointer overflow-hidden"
                      onClick={() => {
                        if (log.isEvent) {
                          setSelectedEvent(log.eventData)
                          setIsEventModalOpen(true)
                        } else {
                          setSelectedLog(log as SystemLog)
                          setIsLogModalOpen(true)
                        }
                      }}
                    >
                      <div className="flex-shrink-0 flex gap-2 flex-wrap">
                        <Badge variant="outline" className={getLevelColor(log.level)}>
                          {getLevelIcon(log.level)}
                          {log.level.toUpperCase()}
                        </Badge>
                        {log.isEvent && (
                          <Badge variant="outline" className="bg-purple-500/10 text-purple-500 border-purple-500/20">
                            <Activity className="h-3 w-3 mr-1" />
                            EVENT
                          </Badge>
                        )}
                      </div>

                      <div className="flex-1 min-w-0 overflow-hidden">
                        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-1 gap-1">
                          <div className="text-sm font-medium text-foreground truncate">{log.service}</div>
                          <div className="text-xs text-muted-foreground font-mono truncate flex-shrink-0">
                            {log.timestamp}
                          </div>
                        </div>
                        <div className="text-sm text-foreground mb-1 truncate">{log.message}</div>
                        <div className="text-xs text-muted-foreground truncate">
                          {log.source}
                          {log.pid && ` • PID: ${log.pid}`}
                          {log.hostname && ` • Host: ${log.hostname}`}
                        </div>
                      </div>
                    </div>
                  ))}

                  {displayedLogs.length === 0 && (
                    <div className="text-center py-8 text-muted-foreground">
                      <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
                      <p>No logs or events found matching your criteria</p>
                    </div>
                  )}

                  {hasMoreLogs && (
                    <div className="flex justify-center pt-4">
                      <Button
                        variant="outline"
                        onClick={() => setDisplayedLogsCount((prev) => prev + 500)}
                        className="border-border"
                      >
                        <RefreshCw className="h-4 w-4 mr-2" />
                        Load More ({filteredCombinedLogs.length - displayedLogsCount} remaining)
                      </Button>
                    </div>
                  )}
                </div>
              </ScrollArea>
            </TabsContent>

            {/* Backups Tab */}
            <TabsContent value="backups" className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                <Card className="bg-card/50 border-border">
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold text-cyan-500">{backupStats.qemu}</div>
                    <p className="text-xs text-muted-foreground mt-1">QEMU Backups</p>
                  </CardContent>
                </Card>
                <Card className="bg-card/50 border-border">
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold text-orange-500">{backupStats.lxc}</div>
                    <p className="text-xs text-muted-foreground mt-1">LXC Backups</p>
                  </CardContent>
                </Card>
                <Card className="bg-card/50 border-border">
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold text-foreground">{formatBytes(backupStats.totalSize)}</div>
                    <p className="text-xs text-muted-foreground mt-1">Total Size</p>
                  </CardContent>
                </Card>
              </div>

              <ScrollArea className="h-[500px] w-full rounded-md border border-border">
                <div className="space-y-2 p-4">
                  {backups.map((backup, index) => (
                    <div
                      key={index}
                      className="flex items-start space-x-4 p-3 rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 transition-colors cursor-pointer overflow-hidden"
                      onClick={() => {
                        setSelectedBackup(backup)
                        setIsBackupModalOpen(true)
                      }}
                    >
                      <div className="flex-shrink-0">
                        <HardDrive className="h-5 w-5 text-blue-500" />
                      </div>

                      <div className="flex-1 min-w-0 overflow-hidden">
                        <div className="flex items-center justify-between mb-1 gap-2 flex-wrap">
                          <div className="flex items-center gap-2 flex-wrap">
                            <Badge variant="outline" className={getBackupTypeColor(backup.volid)}>
                              {getBackupTypeLabel(backup.volid)}
                            </Badge>
                            <Badge variant="outline" className={getBackupStorageColor(backup.volid)}>
                              {getBackupStorageLabel(backup.volid)}
                            </Badge>
                          </div>
                          <Badge
                            variant="outline"
                            className="bg-green-500/10 text-green-500 border-green-500/20 whitespace-nowrap"
                          >
                            {backup.size_human}
                          </Badge>
                        </div>
                        <div className="text-xs text-muted-foreground mb-1 truncate break-words">
                          Storage: {backup.storage}
                        </div>
                        <div className="text-xs text-muted-foreground flex items-center">
                          <Calendar className="h-3 w-3 mr-1 flex-shrink-0" />
                          <span className="truncate">{backup.created}</span>
                        </div>
                      </div>
                    </div>
                  ))}

                  {backups.length === 0 && (
                    <div className="text-center py-8 text-muted-foreground">
                      <Database className="h-12 w-12 mx-auto mb-4 opacity-50" />
                      <p>No backups found</p>
                    </div>
                  )}
                </div>
              </ScrollArea>
            </TabsContent>

            {/* Notifications Tab */}
            <TabsContent value="notifications" className="space-y-4">
              <ScrollArea className="h-[600px] w-full rounded-md border border-border">
                <div className="space-y-2 p-4">
                  {notifications.map((notification, index) => (
                    <div
                      key={index}
                      className="flex flex-col md:flex-row md:items-start space-y-2 md:space-y-0 md:space-x-4 p-3 rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 transition-colors cursor-pointer overflow-hidden w-full"
                      onClick={() => {
                        setSelectedNotification(notification)
                        setIsNotificationModalOpen(true)
                      }}
                    >
                      <div className="flex-shrink-0 flex gap-2 flex-wrap">
                        <Badge variant="outline" className={getNotificationTypeColor(notification.type)}>
                          {notification.type.toUpperCase()}
                        </Badge>
                        <Badge variant="outline" className={getNotificationSourceColor(notification.source)}>
                          {notification.source === "task-log" && <Activity className="h-3 w-3 mr-1" />}
                          {notification.source === "journal" && <FileText className="h-3 w-3 mr-1" />}
                          {notification.source.toUpperCase()}
                        </Badge>
                      </div>

                      <div className="flex-1 min-w-0 overflow-hidden">
                        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-1 gap-1">
                          <div className="text-sm font-medium text-foreground truncate">{notification.service}</div>
                          <div className="text-xs text-muted-foreground font-mono truncate flex-shrink-0">
                            {notification.timestamp}
                          </div>
                        </div>
                        <div className="text-sm text-foreground mb-1 line-clamp-2 break-words overflow-hidden">
                          {notification.message}
                        </div>
                        <div className="text-xs text-muted-foreground break-words overflow-hidden">
                          Service: {notification.service} • Source: {notification.source}
                        </div>
                      </div>
                    </div>
                  ))}

                  {notifications.length === 0 && (
                    <div className="text-center py-8 text-muted-foreground">
                      <Bell className="h-12 w-12 mx-auto mb-4 opacity-50" />
                      <p>No notifications found</p>
                    </div>
                  )}
                </div>
              </ScrollArea>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <Dialog open={isLogModalOpen} onOpenChange={setIsLogModalOpen}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5" />
              Log Details
            </DialogTitle>
            <DialogDescription>Complete information about this log entry</DialogDescription>
          </DialogHeader>
          {selectedLog && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Level</div>
                  <Badge variant="outline" className={getLevelColor(selectedLog.level)}>
                    {getLevelIcon(selectedLog.level)}
                    {selectedLog.level.toUpperCase()}
                  </Badge>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Service</div>
                  <div className="text-sm text-foreground break-words">{selectedLog.service}</div>
                </div>
                <div className="sm:col-span-2">
                  <div className="text-sm font-medium text-muted-foreground mb-1">Timestamp</div>
                  <div className="text-sm text-foreground font-mono break-words">{selectedLog.timestamp}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Source</div>
                  <div className="text-sm text-foreground break-words">{selectedLog.source}</div>
                </div>
                {selectedLog.pid && (
                  <div>
                    <div className="text-sm font-medium text-muted-foreground mb-1">Process ID</div>
                    <div className="text-sm text-foreground font-mono">{selectedLog.pid}</div>
                  </div>
                )}
                {selectedLog.hostname && (
                  <div className="sm:col-span-2">
                    <div className="text-sm font-medium text-muted-foreground mb-1">Hostname</div>
                    <div className="text-sm text-foreground break-words">{selectedLog.hostname}</div>
                  </div>
                )}
              </div>
              <div>
                <div className="text-sm font-medium text-muted-foreground mb-2">Message</div>
                <div className="p-4 rounded-lg bg-muted/50 border border-border">
                  <pre className="text-sm text-foreground whitespace-pre-wrap break-words">{selectedLog.message}</pre>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={isEventModalOpen} onOpenChange={setIsEventModalOpen}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Event Details
            </DialogTitle>
            <DialogDescription>Complete information about this event</DialogDescription>
            {selectedEvent && (
              <div className="flex gap-2 mt-2">
                <Badge variant="outline" className={getLevelColor(selectedEvent.level)}>
                  {getLevelIcon(selectedEvent.level)}
                  {selectedEvent.level.toUpperCase()}
                </Badge>
                <Badge variant="outline" className="bg-purple-500/10 text-purple-500 border-purple-500/20">
                  <Activity className="h-3 w-3 mr-1" />
                  EVENT
                </Badge>
              </div>
            )}
          </DialogHeader>
          {selectedEvent && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="sm:col-span-2">
                  <div className="text-sm font-medium text-muted-foreground mb-1">Message</div>
                  <div className="text-sm text-foreground break-words">{selectedEvent.status}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Type</div>
                  <div className="text-sm text-foreground break-words">{selectedEvent.type}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Node</div>
                  <div className="text-sm text-foreground">{selectedEvent.node}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">User</div>
                  <div className="text-sm text-foreground break-words">{selectedEvent.user}</div>
                </div>
                {selectedEvent.vmid && (
                  <div>
                    <div className="text-sm font-medium text-muted-foreground mb-1">VM/CT ID</div>
                    <div className="text-sm text-foreground font-mono">{selectedEvent.vmid}</div>
                  </div>
                )}
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Duration</div>
                  <div className="text-sm text-foreground">{selectedEvent.duration}</div>
                </div>
                <div className="sm:col-span-2">
                  <div className="text-sm font-medium text-muted-foreground mb-1">Start Time</div>
                  <div className="text-sm text-foreground break-words">{selectedEvent.starttime}</div>
                </div>
                <div className="sm:col-span-2">
                  <div className="text-sm font-medium text-muted-foreground mb-1">End Time</div>
                  <div className="text-sm text-foreground break-words">{selectedEvent.endtime}</div>
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-muted-foreground mb-2">UPID</div>
                <div className="p-4 rounded-lg bg-muted/50 border border-border">
                  <pre className="text-sm text-foreground font-mono whitespace-pre-wrap break-all">
                    {selectedEvent.upid}
                  </pre>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={isBackupModalOpen} onOpenChange={setIsBackupModalOpen}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              Backup Details
            </DialogTitle>
            <DialogDescription>Complete information about this backup</DialogDescription>
          </DialogHeader>
          {selectedBackup && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Type</div>
                  <Badge variant="outline" className={getBackupTypeColor(selectedBackup.volid)}>
                    {getBackupTypeLabel(selectedBackup.volid)}
                  </Badge>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Storage Type</div>
                  <Badge variant="outline" className={getBackupStorageColor(selectedBackup.volid)}>
                    {getBackupStorageLabel(selectedBackup.volid)}
                  </Badge>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Storage</div>
                  <div className="text-sm text-foreground break-words">{selectedBackup.storage}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Size</div>
                  <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                    {selectedBackup.size_human}
                  </Badge>
                </div>
                {selectedBackup.vmid && (
                  <div>
                    <div className="text-sm font-medium text-muted-foreground mb-1">VM/CT ID</div>
                    <div className="text-sm text-foreground font-mono">{selectedBackup.vmid}</div>
                  </div>
                )}
                <div className="sm:col-span-2">
                  <div className="text-sm font-medium text-muted-foreground mb-1">Created</div>
                  <div className="text-sm text-foreground break-words">{selectedBackup.created}</div>
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-muted-foreground mb-2">Volume ID</div>
                <div className="p-4 rounded-lg bg-muted/50 border border-border">
                  <pre className="text-sm text-foreground font-mono whitespace-pre-wrap break-all">
                    {selectedBackup.volid}
                  </pre>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={isNotificationModalOpen} onOpenChange={setIsNotificationModalOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto w-[96vw] sm:w-full mx-2 sm:mx-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base sm:text-lg pr-8">
              <Bell className="h-4 w-4 sm:h-5 sm:w-5 flex-shrink-0" />
              <span className="truncate">Notification Details</span>
            </DialogTitle>
            <DialogDescription className="text-xs sm:text-sm">
              Complete information about this notification
            </DialogDescription>
          </DialogHeader>
          {selectedNotification && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 sm:gap-4">
                <div>
                  <div className="text-xs sm:text-sm font-medium text-muted-foreground mb-1.5">Type</div>
                  <Badge variant="outline" className={`${getNotificationTypeColor(selectedNotification.type)} text-xs`}>
                    {selectedNotification.type.toUpperCase()}
                  </Badge>
                </div>
                <div>
                  <div className="text-xs sm:text-sm font-medium text-muted-foreground mb-1.5">Timestamp</div>
                  <div className="text-xs sm:text-sm text-foreground font-mono break-all">
                    {selectedNotification.timestamp}
                  </div>
                </div>
                <div>
                  <div className="text-xs sm:text-sm font-medium text-muted-foreground mb-1.5">Service</div>
                  <div className="text-xs sm:text-sm text-foreground break-words">{selectedNotification.service}</div>
                </div>
                <div>
                  <div className="text-xs sm:text-sm font-medium text-muted-foreground mb-1.5">Source</div>
                  <div className="text-xs sm:text-sm text-foreground break-words">{selectedNotification.source}</div>
                </div>
              </div>
              <div>
                <div className="text-xs sm:text-sm font-medium text-muted-foreground mb-2">Message</div>
                <div className="p-3 sm:p-4 rounded-lg bg-muted/50 border border-border max-h-[180px] sm:max-h-[300px] overflow-y-auto">
                  <pre className="text-xs sm:text-sm text-foreground whitespace-pre-wrap break-all font-mono">
                    {selectedNotification.message}
                  </pre>
                </div>
              </div>
              <div className="flex justify-end pt-2">
                <Button
                  variant="outline"
                  onClick={() => handleDownloadNotificationLog(selectedNotification)}
                  className="border-border w-full sm:w-auto text-xs sm:text-sm h-9 sm:h-10"
                >
                  <Download className="h-3 w-3 sm:h-4 sm:w-4 mr-2" />
                  <span className="truncate">Download Complete Message</span>
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
