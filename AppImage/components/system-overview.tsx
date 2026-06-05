"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { Cpu, MemoryStick, Thermometer, Server, Zap, AlertCircle, HardDrive, Network, ChevronRight } from "lucide-react"
import { NodeMetricsCharts } from "./node-metrics-charts"
import { NetworkTrafficChart } from "./network-traffic-chart"
import { TemperatureDetailModal } from "./temperature-detail-modal"
import { ProcessDetailModal } from "./process-detail-modal"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { fetchApi } from "../lib/api-config"
import { formatNetworkTraffic, getNetworkUnit } from "../lib/format-network"
import { formatStorage } from "../lib/utils"
import { Area, AreaChart, ResponsiveContainer } from "recharts"

interface TempDataPoint {
  timestamp: number
  value: number
}

interface SystemData {
  cpu_usage: number
  cpu_user?: number  // preview restyle
  cpu_system?: number  // preview restyle
  memory_usage: number
  memory_total: number
  memory_used: number
  memory_cached?: number  // preview restyle
  temperature: number
  temperature_sparkline?: TempDataPoint[]
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
    } catch {
      if (attempt === retries - 1) {
        // Silent fail - API not available (expected in preview environment)
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
  } catch {
    // Silent fail - API not available
    return []
  }
}

const fetchStorageData = async (): Promise<StorageData | null> => {
  try {
    const data = await fetchApi<StorageData>("/api/storage/summary")
    return data
  } catch {
    return null
  }
}

const fetchNetworkData = async (): Promise<NetworkData | null> => {
  try {
    const data = await fetchApi<NetworkData>("/api/network/summary")
    return data
  } catch {
    return null
  }
}

