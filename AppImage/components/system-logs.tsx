"use client"

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { ScrollArea } from "./ui/scroll-area"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog"
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
  Eye,
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

  const [selectedLog, setSelectedLog] = useState<SystemLog | null>(null)
  const [selectedEvent, setSelectedEvent] = useState<Event | null>(null)
  const [selectedBackup, setSelectedBackup] = useState<Backup | null>(null)
  const [isLogModalOpen, setIsLogModalOpen] = useState(false)
  const [isEventModalOpen, setIsEventModalOpen] = useState(false)
  const [isBackupModalOpen, setIsBackupModalOpen] = useState(false)

  const getApiUrl = (endpoint: string) => {
    if (typeof window !== "undefined") {
      return `${window.location.protocol}//${window.location.hostname}:8008${endpoint}`
    }
    return `http://localhost:8008${endpoint}`
  }

  useEffect(() => {
    fetchAllData()
  }, [])

  const fetchAllData = async () => {
    try {
      setLoading(true)
      setError(null)

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
      const apiUrl = getApiUrl("/api/logs")

      const response = await fetch(apiUrl, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
        cache: "no-store",
      })

      if (!response.ok) {
        throw new Error(`Flask server responded with status: ${response.status}`)
      }

      const data = await response.json()
      return Array.isArray(data) ? data : data.logs || []
    } catch (error) {
      console.error("[v0] Failed to fetch system logs:", error)
      return []
    }
  }

  const handleDownloadLogs = async (type = "system") => {
    try {
      const response = await fetch(getApiUrl(`/api/logs/download?type=${type}&lines=1000`))
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `proxmox_${type}.log`
        document.body.appendChild(a)
        a.click()
        window.URL.revokeObjectURL(url)
        document.body.removeChild(a)
      }
    } catch (err) {
      console.error("[v0] Error downloading logs:", err)
    }
  }

  // Filter logs
  const filteredLogs = logs.filter((log) => {
    const matchesSearch =
      log.message.toLowerCase().includes(searchTerm.toLowerCase()) ||
      log.service.toLowerCase().includes(searchTerm.toLowerCase())
    const matchesLevel = levelFilter === "all" || log.level === levelFilter
    const matchesService = serviceFilter === "all" || log.service === serviceFilter

    return matchesSearch && matchesLevel && matchesService
  })

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

  const logCounts = {
    total: logs.length,
    error: logs.filter((log) => ["error", "critical", "emergency", "alert"].includes(log.level)).length,
    warning: logs.filter((log) => log.level === "warning").length,
    info: logs.filter((log) => ["info", "notice", "debug"].includes(log.level)).length,
  }

  const uniqueServices = [...new Set(logs.map((log) => log.service))]

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

  if (loading && logs.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Statistics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Logs</CardTitle>
            <FileText className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{logCounts.total}</div>
            <p className="text-xs text-muted-foreground mt-2">Last 200 entries</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Errors</CardTitle>
            <XCircle className="h-4 w-4 text-red-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-500">{logCounts.error}</div>
            <p className="text-xs text-muted-foreground mt-2">Requires attention</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Warnings</CardTitle>
            <AlertTriangle className="h-4 w-4 text-yellow-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-yellow-500">{logCounts.warning}</div>
            <p className="text-xs text-muted-foreground mt-2">Monitor closely</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Backups</CardTitle>
            <Database className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-500">{backupStats.total}</div>
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
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="logs">System Logs</TabsTrigger>
              <TabsTrigger value="events">Recent Events</TabsTrigger>
              <TabsTrigger value="backups">Backups</TabsTrigger>
              <TabsTrigger value="notifications">Notifications</TabsTrigger>
            </TabsList>

            {/* System Logs Tab */}
            <TabsContent value="logs" className="space-y-4">
              <div className="flex flex-col sm:flex-row gap-4">
                <div className="flex-1">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Search logs..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="pl-10 bg-background border-border"
                    />
                  </div>
                </div>

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

                <Button
                  variant="outline"
                  className="border-border bg-transparent"
                  onClick={() => handleDownloadLogs("system")}
                >
                  <Download className="h-4 w-4 mr-2" />
                  Export
                </Button>
              </div>

              <ScrollArea className="h-[600px] w-full rounded-md border border-border">
                <div className="space-y-2 p-4">
                  {filteredLogs.map((log, index) => (
                    <div
                      key={index}
                      className="flex items-start space-x-4 p-3 rounded-lg bg-card/50 border border-border/50 hover:bg-card/80 transition-colors cursor-pointer"
                      onClick={() => {
                        setSelectedLog(log)
                        setIsLogModalOpen(true)
                      }}
                    >
                      <div className="flex-shrink-0">
                        <Badge variant="outline" className={getLevelColor(log.level)}>
                          {getLevelIcon(log.level)}
                          {log.level.toUpperCase()}
                        </Badge>
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <div className="text-sm font-medium text-foreground">{log.service}</div>
                          <div className="flex items-center gap-2">
                            <Eye className="h-3 w-3 text-muted-foreground" />
                            <div className="text-xs text-muted-foreground font-mono">{log.timestamp}</div>
                          </div>
                        </div>
                        <div className="text-sm text-foreground mb-1 line-clamp-2">{log.message}</div>
                        <div className="text-xs text-muted-foreground">
                          Source: {log.source}
                          {log.pid && ` • PID: ${log.pid}`}
                          {log.hostname && ` • Host: ${log.hostname}`}
                        </div>
                      </div>
                    </div>
                  ))}

                  {filteredLogs.length === 0 && (
                    <div className="text-center py-8 text-muted-foreground">
                      <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
                      <p>No logs found matching your criteria</p>
                    </div>
                  )}
                </div>
              </ScrollArea>
            </TabsContent>

            {/* Recent Events Tab */}
            <TabsContent value="events" className="space-y-4">
              <ScrollArea className="h-[600px] w-full rounded-md border border-border">
                <div className="space-y-2 p-4">
                  {events.map((event, index) => (
                    <div
                      key={index}
                      className="flex items-start space-x-4 p-3 rounded-lg bg-card/50 border border-border/50 hover:bg-card/80 transition-colors cursor-pointer"
                      onClick={() => {
                        setSelectedEvent(event)
                        setIsEventModalOpen(true)
                      }}
                    >
                      <div className="flex-shrink-0">
                        <Badge variant="outline" className={getLevelColor(event.level)}>
                          {getLevelIcon(event.level)}
                          {event.status}
                        </Badge>
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <div className="text-sm font-medium text-foreground">
                            {event.type}
                            {event.vmid && ` (VM/CT ${event.vmid})`}
                          </div>
                          <div className="flex items-center gap-2">
                            <Eye className="h-3 w-3 text-muted-foreground" />
                            <div className="text-xs text-muted-foreground">{event.duration}</div>
                          </div>
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Node: {event.node} • User: {event.user}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">Started: {event.starttime}</div>
                      </div>
                    </div>
                  ))}

                  {events.length === 0 && (
                    <div className="text-center py-8 text-muted-foreground">
                      <Activity className="h-12 w-12 mx-auto mb-4 opacity-50" />
                      <p>No recent events found</p>
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
                    <div className="text-2xl font-bold text-foreground">{backupStats.qemu}</div>
                    <p className="text-xs text-muted-foreground mt-1">QEMU Backups</p>
                  </CardContent>
                </Card>
                <Card className="bg-card/50 border-border">
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold text-foreground">{backupStats.lxc}</div>
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
                      className="flex items-start space-x-4 p-3 rounded-lg bg-card/50 border border-border/50 hover:bg-card/80 transition-colors cursor-pointer"
                      onClick={() => {
                        setSelectedBackup(backup)
                        setIsBackupModalOpen(true)
                      }}
                    >
                      <div className="flex-shrink-0">
                        <HardDrive className="h-5 w-5 text-blue-500" />
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <div className="text-sm font-medium text-foreground">
                              {backup.volid.includes("/vm/") || backup.volid.includes("vzdump-qemu") ? "QEMU" : "LXC"}
                              {backup.vmid && ` VM ${backup.vmid}`}
                            </div>
                            <Badge variant="outline" className={getBackupStorageColor(backup.volid)}>
                              {getBackupStorageLabel(backup.volid)}
                            </Badge>
                          </div>
                          <div className="flex items-center gap-2">
                            <Eye className="h-3 w-3 text-muted-foreground" />
                            <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">
                              {backup.size_human}
                            </Badge>
                          </div>
                        </div>
                        <div className="text-xs text-muted-foreground mb-1">Storage: {backup.storage}</div>
                        <div className="text-xs text-muted-foreground flex items-center">
                          <Calendar className="h-3 w-3 mr-1" />
                          {backup.created}
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
                      className="flex items-start space-x-4 p-3 rounded-lg bg-card/50 border border-border/50 hover:bg-card/80 transition-colors"
                    >
                      <div className="flex-shrink-0">{getNotificationIcon(notification.type)}</div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <div className="text-sm font-medium text-muted-foreground capitalize">
                            {notification.type}
                          </div>
                          <div className="text-xs text-muted-foreground font-mono">{notification.timestamp}</div>
                        </div>
                        <div className="text-sm text-foreground mb-1">{notification.message}</div>
                        <div className="text-xs text-muted-foreground">
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
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Level</div>
                  <Badge variant="outline" className={getLevelColor(selectedLog.level)}>
                    {getLevelIcon(selectedLog.level)}
                    {selectedLog.level.toUpperCase()}
                  </Badge>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Service</div>
                  <div className="text-sm text-foreground">{selectedLog.service}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Timestamp</div>
                  <div className="text-sm text-foreground font-mono">{selectedLog.timestamp}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Source</div>
                  <div className="text-sm text-foreground">{selectedLog.source}</div>
                </div>
                {selectedLog.pid && (
                  <div>
                    <div className="text-sm font-medium text-muted-foreground mb-1">Process ID</div>
                    <div className="text-sm text-foreground font-mono">{selectedLog.pid}</div>
                  </div>
                )}
                {selectedLog.hostname && (
                  <div>
                    <div className="text-sm font-medium text-muted-foreground mb-1">Hostname</div>
                    <div className="text-sm text-foreground">{selectedLog.hostname}</div>
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
          </DialogHeader>
          {selectedEvent && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Status</div>
                  <Badge variant="outline" className={getLevelColor(selectedEvent.level)}>
                    {getLevelIcon(selectedEvent.level)}
                    {selectedEvent.status}
                  </Badge>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Type</div>
                  <div className="text-sm text-foreground">{selectedEvent.type}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Node</div>
                  <div className="text-sm text-foreground">{selectedEvent.node}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">User</div>
                  <div className="text-sm text-foreground">{selectedEvent.user}</div>
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
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Start Time</div>
                  <div className="text-sm text-foreground">{selectedEvent.starttime}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">End Time</div>
                  <div className="text-sm text-foreground">{selectedEvent.endtime}</div>
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
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Type</div>
                  <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">
                    {selectedBackup.volid.includes("/vm/") || selectedBackup.volid.includes("vzdump-qemu")
                      ? "QEMU"
                      : "LXC"}
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
                  <div className="text-sm text-foreground">{selectedBackup.storage}</div>
                </div>
                {selectedBackup.vmid && (
                  <div>
                    <div className="text-sm font-medium text-muted-foreground mb-1">VM/CT ID</div>
                    <div className="text-sm text-foreground font-mono">{selectedBackup.vmid}</div>
                  </div>
                )}
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Size</div>
                  <div className="text-sm text-foreground font-mono">{selectedBackup.size_human}</div>
                </div>
                <div>
                  <div className="text-sm font-medium text-muted-foreground mb-1">Created</div>
                  <div className="text-sm text-foreground">{selectedBackup.created}</div>
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
    </div>
  )
}
