"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts"
import { Cpu, MemoryStick, Thermometer, Users, Activity, Server, Zap, AlertCircle, RefreshCw } from "lucide-react"

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
}

const generateDemoSystemData = (): SystemData => ({
  cpu_usage: Math.floor(Math.random() * 20) + 60, // 60-80%
  memory_usage: Math.floor(Math.random() * 10) + 45, // 45-55%
  memory_total: 32.0,
  memory_used: 15.8 + Math.random() * 2, // 15.8-17.8 GB
  temperature: Math.floor(Math.random() * 8) + 48, // 48-56°C
  uptime: "15d 7h 23m",
  load_average: [1.23, 1.45, 1.67],
  hostname: "proxmox-demo",
  node_id: "pve-demo-node",
  timestamp: new Date().toISOString(),
})

const demVMData: VMData[] = [
  {
    vmid: 100,
    name: "web-server-01",
    status: "running",
    cpu: 0.45,
    mem: 8589934592,
    maxmem: 17179869184,
    disk: 53687091200,
    maxdisk: 107374182400,
    uptime: 1324800,
  },
  {
    vmid: 101,
    name: "database-server",
    status: "running",
    cpu: 0.23,
    mem: 4294967296,
    maxmem: 8589934592,
    disk: 26843545600,
    maxdisk: 53687091200,
    uptime: 864000,
  },
  {
    vmid: 102,
    name: "backup-server",
    status: "stopped",
    cpu: 0,
    mem: 0,
    maxmem: 4294967296,
    disk: 10737418240,
    maxdisk: 21474836480,
    uptime: 0,
  },
]

