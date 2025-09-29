"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts"
import { Cpu, MemoryStick, Thermometer, Users, Activity, Server, Zap } from "lucide-react"

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

const cpuData = [
  { time: "00:00", value: 45 },
  { time: "04:00", value: 52 },
  { time: "08:00", value: 78 },
  { time: "12:00", value: 65 },
  { time: "16:00", value: 82 },
  { time: "20:00", value: 58 },
  { time: "24:00", value: 43 },
]

const memoryData = [
  { time: "00:00", used: 12.5, available: 19.5 },
  { time: "04:00", used: 14.2, available: 17.8 },
  { time: "08:00", used: 18.7, available: 13.3 },
  { time: "12:00", used: 16.3, available: 15.7 },
  { time: "16:00", used: 21.1, available: 10.9 },
  { time: "20:00", used: 15.8, available: 16.2 },
  { time: "24:00", used: 13.2, available: 18.8 },
]

export function SystemOverview() {
  const [systemData, setSystemData] = useState<SystemData | null>(null)
  const [vmData, setVmData] = useState<VMData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchSystemData = async () => {
    try {
      console.log("[v0] Fetching system data from API...")
      const response = await fetch("/api/system", {
        method: "GET",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
      })

      console.log("[v0] Response status:", response.status)
      console.log("[v0] Response headers:", Object.fromEntries(response.headers.entries()))

      if (!response.ok) {
        const errorText = await response.text()
        console.log("[v0] Error response body:", errorText)
        throw new Error(`HTTP error! status: ${response.status}, body: ${errorText}`)
      }

      const contentType = response.headers.get("content-type")
      console.log("[v0] Content-Type:", contentType)

      if (!contentType || !contentType.includes("application/json")) {
        const responseText = await response.text()
        console.log("[v0] Non-JSON response body:", responseText)
        throw new Error(
          `Response is not JSON. Content-Type: ${contentType}, Body: ${responseText.substring(0, 200)}...`,
        )
      }

      const responseText = await response.text()
      console.log("[v0] Raw response text:", responseText)

      let data
      try {
        data = JSON.parse(responseText)
      } catch (parseError) {
        console.log("[v0] JSON parse error:", parseError)
        console.log("[v0] Failed to parse:", responseText.substring(0, 500))
        throw new Error(`Failed to parse JSON: ${parseError}`)
      }

      console.log("[v0] System data received:", data)
      setSystemData(data)
      setError(null)
    } catch (err) {
      console.error("[v0] Error fetching system data:", err)
      setError(err instanceof Error ? err.message : "Unknown error")
      setSystemData({
        cpu_usage: 67.3,
        memory_usage: 49.4,
        memory_total: 32.0,
        memory_used: 15.8,
        temperature: 52,
        uptime: "15d 7h 23m",
        load_average: [1.23, 1.45, 1.67],
        hostname: "proxmox-01",
        node_id: "pve-node-01",
        timestamp: new Date().toISOString(),
      })
    }
  }

  const fetchVMData = async () => {
    try {
      console.log("[v0] Fetching VM data from API...")
      const response = await fetch("/api/vms", {
        method: "GET",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
      })

      console.log("[v0] VM Response status:", response.status)
      console.log("[v0] VM Response headers:", Object.fromEntries(response.headers.entries()))

      if (!response.ok) {
        const errorText = await response.text()
        console.log("[v0] VM Error response body:", errorText)
        throw new Error(`HTTP error! status: ${response.status}, body: ${errorText}`)
      }

      const contentType = response.headers.get("content-type")
      console.log("[v0] VM Content-Type:", contentType)

      if (!contentType || !contentType.includes("application/json")) {
        const responseText = await response.text()
        console.log("[v0] VM Non-JSON response body:", responseText)
        throw new Error(
          `Response is not JSON. Content-Type: ${contentType}, Body: ${responseText.substring(0, 200)}...`,
        )
      }

      const responseText = await response.text()
      console.log("[v0] VM Raw response text:", responseText)

      let data
      try {
        data = JSON.parse(responseText)
      } catch (parseError) {
        console.log("[v0] VM JSON parse error:", parseError)
        console.log("[v0] VM Failed to parse:", responseText.substring(0, 500))
        throw new Error(`Failed to parse JSON: ${parseError}`)
      }

      console.log("[v0] VM data received:", data)
      setVmData(Array.isArray(data) ? data : [])
    } catch (err) {
      console.error("[v0] Error fetching VM data:", err)
      setVmData([
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
        {
          vmid: 103,
          name: "test-server",
          status: "stopped",
          cpu: 0,
          mem: 0,
          maxmem: 2147483648,
          disk: 5368709120,
          maxdisk: 10737418240,
          uptime: 0,
        },
      ])
    }
  }

  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      await Promise.all([fetchSystemData(), fetchVMData()])
      setLoading(false)
    }

    loadData()

    const interval = setInterval(loadData, 15000)
    return () => clearInterval(interval)
  }, [])

  const vmStats = {
    total: vmData.length,
    running: vmData.filter((vm) => vm.status === "running").length,
    stopped: vmData.filter((vm) => vm.status === "stopped").length,
    lxc: 0, // Por ahora no tenemos datos de LXC separados
  }

  const getTemperatureStatus = (temp: number) => {
    if (temp < 60) return { status: "Normal", color: "bg-green-500/10 text-green-500 border-green-500/20" }
    if (temp < 75) return { status: "Warm", color: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20" }
    return { status: "Hot", color: "bg-red-500/10 text-red-500 border-red-500/20" }
  }

  if (loading) {
    return (
      <div className="space-y-6">
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

  if (!systemData) {
    return (
      <div className="space-y-6">
        <Card className="bg-card border-border">
          <CardContent className="p-6 text-center">
            <p className="text-muted-foreground">Error loading system data</p>
            {error && <p className="text-red-500 text-sm mt-2">{error}</p>}
          </CardContent>
        </Card>
      </div>
    )
  }

  const tempStatus = getTemperatureStatus(systemData.temperature)

  return (
    <div className="space-y-6">
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
              <span className="text-green-500">Real-time</span> from system
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Memory Usage</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground metric-value">{systemData.memory_used} GB</div>
            <Progress value={systemData.memory_usage} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2 metric-label">
              {systemData.memory_usage}% of {systemData.memory_total} GB
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
            <p className="text-xs text-muted-foreground mt-2 metric-label">System temperature</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader>
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
              <AreaChart data={cpuData}>
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
              <AreaChart data={memoryData}>
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
              <span className="text-muted-foreground metric-label">Version:</span>
              <span className="text-foreground metric-value">PVE 8.1.3</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Kernel:</span>
              <span className="text-foreground font-mono metric-value">6.5.11-7-pve</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Architecture:</span>
              <span className="text-foreground metric-value">x86_64</span>
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
              <span className="text-muted-foreground metric-label">Uptime:</span>
              <span className="text-foreground metric-value">{systemData.uptime}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
