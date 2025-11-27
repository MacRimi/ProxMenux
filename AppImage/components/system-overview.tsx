"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { Cpu, MemoryStick, Thermometer, Server, Zap, AlertCircle, HardDrive, Network } from "lucide-react"
import { NodeMetricsCharts } from "./node-metrics-charts"
import { NetworkTrafficChart } from "./network-traffic-chart"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { fetchApi } from "../lib/api-config"
import { formatNetworkTraffic, getNetworkUnit } from "../lib/format-network"

interface SystemData {
  cpu_usage: number
  memory_usage: number
  memory_total: number
  memory_used: number
  temperature: number
  uptime: string
  load_average: number[]
  hostname: string
  node_id: string
  timestamp: string
  cpu_cores?: number
  cpu_threads?: number
  proxmox_version?: string
  kernel_version?: string
  available_updates?: number
}

interface VMData {
  vmid: number
  name: string
  status: string
  cpu: number
  mem: number
  maxmem: number
  disk: number
  maxdisk: number
  uptime: number
  type?: string
}

interface StorageData {
  total: number
  used: number
  available: number
  disk_count: number
  disks: Array<{
    name: string
    mountpoint: string
    total: number
    used: number
    available: number
    usage_percent: number
  }>
}

interface NetworkData {
  interfaces: Array<{
    name: string
    status: string
    addresses: Array<{ ip: string; netmask: string }>
  }>
  traffic: {
    bytes_sent: number
    bytes_recv: number
    packets_sent: number
    packets_recv: number
  }
  physical_active_count?: number
  physical_total_count?: number
  bridge_active_count?: number
  bridge_total_count?: number
  physical_interfaces?: Array<{
    name: string
    status: string
    addresses: Array<{ ip: string; netmask: string }>
  }>
  bridge_interfaces?: Array<{
    name: string
    status: string
    addresses: Array<{ ip: string; netmask: string }>
  }>
}

interface ProxmoxStorageData {
  storage: Array<{
    name: string
    type: string
    status: string
    total: number
    used: number
    available: number
    percent: number
  }>
}

const fetchSystemData = async (retries = 3, delayMs = 500): Promise<SystemData | null> => {
  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      const data = await fetchApi<SystemData>("/api/system")
      return data
    } catch (error) {
      if (attempt === retries - 1) {
        console.error("[v0] Failed to fetch system data after retries:", error)
        return null
      }
      // Wait before retry
      await new Promise((resolve) => setTimeout(resolve, delayMs))
    }
  }
  return null
}

const fetchVMData = async (): Promise<VMData[]> => {
  try {
    const data = await fetchApi<any>("/api/vms")
    return Array.isArray(data) ? data : data.vms || []
  } catch (error) {
    console.error("[v0] Failed to fetch VM data:", error)
    return []
  }
}

const fetchStorageData = async (): Promise<StorageData | null> => {
  try {
    const data = await fetchApi<StorageData>("/api/storage/summary")
    return data
  } catch (error) {
    console.log("[v0] Storage API not available (this is normal if not configured)")
    return null
  }
}

const fetchNetworkData = async (): Promise<NetworkData | null> => {
  try {
    const data = await fetchApi<NetworkData>("/api/network/summary")
    return data
  } catch (error) {
    console.log("[v0] Network API not available (this is normal if not configured)")
    return null
  }
}

const fetchProxmoxStorageData = async (): Promise<ProxmoxStorageData | null> => {
  try {
    const data = await fetchApi<ProxmoxStorageData>("/api/proxmox-storage")
    return data
  } catch (error) {
    console.log("[v0] Proxmox storage API not available")
    return null
  }
}

const getUnitsSettings = (): "Bytes" | "Bits" => {
  if (typeof window === "undefined") return "Bytes"
  const raw = window.localStorage.getItem("proxmenux-network-unit")
  return raw && raw.toLowerCase() === "bits" ? "Bits" : "Bytes"
}