const fetchSystemData = async (): Promise<{ data: SystemData | null; isDemo: boolean }> => {
  try {
    console.log("[v0] Attempting to fetch system data from Flask server...")
    const response = await fetch("/api/system", {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      signal: AbortSignal.timeout(3000), // Reduced timeout for faster fallback
    })

    if (!response.ok) {
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const data = await response.json()
    console.log("[v0] Successfully fetched real system data from Flask:", data)
    return { data, isDemo: false }
  } catch (error) {
    console.log("[v0] Flask server not available, using demo data for development")
    return { data: generateDemoSystemData(), isDemo: true }
  }
}

const fetchVMData = async (): Promise<{ data: VMData[]; isDemo: boolean }> => {
  try {
    console.log("[v0] Attempting to fetch VM data from Flask server...")
    const response = await fetch("/api/vms", {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      signal: AbortSignal.timeout(3000), // Reduced timeout for faster fallback
    })

    if (!response.ok) {
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const data = await response.json()
    console.log("[v0] Successfully fetched VM data from Flask:", data)
    return { data: data.vms || [], isDemo: false }
  } catch (error) {
    console.log("[v0] Flask server not available, using demo VM data")
    return { data: demVMData, isDemo: true }
  }
}

const generateChartData = (systemData?: SystemData) => {
  const cpuData = []
  const memoryData = []

  for (let i = 0; i < 24; i += 4) {
    const time = `${i.toString().padStart(2, "0")}:00`
    // Use real CPU data as base if available, otherwise use random data
    const baseCpu = systemData?.cpu_usage || 60
    cpuData.push({
      time,
      value: Math.max(0, Math.min(100, baseCpu + (Math.random() - 0.5) * 20)),
    })

    // Use real memory data as base if available
    const baseMemory = systemData?.memory_used || 15.8
    const totalMemory = systemData?.memory_total || 32
    memoryData.push({
      time,
      used: Math.max(0, baseMemory + (Math.random() - 0.5) * 4),
      available: Math.max(0, totalMemory - (baseMemory + (Math.random() - 0.5) * 4)),
    })
  }

  return { cpuData, memoryData }
}

export function SystemOverview() {
  const [systemData, setSystemData] = useState<SystemData | null>(null)
  const [vmData, setVmData] = useState<VMData[]>([])
  const [chartData, setChartData] = useState(generateChartData())
  const [loading, setLoading] = useState(true)
  const [isDemo, setIsDemo] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date())

  const fetchData = async () => {
    try {
      setIsRefreshing(true)

      const [systemResult, vmResult] = await Promise.all([fetchSystemData(), fetchVMData()])

      setSystemData(systemResult.data)
      setVmData(vmResult.data)
      setIsDemo(systemResult.isDemo || vmResult.isDemo)
      setLastUpdate(new Date())

      if (systemResult.data) {
        setChartData(generateChartData(systemResult.data))
      }
    } catch (err) {
      console.error("[v0] Error fetching data:", err)
      const fallbackData = generateDemoSystemData()
      setSystemData(fallbackData)
      setVmData(demVMData)
      setChartData(generateChartData(fallbackData))
      setIsDemo(true)
      setLastUpdate(new Date())
    } finally {
      setLoading(false)
      setIsRefreshing(false)
    }
  }

  const handleManualRefresh = () => {
    fetchData()
  }

  useEffect(() => {
    fetchData()

    const interval = setInterval(() => {
      if (!isDemo) {
        fetchData()
      } else {
        const newDemoData = generateDemoSystemData()
        setSystemData(newDemoData)
        setChartData(generateChartData(newDemoData))
        setLastUpdate(new Date())
      }
    }, 30000)

    return () => {
      clearInterval(interval)
    }
  }, [isDemo])

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-6">
        <div className="max-w-7xl mx-auto space-y-6">
          <div className="text-center py-12">
            <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-500/10 rounded-full mb-4">
              <Server className="w-8 h-8 text-blue-500 animate-pulse" />
            </div>
            <div className="text-2xl font-bold text-white mb-2">Connecting to ProxMenux Monitor...</div>
            <div className="text-slate-400">Fetching real-time system data</div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {[...Array(4)].map((_, i) => (
              <Card key={i} className="bg-slate-800/50 border-slate-700 backdrop-blur-sm animate-pulse">
                <CardContent className="p-6">
                  <div className="h-4 bg-slate-700 rounded w-1/2 mb-4"></div>
                  <div className="h-8 bg-slate-700 rounded w-3/4 mb-2"></div>
                  <div className="h-2 bg-slate-700 rounded w-full mb-2"></div>
                  <div className="h-3 bg-slate-700 rounded w-2/3"></div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </div>
    )
  }

  if (!systemData) return null

  const vmStats = {
    total: vmData.length,
    running: vmData.filter((vm) => vm.status === "running").length,
    stopped: vmData.filter((vm) => vm.status === "stopped").length,
    lxc: 0,
  }

  const getTemperatureStatus = (temp: number) => {
    if (temp < 60) return { status: "Normal", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" }
    if (temp < 75) return { status: "Warm", color: "bg-amber-500/10 text-amber-400 border-amber-500/20" }
    return { status: "Hot", color: "bg-red-500/10 text-red-400 border-red-500/20" }
  }

  const tempStatus = getTemperatureStatus(systemData.temperature)

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-white mb-2">ProxMenux System Dashboard</h1>
            <p className="text-slate-400">Last updated: {lastUpdate.toLocaleTimeString()} • Auto-refresh every 30s</p>
          </div>
          <Button
            onClick={handleManualRefresh}
            disabled={isRefreshing}
            className="bg-blue-600 hover:bg-blue-700 text-white border-0"
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${isRefreshing ? "animate-spin" : ""}`} />
            {isRefreshing ? "Refreshing..." : "Refresh"}
          </Button>
        </div>

        {isDemo && (
          <Card className="bg-blue-500/10 border-blue-500/20 backdrop-blur-sm">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 text-sm text-blue-400">
                <AlertCircle className="h-4 w-4" />
                <span>
                  <strong>Demo Mode:</strong> Flask server not available. Showing simulated data for development. In the
                  AppImage, this will connect to the real Flask server.
                </span>
              </div>
            </CardContent>
          </Card>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm hover:bg-slate-800/70 transition-all duration-200">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-slate-400">CPU Usage</CardTitle>
              <div className="p-2 bg-blue-500/10 rounded-lg">
                <Cpu className="h-4 w-4 text-blue-400" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-white mb-2">{systemData.cpu_usage}%</div>
              <Progress value={systemData.cpu_usage} className="mt-2 h-2" />
              <p className="text-xs text-slate-400 mt-2">
                {isDemo ? "Simulated data" : "Real-time data from Flask server"}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm hover:bg-slate-800/70 transition-all duration-200">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-slate-400">Memory Usage</CardTitle>
              <div className="p-2 bg-emerald-500/10 rounded-lg">
                <MemoryStick className="h-4 w-4 text-emerald-400" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-white mb-2">{systemData.memory_used.toFixed(1)} GB</div>
              <Progress value={systemData.memory_usage} className="mt-2 h-2" />
              <p className="text-xs text-slate-400 mt-2">
                {systemData.memory_usage.toFixed(1)}% of {systemData.memory_total} GB
              </p>
            </CardContent>
          </Card>

          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm hover:bg-slate-800/70 transition-all duration-200">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-slate-400">Temperature</CardTitle>
              <div className="p-2 bg-orange-500/10 rounded-lg">
                <Thermometer className="h-4 w-4 text-orange-400" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-white mb-2">{systemData.temperature}°C</div>
              <div className="flex items-center mt-2">
                <Badge variant="outline" className={tempStatus.color}>
                  {tempStatus.status}
                </Badge>
              </div>
              <p className="text-xs text-slate-400 mt-2">
                {isDemo ? "Simulated temperature" : "Live temperature reading"}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm hover:bg-slate-800/70 transition-all duration-200">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-slate-400">Active VMs</CardTitle>
              <div className="p-2 bg-purple-500/10 rounded-lg">
                <Server className="h-4 w-4 text-purple-400" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-white mb-2">{vmStats.running}</div>
              <div className="flex flex-wrap gap-1 mt-2">
                <Badge variant="outline" className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
                  {vmStats.running} Running
                </Badge>
                {vmStats.stopped > 0 && (
                  <Badge variant="outline" className="bg-amber-500/10 text-amber-400 border-amber-500/20">
                    {vmStats.stopped} Stopped
                  </Badge>
                )}
              </div>
              <p className="text-xs text-slate-400 mt-2">Total: {vmStats.total} VMs configured</p>
            </CardContent>
          </Card>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm">
            <CardHeader>
              <CardTitle className="text-white flex items-center">
                <div className="p-2 bg-blue-500/10 rounded-lg mr-3">
                  <Activity className="h-5 w-5 text-blue-400" />
                </div>
                CPU Usage (24h)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={chartData.cpuData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="time" stroke="#9CA3AF" fontSize={12} />
                  <YAxis stroke="#9CA3AF" fontSize={12} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1F2937",
                      border: "1px solid #374151",
                      borderRadius: "8px",
                      color: "#F9FAFB",
                    }}
                  />
                  <Area type="monotone" dataKey="value" stroke="#3B82F6" fill="#3B82F6" fillOpacity={0.3} />
                </AreaChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm">
            <CardHeader>
              <CardTitle className="text-white flex items-center">
                <div className="p-2 bg-emerald-500/10 rounded-lg mr-3">
                  <MemoryStick className="h-5 w-5 text-emerald-400" />
                </div>
                Memory Usage (24h)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={chartData.memoryData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="time" stroke="#9CA3AF" fontSize={12} />
                  <YAxis stroke="#9CA3AF" fontSize={12} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1F2937",
                      border: "1px solid #374151",
                      borderRadius: "8px",
                      color: "#F9FAFB",
                    }}
                  />
                  <Area type="monotone" dataKey="used" stackId="1" stroke="#3B82F6" fill="#3B82F6" fillOpacity={0.6} />
                  <Area
                    type="monotone"
                    dataKey="available"
                    stackId="1"
                    stroke="#10B981"
                    fill="#10B981"
                    fillOpacity={0.6}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm">
            <CardHeader>
              <CardTitle className="text-white flex items-center">
                <div className="p-2 bg-blue-500/10 rounded-lg mr-3">
                  <Server className="h-5 w-5 text-blue-400" />
                </div>
                System Information
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Hostname:</span>
                <span className="text-white font-mono bg-slate-700/50 px-2 py-1 rounded text-sm">
                  {systemData.hostname}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Uptime:</span>
                <span className="text-white font-semibold">{systemData.uptime}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Node ID:</span>
                <span className="text-white font-mono bg-slate-700/50 px-2 py-1 rounded text-sm">
                  {systemData.node_id}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Status:</span>
                <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">healthy</Badge>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm">
            <CardHeader>
              <CardTitle className="text-white flex items-center">
                <div className="p-2 bg-emerald-500/10 rounded-lg mr-3">
                  <Users className="h-5 w-5 text-emerald-400" />
                </div>
                Active Sessions
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Web Console:</span>
                <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">3 active</Badge>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">SSH Sessions:</span>
                <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20">1 active</Badge>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">API Calls:</span>
                <span className="text-white font-semibold">247/hour</span>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-slate-800/50 border-slate-700 backdrop-blur-sm">
            <CardHeader>
              <CardTitle className="text-white flex items-center">
                <div className="p-2 bg-amber-500/10 rounded-lg mr-3">
                  <Zap className="h-5 w-5 text-amber-400" />
                </div>
                Power & Performance
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Power State:</span>
                <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">Running</Badge>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Load Average:</span>
                <span className="text-white font-mono bg-slate-700/50 px-2 py-1 rounded text-sm">
                  {systemData.load_average.map((avg) => avg.toFixed(2)).join(", ")}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-400">Boot Time:</span>
                <span className="text-white font-semibold">2.3s</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
