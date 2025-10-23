"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts"
import { Loader2, TrendingUp, MemoryStick } from "lucide-react"

const TIMEFRAME_OPTIONS = [
  { value: "hour", label: "1 Hour" },
  { value: "day", label: "24 Hours" },
  { value: "week", label: "7 Days" },
  { value: "month", label: "30 Days" },
]

interface NodeMetricsData {
  time: string
  timestamp: number
  cpu: number
  load: number
  memoryTotal: number
  memoryUsed: number
  memoryFree: number
  memoryZfsArc: number
}

export function NodeMetricsCharts() {
  const [timeframe, setTimeframe] = useState("day")
  const [data, setData] = useState<NodeMetricsData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    console.log("[v0] NodeMetricsCharts component mounted")
    fetchMetrics()
  }, [timeframe])

  const fetchMetrics = async () => {
    console.log("[v0] fetchMetrics called with timeframe:", timeframe)
    setLoading(true)
    setError(null)

    try {
      const baseUrl =
        typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""
      const apiUrl = `${baseUrl}/api/node/metrics?timeframe=${timeframe}`

      console.log("[v0] Fetching node metrics from:", apiUrl)

      const response = await fetch(apiUrl)

      console.log("[v0] Response status:", response.status)
      console.log("[v0] Response ok:", response.ok)

      if (!response.ok) {
        const errorText = await response.text()
        console.log("[v0] Error response text:", errorText)
        throw new Error(`Failed to fetch node metrics: ${response.status}`)
      }

      const result = await response.json()
      console.log("[v0] Node metrics result:", result)
      console.log("[v0] Result keys:", Object.keys(result))
      console.log("[v0] Data array length:", result.data?.length || 0)

      if (!result.data || !Array.isArray(result.data)) {
        console.error("[v0] Invalid data format - data is not an array:", result)
        throw new Error("Invalid data format received from server")
      }

      if (result.data.length === 0) {
        console.warn("[v0] No data points received")
        setData([])
        setLoading(false)
        return
      }

      console.log("[v0] First data point sample:", result.data[0])

      const transformedData = result.data.map((item: any, index: number) => {
        const date = new Date(item.time * 1000)
        let timeLabel = ""

        if (timeframe === "hour") {
          timeLabel = date.toLocaleString("en-US", {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          })
        } else if (timeframe === "day") {
          timeLabel = date.toLocaleString("en-US", {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          })
        } else if (timeframe === "week") {
          timeLabel = date.toLocaleString("en-US", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            hour12: false,
          })
        } else {
          timeLabel = date.toLocaleString("en-US", {
            month: "short",
            day: "numeric",
          })
        }

        const transformed = {
          time: timeLabel,
          timestamp: item.time,
          cpu: item.cpu ? Number((item.cpu * 100).toFixed(2)) : 0,
          load:
            item.loadavg && Array.isArray(item.loadavg) && item.loadavg.length > 0
              ? Number(item.loadavg[0].toFixed(2))
              : 0,
          memoryTotal: item.memtotal ? Number((item.memtotal / 1024 / 1024 / 1024).toFixed(2)) : 0,
          memoryUsed: item.memused ? Number((item.memused / 1024 / 1024 / 1024).toFixed(2)) : 0,
          memoryFree: item.memfree ? Number((item.memfree / 1024 / 1024 / 1024).toFixed(2)) : 0,
          memoryZfsArc: item.zfsarc ? Number((item.zfsarc / 1024 / 1024 / 1024).toFixed(2)) : 0,
        }

        if (index < 5 || index === result.data.length - 1) {
          console.log(`[v0] Data point ${index}:`, {
            rawCpu: item.cpu,
            transformedCpu: transformed.cpu,
            rawLoad: item.loadavg,
            transformedLoad: transformed.load,
          })
        }

        return transformed
      })

      const cpuValues = transformedData.map((d) => d.cpu)
      const minCpu = Math.min(...cpuValues)
      const maxCpu = Math.max(...cpuValues)
      const avgCpu = cpuValues.reduce((a, b) => a + b, 0) / cpuValues.length
      console.log("[v0] CPU Statistics:", {
        min: minCpu,
        max: maxCpu,
        avg: avgCpu.toFixed(2),
        sampleSize: cpuValues.length,
      })

      console.log("[v0] Total transformed data points:", transformedData.length)
      console.log("[v0] Setting data state with", transformedData.length, "points")

      setData(transformedData)
    } catch (err: any) {
      console.error("[v0] Error fetching node metrics:", err)
      console.error("[v0] Error message:", err.message)
      console.error("[v0] Error stack:", err.stack)
      setError(err.message || "Error loading metrics")
    } finally {
      console.log("[v0] fetchMetrics finally block - setting loading to false")
      setLoading(false)
    }
  }

  const tickInterval = Math.ceil(data.length / 8)

  console.log("[v0] Render state - loading:", loading, "error:", error, "data length:", data.length)

  if (loading) {
    console.log("[v0] Rendering loading state")
    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-center justify-center h-[300px]">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-center justify-center h-[300px]">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (error) {
    console.log("[v0] Rendering error state:", error)
    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex flex-col items-center justify-center h-[300px] gap-2">
              <p className="text-muted-foreground text-sm">Metrics data not available yet</p>
              <p className="text-xs text-red-500">{error}</p>
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex flex-col items-center justify-center h-[300px] gap-2">
              <p className="text-muted-foreground text-sm">Metrics data not available yet</p>
              <p className="text-xs text-red-500">{error}</p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (data.length === 0) {
    console.log("[v0] Rendering no data state")
    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-center justify-center h-[300px]">
              <p className="text-muted-foreground text-sm">No metrics data available</p>
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-center justify-center h-[300px]">
              <p className="text-muted-foreground text-sm">No metrics data available</p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  console.log("[v0] Rendering charts with", data.length, "data points")

  return (
    <div className="space-y-6">
      {/* Timeframe Selector */}
      <div className="flex justify-end">
        <Select value={timeframe} onValueChange={setTimeframe}>
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TIMEFRAME_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* CPU Usage + Load Average Chart */}
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <TrendingUp className="h-5 w-5 mr-2" />
              CPU Usage & Load Average
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={data} margin={{ bottom: 60, left: 10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
                <XAxis
                  dataKey="time"
                  stroke="currentColor"
                  className="text-foreground"
                  tick={{ fill: "currentColor", fontSize: 12 }}
                  angle={-45}
                  textAnchor="end"
                  height={60}
                  interval={tickInterval}
                />
                <YAxis
                  yAxisId="left"
                  stroke="currentColor"
                  className="text-foreground"
                  tick={{ fill: "currentColor", fontSize: 12 }}
                  label={{ value: "CPU %", angle: -90, position: "insideLeft", fill: "currentColor" }}
                  domain={[0, 100]}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  stroke="currentColor"
                  className="text-foreground"
                  tick={{ fill: "currentColor", fontSize: 12 }}
                  label={{ value: "Load", angle: 90, position: "insideRight", fill: "currentColor" }}
                  domain={[0, "dataMax"]}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--background))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "6px",
                  }}
                />
                <Legend verticalAlign="top" height={36} iconType="line" wrapperStyle={{ paddingBottom: "10px" }} />
                <Area
                  yAxisId="left"
                  type="monotone"
                  dataKey="cpu"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  fill="#3b82f6"
                  fillOpacity={0.3}
                  name="CPU %"
                />
                <Area
                  yAxisId="right"
                  type="monotone"
                  dataKey="load"
                  stroke="#10b981"
                  strokeWidth={2}
                  fill="#10b981"
                  fillOpacity={0.3}
                  name="Load Avg"
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Memory Usage Chart */}
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <MemoryStick className="h-5 w-5 mr-2" />
              Memory Usage
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={data} margin={{ bottom: 60, left: 10, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
                <XAxis
                  dataKey="time"
                  stroke="currentColor"
                  className="text-foreground"
                  tick={{ fill: "currentColor", fontSize: 12 }}
                  angle={-45}
                  textAnchor="end"
                  height={60}
                  interval={tickInterval}
                />
                <YAxis
                  stroke="currentColor"
                  className="text-foreground"
                  tick={{ fill: "currentColor", fontSize: 12 }}
                  label={{ value: "GB", angle: -90, position: "insideLeft", fill: "currentColor" }}
                  domain={[0, "dataMax"]}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--background))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "6px",
                  }}
                />
                <Legend verticalAlign="top" height={36} iconType="line" wrapperStyle={{ paddingBottom: "10px" }} />
                <Area
                  type="monotone"
                  dataKey="memoryTotal"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  fill="#3b82f6"
                  fillOpacity={0.1}
                  name="Total"
                />
                <Area
                  type="monotone"
                  dataKey="memoryUsed"
                  stroke="#10b981"
                  strokeWidth={2}
                  fill="#10b981"
                  fillOpacity={0.3}
                  name="Used"
                />
                <Area
                  type="monotone"
                  dataKey="memoryZfsArc"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  fill="#f59e0b"
                  fillOpacity={0.3}
                  name="ZFS ARC"
                />
                <Area
                  type="monotone"
                  dataKey="memoryFree"
                  stroke="#06b6d4"
                  strokeWidth={2}
                  fill="#06b6d4"
                  fillOpacity={0.3}
                  name="Available"
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
