"use client"

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { ScrollArea } from "./ui/scroll-area"
import { FileText, Search, Download, AlertTriangle, Info, CheckCircle, XCircle } from "lucide-react"
import { useState } from "react"

const systemLogs = [
  {
    timestamp: "2024-01-15 14:32:15",
    level: "info",
    service: "pveproxy",
    message: "User root@pam authenticated successfully",
    source: "auth.log",
  },
  {
    timestamp: "2024-01-15 14:31:45",
    level: "warning",
    service: "pvedaemon",
    message: "VM 101 high memory usage detected (85%)",
    source: "syslog",
  },
  {
    timestamp: "2024-01-15 14:30:22",
    level: "error",
    service: "pve-cluster",
    message: "Failed to connect to cluster node pve-02",
    source: "cluster.log",
  },
  {
    timestamp: "2024-01-15 14:29:18",
    level: "info",
    service: "pvestatd",
    message: "Storage local: 1.25TB used, 750GB available",
    source: "syslog",
  },
  {
    timestamp: "2024-01-15 14:28:33",
    level: "info",
    service: "pve-firewall",
    message: "Blocked connection attempt from 192.168.1.50",
    source: "firewall.log",
  },
  {
    timestamp: "2024-01-15 14:27:45",
    level: "warning",
    service: "smartd",
    message: "SMART warning: /dev/nvme0n1 temperature high (55°C)",
    source: "smart.log",
  },
  {
    timestamp: "2024-01-15 14:26:12",
    level: "info",
    service: "pveproxy",
    message: "Started backup job for VM 100",
    source: "backup.log",
  },
  {
    timestamp: "2024-01-15 14:25:38",
    level: "error",
    service: "qemu-server",
    message: "VM 102 failed to start: insufficient memory",
    source: "qemu.log",
  },
  {
    timestamp: "2024-01-15 14:24:55",
    level: "info",
    service: "pvedaemon",
    message: "VM 103 migrated successfully to node pve-01",
    source: "migration.log",
  },
  {
    timestamp: "2024-01-15 14:23:17",
    level: "warning",
    service: "pve-ha-lrm",
    message: "Resource VM:104 state changed to error",
    source: "ha.log",
  },
]

export function SystemLogs() {
  const [searchTerm, setSearchTerm] = useState("")
  const [levelFilter, setLevelFilter] = useState("all")
  const [serviceFilter, setServiceFilter] = useState("all")

  const filteredLogs = systemLogs.filter((log) => {
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
        return "bg-red-500/10 text-red-500 border-red-500/20"
      case "warning":
        return "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
      case "info":
        return "bg-blue-500/10 text-blue-500 border-blue-500/20"
      default:
        return "bg-gray-500/10 text-gray-500 border-gray-500/20"
    }
  }

  const getLevelIcon = (level: string) => {
    switch (level) {
      case "error":
        return <XCircle className="h-3 w-3 mr-1" />
      case "warning":
        return <AlertTriangle className="h-3 w-3 mr-1" />
      case "info":
        return <Info className="h-3 w-3 mr-1" />
      default:
        return <CheckCircle className="h-3 w-3 mr-1" />
    }
  }

  const logCounts = {
    total: systemLogs.length,
    error: systemLogs.filter((log) => log.level === "error").length,
    warning: systemLogs.filter((log) => log.level === "warning").length,
    info: systemLogs.filter((log) => log.level === "info").length,
  }

  const uniqueServices = [...new Set(systemLogs.map((log) => log.service))]

  return (
    <div className="space-y-6">
      {/* Log Statistics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Logs</CardTitle>
            <FileText className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{logCounts.total}</div>
            <p className="text-xs text-muted-foreground mt-2">Last 24 hours</p>
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
            <CardTitle className="text-sm font-medium text-muted-foreground">Info</CardTitle>
            <Info className="h-4 w-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-500">{logCounts.info}</div>
            <p className="text-xs text-muted-foreground mt-2">Normal operations</p>
          </CardContent>
        </Card>
      </div>

      {/* Log Filters and Search */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-foreground flex items-center">
            <FileText className="h-5 w-5 mr-2" />
            System Logs
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col sm:flex-row gap-4 mb-6">
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
                {uniqueServices.map((service) => (
                  <SelectItem key={service} value={service}>
                    {service}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Button variant="outline" className="border-border bg-transparent">
              <Download className="h-4 w-4 mr-2" />
              Export
            </Button>
          </div>

          <ScrollArea className="h-[600px] w-full rounded-md border border-border">
            <div className="space-y-2 p-4">
              {filteredLogs.map((log, index) => (
                <div
                  key={index}
                  className="flex items-start space-x-4 p-3 rounded-lg bg-card/50 border border-border/50"
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
                      <div className="text-xs text-muted-foreground font-mono">{log.timestamp}</div>
                    </div>
                    <div className="text-sm text-foreground mb-1">{log.message}</div>
                    <div className="text-xs text-muted-foreground">Source: {log.source}</div>
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
        </CardContent>
      </Card>
    </div>
  )
}
