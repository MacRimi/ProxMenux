"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { Cpu, MemoryStick, Thermometer, Server, Zap, AlertCircle, HardDrive, Network } from "lucide-react"

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
}

const fetchSystemData = async (): Promise<SystemData | null> => {
  try {
    const baseUrl = typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""
    const apiUrl = `${baseUrl}/api/system`

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
    return data
  } catch (error) {
    console.error("[v0] Failed to fetch system data:", error)
    return null
  }
}

const fetchVMData = async (): Promise<VMData[]> => {
  try {
    const baseUrl = typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""
    const apiUrl = `${baseUrl}/api/vms`

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
    return Array.isArray(data) ? data : data.vms || []
  } catch (error) {
    console.error("[v0] Failed to fetch VM data:", error)
    return []
  }
}

const fetchStorageData = async (): Promise<StorageData | null> => {
  try {
    const baseUrl = typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""
    const apiUrl = `${baseUrl}/api/storage`

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
    return data
  } catch (error) {
    console.error("[v0] Failed to fetch storage data:", error)
    return null
  }
}

const fetchNetworkData = async (): Promise<NetworkData | null> => {
  try {
    const baseUrl = typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""
    const apiUrl = `${baseUrl}/api/network`

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
    return data
  } catch (error) {
    console.error("[v0] Failed to fetch network data:", error)
    return null
  }
}

export function SystemOverview() {
  const [systemData, setSystemData] = useState<SystemData | null>(null)
  const [vmData, setVmData] = useState<VMData[]>([])
  const [storageData, setStorageData] = useState<StorageData | null>(null)
  const [networkData, setNetworkData] = useState<NetworkData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true)
        setError(null)

        const [systemResult, vmResult, storageResult, networkResult] = await Promise.all([
          fetchSystemData(),
          fetchVMData(),
          fetchStorageData(),
          fetchNetworkData(),
        ])

        if (!systemResult) {
          setError("Flask server not available. Please ensure the server is running.")
          setLoading(false)
          return
        }

        setSystemData(systemResult)
        setVmData(vmResult)
        setStorageData(storageResult)
        setNetworkData(networkResult)
      } catch (err) {
        console.error("[v0] Error fetching data:", err)
        setError("Failed to connect to Flask server. Please check your connection.")
      } finally {
        setLoading(false)
      }
    }

    fetchData()

    const interval = setInterval(() => {
      fetchData()
    }, 60000) // Update every 60 seconds instead of 30

    return () => {
      clearInterval(interval)
    }
  }, [])

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8">
          <div className="text-lg font-medium text-foreground mb-2">Connecting to ProxMenux Monitor...</div>
          <div className="text-sm text-muted-foreground">Fetching real-time system data</div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
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

  const tempStatus = getTemperatureStatus(systemData.temperature)

  return (
    <div className="space-y-6">
      {/* Key Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">CPU Usage</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{systemData.cpu_usage}%</div>
            <Progress value={systemData.cpu_usage} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2">Real-time data from Flask server</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Memory Usage</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{systemData.memory_used.toFixed(1)} GB</div>
            <Progress value={systemData.memory_usage} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2">
              {systemData.memory_usage.toFixed(1)}% of {systemData.memory_total} GB
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Temperature</CardTitle>
            <Thermometer className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">
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

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Active VM & LXC</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{vmStats.running}</div>
            <div className="mt-2 flex flex-wrap gap-1">
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                {vmStats.running} Running
              </Badge>
              {vmStats.stopped > 0 && (
                <Badge variant="outline" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                  {vmStats.stopped} Stopped
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              Total: {vmStats.vms} VMs, {vmStats.lxc} LXC
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Storage Summary */}
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <HardDrive className="h-5 w-5 mr-2" />
              Storage Overview
            </CardTitle>
          </CardHeader>
          <CardContent>
            {storageData ? (
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Total Storage:</span>
                  <span className="text-lg font-semibold text-foreground">{storageData.total} GB</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Used:</span>
                  <span className="text-lg font-semibold text-foreground">{storageData.used} GB</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Available:</span>
                  <span className="text-lg font-semibold text-green-500">{storageData.available} GB</span>
                </div>
                <Progress value={(storageData.used / storageData.total) * 100} className="mt-2" />
                <div className="pt-2 border-t border-border">
                  <p className="text-xs text-muted-foreground">
                    {storageData.disks.length} disk{storageData.disks.length !== 1 ? "s" : ""} configured
                  </p>
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">Storage data not available</div>
            )}
          </CardContent>
        </Card>

        {/* Network Summary */}
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Network className="h-5 w-5 mr-2" />
              Network Overview
            </CardTitle>
          </CardHeader>
          <CardContent>
            {networkData ? (
              <div className="space-y-4">
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Active Interfaces:</span>
                  <span className="text-lg font-semibold text-foreground">
                    {networkData.interfaces.filter((i) => i.status === "up").length}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Data Sent:</span>
                  <span className="text-lg font-semibold text-foreground">
                    {(networkData.traffic.bytes_sent / 1024 ** 3).toFixed(2)} GB
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Data Received:</span>
                  <span className="text-lg font-semibold text-foreground">
                    {(networkData.traffic.bytes_recv / 1024 ** 3).toFixed(2)} GB
                  </span>
                </div>
                <div className="pt-2 border-t border-border space-y-1">
                  {networkData.interfaces.slice(0, 3).map((iface) => (
                    <div key={iface.name} className="flex justify-between items-center">
                      <span className="text-xs text-muted-foreground">{iface.name}:</span>
                      <Badge
                        variant="outline"
                        className={
                          iface.status === "up"
                            ? "bg-green-500/10 text-green-500 border-green-500/20"
                            : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                        }
                      >
                        {iface.status}
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">Network data not available</div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* System Information */}
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
              Performance Metrics
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between items-start">
              <div className="flex flex-col">
                <span className="text-muted-foreground">Load Average:</span>
                <span className="text-xs text-muted-foreground">(1m, 5m, 15m)</span>
              </div>
              <span className="text-foreground font-mono">
                {systemData.load_average.map((avg) => avg.toFixed(2)).join(", ")}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Total Memory:</span>
              <span className="text-foreground">{systemData.memory_total} GB</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Available Memory:</span>
              <span className="text-foreground">
                {(systemData.memory_total - systemData.memory_used).toFixed(1)} GB
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">CPU Cores:</span>
              <span className="text-foreground">{systemData.cpu_cores || "N/A"}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