const fetchProxmoxStorageData = async (): Promise<ProxmoxStorage[] | null> => {
  try {
    const data = await fetchApi<ProxmoxStorage[]>("/api/proxmox-storage")
    return data
  } catch {
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
  const [tempModalOpen, setTempModalOpen] = useState(false)
  const [cpuProcModalOpen, setCpuProcModalOpen] = useState(false)
  const [memProcModalOpen, setMemProcModalOpen] = useState(false)

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
    }, 5000)

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
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <div className="relative">
          <div className="h-12 w-12 rounded-full border-2 border-muted"></div>
          <div className="absolute inset-0 h-12 w-12 rounded-full border-2 border-transparent border-t-primary animate-spin"></div>
        </div>
        <div className="text-sm font-medium text-foreground">Loading system overview...</div>
        <p className="text-xs text-muted-foreground">Fetching system status and metrics</p>
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
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-6">
        {/* ── CPU Usage (preview restyle v2: tamaño igual a System Info, bars más anchas) ── */}
        <Card
          className="bg-card border-border cursor-pointer hover:bg-white/5 transition-colors"
          onClick={() => setCpuProcModalOpen(true)}
          title="View top processes by CPU"
        >
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">CPU Usage</CardTitle>
            <div className="flex items-center gap-1 text-muted-foreground">
              <Cpu className="h-4 w-4" />
              <ChevronRight className="h-4 w-4 opacity-60" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-4">
              <svg viewBox="0 0 36 36" className="w-[72px] h-[72px] flex-shrink-0">
                <circle cx="18" cy="18" r="15.9155" fill="none" stroke="rgba(99,102,241,0.15)" strokeWidth="3"/>
                <circle cx="18" cy="18" r="15.9155" fill="none" stroke="#3b82f6" strokeWidth="3"
                        strokeDasharray={`${systemData.cpu_usage} 100`} strokeLinecap="round"
                        style={{ transform: 'rotate(-90deg)', transformOrigin: '50% 50%' }}/>
                <text x="18" y="19.5" textAnchor="middle" fontSize="10" fontWeight="700" fill="currentColor">{Math.round(systemData.cpu_usage)}%</text>
              </svg>
              <div className="flex-1 space-y-2 min-w-0">
                <div>
                  <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">User</span>
                  <span className="font-medium font-mono whitespace-nowrap">{systemData.cpu_user !== undefined ? `${Math.round(systemData.cpu_user)}%` : '—'}</span>
                  </div>
                  <div className="mt-1 h-1.5 bg-muted rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full" style={{ width: `${systemData.cpu_user ?? 0}%` }}/>
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">System</span>
                  <span className="font-medium font-mono whitespace-nowrap">{systemData.cpu_system !== undefined ? `${Math.round(systemData.cpu_system)}%` : '—'}</span>
                  </div>
                  <div className="mt-1 h-1.5 bg-muted rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${systemData.cpu_system ?? 0}%`, background: 'rgba(99,102,241,0.55)' }}/>
                  </div>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Cores</span>
                  <span className="font-medium font-mono whitespace-nowrap">{systemData.cpu_cores ?? '—'}{systemData.cpu_threads ? `/${systemData.cpu_threads}` : ''}</span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* ── Memory (preview restyle v2: tamaño igual a System Info, bars más anchas) ── */}
        <Card
          className="bg-card border-border cursor-pointer hover:bg-white/5 transition-colors"
          onClick={() => setMemProcModalOpen(true)}
          title="View top processes by memory"
        >
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Memory</CardTitle>
            <div className="flex items-center gap-1 text-muted-foreground">
              <MemoryStick className="h-4 w-4" />
              <ChevronRight className="h-4 w-4 opacity-60" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-4">
              <svg viewBox="0 0 36 36" className="w-[72px] h-[72px] flex-shrink-0">
                <circle cx="18" cy="18" r="15.9155" fill="none" stroke="rgba(99,102,241,0.15)" strokeWidth="3"/>
                <circle cx="18" cy="18" r="15.9155" fill="none" stroke="#3b82f6" strokeWidth="3"
                        strokeDasharray={`${systemData.memory_usage} 100`} strokeLinecap="round"
                        style={{ transform: 'rotate(-90deg)', transformOrigin: '50% 50%' }}/>
                <text x="18" y="19.5" textAnchor="middle" fontSize="10" fontWeight="700" fill="currentColor">{Math.round(systemData.memory_usage)}%</text>
              </svg>
              <div className="flex-1 space-y-2 min-w-0">
                <div>
                  <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Used</span>
                  <span className="font-medium font-mono whitespace-nowrap">{systemData.memory_used.toFixed(1)}</span>
                  </div>
                  <div className="mt-1 h-1.5 bg-muted rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full" style={{ width: `${systemData.memory_usage}%` }}/>
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Cached</span>
                  <span className="font-medium font-mono whitespace-nowrap">{systemData.memory_cached !== undefined ? systemData.memory_cached.toFixed(1) : '—'}</span>
                  </div>
                  <div className="mt-1 h-1.5 bg-muted rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${systemData.memory_cached !== undefined && systemData.memory_total > 0 ? (systemData.memory_cached / systemData.memory_total) * 100 : 0}%`, background: 'rgba(99,102,241,0.55)' }}/>
                  </div>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Total</span>
                  <span className="font-medium font-mono whitespace-nowrap">{systemData.memory_total.toFixed(0)} GB</span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* ── Active VM & LXC (preview restyle v2: pills mismo tamaño que "X running") ── */}
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Active VM &amp; LXC</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {loadingStates.vms ? (
              <div className="space-y-2 animate-pulse">
                <div className="h-10 bg-muted rounded w-20"></div>
                <div className="h-5 bg-muted rounded w-32"></div>
              </div>
            ) : (
              <>
                <div className="flex items-end justify-between">
                  <div>
                    <span className="text-4xl font-bold leading-none text-foreground">{vmStats.running}</span>
                    <span className="text-lg font-medium ml-1 text-muted-foreground">/ {vmStats.vms + vmStats.lxc}</span>
                  </div>
                  <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">{vmStats.running} running</Badge>
                </div>
                <div className="mt-3 flex gap-1 flex-wrap">
                  <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">{vmStats.vms} VMs</Badge>
                  <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">{vmStats.lxc} LXC</Badge>
                  {vmStats.stopped > 0 && (
                    <Badge variant="outline" className="bg-muted text-muted-foreground border-border">{vmStats.stopped} stopped</Badge>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card 
          className={`bg-card border-border ${systemData.temperature > 0 ? "cursor-pointer hover:bg-white/5 transition-colors" : ""}`}
          onClick={() => systemData.temperature > 0 && setTempModalOpen(true)}
        >
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Temperature</CardTitle>
            <Thermometer className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <span className="text-xl lg:text-2xl font-bold text-foreground">
                {systemData.temperature === 0 ? "N/A" : `${Math.round(systemData.temperature * 10) / 10}°C`}
              </span>
              <Badge variant="outline" className={`${tempStatus.color}`}>
                {tempStatus.status}
              </Badge>
            </div>
            {systemData.temperature > 0 && systemData.temperature_sparkline && systemData.temperature_sparkline.length > 1 ? (
              <div className="mt-2 h-10">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={systemData.temperature_sparkline} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="tempSparkGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={systemData.temperature >= 75 ? "#ef4444" : systemData.temperature >= 60 ? "#f59e0b" : "#22c55e"} stopOpacity={0.3} />
                        <stop offset="100%" stopColor={systemData.temperature >= 75 ? "#ef4444" : systemData.temperature >= 60 ? "#f59e0b" : "#22c55e"} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <Area
                      type="monotone"
                      dataKey="value"
                      stroke={systemData.temperature >= 75 ? "#ef4444" : systemData.temperature >= 60 ? "#f59e0b" : "#22c55e"}
                      strokeWidth={1.5}
                      fill="url(#tempSparkGradient)"
                      dot={false}
                      isAnimationActive={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground mt-2">
                {systemData.temperature === 0 ? "No sensor available" : "Collecting data..."}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <TemperatureDetailModal
        open={tempModalOpen}
        onOpenChange={setTempModalOpen}
        liveTemperature={systemData.temperature}
      />

      <ProcessDetailModal
        open={cpuProcModalOpen}
        onOpenChange={setCpuProcModalOpen}
        sort="cpu"
      />

      <ProcessDetailModal
        open={memProcModalOpen}
        onOpenChange={setMemProcModalOpen}
        sort="mem"
      />

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
                          {formatStorage(totalCapacity)}
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
                              {formatStorage(totalUsed)}
                            </span>
                          </span>
                          <span className="text-xs text-muted-foreground">
                            Free:{" "}
                            <span className="font-semibold text-green-500">
                              {formatStorage(totalAvailable)}
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
                        {formatStorage(vmLxcStorageUsed)}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-muted-foreground">Available:</span>
                      <span className="text-sm font-semibold text-green-500">
                        {formatStorage(vmLxcStorageAvailable)}
                      </span>
                    </div>
                    <Progress value={vmLxcStoragePercent} className="mt-2 [&>div]:bg-blue-500" />
                    <div className="flex justify-between items-center mt-1">
                      <span className="text-xs text-muted-foreground">
                        {formatStorage(vmLxcStorageUsed)} /{" "}
                        {formatStorage(vmLxcStorageTotal)}
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
                        {formatStorage(localStorage.used)}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-muted-foreground">Available:</span>
                      <span className="text-sm font-semibold text-green-500">
                        {formatStorage(localStorage.available)}
                      </span>
                    </div>
                    <Progress value={localStorage.percent} className="mt-2 [&>div]:bg-purple-500" />
                    <div className="flex justify-between items-center mt-1">
                      <span className="text-xs text-muted-foreground">
                        {formatStorage(localStorage.used)} /{" "}
                        {formatStorage(localStorage.total)}
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
