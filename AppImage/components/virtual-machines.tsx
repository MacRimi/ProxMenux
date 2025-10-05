"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Progress } from "./ui/progress"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog"
import {
  Server,
  Play,
  Square,
  Monitor,
  Cpu,
  MemoryStick,
  AlertCircle,
  HardDrive,
  Network,
  Power,
  RotateCcw,
  Download,
  StopCircle,
} from "lucide-react"
import useSWR from "swr"

interface VMData {
  vmid: number
  name: string
  status: string
  type: string
  cpu: number
  mem: number
  maxmem: number
  disk: number
  maxdisk: number
  uptime: number
  netin?: number
  netout?: number
  diskread?: number
  diskwrite?: number
}

const fetcher = async (url: string) => {
  const response = await fetch(url, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
    signal: AbortSignal.timeout(5000),
  })

  if (!response.ok) {
    throw new Error(`Flask server responded with status: ${response.status}`)
  }

  const data = await response.json()
  return Array.isArray(data) ? data : []
}

const formatBytes = (bytes: number | undefined): string => {
  if (!bytes || bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

export function VirtualMachines() {
  const {
    data: vmData,
    error,
    isLoading,
    mutate,
  } = useSWR<VMData[]>("/api/vms", fetcher, {
    refreshInterval: 30000, // Refresh every 30 seconds
    revalidateOnFocus: false,
    revalidateOnReconnect: true,
  })

  const [selectedVM, setSelectedVM] = useState<VMData | null>(null)
  const [controlLoading, setControlLoading] = useState(false)

  const handleVMControl = async (vmid: number, action: string) => {
    setControlLoading(true)
    try {
      const response = await fetch(`/api/vms/${vmid}/control`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action }),
      })

      if (response.ok) {
        // Refresh VM data after action
        mutate()
        setSelectedVM(null)
      } else {
        console.error("Failed to control VM")
      }
    } catch (error) {
      console.error("Error controlling VM:", error)
    } finally {
      setControlLoading(false)
    }
  }

  const handleDownloadLogs = async (vmid: number) => {
    try {
      const response = await fetch(`/api/vms/${vmid}/logs`)
      if (response.ok) {
        const data = await response.json()
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `vm-${vmid}-logs.json`
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Error downloading logs:", error)
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8">
          <div className="text-lg font-medium text-foreground mb-2">Loading VM data...</div>
        </div>
      </div>
    )
  }

  if (error || !vmData) {
    return (
      <div className="space-y-6">
        <Card className="bg-red-500/10 border-red-500/20">
          <CardContent className="p-6">
            <div className="flex items-center gap-3 text-red-600">
              <AlertCircle className="h-6 w-6" />
              <div>
                <div className="font-semibold text-lg mb-1">Flask Server Not Available</div>
                <div className="text-sm">
                  {error?.message ||
                    "Unable to connect to the Flask server. Please ensure the server is running and try again."}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const runningVMs = vmData.filter((vm) => vm.status === "running").length
  const stoppedVMs = vmData.filter((vm) => vm.status === "stopped").length
  const totalCPU = vmData.reduce((sum, vm) => sum + (vm.cpu || 0), 0)
  const totalMemory = vmData.reduce((sum, vm) => sum + (vm.maxmem || 0), 0)

  const getStatusColor = (status: string) => {
    switch (status) {
      case "running":
        return "bg-green-500/10 text-green-500 border-green-500/20"
      case "stopped":
        return "bg-red-500/10 text-red-500 border-red-500/20"
      default:
        return "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "running":
        return <Play className="h-3 w-3 mr-1" />
      case "stopped":
        return <Square className="h-3 w-3 mr-1" />
      default:
        return null
    }
  }

  const getTypeBadge = (type: string) => {
    if (type === "lxc") {
      return { color: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20", label: "LXC" }
    }
    return { color: "bg-purple-500/10 text-purple-500 border-purple-500/20", label: "VM" }
  }

  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / 86400)
    const hours = Math.floor((seconds % 86400) / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `${days}d ${hours}h ${minutes}m`
  }

  return (
    <div className="space-y-6">
      {/* VM Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total VMs & LXCs</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{vmData.length}</div>
            <div className="vm-badges mt-2">
              <Badge variant="outline" className="vm-badge bg-green-500/10 text-green-500 border-green-500/20">
                {runningVMs} Running
              </Badge>
              <Badge variant="outline" className="vm-badge bg-red-500/10 text-red-500 border-red-500/20">
                {stoppedVMs} Stopped
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Virtual machines configured</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total CPU</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{(totalCPU * 100).toFixed(0)}%</div>
            <p className="text-xs text-muted-foreground mt-2">Allocated CPU usage</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Memory</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{(totalMemory / 1024 ** 3).toFixed(1)} GB</div>
            <p className="text-xs text-muted-foreground mt-2">Allocated RAM</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Average Load</CardTitle>
            <Monitor className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">
              {runningVMs > 0 ? ((totalCPU / runningVMs) * 100).toFixed(0) : 0}%
            </div>
            <p className="text-xs text-muted-foreground mt-2">Average resource utilization</p>
          </CardContent>
        </Card>
      </div>

      {/* Virtual Machines List */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-foreground flex items-center">
            <Server className="h-5 w-5 mr-2" />
            Virtual Machines & Containers
          </CardTitle>
        </CardHeader>
        <CardContent>
          {vmData.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">No virtual machines found</div>
          ) : (
            <div className="space-y-4">
              {vmData.map((vm) => {
                const cpuPercent = (vm.cpu * 100).toFixed(1)
                const memPercent = vm.maxmem > 0 ? ((vm.mem / vm.maxmem) * 100).toFixed(1) : "0"
                const memGB = (vm.mem / 1024 ** 3).toFixed(1)
                const maxMemGB = (vm.maxmem / 1024 ** 3).toFixed(1)
                const typeBadge = getTypeBadge(vm.type)

                return (
                  <div
                    key={vm.vmid}
                    className="p-6 rounded-lg border border-border bg-card/50 hover:bg-card/80 transition-colors cursor-pointer"
                    onClick={() => setSelectedVM(vm)}
                  >
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center space-x-4">
                        <Server className="h-6 w-6 text-muted-foreground" />
                        <div>
                          <div className="font-semibold text-foreground text-lg flex items-center">
                            {vm.name}
                            <Badge variant="outline" className={`ml-2 text-xs ${typeBadge.color}`}>
                              {typeBadge.label}
                            </Badge>
                          </div>
                          <div className="text-sm text-muted-foreground">ID: {vm.vmid}</div>
                        </div>
                      </div>

                      <div className="flex items-center space-x-3">
                        <Badge variant="outline" className={getStatusColor(vm.status)}>
                          {getStatusIcon(vm.status)}
                          {vm.status.toUpperCase()}
                        </Badge>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                      <div>
                        <div className="text-sm text-muted-foreground mb-2">CPU Usage</div>
                        <div className="text-lg font-semibold text-foreground mb-1">{cpuPercent}%</div>
                        <Progress value={Number.parseFloat(cpuPercent)} className="h-2 [&>div]:bg-blue-500" />
                      </div>

                      <div>
                        <div className="text-sm text-muted-foreground mb-2">Memory Usage</div>
                        <div className="text-lg font-semibold text-foreground mb-1">
                          {memGB} / {maxMemGB} GB
                        </div>
                        <Progress value={Number.parseFloat(memPercent)} className="h-2 [&>div]:bg-blue-500" />
                      </div>

                      <div>
                        <div className="text-sm text-muted-foreground mb-2">Disk I/O</div>
                        <div className="text-sm font-semibold text-foreground">
                          <div className="flex items-center gap-1">
                            <HardDrive className="h-3 w-3 text-green-500" />
                            <span className="text-green-500">↓ {formatBytes(vm.diskread)}</span>
                          </div>
                          <div className="flex items-center gap-1 mt-1">
                            <HardDrive className="h-3 w-3 text-blue-500" />
                            <span className="text-blue-500">↑ {formatBytes(vm.diskwrite)}</span>
                          </div>
                        </div>
                      </div>

                      <div>
                        <div className="text-sm text-muted-foreground mb-2">Network I/O</div>
                        <div className="text-sm font-semibold text-foreground">
                          <div className="flex items-center gap-1">
                            <Network className="h-3 w-3 text-green-500" />
                            <span className="text-green-500">↓ {formatBytes(vm.netin)}</span>
                          </div>
                          <div className="flex items-center gap-1 mt-1">
                            <Network className="h-3 w-3 text-blue-500" />
                            <span className="text-blue-500">↑ {formatBytes(vm.netout)}</span>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="mt-4 pt-4 border-t border-border">
                      <div className="text-sm text-muted-foreground">Uptime</div>
                      <div className="text-lg font-semibold text-foreground">{formatUptime(vm.uptime)}</div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* VM Details Modal */}
      <Dialog open={!!selectedVM} onOpenChange={() => setSelectedVM(null)}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Server className="h-5 w-5" />
              {selectedVM?.name} - Details
            </DialogTitle>
          </DialogHeader>

          {selectedVM && (
            <div className="space-y-6">
              {/* Basic Information */}
              <div>
                <h3 className="text-sm font-semibold text-muted-foreground mb-3">Basic Information</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-sm text-muted-foreground">Name</div>
                    <div className="font-medium">{selectedVM.name}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Type</div>
                    <Badge variant="outline" className={getTypeBadge(selectedVM.type).color}>
                      {getTypeBadge(selectedVM.type).label}
                    </Badge>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">VMID</div>
                    <div className="font-medium">{selectedVM.vmid}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Status</div>
                    <Badge variant="outline" className={getStatusColor(selectedVM.status)}>
                      {selectedVM.status.toUpperCase()}
                    </Badge>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">CPU Usage</div>
                    <div className="font-medium">{(selectedVM.cpu * 100).toFixed(1)}%</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Memory</div>
                    <div className="font-medium">
                      {(selectedVM.mem / 1024 ** 3).toFixed(1)} / {(selectedVM.maxmem / 1024 ** 3).toFixed(1)} GB
                    </div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Disk</div>
                    <div className="font-medium">
                      {(selectedVM.disk / 1024 ** 3).toFixed(1)} / {(selectedVM.maxdisk / 1024 ** 3).toFixed(1)} GB
                    </div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Uptime</div>
                    <div className="font-medium">{formatUptime(selectedVM.uptime)}</div>
                  </div>
                </div>
              </div>

              {/* Control Actions */}
              <div>
                <h3 className="text-sm font-semibold text-muted-foreground mb-3">Control Actions</h3>
                <div className="grid grid-cols-2 gap-3">
                  <Button
                    variant="outline"
                    className="w-full bg-transparent"
                    disabled={selectedVM.status === "running" || controlLoading}
                    onClick={() => handleVMControl(selectedVM.vmid, "start")}
                  >
                    <Play className="h-4 w-4 mr-2" />
                    Start
                  </Button>
                  <Button
                    variant="outline"
                    className="w-full bg-transparent"
                    disabled={selectedVM.status !== "running" || controlLoading}
                    onClick={() => handleVMControl(selectedVM.vmid, "shutdown")}
                  >
                    <Power className="h-4 w-4 mr-2" />
                    Shutdown
                  </Button>
                  <Button
                    variant="outline"
                    className="w-full bg-transparent"
                    disabled={selectedVM.status !== "running" || controlLoading}
                    onClick={() => handleVMControl(selectedVM.vmid, "reboot")}
                  >
                    <RotateCcw className="h-4 w-4 mr-2" />
                    Reboot
                  </Button>
                  <Button
                    variant="outline"
                    className="w-full bg-transparent"
                    disabled={selectedVM.status !== "running" || controlLoading}
                    onClick={() => handleVMControl(selectedVM.vmid, "stop")}
                  >
                    <StopCircle className="h-4 w-4 mr-2" />
                    Force Stop
                  </Button>
                </div>
              </div>

              {/* Download Logs */}
              <div>
                <Button
                  variant="outline"
                  className="w-full bg-transparent"
                  onClick={() => handleDownloadLogs(selectedVM.vmid)}
                >
                  <Download className="h-4 w-4 mr-2" />
                  Download Logs
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
