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
  onBack: () => void
}

const TIMEFRAME_OPTIONS = [
  { value: "hour", label: "1 Hour" },
  { value: "day", label: "24 Hours" },
  { value: "week", label: "7 Days" },
  { value: "month", label: "30 Days" },
  { value: "year", label: "1 Year" },
]

const CustomCPUTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-900/95 backdrop-blur-sm border border-gray-700 rounded-lg p-3 shadow-xl">
        <p className="text-sm font-semibold text-white mb-2">{label}</p>
        <div className="space-y-1.5">
          {payload.map((entry: any, index: number) => (
            <div key={index} className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: entry.color }} />
              <span className="text-xs text-gray-300 min-w-[60px]">{entry.name}:</span>
              <span className="text-sm font-semibold text-white">{entry.value}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }
  return null
}

const CustomMemoryTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-900/95 backdrop-blur-sm border border-gray-700 rounded-lg p-3 shadow-xl">
        <p className="text-sm font-semibold text-white mb-2">{label}</p>
        <div className="space-y-1.5">
          {payload.map((entry: any, index: number) => (
            <div key={index} className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: entry.color }} />
              <span className="text-xs text-gray-300 min-w-[60px]">{entry.name}:</span>
              <span className="text-sm font-semibold text-white">{entry.value} GB</span>
            </div>
          ))}
        </div>
      </div>
    )
  }
  return null
}

const CustomDiskTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-900/95 backdrop-blur-sm border border-gray-700 rounded-lg p-3 shadow-xl">
        <p className="text-sm font-semibold text-white mb-2">{label}</p>
        <div className="space-y-1.5">
          {payload.map((entry: any, index: number) => (
            <div key={index} className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: entry.color }} />
              <span className="text-xs text-gray-300 min-w-[60px]">{entry.name}:</span>
              <span className="text-sm font-semibold text-white">{entry.value} MB</span>
            </div>
          ))}
        </div>
      </div>
    )
  }
  return null
}

const CustomNetworkTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-900/95 backdrop-blur-sm border border-gray-700 rounded-lg p-3 shadow-xl">
        <p className="text-sm font-semibold text-white mb-2">{label}</p>
        <div className="space-y-1.5">
          {payload.map((entry: any, index: number) => (
            <div key={index} className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: entry.color }} />
              <span className="text-xs text-gray-300 min-w-[60px]">{entry.name}:</span>
              <span className="text-sm font-semibold text-white">{entry.value} MB</span>
            </div>
          ))}
        </div>
      </div>
    )
  }
  return null
}

