"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ArrowLeft, Loader2 } from "lucide-react"
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts"

interface MetricsViewProps {
  vmid: number
  vmName: string
  vmType: "qemu" | "lxc"
  metricType: "cpu" | "memory" | "network" | "disk"
  onBack: () => void
}

const TIMEFRAME_OPTIONS = [
  { value: "hour", label: "1 Hour" },
  { value: "day", label: "24 Hours" },
  { value: "week", label: "7 Days" },
  { value: "month", label: "30 Days" },
  { value: "year", label: "1 Year" },
]

const METRIC_TITLES = {
  cpu: "CPU Usage",
  memory: "Memory Usage",
  network: "Network Traffic",
  disk: "Disk I/O",
}

export function MetricsView({ vmid, vmName, vmType, metricType, onBack }: MetricsViewProps) {
  const [timeframe, setTimeframe] = useState("week")
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchMetrics()
  }, [vmid, timeframe])

  const fetchMetrics = async () => {
    setLoading(true)
    setError(null)

    console.log("[v0] Fetching metrics for VMID:", vmid, "Timeframe:", timeframe, "Type:", vmType)

    try {
      const baseUrl =
        typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""
      const apiUrl = `${baseUrl}/api/vms/${vmid}/metrics?timeframe=${timeframe}`

      console.log("[v0] Fetching from URL:", apiUrl)

      const response = await fetch(apiUrl)

      console.log("[v0] Response status:", response.status)

      if (!response.ok) {
        const errorData = await response.json()
        console.error("[v0] Error response:", errorData)
        throw new Error(errorData.error || "Failed to fetch metrics")
      }

      const result = await response.json()
      console.log("[v0] Metrics data received:", result)

      const transformedData = result.data.map((item: any) => {
        const date = new Date(item.time * 1000)
        let timeLabel = ""

        // Format time based on timeframe
        if (timeframe === "hour") {
          // For 1 hour: show HH:mm
          timeLabel = date.toLocaleString("en-US", {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          })
        } else if (timeframe === "day") {
          // For 24 hours: show HH:mm
          timeLabel = date.toLocaleString("en-US", {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          })
        } else if (timeframe === "week") {
          // For 7 days: show Mon DD HH:mm
          timeLabel = date.toLocaleString("en-US", {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          })
        } else if (timeframe === "month") {
          // For 30 days: show Mon DD
          timeLabel = date.toLocaleString("en-US", {
            month: "short",
            day: "numeric",
          })
        } else {
          // For 1 year: show Mon YYYY
          timeLabel = date.toLocaleString("en-US", {
            month: "short",
            year: "numeric",
          })
        }

        return {
          time: timeLabel,
          timestamp: item.time,
          cpu: item.cpu ? (item.cpu * 100).toFixed(2) : 0,
          memory: item.mem ? ((item.mem / item.maxmem) * 100).toFixed(2) : 0,
          memoryMB: item.mem ? (item.mem / 1024 / 1024).toFixed(0) : 0,
          maxMemoryMB: item.maxmem ? (item.maxmem / 1024 / 1024).toFixed(0) : 0,
          netin: item.netin ? (item.netin / 1024 / 1024).toFixed(2) : 0,
          netout: item.netout ? (item.netout / 1024 / 1024).toFixed(2) : 0,
          diskread: item.diskread ? (item.diskread / 1024 / 1024).toFixed(2) : 0,
          diskwrite: item.diskwrite ? (item.diskwrite / 1024 / 1024).toFixed(2) : 0,
        }
      })

      console.log("[v0] Transformed data:", transformedData.length, "points")
      setData(transformedData)
    } catch (err: any) {
      console.error("[v0] Error fetching metrics:", err)
      setError(err.message || "Error loading metrics")
    } finally {
      setLoading(false)
    }
  }

  const formatXAxisTick = (tick: any) => {
    return tick
  }

  const renderChart = () => {
    if (loading) {
      return (
        <div className="flex items-center justify-center h-[400px]">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )
    }

    if (error) {
      return (
        <div className="flex items-center justify-center h-[400px]">
          <p className="text-red-500">{error}</p>
        </div>
      )
    }

    if (data.length === 0) {
      return (
        <div className="flex items-center justify-center h-[400px]">
          <p className="text-muted-foreground">No data available</p>
        </div>
      )
    }

    // Calculate tick interval based on data length
    const tickInterval = Math.ceil(data.length / 8)

    switch (metricType) {
      case "cpu":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <AreaChart data={data} margin={{ bottom: 70 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
              <XAxis
                dataKey="time"
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                angle={-45}
                textAnchor="end"
                height={80}
                interval={tickInterval}
                tickFormatter={formatXAxisTick}
              />
              <YAxis
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                label={{ value: "%", angle: -90, position: "insideLeft", fill: "currentColor" }}
                domain={[
                  0,
                  (dataMax: number) => {
                    const percentMargin = Math.ceil(dataMax * 1.1)
                    const fixedMargin = dataMax + 5
                    return Math.max(percentMargin, fixedMargin, 10)
                  },
                ]}
                allowDataOverflow={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--background))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "6px",
                }}
              />
              <Legend />
              <Area
                type="monotone"
                dataKey="cpu"
                stroke="#3b82f6"
                strokeWidth={2}
                fill="#3b82f6"
                fillOpacity={0.3}
                name="CPU %"
              />
            </AreaChart>
          </ResponsiveContainer>
        )

      case "memory":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <AreaChart data={data} margin={{ bottom: 70 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
              <XAxis
                dataKey="time"
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                angle={-45}
                textAnchor="end"
                height={80}
                interval={tickInterval}
                tickFormatter={formatXAxisTick}
              />
              <YAxis
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                label={{ value: "%", angle: -90, position: "insideLeft", fill: "currentColor" }}
                domain={[
                  0,
                  (dataMax: number) => {
                    const percentMargin = Math.ceil(dataMax * 1.1)
                    const fixedMargin = dataMax + 5
                    return Math.max(percentMargin, fixedMargin, 10)
                  },
                ]}
                allowDataOverflow={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--background))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "6px",
                }}
              />
              <Legend />
              <Area
                type="monotone"
                dataKey="memory"
                stroke="#10b981"
                fill="#10b981"
                fillOpacity={0.3}
                strokeWidth={2}
                name="Memory %"
              />
            </AreaChart>
          </ResponsiveContainer>
        )

      case "network":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <AreaChart data={data} margin={{ bottom: 70 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
              <XAxis
                dataKey="time"
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                angle={-45}
                textAnchor="end"
                height={80}
                interval={tickInterval}
                tickFormatter={formatXAxisTick}
              />
              <YAxis
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                label={{ value: "MB", angle: -90, position: "insideLeft", fill: "currentColor" }}
                domain={[
                  0,
                  (dataMax: number) => {
                    const percentMargin = Math.ceil(dataMax * 1.1)
                    const fixedMargin = dataMax + 5
                    return Math.max(percentMargin, fixedMargin, 10)
                  },
                ]}
                allowDataOverflow={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--background))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "6px",
                }}
              />
              <Legend />
              <Area
                type="monotone"
                dataKey="netin"
                stroke="#10b981"
                fill="#10b981"
                fillOpacity={0.3}
                strokeWidth={2}
                name="Download (MB)"
              />
              <Area
                type="monotone"
                dataKey="netout"
                stroke="#3b82f6"
                fill="#3b82f6"
                fillOpacity={0.3}
                strokeWidth={2}
                name="Upload (MB)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )

      case "disk":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <AreaChart data={data} margin={{ bottom: 70 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
              <XAxis
                dataKey="time"
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                angle={-45}
                textAnchor="end"
                height={80}
                interval={tickInterval}
                tickFormatter={formatXAxisTick}
              />
              <YAxis
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                label={{ value: "MB", angle: -90, position: "insideLeft", fill: "currentColor" }}
                domain={[
                  0,
                  (dataMax: number) => {
                    const percentMargin = Math.ceil(dataMax * 1.1)
                    const fixedMargin = dataMax + 5
                    return Math.max(percentMargin, fixedMargin, 10)
                  },
                ]}
                allowDataOverflow={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--background))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "6px",
                }}
              />
              <Legend />
              <Area
                type="monotone"
                dataKey="diskread"
                stroke="#10b981"
                fill="#10b981"
                fillOpacity={0.3}
                strokeWidth={2}
                name="Read (MB)"
              />
              <Area
                type="monotone"
                dataKey="diskwrite"
                stroke="#3b82f6"
                fill="#3b82f6"
                fillOpacity={0.3}
                strokeWidth={2}
                name="Write (MB)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )

      default:
        return null
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Fixed Header */}
      <div className="p-6 pb-4 border-b shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={onBack}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h2 className="text-xl font-semibold">
                {METRIC_TITLES[metricType]} - {vmName}
              </h2>
              <p className="text-sm text-muted-foreground mt-1">
                VMID: {vmid} • Type: {vmType.toUpperCase()}
              </p>
            </div>
          </div>
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
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-y-auto p-6">{renderChart()}</div>
    </div>
  )
}