export function SystemOverview() {
  const [systemData, setSystemData] = useState<SystemData | null>(null)
  const [vmData, setVmData] = useState<VMData[]>([])
  const [storageData, setStorageData] = useState<StorageData | null>(null)
  const [proxmoxStorageData, setProxmoxStorageData] = useState<ProxmoxStorageData | null>(null)
  const [networkData, setNetworkData] = useState<NetworkData | null>(null)
  const [loadingStates, setLoadingStates] = useState({
    system: true,
    vms: true,
    storage: true,
    network: true,
  })
  const [error, setError] = useState<string | null>(null)
  const [hasAttemptedLoad, setHasAttemptedLoad] = useState(false) // Added hasAttemptedLoad state
  const [networkTimeframe, setNetworkTimeframe] = useState("day")
  const [networkTotals, setNetworkTotals] = useState<{ received: number; sent: number }>({ received: 0, sent: 0 })
  const [networkUnit, setNetworkUnit] = useState<"Bytes" | "Bits">("Bytes") // Added networkUnit state

  useEffect(() => {
    const fetchAllData = async () => {
      const [systemResult, vmResult, storageResults, networkResult] = await Promise.all([
        fetchSystemData().finally(() => setLoadingStates((prev) => ({ ...prev, system: false }))),
        fetchVMData().finally(() => setLoadingStates((prev) => ({ ...prev, vms: false }))),
        Promise.all([fetchStorageData(), fetchProxmoxStorageData()]).finally(() =>
          setLoadingStates((prev) => ({ ...prev, storage: false })),
        ),
        fetchNetworkData().finally(() => setLoadingStates((prev) => ({ ...prev, network: false }))),
      ])

      setHasAttemptedLoad(true)

      if (!systemResult) {
        setError("Flask server not available. Please ensure the server is running.")
        return
      }

      setSystemData(systemResult)
      setVmData(vmResult)
      setStorageData(storageResults[0])
      setProxmoxStorageData(storageResults[1])
      setNetworkData(networkResult)

      setTimeout(async () => {
        const refreshedSystemData = await fetchSystemData()
        if (refreshedSystemData) {
          setSystemData(refreshedSystemData)
        }
      }, 2000)
    }

    fetchAllData()

    const systemInterval = setInterval(async () => {
      const data = await fetchSystemData()
      if (data) setSystemData(data)
    }, 9000)

    const vmInterval = setInterval(async () => {
      const data = await fetchVMData()
      setVmData(data)
    }, 59000)

    const storageInterval = setInterval(async () => {
      const [storage, proxmoxStorage] = await Promise.all([fetchStorageData(), fetchProxmoxStorageData()])
      if (storage) setStorageData(storage)
      if (proxmoxStorage) setProxmoxStorageData(proxmoxStorage)
    }, 59000)

    const networkInterval = setInterval(async () => {
      const data = await fetchNetworkData()
      if (data) setNetworkData(data)
    }, 59000)

    setNetworkUnit(getNetworkUnit()) // Load initial setting

    const handleUnitChange = (e: CustomEvent) => {
      setNetworkUnit(e.detail === "Bits" ? "Bits" : "Bytes")
    }

    window.addEventListener("networkUnitChanged" as any, handleUnitChange)

    return () => {
      clearInterval(systemInterval)
      clearInterval(vmInterval)
      clearInterval(storageInterval)
      clearInterval(networkInterval)
      window.removeEventListener("networkUnitChanged" as any, handleUnitChange)
    }
  }, [])

  if (!hasAttemptedLoad || loadingStates.system) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
          {[...Array(4)].map((_, i) => (
            <Card key={i} className="bg-card border-border animate-pulse">
              <CardContent className="p-6">
                <div className="h-4 bg-muted rounded w-1/2 mb-4"></div>
                <div className="h-8 bg-muted rounded w-3/4 mb-2"></div>
                <div className="h-2 bg-muted rounded w-full mb-2"></div>
                <div className="h-3 bg-muted rounded w-2/3"></div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    )
  }

  if (error || !systemData) {
    return (
      <div className="space-y-6">
        <Card className="bg-red-500/10 border-red-500/20">
          <CardContent className="p-6">
            <div className="flex items-center gap-3 text-red-600">
              <AlertCircle className="h-6 w-6" />
              <div>
                <div className="font-semibold text-lg mb-1">Flask Server Not Available</div>
                <div className="text-sm">
                  {error || "Unable to connect to the Flask server. Please ensure the server is running and try again."}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const vmStats = {
    total: vmData.length,
    running: vmData.filter((vm) => vm.status === "running").length,
    stopped: vmData.filter((vm) => vm.status === "stopped").length,
    lxc: vmData.filter((vm) => vm.type === "lxc").length,
    vms: vmData.filter((vm) => vm.type === "qemu" || !vm.type).length,
  }

  const getTemperatureStatus = (temp: number) => {
    if (temp === 0) return { status: "N/A", color: "bg-gray-500/10 text-gray-500 border-gray-500/20" }
    if (temp < 60) return { status: "Normal", color: "bg-green-500/10 text-green-500 border-green-500/20" }
    if (temp < 75) return { status: "Warm", color: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20" }
    return { status: "Hot", color: "bg-red-500/10 text-red-500 border-red-500/20" }
  }

  const formatUptime = (seconds: number) => {
    if (!seconds || seconds === 0) return "Stopped"
    const days = Math.floor(seconds / 86400)
    const hours = Math.floor((seconds % 86400) / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)

    if (days > 0) return `${days}d ${hours}h`
    if (hours > 0) return `${hours}h ${minutes}m`
    return `${minutes}m`
  }

  const formatBytes = (bytes: number) => {
    return (bytes / 1024 ** 3).toFixed(2)
  }

  const tempStatus = getTemperatureStatus(systemData.temperature)

  const localStorage = proxmoxStorageData?.storage.find((s) => s.name === "local")

  const vmLxcStorages = proxmoxStorageData?.storage.filter(
    (s) =>
      (s.type === "lvm" || s.type === "lvmthin" || s.type === "zfspool" || s.type === "btrfs" || s.type === "dir") &&
      s.type !== "nfs" &&
      s.type !== "cifs" &&
      s.type !== "iscsi" &&
      s.name !== "local",
  )

  const vmLxcStorageTotal = vmLxcStorages?.reduce((acc, s) => acc + s.total, 0) || 0
  const vmLxcStorageUsed = vmLxcStorages?.reduce((acc, s) => acc + s.used, 0) || 0
  const vmLxcStorageAvailable = vmLxcStorages?.reduce((acc, s) => acc + s.available, 0) || 0
  const vmLxcStoragePercent = vmLxcStorageTotal > 0 ? (vmLxcStorageUsed / vmLxcStorageTotal) * 100 : 0

  const getLoadStatus = (load: number, cores: number) => {
    if (load < cores) {
      return { status: "Normal", color: "bg-green-500/10 text-green-500 border-green-500/20" }
    } else if (load < cores * 1.5) {
      return { status: "Moderate", color: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20" }
    } else {
      return { status: "High", color: "bg-red-500/10 text-red-500 border-red-500/20" }
    }
  }

  const systemAlerts = []
  if (systemData.available_updates && systemData.available_updates > 0) {
    systemAlerts.push({
      type: "warning",
      message: `${systemData.available_updates} updates available`,
    })
  }
  if (vmStats.stopped > 0) {
    systemAlerts.push({
      type: "info",
      message: `${vmStats.stopped} VM${vmStats.stopped > 1 ? "s" : ""} stopped`,
    })
  }
  if (systemData.temperature > 75) {
    systemAlerts.push({
      type: "warning",
      message: "High temperature detected",
    })
  }
  if (localStorage && localStorage.percent > 90) {
    systemAlerts.push({
      type: "warning",
      message: "System storage almost full",
    })
  }

  const loadStatus = getLoadStatus(systemData.load_average[0], systemData.cpu_cores || 8)

  const getTimeframeLabel = (timeframe: string): string => {
    switch (timeframe) {
      case "hour":
        return "1h"
      case "day":
        return "24h"
      case "week":
        return "7d"
      case "month":
        return "30d"
      case "year":
        return "1y"
      default:
        return timeframe
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">CPU Usage</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">{systemData.cpu_usage}%</div>
            <Progress value={systemData.cpu_usage} className="mt-2 [&>div]:bg-blue-500" />
            <p className="text-xs text-muted-foreground mt-2">Real-time usage</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Memory Usage</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">{systemData.memory_used.toFixed(1)} GB</div>
            <Progress value={systemData.memory_usage} className="mt-2 [&>div]:bg-blue-500" />
            <p className="text-xs text-muted-foreground mt-2">
              <span className="text-green-500 font-medium">{systemData.memory_usage.toFixed(1)}%</span> of{" "}
              {systemData.memory_total} GB
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Server className="h-5 w-5 mr-2" />
              Active VM & LXC
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loadingStates.vms ? (
              <div className="space-y-2 animate-pulse">
                <div className="h-8 bg-muted rounded w-12"></div>
                <div className="h-5 bg-muted rounded w-24"></div>
                <div className="h-4 bg-muted rounded w-32"></div>
              </div>
            ) : (
              <>
                <div className="text-xl lg:text-2xl font-bold text-foreground">{vmStats.running}</div>
                <div className="mt-2 flex flex-wrap gap-1">
                  <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                    {vmStats.running} Running
                  </Badge>
                  {vmStats.stopped > 0 && (
                    <Badge variant="outline" className="bg-red-500/10 text-red-500 border-red-500/20">
                      {vmStats.stopped} Stopped
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground mt-2">
                  Total: {vmStats.vms} VMs, {vmStats.lxc} LXC
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Temperature</CardTitle>
            <Thermometer className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">
              {systemData.temperature === 0 ? "N/A" : `${systemData.temperature}°C`}
            </div>
            <div className="flex items-center mt-2">
              <Badge variant="outline" className={tempStatus.color}>
                {tempStatus.status}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              {systemData.temperature === 0 ? "No sensor available" : "Live temperature reading"}
            </p>
          </CardContent>
        </Card>
      </div>

      <NodeMetricsCharts />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <HardDrive className="h-5 w-5 mr-2" />
              Storage Overview
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loadingStates.storage ? (
              <div className="space-y-4 animate-pulse">
                <div className="h-6 bg-muted rounded w-full"></div>
                <div className="h-4 bg-muted rounded w-3/4"></div>
                <div className="h-4 bg-muted rounded w-2/3"></div>
              </div>
            ) : storageData ? (
              <div className="space-y-4">
                {(() => {
                  const totalCapacity = (vmLxcStorageTotal || 0) + (localStorage?.total || 0)
                  const totalUsed = (vmLxcStorageUsed || 0) + (localStorage?.used || 0)
                  const totalAvailable = (vmLxcStorageAvailable || 0) + (localStorage?.available || 0)
                  const totalPercent = totalCapacity > 0 ? (totalUsed / totalCapacity) * 100 : 0

                  return totalCapacity > 0 ? (
                    <div className="space-y-2 pb-4 border-b-2 border-border">
                      <div className="flex justify-between items-center">
                        <span className="text-sm font-medium text-foreground">Total Node Capacity:</span>
                        <span className="text-lg font-bold text-foreground">
                          {formatNetworkTraffic(totalCapacity, "Bytes")}
                        </span>
                      </div>
                      <Progress
                        value={totalPercent}
                        className="mt-2 h-3 [&>div]:bg-gradient-to-r [&>div]:from-blue-500 [&>div]:to-purple-500"
                      />
                      <div className="flex justify-between items-center mt-1">
                        <div className="flex items-center gap-3">
                          <span className="text-xs text-muted-foreground">
                            Used:{" "}
                            <span className="font-semibold text-foreground">
                              {formatNetworkTraffic(totalUsed, "Bytes")}
                            </span>
                          </span>
                          <span className="text-xs text-muted-foreground">
                            Free:{" "}
                            <span className="font-semibold text-green-500">
                              {formatNetworkTraffic(totalAvailable, "Bytes")}
                            </span>
                          </span>
                        </div>
                        <span className="text-xs font-semibold text-muted-foreground">{totalPercent.toFixed(1)}%</span>
                      </div>
                    </div>
                  ) : null
                })()}

                <div className="space-y-2 pb-3 border-b border-border">
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-muted-foreground">Total Capacity:</span>
                    <span className="text-lg font-semibold text-foreground">{storageData.total} TB</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-muted-foreground">Physical Disks:</span>
                    <span className="text-sm font-semibold text-foreground">
                      {storageData.disk_count} disk{storageData.disk_count !== 1 ? "s" : ""}
                    </span>
                  </div>
                </div>

                {vmLxcStorages && vmLxcStorages.length > 0 ? (
                  <div className="space-y-2 pb-3 border-b border-border">
                    <div className="text-xs font-medium text-muted-foreground mb-2">VM/LXC Storage</div>
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-muted-foreground">Used:</span>
                      <span className="text-sm font-semibold text-foreground">
                        {formatNetworkTraffic(vmLxcStorageUsed, "Bytes")}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-muted-foreground">Available:</span>
                      <span className="text-sm font-semibold text-green-500">
                        {formatNetworkTraffic(vmLxcStorageAvailable, "Bytes")}
                      </span>
                    </div>
                    <Progress value={vmLxcStoragePercent} className="mt-2 [&>div]:bg-blue-500" />
                    <div className="flex justify-between items-center mt-1">
                      <span className="text-xs text-muted-foreground">
                        {formatNetworkTraffic(vmLxcStorageUsed, "Bytes")} /{" "}
                        {formatNetworkTraffic(vmLxcStorageTotal, "Bytes")}
                      </span>
                      <span className="text-xs text-muted-foreground">{vmLxcStoragePercent.toFixed(1)}%</span>
                    </div>
                    {vmLxcStorages.length > 1 && (
                      <div className="text-xs text-muted-foreground mt-1">
                        {vmLxcStorages.length} storage volume{vmLxcStorages.length > 1 ? "s" : ""}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2 pb-3 border-b border-border">
                    <div className="text-xs font-medium text-muted-foreground mb-2">VM/LXC Storage</div>
                    <div className="text-center py-4 text-muted-foreground text-sm">No VM/LXC storage configured</div>
                  </div>
                )}

                {localStorage && (
                  <div className="space-y-2">
                    <div className="text-xs font-medium text-muted-foreground mb-2">Local Storage (System)</div>
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-muted-foreground">Used:</span>
                      <span className="text-sm font-semibold text-foreground">
                        {formatNetworkTraffic(localStorage.used, "Bytes")}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-muted-foreground">Available:</span>
                      <span className="text-sm font-semibold text-green-500">
                        {formatNetworkTraffic(localStorage.available, "Bytes")}
                      </span>
                    </div>
                    <Progress value={localStorage.percent} className="mt-2 [&>div]:bg-purple-500" />
                    <div className="flex justify-between items-center mt-1">
                      <span className="text-xs text-muted-foreground">
                        {formatNetworkTraffic(localStorage.used, "Bytes")} /{" "}
                        {formatNetworkTraffic(localStorage.total, "Bytes")}
                      </span>
                      <span className="text-xs text-muted-foreground">{localStorage.percent.toFixed(1)}%</span>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">Storage data not available</div>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center justify-between">
              <div className="flex items-center">
                <Network className="h-5 w-5 mr-2" />
                Network Overview
              </div>
              <Select value={networkTimeframe} onValueChange={setNetworkTimeframe}>
                <SelectTrigger className="w-28 h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="hour">1 Hour</SelectItem>
                  <SelectItem value="day">24 Hours</SelectItem>
                  <SelectItem value="week">7 Days</SelectItem>
                  <SelectItem value="month">30 Days</SelectItem>
                  <SelectItem value="year">1 Year</SelectItem>
                </SelectContent>
              </Select>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loadingStates.network ? (
              <div className="space-y-4 animate-pulse">
                <div className="h-6 bg-muted rounded w-full"></div>
                <div className="h-4 bg-muted rounded w-3/4"></div>
                <div className="h-4 bg-muted rounded w-2/3"></div>
              </div>
            ) : networkData ? (
              <div className="space-y-4">
                <div className="flex justify-between items-center pb-3 border-b border-border">
                  <span className="text-sm text-muted-foreground">Active Interfaces:</span>
                  <span className="text-lg font-semibold text-foreground">
                    {(networkData.physical_active_count || 0) + (networkData.bridge_active_count || 0)}
                  </span>
                </div>

                <div className="space-y-2">
                  {networkData.physical_interfaces && networkData.physical_interfaces.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {networkData.physical_interfaces
                        .filter((iface) => iface.status === "up")
                        .map((iface) => (
                          <Badge
                            key={iface.name}
                            variant="outline"
                            className="bg-blue-500/10 text-blue-500 border-blue-500/20"
                          >
                            {iface.name}
                          </Badge>
                        ))}
                    </div>
                  )}

                  {networkData.bridge_interfaces && networkData.bridge_interfaces.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {networkData.bridge_interfaces
                        .filter((iface) => iface.status === "up")
                        .map((iface) => (
                          <Badge
                            key={iface.name}
                            variant="outline"
                            className="bg-green-500/10 text-green-500 border-green-500/20"
                          >
                            {iface.name}
                          </Badge>
                        ))}
                    </div>
                  )}
                </div>

                <div className="pt-2 border-t border-border space-y-2">
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-muted-foreground">Received:</span>
                    <span className="text-lg font-semibold text-green-500 flex items-center gap-1">
                      ↓{" "}
                      {networkUnit === "Bytes"
                        ? `${networkTotals.received.toFixed(2)} GB`
                        : formatNetworkTraffic(networkTotals.received * 1024 * 1024 * 1024, "Bits")}
                      <span className="text-xs text-muted-foreground">({getTimeframeLabel(networkTimeframe)})</span>
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-muted-foreground">Sent:</span>
                    <span className="text-lg font-semibold text-blue-500 flex items-center gap-1">
                      ↑{" "}
                      {networkUnit === "Bytes"
                        ? `${networkTotals.sent.toFixed(2)} GB`
                        : formatNetworkTraffic(networkTotals.sent * 1024 * 1024 * 1024, "Bits")}
                      <span className="text-xs text-muted-foreground">({getTimeframeLabel(networkTimeframe)})</span>
                    </span>
                  </div>
                </div>

                <div className="pt-3 border-t border-border">
                  <NetworkTrafficChart
                    timeframe={networkTimeframe}
                    onTotalsCalculated={setNetworkTotals}
                    networkUnit={networkUnit}
                  />
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">Network data not available</div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Server className="h-5 w-5 mr-2" />
              System Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Uptime:</span>
              <span className="text-foreground">{systemData.uptime}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Proxmox Version:</span>
              <span className="text-foreground">{systemData.proxmox_version || "N/A"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Kernel:</span>
              <span className="text-foreground font-mono text-sm">{systemData.kernel_version || "Linux"}</span>
            </div>
            {systemData.available_updates !== undefined && systemData.available_updates > 0 && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Available Updates:</span>
                <Badge variant="outline" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                  {systemData.available_updates} packages
                </Badge>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Zap className="h-5 w-5 mr-2" />
              System Overview
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex justify-between items-center pb-3 border-b border-border">
              <div className="flex flex-col">
                <span className="text-sm text-muted-foreground">Load Average (1m):</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-lg font-semibold text-foreground font-mono">
                  {systemData.load_average[0].toFixed(2)}
                </span>
                <Badge variant="outline" className={loadStatus.color}>
                  {loadStatus.status}
                </Badge>
              </div>
            </div>

            <div className="flex justify-between items-center pb-3 border-b border-border">
              <span className="text-sm text-muted-foreground">CPU Threads:</span>
              <span className="text-lg font-semibold text-foreground">{systemData.cpu_threads || "N/A"}</span>
            </div>

            <div className="flex justify-between items-center pb-3 border-b border-border">
              <span className="text-sm text-muted-foreground">Physical Disks:</span>
              <span className="text-lg font-semibold text-foreground">{storageData?.disk_count || "N/A"}</span>
            </div>

            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">Network Interfaces:</span>
              <span className="text-lg font-semibold text-foreground">
                {networkData?.physical_total_count || networkData?.physical_interfaces?.length || "N/A"}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
