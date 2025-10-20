"use client"

import { useState, useMemo, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Progress } from "./ui/progress"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog"
import {
  Server,
  Play,
  Square,
  Cpu,
  MemoryStick,
  HardDrive,
  Network,
  Power,
  RotateCcw,
  StopCircle,
  Container,
} from "lucide-react"
import useSWR from "swr"
import { MetricsDialog } from "./metrics-dialog" // Import MetricsDialog

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
  ip?: string
}

interface VMConfig {
  cores?: number
  memory?: number
  swap?: number
  rootfs?: string
  net0?: string
  net1?: string
  net2?: string
  nameserver?: string
  searchdomain?: string
  onboot?: number
  unprivileged?: number
  features?: string
  ostype?: string
  arch?: string
  hostname?: string
  // VM specific
  sockets?: number
  scsi0?: string
  ide0?: string
  boot?: string
  [key: string]: any
}

interface VMDetails extends VMData {
  config?: VMConfig
  node?: string
  vm_type?: string
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
  return data
}

const formatBytes = (bytes: number | undefined): string => {
  if (!bytes || bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

const formatUptime = (seconds: number) => {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${days}d ${hours}h ${minutes}m`
}

const extractIPFromConfig = (config?: VMConfig): string => {
  if (!config) return "DHCP"

  // Check net0, net1, net2, etc.
  for (let i = 0; i < 10; i++) {
    const netKey = `net${i}`
    const netConfig = config[netKey]

    if (netConfig && typeof netConfig === "string") {
      // Look for ip=x.x.x.x/xx or ip=x.x.x.x pattern
      const ipMatch = netConfig.match(/ip=([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})/)
      if (ipMatch) {
        return ipMatch[1] // Return just the IP without CIDR
      }

      // Check if it's explicitly DHCP
      if (netConfig.includes("ip=dhcp")) {
        return "DHCP"
      }
    }
  }

  return "DHCP"
}

const formatStorage = (sizeInGB: number): string => {
  if (sizeInGB < 1) {
    // Less than 1 GB, show in MB
    return `${(sizeInGB * 1024).toFixed(1)} MB`
  } else if (sizeInGB < 1024) {
    // Less than 1024 GB, show in GB
    return `${sizeInGB.toFixed(1)} GB`
  } else {
    // 1024 GB or more, show in TB
    return `${(sizeInGB / 1024).toFixed(1)} TB`
  }
}

const getUsageColor = (percent: number): string => {
  if (percent >= 95) return "text-red-500"
  if (percent >= 86) return "text-orange-500"
  if (percent >= 71) return "text-yellow-500"
  return "text-white"
}

const getIconColor = (percent: number): string => {
  if (percent >= 95) return "text-red-500"
  if (percent >= 86) return "text-orange-500"
  if (percent >= 71) return "text-yellow-500"
  return "text-green-500"
}

const getProgressColor = (percent: number): string => {
  if (percent >= 95) return "[&>div]:bg-red-500"
  if (percent >= 86) return "[&>div]:bg-orange-500"
  if (percent >= 71) return "[&>div]:bg-yellow-500"
  return "[&>div]:bg-blue-500"
}

const getModalProgressColor = (percent: number): string => {
  if (percent >= 95) return "[&>div]:bg-red-500"
  if (percent >= 86) return "[&>div]:bg-orange-500"
  if (percent >= 71) return "[&>div]:bg-yellow-500"
  return "[&>div]:bg-blue-500"
}

export function VirtualMachines() {
  const {
    data: vmData,
    error,
    isLoading,
    mutate,
  } = useSWR<VMData[]>("/api/vms", fetcher, {
    refreshInterval: 30000,
    revalidateOnFocus: false,
    revalidateOnReconnect: true,
  })

  const [selectedVM, setSelectedVM] = useState<VMData | null>(null)
  const [vmDetails, setVMDetails] = useState<VMDetails | null>(null)
  const [controlLoading, setControlLoading] = useState(false)
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [vmConfigs, setVmConfigs] = useState<Record<number, string>>({})
  const [currentView, setCurrentView] = useState<"main" | "metrics">("main")
  const [selectedMetric, setSelectedMetric] = useState<"cpu" | "memory" | "disk" | "network" | null>(null)

  useEffect(() => {
    const fetchLXCIPs = async () => {
      if (!vmData) return

      const lxcs = vmData.filter((vm) => vm.type === "lxc")
      const configs: Record<number, string> = {}

      await Promise.all(
        lxcs.map(async (lxc) => {
          try {
            const response = await fetch(`/api/vms/${lxc.vmid}`)
            if (response.ok) {
              const details = await response.json()
              if (details.config) {
                configs[lxc.vmid] = extractIPFromConfig(details.config)
              }
            }
          } catch (error) {
            console.error(`Error fetching config for LXC ${lxc.vmid}:`, error)
          }
        }),
      )

      setVmConfigs(configs)
    }

    fetchLXCIPs()
  }, [vmData])

  const handleVMClick = async (vm: VMData) => {
    setSelectedVM(vm)
    setCurrentView("main")
    setSelectedMetric(null)
    setDetailsLoading(true)
    try {
      const response = await fetch(`/api/vms/${vm.vmid}`)
      if (response.ok) {
        const details = await response.json()
        setVMDetails(details)
      }
    } catch (error) {
      console.error("Error fetching VM details:", error)
    } finally {
      setDetailsLoading(false)
    }
  }

  const handleMetricClick = (metric: "cpu" | "memory" | "disk" | "network") => {
    setSelectedMetric(metric)
    setCurrentView("metrics")
  }

  const handleBackToMain = () => {
    setCurrentView("main")
    setSelectedMetric(null)
  }

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
        mutate()
        setSelectedVM(null)
        setVMDetails(null)
      } else {
        console.error("Failed to control VM")
      }
    } catch (error) {
      console.error("Error controlling VM:", error)
    } finally {
      setControlLoading(false)
    }
  }

  const handleDownloadLogs = async (vmid: number, vmName: string) => {
    try {
      const response = await fetch(`/api/vms/${vmid}/logs`)
      if (response.ok) {
        const data = await response.json()

        // Format logs as plain text
        let logText = `=== Logs for ${vmName} (VMID: ${vmid}) ===\n`
        logText += `Node: ${data.node}\n`
        logText += `Type: ${data.type}\n`
        logText += `Total lines: ${data.log_lines}\n`
        logText += `Generated: ${new Date().toISOString()}\n`
        logText += `\n${"=".repeat(80)}\n\n`

        if (data.logs && Array.isArray(data.logs)) {
          data.logs.forEach((log: any) => {
            if (typeof log === "object" && log.t) {
              logText += `${log.t}\n`
            } else if (typeof log === "string") {
              logText += `${log}\n`
            }
          })
        }

        const blob = new Blob([logText], { type: "text/plain" })
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `${vmName}-${vmid}-logs.txt`
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Error downloading logs:", error)
    }
  }

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
        return <Play className="h-3 w-3" />
      case "stopped":
        return <Square className="h-3 w-3" />
      default:
        return null
    }
  }

  const getTypeBadge = (type: string) => {
    if (type === "lxc") {
      return {
        color: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
        label: "LXC",
        icon: <Container className="h-3 w-3 mr-1" />,
      }
    }
    return {
      color: "bg-purple-500/10 text-purple-500 border-purple-500/20",
      label: "VM",
      icon: <Server className="h-3 w-3 mr-1" />,
    }
  }

  const safeVMData = vmData || []

  const totalAllocatedMemoryGB = useMemo(() => {
    return (safeVMData.reduce((sum, vm) => sum + (vm.maxmem || 0), 0) / 1024 ** 3).toFixed(1)
  }, [safeVMData])

  const { data: systemData } = useSWR<{ memory_total: number; memory_used: number; memory_usage: number }>(
    "/api/system",
    fetcher,
    {
      refreshInterval: 30000,
      revalidateOnFocus: false,
    },
  )

  const physicalMemoryGB = systemData?.memory_total ?? null
  const usedMemoryGB = systemData?.memory_used ?? null
  const memoryUsagePercent = systemData?.memory_usage ?? null
  const allocatedMemoryGB = Number.parseFloat(totalAllocatedMemoryGB)
  const isMemoryOvercommit = physicalMemoryGB !== null && allocatedMemoryGB > physicalMemoryGB

  const getMemoryUsageColor = (percent: number | null) => {
    if (percent === null) return "bg-blue-500"
    if (percent >= 95) return "bg-red-500"
    if (percent >= 86) return "bg-orange-500"
    if (percent >= 71) return "bg-yellow-500"
    return "bg-blue-500"
  }

  const getMemoryPercentTextColor = (percent: number | null) => {
    if (percent === null) return "text-muted-foreground"
    if (percent >= 95) return "text-red-500"
    if (percent >= 86) return "text-orange-500"
    if (percent >= 71) return "text-yellow-500"
    return "text-green-500"
  }

  console.log("[v0] Memory status:", {
    physical: physicalMemoryGB,
    allocated: allocatedMemoryGB,
    isOvercommit: isMemoryOvercommit,
  })

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8 text-muted-foreground">Loading virtual machines...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8 text-red-500">Error loading virtual machines: {error.message}</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total VMs & LXCs</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">{safeVMData.length}</div>
            <div className="vm-badges mt-2">
              <Badge variant="outline" className="vm-badge bg-green-500/10 text-green-500 border-green-500/20">
                {safeVMData.filter((vm) => vm.status === "running").length} Running
              </Badge>
              <Badge variant="outline" className="vm-badge bg-red-500/10 text-red-500 border-red-500/20">
                {safeVMData.filter((vm) => vm.status === "stopped").length} Stopped
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
            <div className="text-xl lg:text-2xl font-bold text-foreground">
              {(safeVMData.reduce((sum, vm) => sum + (vm.cpu || 0), 0) * 100).toFixed(0)}%
            </div>
            <p className="text-xs text-muted-foreground mt-2">Allocated CPU usage</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Memory</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Memory Usage (current) */}
            {physicalMemoryGB !== null && usedMemoryGB !== null && memoryUsagePercent !== null ? (
              <div>
                <div className="text-xl lg:text-2xl font-bold text-foreground">{usedMemoryGB.toFixed(1)} GB</div>
                <div className="text-xs text-muted-foreground mt-1">
                  <span className={getMemoryPercentTextColor(memoryUsagePercent)}>
                    {memoryUsagePercent.toFixed(1)}%
                  </span>{" "}
                  of {physicalMemoryGB.toFixed(1)} GB
                </div>
                <Progress value={memoryUsagePercent} className="h-2 [&>div]:bg-blue-500" />
              </div>
            ) : (
              <div>
                <div className="text-xl lg:text-2xl font-bold text-muted-foreground">--</div>
                <div className="text-xs text-muted-foreground mt-1">Loading memory usage...</div>
              </div>
            )}

            {/* Allocated RAM (configured) */}
            <div className="pt-3 border-t border-border">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-lg font-semibold text-foreground">{totalAllocatedMemoryGB} GB</div>
                  <div className="text-xs text-muted-foreground">Allocated RAM</div>
                </div>
                {physicalMemoryGB !== null && (
                  <div>
                    {isMemoryOvercommit ? (
                      <Badge variant="outline" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                        Exceeds Physical
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                        Within Limits
                      </Badge>
                    )}
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Disk</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">
              {formatStorage(safeVMData.reduce((sum, vm) => sum + (vm.maxdisk || 0), 0) / 1024 ** 3)}
            </div>
            <p className="text-xs text-muted-foreground mt-2">Allocated disk space</p>
          </CardContent>
        </Card>
      </div>

      <Card className="bg-card border-border">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-xl lg:text-2xl font-bold text-foreground">
            <Server className="h-6 w-6" />
            Virtual Machines & Containers
          </CardTitle>
        </CardHeader>
        <CardContent>
          {safeVMData.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">No virtual machines found</div>
          ) : (
            <div className="space-y-3">
              {safeVMData.map((vm) => {
                const cpuPercent = (vm.cpu * 100).toFixed(1)
                const memPercent = vm.maxmem > 0 ? ((vm.mem / vm.maxmem) * 100).toFixed(1) : "0"
                const memGB = (vm.mem / 1024 ** 3).toFixed(1)
                const maxMemGB = (vm.maxmem / 1024 ** 3).toFixed(1)
                const diskPercent = vm.maxdisk > 0 ? ((vm.disk / vm.maxdisk) * 100).toFixed(1) : "0"
                const diskGB = (vm.disk / 1024 ** 3).toFixed(1)
                const maxDiskGB = (vm.maxdisk / 1024 ** 3).toFixed(1)
                const typeBadge = getTypeBadge(vm.type)
                const lxcIP = vm.type === "lxc" ? vmConfigs[vm.vmid] : null

                return (
                  <div key={vm.vmid}>
                    <div
                      className="hidden sm:block p-4 rounded-lg border border-border bg-card hover:bg-white/5 dark:hover:bg-white/5 transition-colors cursor-pointer"
                      onClick={() => handleVMClick(vm)}
                    >
                      <div className="flex items-center gap-2 flex-wrap mb-3">
                        <Badge variant="outline" className={`text-xs flex-shrink-0 ${getStatusColor(vm.status)}`}>
                          {getStatusIcon(vm.status)}
                          {vm.status.toUpperCase()}
                        </Badge>
                        <Badge variant="outline" className={`text-xs flex-shrink-0 ${typeBadge.color}`}>
                          {typeBadge.icon}
                          {typeBadge.label}
                        </Badge>
                        <div className="flex-1 min-w-0">
                          <div className="font-semibold text-foreground truncate">{vm.name}</div>
                          <div className="text-[10px] text-muted-foreground">ID: {vm.vmid}</div>
                        </div>
                        {lxcIP && (
                          <span className={`text-sm ${lxcIP === "DHCP" ? "text-yellow-500" : "text-green-500"}`}>
                            IP: {lxcIP}
                          </span>
                        )}
                        <span className="text-sm text-muted-foreground ml-auto">Uptime: {formatUptime(vm.uptime)}</span>
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                        <div>
                          <div className="text-xs text-muted-foreground mb-1">CPU Usage</div>
                          <div
                            className="cursor-pointer hover:opacity-80 transition-opacity"
                            onClick={() => {
                              setSelectedMetric("cpu")
                            }}
                          >
                            <div
                              className={`text-sm font-semibold mb-1 ${getUsageColor(Number.parseFloat(cpuPercent))}`}
                            >
                              {cpuPercent}%
                            </div>
                            <Progress
                              value={Number.parseFloat(cpuPercent)}
                              className={`h-1.5 ${getProgressColor(Number.parseFloat(cpuPercent))}`}
                            />
                          </div>
                        </div>

                        <div>
                          <div className="text-xs text-muted-foreground mb-1">Memory</div>
                          <div
                            className="cursor-pointer hover:opacity-80 transition-opacity"
                            onClick={() => {
                              setSelectedMetric("memory")
                            }}
                          >
                            <div
                              className={`text-sm font-semibold mb-1 ${getUsageColor(Number.parseFloat(memPercent))}`}
                            >
                              {memGB} / {maxMemGB} GB
                            </div>
                            <Progress
                              value={Number.parseFloat(memPercent)}
                              className={`h-1.5 ${getProgressColor(Number.parseFloat(memPercent))}`}
                            />
                          </div>
                        </div>

                        <div>
                          <div className="text-xs text-muted-foreground mb-1">Disk Usage</div>
                          <div
                            className="cursor-pointer hover:opacity-80 transition-opacity"
                            onClick={() => {
                              setSelectedMetric("disk")
                            }}
                          >
                            <div
                              className={`text-sm font-semibold mb-1 ${getUsageColor(Number.parseFloat(diskPercent))}`}
                            >
                              {diskGB} / {maxDiskGB} GB
                            </div>
                            <Progress
                              value={Number.parseFloat(diskPercent)}
                              className={`h-1.5 ${getProgressColor(Number.parseFloat(diskPercent))}`}
                            />
                          </div>
                        </div>

                        <div className="hidden md:block">
                          <div className="text-xs text-muted-foreground mb-1">Disk I/O</div>
                          <div className="text-sm font-semibold space-y-0.5">
                            <div className="flex items-center gap-1">
                              <HardDrive className="h-3 w-3 text-green-500" />
                              <span className="text-green-500">↓ {formatBytes(vm.diskread)}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <HardDrive className="h-3 w-3 text-blue-500" />
                              <span className="text-blue-500">↑ {formatBytes(vm.diskwrite)}</span>
                            </div>
                          </div>
                        </div>

                        <div>
                          <div className="text-xs text-muted-foreground mb-1">Network I/O</div>
                          <div className="text-sm font-semibold space-y-0.5">
                            <div className="flex items-center gap-1">
                              <Network className="h-3 w-3 text-green-500" />
                              <span className="text-green-500">↓ {formatBytes(vm.netin)}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Network className="h-3 w-3 text-blue-500" />
                              <span className="text-blue-500">↑ {formatBytes(vm.netout)}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div
                      className="sm:hidden p-4 rounded-lg border border-white/10 bg-white/5 dark:bg-white/5 transition-colors cursor-pointer"
                      onClick={() => handleVMClick(vm)}
                    >
                      <div className="flex items-center gap-3">
                        {vm.status === "running" ? (
                          <Play className="h-5 w-5 text-green-500 fill-current flex-shrink-0" />
                        ) : (
                          <Square className="h-5 w-5 text-red-500 fill-current flex-shrink-0" />
                        )}

                        <Badge variant="outline" className={`${getTypeBadge(vm.type).color} flex-shrink-0`}>
                          {getTypeBadge(vm.type).label}
                        </Badge>

                        {/* Name and ID */}
                        <div className="flex-1 min-w-0">
                          <div className="font-semibold text-foreground truncate">{vm.name}</div>
                          <div className="text-[10px] text-muted-foreground">ID: {vm.vmid}</div>
                        </div>

                        <div className="flex items-center gap-3 flex-shrink-0">
                          {/* CPU icon with percentage */}
                          <div className="flex flex-col items-center gap-0.5">
                            {vm.status === "running" && (
                              <span className="text-[10px] font-medium text-muted-foreground">{cpuPercent}%</span>
                            )}
                            <Cpu
                              className={`h-4 w-4 ${
                                vm.status === "stopped" ? "text-gray-500" : getIconColor(Number.parseFloat(cpuPercent))
                              }`}
                            />
                          </div>

                          {/* Memory icon with percentage */}
                          <div className="flex flex-col items-center gap-0.5">
                            {vm.status === "running" && (
                              <span className="text-[10px] font-medium text-muted-foreground">{memPercent}%</span>
                            )}
                            <MemoryStick
                              className={`h-4 w-4 ${
                                vm.status === "stopped" ? "text-gray-500" : getIconColor(Number.parseFloat(memPercent))
                              }`}
                            />
                          </div>

                          {/* Disk icon with percentage */}
                          <div className="flex flex-col items-center gap-0.5">
                            {vm.status === "running" && (
                              <span className="text-[10px] font-medium text-muted-foreground">{diskPercent}%</span>
                            )}
                            <HardDrive
                              className={`h-4 w-4 ${
                                vm.status === "stopped" ? "text-gray-500" : getIconColor(Number.parseFloat(diskPercent))
                              }`}
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={!!selectedVM}
        onOpenChange={() => {
          setSelectedVM(null)
          setVMDetails(null)
          setCurrentView("main")
          setSelectedMetric(null)
        }}
      >
        <DialogContent className="max-w-4xl max-h-[95vh] p-0 flex flex-col overflow-hidden">
          {currentView === "main" ? (
            <>
              <DialogHeader className="pb-4 border-b border-border px-6 pt-6 flex-shrink-0">
                <DialogTitle className="flex flex-col sm:flex-row sm:items-center gap-3">
                  {/* Desktop layout */}
                  <div className="hidden sm:flex items-center gap-3 flex-wrap">
                    <div className="flex items-center gap-2">
                      <Server className="h-5 w-5 flex-shrink-0" />
                      <span className="text-lg truncate">{selectedVM?.name}</span>
                      <span className="text-sm text-muted-foreground">ID: {selectedVM?.vmid}</span>
                    </div>
                    {selectedVM && (
                      <>
                        <Badge variant="outline" className={`${getTypeBadge(selectedVM.type).color} flex-shrink-0`}>
                          {getTypeBadge(selectedVM.type).icon}
                          {getTypeBadge(selectedVM.type).label}
                        </Badge>
                        <Badge variant="outline" className={`${getStatusColor(selectedVM.status)} flex-shrink-0`}>
                          {selectedVM.status.toUpperCase()}
                        </Badge>
                        {selectedVM.status === "running" && (
                          <span className="text-sm text-muted-foreground">
                            Uptime: {formatUptime(selectedVM.uptime)}
                          </span>
                        )}
                      </>
                    )}
                  </div>

                  {/* Mobile layout */}
                  <div className="flex sm:hidden flex-col gap-2">
                    <div className="flex items-center gap-2">
                      <Server className="h-5 w-5 flex-shrink-0" />
                      <span className="text-lg truncate">{selectedVM?.name}</span>
                      <span className="text-sm text-muted-foreground">ID: {selectedVM?.vmid}</span>
                    </div>
                    {selectedVM && (
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="outline" className={`${getTypeBadge(selectedVM.type).color} flex-shrink-0`}>
                          {getTypeBadge(selectedVM.type).icon}
                          {getTypeBadge(selectedVM.type).label}
                        </Badge>
                        <Badge variant="outline" className={`${getStatusColor(selectedVM.status)} flex-shrink-0`}>
                          {selectedVM.status.toUpperCase()}
                        </Badge>
                        {selectedVM.status === "running" && (
                          <span className="text-sm text-muted-foreground">
                            Uptime: {formatUptime(selectedVM.uptime)}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </DialogTitle>
              </DialogHeader>

              <div className="flex-1 overflow-y-auto px-6 py-4">
                <div className="space-y-6">
                  {selectedVM && (
                    <>
                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                          Basic Information
                        </h3>
                        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">CPU Usage</div>
                            <div
                              className="cursor-pointer hover:opacity-80 transition-opacity"
                              onClick={() => handleMetricClick("cpu")}
                            >
                              <div className={`font-semibold mb-1 ${getUsageColor(selectedVM.cpu * 100)}`}>
                                {(selectedVM.cpu * 100).toFixed(1)}%
                              </div>
                              <Progress
                                value={selectedVM.cpu * 100}
                                className={`h-1.5 ${getModalProgressColor(selectedVM.cpu * 100)}`}
                              />
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">Memory</div>
                            <div
                              className="cursor-pointer hover:opacity-80 transition-opacity"
                              onClick={() => handleMetricClick("memory")}
                            >
                              <div
                                className={`font-semibold mb-1 ${getUsageColor((selectedVM.mem / selectedVM.maxmem) * 100)}`}
                              >
                                {(selectedVM.mem / 1024 ** 3).toFixed(1)} / {(selectedVM.maxmem / 1024 ** 3).toFixed(1)}{" "}
                                GB
                              </div>
                              <Progress
                                value={(selectedVM.mem / selectedVM.maxmem) * 100}
                                className={`h-1.5 ${getModalProgressColor((selectedVM.mem / selectedVM.maxmem) * 100)}`}
                              />
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">Disk</div>
                            <div
                              className="cursor-pointer hover:opacity-80 transition-opacity"
                              onClick={() => handleMetricClick("disk")}
                            >
                              <div
                                className={`font-semibold mb-1 ${getUsageColor((selectedVM.disk / selectedVM.maxdisk) * 100)}`}
                              >
                                {(selectedVM.disk / 1024 ** 3).toFixed(1)} /{" "}
                                {(selectedVM.maxdisk / 1024 ** 3).toFixed(1)} GB
                              </div>
                              <Progress
                                value={(selectedVM.disk / selectedVM.maxdisk) * 100}
                                className={`h-1.5 ${getModalProgressColor((selectedVM.disk / selectedVM.maxdisk) * 100)}`}
                              />
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">Disk I/O</div>
                            <div
                              className="cursor-pointer hover:opacity-80 transition-opacity"
                              onClick={() => handleMetricClick("disk")}
                            >
                              <div className="text-sm text-green-500 flex items-center gap-1">
                                <span>↓</span>
                                <span>{((selectedVM.diskread || 0) / 1024 ** 2).toFixed(2)} MB</span>
                              </div>
                              <div className="text-sm text-blue-500 flex items-center gap-1">
                                <span>↑</span>
                                <span>{((selectedVM.diskwrite || 0) / 1024 ** 2).toFixed(2)} MB</span>
                              </div>
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">Network I/O</div>
                            <div
                              className="cursor-pointer hover:opacity-80 transition-opacity"
                              onClick={() => handleMetricClick("network")}
                            >
                              <div className="text-sm text-green-500 flex items-center gap-1">
                                <span>↓</span>
                                <span>{((selectedVM.netin || 0) / 1024 ** 2).toFixed(2)} MB</span>
                              </div>
                              <div className="text-sm text-blue-500 flex items-center gap-1">
                                <span>↑</span>
                                <span>{((selectedVM.netout || 0) / 1024 ** 2).toFixed(2)} MB</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>

                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                          Resources
                        </h3>
                        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                          {vmDetails?.config.cores && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">CPU Cores</div>
                              <div className="font-semibold text-blue-500">{vmDetails.config.cores}</div>
                            </div>
                          )}
                          {vmDetails?.config.sockets && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">CPU Sockets</div>
                              <div className="font-semibold text-foreground">{vmDetails.config.sockets}</div>
                            </div>
                          )}
                          {vmDetails?.config.memory && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">Memory</div>
                              <div className="font-semibold text-blue-500">{vmDetails.config.memory} MB</div>
                            </div>
                          )}
                          {vmDetails?.config.swap && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">Swap</div>
                              <div className="font-semibold text-foreground">{vmDetails.config.swap} MB</div>
                            </div>
                          )}
                          {vmDetails?.config.rootfs && (
                            <div className="col-span-2 lg:col-span-3">
                              <div className="text-xs text-muted-foreground mb-1">Root Filesystem</div>
                              <div className="font-medium text-foreground text-sm break-all font-mono">
                                {vmDetails.config.rootfs}
                              </div>
                            </div>
                          )}
                          {Object.keys(vmDetails?.config || {})
                            .filter((key) => key.match(/^(scsi|sata|ide|virtio)\d+$/))
                            .map((diskKey) => (
                              <div key={diskKey} className="col-span-2 lg:col-span-3">
                                <div className="text-xs text-muted-foreground mb-1">
                                  {diskKey.toUpperCase().replace(/(\d+)/, " $1")}
                                </div>
                                <div className="font-medium text-foreground text-sm break-all font-mono">
                                  {vmDetails?.config[diskKey]}
                                </div>
                              </div>
                            ))}
                        </div>
                      </div>

                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                          Network
                        </h3>
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                          {Object.keys(vmDetails?.config || {})
                            .filter((key) => key.match(/^net\d+$/))
                            .map((netKey) => (
                              <div key={netKey} className="col-span-1">
                                <div className="text-xs text-muted-foreground mb-1">
                                  Network Interface {netKey.replace("net", "")}
                                </div>
                                <div className="font-medium text-green-500 text-sm break-all font-mono">
                                  {vmDetails?.config[netKey]}
                                </div>
                              </div>
                            ))}
                          {vmDetails?.config.nameserver && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">DNS Nameserver</div>
                              <div className="font-medium text-foreground font-mono">{vmDetails.config.nameserver}</div>
                            </div>
                          )}
                          {vmDetails?.config.searchdomain && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">Search Domain</div>
                              <div className="font-medium text-foreground">{vmDetails.config.searchdomain}</div>
                            </div>
                          )}
                          {vmDetails?.config.hostname && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">Hostname</div>
                              <div className="font-medium text-foreground">{vmDetails.config.hostname}</div>
                            </div>
                          )}
                        </div>
                      </div>

                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                          Options
                        </h3>
                        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                          {vmDetails?.config.onboot !== undefined && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">Start on Boot</div>
                              <Badge
                                variant="outline"
                                className={
                                  vmDetails.config.onboot
                                    ? "bg-green-500/10 text-green-500 border-green-500/20"
                                    : "bg-red-500/10 text-red-500 border-red-500/20"
                                }
                              >
                                {vmDetails.config.onboot ? "Yes" : "No"}
                              </Badge>
                            </div>
                          )}
                          {vmDetails?.config.unprivileged !== undefined && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">Unprivileged</div>
                              <Badge
                                variant="outline"
                                className={
                                  vmDetails.config.unprivileged
                                    ? "bg-green-500/10 text-green-500 border-green-500/20"
                                    : "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                                }
                              >
                                {vmDetails.config.unprivileged ? "Yes" : "No"}
                              </Badge>
                            </div>
                          )}
                          {vmDetails?.config.ostype && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">OS Type</div>
                              <div className="font-medium text-foreground">{vmDetails.config.ostype}</div>
                            </div>
                          )}
                          {vmDetails?.config.arch && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">Architecture</div>
                              <div className="font-medium text-foreground">{vmDetails.config.arch}</div>
                            </div>
                          )}
                          {vmDetails?.config.boot && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-1">Boot Order</div>
                              <div className="font-medium text-foreground">{vmDetails.config.boot}</div>
                            </div>
                          )}
                          {vmDetails?.config.features && (
                            <div className="col-span-2 lg:col-span-3">
                              <div className="text-xs text-muted-foreground mb-1">Features</div>
                              <div className="font-medium text-foreground text-sm">{vmDetails.config.features}</div>
                            </div>
                          )}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>

              <div className="border-t border-border bg-background px-6 py-4 flex-shrink-0">
                <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                  Control Actions
                </h3>
                <div className="grid grid-cols-2 gap-3">
                  <Button
                    className="w-full bg-green-600 hover:bg-green-700 text-white"
                    disabled={selectedVM?.status === "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "start")}
                  >
                    <Play className="h-4 w-4 mr-2" />
                    Start
                  </Button>
                  <Button
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "shutdown")}
                  >
                    <Power className="h-4 w-4 mr-2" />
                    Shutdown
                  </Button>
                  <Button
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "reboot")}
                  >
                    <RotateCcw className="h-4 w-4 mr-2" />
                    Reboot
                  </Button>
                  <Button
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "stop")}
                  >
                    <StopCircle className="h-4 w-4 mr-2" />
                    Force Stop
                  </Button>
                </div>
              </div>
            </>
          ) : currentView === "metrics" && selectedMetric ? (
            <MetricsDialog
              vmid={selectedVM?.vmid || 0}
              vmName={selectedVM?.name || ""}
              vmType={selectedVM?.type || "qemu"}
              metric={selectedMetric}
              onBack={() => {
                setCurrentView("main")
                setSelectedMetric(null)
              }}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}
