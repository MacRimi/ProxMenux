"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts"
import { Cpu, MemoryStick, Thermometer, Activity, Server, Zap, AlertCircle } from "lucide-react"

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
  type?: string
}

interface HistoricalData {
  timestamp: string
  cpu_usage: number
  memory_used: number
  memory_total: number
}

const historicalDataStore: HistoricalData[] = []
const MAX_HISTORICAL_POINTS = 24 // Store 24 data points for 24h view

const fetchSystemData = async (): Promise<SystemData | null> => {
  try {
    console.log("[v0] Fetching system data from Flask server...")

    const baseUrl = typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""
    const apiUrl = `${baseUrl}/api/system`
    console.log("[v0] Fetching from URL:", apiUrl)

    const response = await fetch(apiUrl, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      cache: "no-store",
    })

    console.log("[v0] Response status:", response.status)
    console.log("[v0] Response ok:", response.ok)
    console.log("[v0] Response headers:", Object.fromEntries(response.headers.entries()))

    if (!response.ok) {
      const errorText = await response.text()
      console.error("[v0] Flask server error response:", errorText)
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const responseText = await response.text()
    console.log("[v0] Raw response text:", responseText)
    console.log("[v0] Response text length:", responseText.length)
    console.log("[v0] First 100 chars:", responseText.substring(0, 100))

    // Try to parse the JSON
    let data
    try {
      data = JSON.parse(responseText)
      console.log("[v0] Successfully parsed JSON:", data)
    } catch (parseError) {
      console.error("[v0] JSON parse error:", parseError)
      console.error("[v0] Failed to parse response as JSON")
      throw new Error("Invalid JSON response from server")
    }

    // Store historical data
    historicalDataStore.push({
      timestamp: data.timestamp,
      cpu_usage: data.cpu_usage,
      memory_used: data.memory_used,
      memory_total: data.memory_total,
    })

    // Keep only last MAX_HISTORICAL_POINTS
    if (historicalDataStore.length > MAX_HISTORICAL_POINTS) {
      historicalDataStore.shift()
    }

    return data
  } catch (error) {
    console.error("[v0] Failed to fetch system data from Flask server:", error)
    console.error("[v0] Error type:", error instanceof Error ? error.constructor.name : typeof error)
    console.error("[v0] Error message:", error instanceof Error ? error.message : String(error))
    console.error("[v0] Error stack:", error instanceof Error ? error.stack : "No stack trace")
    return null
  }
}

const fetchVMData = async (): Promise<VMData[]> => {
  try {
    console.log("[v0] Fetching VM data from Flask server...")

    const baseUrl = typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""
    const apiUrl = `${baseUrl}/api/vms`
    console.log("[v0] Fetching from URL:", apiUrl)

    const response = await fetch(apiUrl, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      cache: "no-store",
    })

    console.log("[v0] VM Response status:", response.status)

    if (!response.ok) {
      const errorText = await response.text()
      console.error("[v0] Flask server error response:", errorText)
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const data = await response.json()
    console.log("[v0] Successfully fetched VM data from Flask:", data)
    return Array.isArray(data) ? data : data.vms || []
  } catch (error) {
    console.error("[v0] Failed to fetch VM data from Flask server:", error)
    console.error("[v0] Error type:", error instanceof Error ? error.constructor.name : typeof error)
    console.error("[v0] Error message:", error instanceof Error ? error.message : String(error))
    return []
  }
}

const generateChartData = () => {
  if (historicalDataStore.length === 0) {
    return { cpuData: [], memoryData: [] }
  }

  const cpuData = historicalDataStore.map((point) => ({
    time: new Date(point.timestamp).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
    value: point.cpu_usage,
  }))

  const memoryData = historicalDataStore.map((point) => ({
    time: new Date(point.timestamp).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
    used: point.memory_used,
    available: point.memory_total - point.memory_used,
  }))

  return { cpuData, memoryData }
}

export function SystemOverview() {
  const [systemData, setSystemData] = useState<SystemData | null>(null)
  const [vmData, setVmData] = useState<VMData[]>([])
  const [chartData, setChartData] = useState(generateChartData())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true)
        setError(null)

        const [systemResult, vmResult] = await Promise.all([fetchSystemData(), fetchVMData()])

        if (!systemResult) {
          setError("Flask server not available. Please ensure the server is running.")
          setLoading(false)
          return
        }

        setSystemData(systemResult)
        setVmData(vmResult)
        setChartData(generateChartData())
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
    }, 30000) // Update every 30 seconds

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
                <div className="text-sm mt-2">
                  <strong>Troubleshooting:</strong>
                  <ul className="list-disc list-inside mt-1 space-y-1">
                    <li>Check if the Flask server is running on the correct port</li>
                    <li>Verify network connectivity</li>
                    <li>Check server logs for errors</li>
                  </ul>
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

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Activity className="h-5 w-5 mr-2" />
              CPU Usage (Last {historicalDataStore.length} readings)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {chartData.cpuData.length > 0 ? (
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
            ) : (
              <div className="h-[300px] flex items-center justify-center text-muted-foreground">
                Collecting data... Check back in a few minutes
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <MemoryStick className="h-5 w-5 mr-2" />
              Memory Usage (Last {historicalDataStore.length} readings)
            </CardTitle>
          </CardHeader>
          <CardContent>
            {chartData.memoryData.length > 0 ? (
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
            ) : (
              <div className="h-[300px] flex items-center justify-center text-muted-foreground">
                Collecting data... Check back in a few minutes
              </div>
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
              <span className="text-muted-foreground">Hostname:</span>
              <span className="text-foreground font-mono">{systemData.hostname}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Uptime:</span>
              <span className="text-foreground">{systemData.uptime}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Node ID:</span>
              <span className="text-foreground font-mono">{systemData.node_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Last Update:</span>
              <span className="text-foreground">{new Date(systemData.timestamp).toLocaleTimeString()}</span>
            </div>
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
            <div className="flex justify-between">
              <span className="text-muted-foreground">Load Average:</span>
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
              <span className="text-foreground">{navigator.hardwareConcurrency || "N/A"}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
