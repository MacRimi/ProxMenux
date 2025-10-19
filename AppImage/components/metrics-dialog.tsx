"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ArrowLeft, Loader2 } from "lucide-react"
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts"

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

      // Transform data for charts
      const transformedData = result.data.map((item: any) => ({
        time: new Date(item.time * 1000).toLocaleString("en-US", {
          month: "short",
          day: "numeric",
          hour: timeframe === "hour" ? "2-digit" : undefined,
          minute: timeframe === "hour" ? "2-digit" : undefined,
        }),
        timestamp: item.time,
        cpu: item.cpu ? (item.cpu * 100).toFixed(2) : 0,
        memory: item.mem ? ((item.mem / item.maxmem) * 100).toFixed(2) : 0,
        memoryMB: item.mem ? (item.mem / 1024 / 1024).toFixed(0) : 0,
        maxMemoryMB: item.maxmem ? (item.maxmem / 1024 / 1024).toFixed(0) : 0,
        netin: item.netin ? (item.netin / 1024 / 1024).toFixed(2) : 0,
        netout: item.netout ? (item.netout / 1024 / 1024).toFixed(2) : 0,
        diskread: item.diskread ? (item.diskread / 1024 / 1024).toFixed(2) : 0,
        diskwrite: item.diskwrite ? (item.diskwrite / 1024 / 1024).toFixed(2) : 0,
      }))

      console.log("[v0] Transformed data:", transformedData.length, "points")
      setData(transformedData)
    } catch (err: any) {
      console.error("[v0] Error fetching metrics:", err)
      setError(err.message || "Error loading metrics")
    } finally {
      setLoading(false)
    }
  }

  const renderChart = () => {
    if (loading) {
      return (
        <div className="flex items-center justify-center h-96">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      )
    }

    if (error) {
      return (
        <div className="flex items-center justify-center h-96">
          <p className="text-destructive">{error}</p>
        </div>
      )
    }

    if (data.length === 0) {
      return (
        <div className="flex items-center justify-center h-96">
          <p className="text-muted-foreground">No data available</p>
        </div>
      )
    }

    switch (metricType) {
      case "cpu":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis stroke="hsl(var(--muted-foreground))" label={{ value: "%", angle: -90, position: "insideLeft" }} />
              <Tooltip
                contentStyle={{ backgroundColor: "hsl(var(--background))", border: "1px solid hsl(var(--border))" }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Legend />
              <Line type="monotone" dataKey="cpu" stroke="#3b82f6" name="CPU %" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )

      case "memory":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis stroke="hsl(var(--muted-foreground))" label={{ value: "%", angle: -90, position: "insideLeft" }} />
              <Tooltip
                contentStyle={{ backgroundColor: "hsl(var(--background))", border: "1px solid hsl(var(--border))" }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Legend />
              <Line type="monotone" dataKey="memory" stroke="#10b981" name="Memory %" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )

      case "network":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis
                stroke="hsl(var(--muted-foreground))"
                label={{ value: "MB", angle: -90, position: "insideLeft" }}
              />
              <Tooltip
                contentStyle={{ backgroundColor: "hsl(var(--background))", border: "1px solid hsl(var(--border))" }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Legend />
              <Line type="monotone" dataKey="netin" stroke="#3b82f6" name="In (MB)" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="netout" stroke="#8b5cf6" name="Out (MB)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )

      case "disk":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis
                stroke="hsl(var(--muted-foreground))"
                label={{ value: "MB", angle: -90, position: "insideLeft" }}
              />
              <Tooltip
                contentStyle={{ backgroundColor: "hsl(var(--background))", border: "1px solid hsl(var(--border))" }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Legend />
              <Line type="monotone" dataKey="diskread" stroke="#10b981" name="Read (MB)" strokeWidth={2} dot={false} />
              <Line
                type="monotone"
                dataKey="diskwrite"
                stroke="#f59e0b"
                name="Write (MB)"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )
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
