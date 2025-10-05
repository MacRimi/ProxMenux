"use client"

import { useState, useMemo } from "react"
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
  HardDrive,
  Network,
  Power,
  RotateCcw,
  StopCircle,
  AlertTriangle,
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
  return Array.isArray(data) ? data : []
}

const formatBytes = (bytes: number | undefined): string => {
  if (!bytes || bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

const extractIPFromNetConfig = (netConfig: string | undefined): string => {
  if (!netConfig) return "N/A"

  // Parse the network config string: name=eth0,bridge=vmbr0,gw=192.168.0.1,hwaddr=...,ip=192.168.0.4/24,type=veth
  const ipMatch = netConfig.match(/ip=([^,]+)/)
  if (ipMatch && ipMatch[1]) {
    const ip = ipMatch[1]
    // Check if it's DHCP
    if (ip.toLowerCase() === "dhcp") {
      return "DHCP"
    }
    // Return the IP without the subnet mask for cleaner display
    return ip.split("/")[0]
  }

  return "N/A"
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

  const handleVMClick = async (vm: VMData) => {
    setSelectedVM(vm)
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

  // Safe data handling with default empty array
  const safeVMData = vmData || []

  const totalAllocatedMemoryGB = useMemo(() => {
    return (safeVMData.reduce((sum, vm) => sum + (vm.maxmem || 0), 0) / 1024 ** 3).toFixed(1)
  }, [safeVMData])

  const { data: overviewData } = useSWR("/api/overview", fetcher, {
    refreshInterval: 30000,
    revalidateOnFocus: false,
  })

  const physicalMemoryGB = useMemo(() => {
    if (overviewData && overviewData.memory) {
      return (overviewData.memory.total / 1024 ** 3).toFixed(1)
    }
    return null
  }, [overviewData])

  const isMemoryOvercommit = useMemo(() => {
    if (physicalMemoryGB) {
      return Number.parseFloat(totalAllocatedMemoryGB) > Number.parseFloat(physicalMemoryGB)
    }
    return false
  }, [totalAllocatedMemoryGB, physicalMemoryGB])

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
      {/* VM Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total VMs & LXCs</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{safeVMData.length}</div>
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
            <div className="text-2xl font-bold text-foreground">
              {(safeVMData.reduce((sum, vm) => sum + (vm.cpu || 0), 0) * 100).toFixed(0)}%
            </div>
            <p className="text-xs text-muted-foreground mt-2">Allocated CPU usage</p>
          </CardContent>
        </Card>

        <Card className={`bg-card ${isMemoryOvercommit ? "border-yellow-500/50" : "border-border"}`}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Memory</CardTitle>
            <div className="flex items-center gap-2">
              {isMemoryOvercommit && <AlertTriangle className="h-4 w-4 text-yellow-500" />}
              <MemoryStick className="h-4 w-4 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${isMemoryOvercommit ? "text-yellow-500" : "text-foreground"}`}>
              {totalAllocatedMemoryGB} GB
            </div>
            {isMemoryOvercommit ? (
              <p className="text-xs text-yellow-500 mt-2 flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" />
                Overcommit: Excede memoria física ({physicalMemoryGB} GB)
              </p>
            ) : (
              <p className="text-xs text-muted-foreground mt-2">Allocated RAM</p>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Average Load</CardTitle>
            <Monitor className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">
              {safeVMData.filter((vm) => vm.status === "running").length > 0
                ? (
                    (safeVMData.reduce((sum, vm) => sum + (vm.cpu || 0), 0) /
                      safeVMData.filter((vm) => vm.status === "running").length) *
                    100
                  ).toFixed(0)
                : 0}
              %
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
          {safeVMData.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">No virtual machines found</div>
          ) : (
            <div className="space-y-4">
              {safeVMData.map((vm) => {
                const cpuPercent = (vm.cpu * 100).toFixed(1)
                const memPercent = vm.maxmem > 0 ? ((vm.mem / vm.maxmem) * 100).toFixed(1) : "0"
                const memGB = (vm.mem / 1024 ** 3).toFixed(1)
                const maxMemGB = (vm.maxmem / 1024 ** 3).toFixed(1)
                const typeBadge = getTypeBadge(vm.type)

                return (
                  <div
                    key={vm.vmid}
                    className="p-6 rounded-lg border border-border bg-card/50 hover:bg-card/80 transition-colors cursor-pointer"
                    onClick={() => handleVMClick(vm)}
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
                      <div className="flex items-center space-x-4">
                        <Server className="h-6 w-6 text-muted-foreground flex-shrink-0" />
                        <div className="min-w-0">
                          <div className="font-semibold text-foreground text-lg flex items-center flex-wrap gap-2">
                            <span className="truncate">{vm.name}</span>
                            <Badge variant="outline" className={`text-xs flex-shrink-0 ${typeBadge.color}`}>
                              {typeBadge.label}
                            </Badge>
                          </div>
                          <div className="text-sm text-muted-foreground">ID: {vm.vmid}</div>
                        </div>
                      </div>

                      <Badge
                        variant="outline"
                        className={`${getStatusColor(vm.status)} flex-shrink-0 self-start sm:self-center`}
                      >
                        {getStatusIcon(vm.status)}
                        {vm.status.toUpperCase()}
                      </Badge>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
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

                      <div className="hidden md:block">
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

                      <div className="hidden md:block">
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
      <Dialog
        open={!!selectedVM}
        onOpenChange={() => {
          setSelectedVM(null)
          setVMDetails(null)
        }}
      >
        <DialogContent className="max-w-4xl max-h-[95vh] overflow-y-auto">
          <DialogHeader className="pb-4 border-b border-border">
            <DialogTitle className="flex flex-col sm:flex-row sm:items-center gap-3">
              <div className="flex items-center gap-2">
                <Server className="h-5 w-5 flex-shrink-0" />
                <span className="text-lg truncate">{selectedVM?.name}</span>
              </div>
              {selectedVM && (
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="outline" className={`${getTypeBadge(selectedVM.type).color} flex-shrink-0`}>
                    {getTypeBadge(selectedVM.type).label}
                  </Badge>
                  <Badge variant="outline" className={`${getStatusColor(selectedVM.status)} flex-shrink-0`}>
                    {selectedVM.status.toUpperCase()}
                  </Badge>
                </div>
              )}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-6 py-4">
            {selectedVM && (
              <>
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                    Basic Information
                  </h3>
                  <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">Name</div>
                      <div className="font-semibold text-foreground">{selectedVM.name}</div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">VMID</div>
                      <div className="font-semibold text-foreground">{selectedVM.vmid}</div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">CPU Usage</div>
                      <div
                        className={`font-semibold ${
                          (selectedVM.cpu * 100) > 80
                            ? "text-red-500"
                            : selectedVM.cpu * 100 > 60
                              ? "text-yellow-500"
                              : "text-green-500"
                        }`}
                      >
                        {(selectedVM.cpu * 100).toFixed(1)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">Memory</div>
                      <div
                        className={`font-semibold ${
                          ((selectedVM.mem / selectedVM.maxmem) * 100) > 80
                            ? "text-red-500"
                            : (selectedVM.mem / selectedVM.maxmem) * 100 > 60
                              ? "text-yellow-500"
                              : "text-blue-500"
                        }`}
                      >
                        {(selectedVM.mem / 1024 ** 3).toFixed(1)} / {(selectedVM.maxmem / 1024 ** 3).toFixed(1)} GB
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">Disk</div>
                      <div className="font-semibold text-foreground">
                        {(selectedVM.disk / 1024 ** 3).toFixed(1)} / {(selectedVM.maxdisk / 1024 ** 3).toFixed(1)} GB
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">Uptime</div>
                      <div className="font-semibold text-foreground">{formatUptime(selectedVM.uptime)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">Disk I/O</div>
                      <div className="text-sm font-semibold">
                        <div className="flex items-center gap-1">
                          <span className="text-green-500">↓ {formatBytes(selectedVM.diskread)}</span>
                        </div>
                        <div className="flex items-center gap-1">
                          <span className="text-blue-500">↑ {formatBytes(selectedVM.diskwrite)}</span>
                        </div>
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">Network I/O</div>
                      <div className="text-sm font-semibold">
                        <div className="flex items-center gap-1">
                          <span className="text-green-500">↓ {formatBytes(selectedVM.netin)}</span>
                        </div>
                        <div className="flex items-center gap-1">
                          <span className="text-blue-500">↑ {formatBytes(selectedVM.netout)}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Resources Configuration */}
                {detailsLoading ? (
                  <div className="text-center py-8 text-muted-foreground">Loading configuration...</div>
                ) : vmDetails?.config ? (
                  <>
                    <div>
                      <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                        Resources
                      </h3>
                      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                        {vmDetails.config.cores && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">CPU Cores</div>
                            <div className="font-semibold text-blue-500">{vmDetails.config.cores}</div>
                          </div>
                        )}
                        {vmDetails.config.sockets && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">CPU Sockets</div>
                            <div className="font-semibold text-foreground">{vmDetails.config.sockets}</div>
                          </div>
                        )}
                        {vmDetails.config.memory && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">Memory</div>
                            <div className="font-semibold text-blue-500">{vmDetails.config.memory} MB</div>
                          </div>
                        )}
                        {vmDetails.config.swap && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">Swap</div>
                            <div className="font-semibold text-foreground">{vmDetails.config.swap} MB</div>
                          </div>
                        )}
                        {vmDetails.config.rootfs && (
                          <div className="col-span-2 lg:col-span-3">
                            <div className="text-xs text-muted-foreground mb-1">Root Filesystem</div>
                            <div className="font-medium text-foreground text-sm break-all font-mono">
                              {vmDetails.config.rootfs}
                            </div>
                          </div>
                        )}
                        {Object.keys(vmDetails.config)
                          .filter((key) => key.match(/^(scsi|sata|ide|virtio)\d+$/))
                          .map((diskKey) => (
                            <div key={diskKey} className="col-span-2 lg:col-span-3">
                              <div className="text-xs text-muted-foreground mb-1">
                                {diskKey.toUpperCase().replace(/(\d+)/, " $1")}
                              </div>
                              <div className="font-medium text-foreground text-sm break-all font-mono">
                                {vmDetails.config[diskKey]}
                              </div>
                            </div>
                          ))}
                      </div>
                    </div>

                    {/* Network Configuration */}
                    <div>
                      <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                        Network
                      </h3>
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        {Object.keys(vmDetails.config)
                          .filter((key) => key.match(/^net\d+$/))
                          .map((netKey) => {
                            const netConfig = vmDetails.config[netKey]
                            const ipAddress = selectedVM?.type === "lxc" ? extractIPFromNetConfig(netConfig) : null

                            return (
                              <div key={netKey} className="col-span-1">
                                <div className="text-xs text-muted-foreground mb-1">
                                  Network Interface {netKey.replace("net", "")}
                                </div>
                                {ipAddress && (
                                  <div className="mb-2">
                                    <span className="text-xs text-muted-foreground">IP Address: </span>
                                    <span
                                      className={`font-semibold ${ipAddress === "DHCP" ? "text-yellow-500" : "text-blue-500"}`}
                                    >
                                      {ipAddress}
                                    </span>
                                  </div>
                                )}
                                <div className="font-medium text-green-500 text-xs break-all font-mono">
                                  {netConfig}
                                </div>
                              </div>
                            )
                          })}
                        {vmDetails.config.nameserver && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">DNS Nameserver</div>
                            <div className="font-medium text-foreground font-mono">{vmDetails.config.nameserver}</div>
                          </div>
                        )}
                        {vmDetails.config.searchdomain && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">Search Domain</div>
                            <div className="font-medium text-foreground">{vmDetails.config.searchdomain}</div>
                          </div>
                        )}
                        {vmDetails.config.hostname && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">Hostname</div>
                            <div className="font-medium text-foreground">{vmDetails.config.hostname}</div>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Options */}
                    <div>
                      <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                        Options
                      </h3>
                      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                        {vmDetails.config.onboot !== undefined && (
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
                        {vmDetails.config.unprivileged !== undefined && (
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
                        {vmDetails.config.ostype && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">OS Type</div>
                            <div className="font-medium text-foreground">{vmDetails.config.ostype}</div>
                          </div>
                        )}
                        {vmDetails.config.arch && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">Architecture</div>
                            <div className="font-medium text-foreground">{vmDetails.config.arch}</div>
                          </div>
                        )}
                        {vmDetails.config.boot && (
                          <div>
                            <div className="text-xs text-muted-foreground mb-1">Boot Order</div>
                            <div className="font-medium text-foreground">{vmDetails.config.boot}</div>
                          </div>
                        )}
                        {vmDetails.config.features && (
                          <div className="col-span-2 lg:col-span-3">
                            <div className="text-xs text-muted-foreground mb-1">Features</div>
                            <div className="font-medium text-foreground text-sm">{vmDetails.config.features}</div>
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                ) : null}

                {/* Control Actions */}
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                    Control Actions
                  </h3>
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
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