export function MetricsView({ vmid, vmName, vmType, onBack }: MetricsViewProps) {
  const [timeframe, setTimeframe] = useState("week")
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hiddenDiskLines, setHiddenDiskLines] = useState<string[]>([])
  const [hiddenNetworkLines, setHiddenNetworkLines] = useState<string[]>([])

  useEffect(() => {
    fetchMetrics()
  }, [vmid, timeframe])

  const fetchMetrics = async () => {
    setLoading(true)
    setError(null)

    try {
      const baseUrl =
        typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""
      const apiUrl = `${baseUrl}/api/vms/${vmid}/metrics?timeframe=${timeframe}`

      const response = await fetch(apiUrl)

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || "Failed to fetch metrics")
      }

      const result = await response.json()

      const transformedData = result.data.map((item: any) => {
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
            minute: "2-digit",
            hour12: false,
          })
        } else if (timeframe === "month") {
          timeLabel = date.toLocaleString("en-US", {
            month: "short",
            day: "numeric",
          })
        } else {
          timeLabel = date.toLocaleString("en-US", {
            month: "short",
            year: "numeric",
          })
        }

        return {
          time: timeLabel,
          timestamp: item.time,
          cpu: item.cpu ? Number((item.cpu * 100).toFixed(2)) : 0,
          memory: item.mem ? Number(((item.mem / item.maxmem) * 100).toFixed(2)) : 0,
          memoryGB: item.mem ? Number((item.mem / 1024 / 1024 / 1024).toFixed(2)) : 0,
          maxMemoryGB: item.maxmem ? Number((item.maxmem / 1024 / 1024 / 1024).toFixed(2)) : 0,
          netin: item.netin ? Number((item.netin / 1024 / 1024).toFixed(2)) : 0,
          netout: item.netout ? Number((item.netout / 1024 / 1024).toFixed(2)) : 0,
          diskread: item.diskread ? Number((item.diskread / 1024 / 1024).toFixed(2)) : 0,
          diskwrite: item.diskwrite ? Number((item.diskwrite / 1024 / 1024).toFixed(2)) : 0,
        }
      })

      setData(transformedData)
    } catch (err: any) {
      setError(err.message || "Error loading metrics")
    } finally {
      setLoading(false)
    }
  }

  const formatXAxisTick = (tick: any) => {
    return tick
  }

  const renderAllCharts = () => {
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

    const tickInterval = Math.ceil(data.length / 8)

    return (
      <div className="space-y-8">
        {/* CPU Chart */}
        <div>
          <h3 className="text-lg font-semibold mb-4">CPU Usage</h3>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data} margin={{ bottom: 80 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
              <XAxis
                dataKey="time"
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                angle={-45}
                textAnchor="end"
                height={60}
                interval={tickInterval}
                tickFormatter={formatXAxisTick}
              />
              <YAxis
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                label={{ value: "%", angle: -90, position: "insideLeft", fill: "currentColor" }}
                domain={[0, "dataMax"]}
              />
              <Tooltip content={<CustomCPUTooltip />} />
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
        </div>

        {/* Memory Chart */}
        <div>
          <h3 className="text-lg font-semibold mb-4">Memory Usage</h3>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data} margin={{ bottom: 80 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
              <XAxis
                dataKey="time"
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                angle={-45}
                textAnchor="end"
                height={60}
                interval={tickInterval}
                tickFormatter={formatXAxisTick}
              />
              <YAxis
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                label={{ value: "GB", angle: -90, position: "insideLeft", fill: "currentColor" }}
                domain={[0, "dataMax"]}
              />
              <Tooltip content={<CustomMemoryTooltip />} />
              <Area
                type="monotone"
                dataKey="memoryGB"
                stroke="#10b981"
                fill="#10b981"
                fillOpacity={0.3}
                strokeWidth={2}
                name="Memory GB"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Disk I/O Chart */}
        <div>
          <h3 className="text-lg font-semibold mb-4">Disk I/O</h3>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data} margin={{ bottom: 80 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
              <XAxis
                dataKey="time"
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                angle={-45}
                textAnchor="end"
                height={60}
                interval={tickInterval}
                tickFormatter={formatXAxisTick}
              />
              <YAxis
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                label={{ value: "MB", angle: -90, position: "insideLeft", fill: "currentColor" }}
                domain={[0, "dataMax"]}
              />
              <Tooltip content={<CustomDiskTooltip />} />
              <Legend content={renderDiskLegend} verticalAlign="top" />
              <Area
                type="monotone"
                dataKey="diskread"
                stroke="#10b981"
                fill="#10b981"
                fillOpacity={0.3}
                strokeWidth={2}
                name="Read"
                hide={hiddenDiskLines.includes("diskread")}
              />
              <Area
                type="monotone"
                dataKey="diskwrite"
                stroke="#3b82f6"
                fill="#3b82f6"
                fillOpacity={0.3}
                strokeWidth={2}
                name="Write"
                hide={hiddenDiskLines.includes("diskwrite")}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Network I/O Chart */}
        <div>
          <h3 className="text-lg font-semibold mb-4">Network I/O</h3>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data} margin={{ bottom: 80 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
              <XAxis
                dataKey="time"
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                angle={-45}
                textAnchor="end"
                height={60}
                interval={tickInterval}
                tickFormatter={formatXAxisTick}
              />
              <YAxis
                stroke="currentColor"
                className="text-foreground"
                tick={{ fill: "currentColor" }}
                label={{ value: "MB", angle: -90, position: "insideLeft", fill: "currentColor" }}
                domain={[0, "dataMax"]}
              />
              <Tooltip content={<CustomNetworkTooltip />} />
              <Legend content={renderNetworkLegend} verticalAlign="top" />
              <Area
                type="monotone"
                dataKey="netin"
                stroke="#10b981"
                fill="#10b981"
                fillOpacity={0.3}
                strokeWidth={2}
                name="Download"
                hide={hiddenNetworkLines.includes("netin")}
              />
              <Area
                type="monotone"
                dataKey="netout"
                stroke="#3b82f6"
                fill="#3b82f6"
                fillOpacity={0.3}
                strokeWidth={2}
                name="Upload"
                hide={hiddenNetworkLines.includes("netout")}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    )
  }

  const handleDiskLegendClick = (dataKey: string) => {
    setHiddenDiskLines((prev) => {
      if (prev.includes(dataKey)) {
        return prev.filter((key) => key !== dataKey)
      } else {
        return [...prev, dataKey]
      }
    })
  }

  const handleNetworkLegendClick = (dataKey: string) => {
    setHiddenNetworkLines((prev) => {
      if (prev.includes(dataKey)) {
        return prev.filter((key) => key !== dataKey)
      } else {
        return [...prev, dataKey]
      }
    })
  }

  const renderDiskLegend = (props: any) => {
    const { payload } = props
    return (
      <div className="flex justify-center gap-6 pb-2">
        {payload.map((entry: any) => (
          <button
            key={entry.dataKey}
            onClick={() => handleDiskLegendClick(entry.dataKey)}
            className={`flex items-center gap-2 cursor-pointer transition-opacity hover:opacity-100 ${
              hiddenDiskLines.includes(entry.dataKey) ? "opacity-40" : "opacity-100"
            }`}
          >
            <span className="w-3 h-3 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className="text-sm">{entry.value}</span>
          </button>
        ))}
      </div>
    )
  }

  const renderNetworkLegend = (props: any) => {
    const { payload } = props
    return (
      <div className="flex justify-center gap-6 pb-2">
        {payload.map((entry: any) => (
          <button
            key={entry.dataKey}
            onClick={() => handleNetworkLegendClick(entry.dataKey)}
            className={`flex items-center gap-2 cursor-pointer transition-opacity hover:opacity-100 ${
              hiddenNetworkLines.includes(entry.dataKey) ? "opacity-40" : "opacity-100"
            }`}
          >
            <span className="w-3 h-3 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className="text-sm">{entry.value}</span>
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full max-h-[90vh]">
      {/* Fixed Header */}
      <div className="p-6 pb-4 border-b shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={onBack}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h2 className="text-xl font-semibold">Metrics - {vmName}</h2>
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

      {/* Scrollable Content with all charts */}
      <div className="flex-1 overflow-y-auto p-6 min-h-0">{renderAllCharts()}</div>
    </div>
  )
}
