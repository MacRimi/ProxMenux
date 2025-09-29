"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts"
import { Cpu, MemoryStick, Thermometer, Users, Activity, Server, Zap, AlertCircle } from "lucide-react"

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
  const [isDemo, setIsDemo] = useState(false) // Added demo mode state

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true)

        const [systemResult, vmResult] = await Promise.all([fetchSystemData(), fetchVMData()])

        setSystemData(systemResult.data)
        setVmData(vmResult.data)
        setIsDemo(systemResult.isDemo || vmResult.isDemo) // Set demo mode if either fetch is demo

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
      } finally {
        setLoading(false)
      }
    }

    fetchData()

    const interval = setInterval(() => {
      if (!isDemo) {
        fetchData()
      } else {
        // In demo mode, just update with new random data
        const newDemoData = generateDemoSystemData()
        setSystemData(newDemoData)
        setChartData(generateChartData(newDemoData))
      }
    }, 5000) // Update every 5 seconds instead of 30

    return () => {
      clearInterval(interval)
    }
  }, [isDemo])

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

  if (!systemData) return null

  const vmStats = {
    total: vmData.length,
    running: vmData.filter((vm) => vm.status === "running").length,
    stopped: vmData.filter((vm) => vm.status === "stopped").length,
    lxc: 0,
  }

  const getTemperatureStatus = (temp: number) => {
    if (temp < 60) return { status: "Normal", color: "bg-green-500/10 text-green-500 border-green-500/20" }
    if (temp < 75) return { status: "Warm", color: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20" }
    return { status: "Hot", color: "bg-red-500/10 text-red-500 border-red-500/20" }
  }

  const tempStatus = getTemperatureStatus(systemData.temperature)

  return (
    <div className="space-y-6">
      {isDemo && (
        <Card className="bg-blue-500/10 border-blue-500/20">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-sm text-blue-600">
              <AlertCircle className="h-4 w-4" />
              <span>
                <strong>Demo Mode:</strong> Flask server not available. Showing simulated data for development. In the
                AppImage, this will connect to the real Flask server.
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Key Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border metric-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">CPU Usage</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground metric-value">{systemData.cpu_usage}%</div>
            <Progress value={systemData.cpu_usage} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2 metric-label">
              {isDemo ? "Simulated data" : "Real-time data from Flask server"}
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Memory Usage</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground metric-value">
              {systemData.memory_used.toFixed(1)} GB
            </div>
            <Progress value={systemData.memory_usage} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2 metric-label">
              {systemData.memory_usage.toFixed(1)}% of {systemData.memory_total} GB
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Temperature</CardTitle>
            <Thermometer className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground metric-value">{systemData.temperature}°C</div>
            <div className="flex items-center mt-2">
              <Badge variant="outline" className={tempStatus.color}>
                {tempStatus.status}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2 metric-label">
              {isDemo ? "Simulated temperature" : "Live temperature reading"}
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Active VMs</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground metric-value">{vmStats.running}</div>
            <div className="vm-badges mt-2 flex flex-wrap gap-1">
              <Badge variant="outline" className="vm-badge bg-green-500/10 text-green-500 border-green-500/20">
                {vmStats.running} Running
              </Badge>
              {vmStats.stopped > 0 && (
                <Badge variant="outline" className="vm-badge bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                  {vmStats.stopped} Stopped
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-2 metric-label">Total: {vmStats.total} VMs configured</p>
          </CardContent>
        </Card>
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-card border-border metric-card">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Activity className="h-5 w-5 mr-2" />
              CPU Usage (24h)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={chartData.cpuData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                    color: "hsl(var(--foreground))",
                  }}
                />
                <Area type="monotone" dataKey="value" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.2} />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <MemoryStick className="h-5 w-5 mr-2" />
              Memory Usage (24h)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={chartData.memoryData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                    color: "hsl(var(--foreground))",
                  }}
                />
                <Area type="monotone" dataKey="used" stackId="1" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.6} />
                <Area
                  type="monotone"
                  dataKey="available"
                  stackId="1"
                  stroke="#10b981"
                  fill="#10b981"
                  fillOpacity={0.6}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* System Information */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="bg-card border-border metric-card">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Server className="h-5 w-5 mr-2" />
              System Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Hostname:</span>
              <span className="text-foreground font-mono metric-value">{systemData.hostname}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Uptime:</span>
              <span className="text-foreground metric-value">{systemData.uptime}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Node ID:</span>
              <span className="text-foreground font-mono metric-value">{systemData.node_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Last Update:</span>
              <span className="text-foreground metric-value">
                {new Date(systemData.timestamp).toLocaleTimeString()}
              </span>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Users className="h-5 w-5 mr-2" />
              Active Sessions
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-muted-foreground metric-label">Web Console:</span>
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                3 active
              </Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-muted-foreground metric-label">SSH Sessions:</span>
              <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">
                1 active
              </Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">API Calls:</span>
              <span className="text-foreground metric-value">247/hour</span>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Zap className="h-5 w-5 mr-2" />
              Power & Performance
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Power State:</span>
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                Running
              </Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Load Average:</span>
              <span className="text-foreground font-mono metric-value">
                {systemData.load_average.map((avg) => avg.toFixed(2)).join(", ")}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Boot Time:</span>
              <span className="text-foreground metric-value">2.3s</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
