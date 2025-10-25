"use client"

import { useState, useEffect } from "react"
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts"
import { Loader2 } from "lucide-react"

interface NetworkMetricsData {
  time: string
  timestamp: number
  netIn: number
  netOut: number
}

interface NetworkTrafficChartProps {
  timeframe: string
  interfaceName?: string // Added optional interfaceName prop for specific interface data
  onTotalsCalculated?: (totals: { received: number; sent: number }) => void
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
              <span className="text-sm font-semibold text-white">{entry.value.toFixed(3)} GB</span>
            </div>
          ))}
        </div>
      </div>
    )
  }
  return null
}

export function NetworkTrafficChart({ timeframe, interfaceName, onTotalsCalculated }: NetworkTrafficChartProps) {
  const [data, setData] = useState<NetworkMetricsData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [visibleLines, setVisibleLines] = useState({
    netIn: true,
    netOut: true,
  })

  useEffect(() => {
    fetchMetrics()
  }, [timeframe, interfaceName])

  const fetchMetrics = async () => {
    setLoading(true)
    setError(null)

    try {
      const baseUrl =
        typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""

      const apiUrl = interfaceName
        ? `${baseUrl}/api/network/${interfaceName}/history?timeframe=${timeframe}`
        : `${baseUrl}/api/node/metrics?timeframe=${timeframe}`

      const response = await fetch(apiUrl)

      if (!response.ok) {
        throw new Error(`Failed to fetch network metrics: ${response.status}`)
      }

      const result = await response.json()

      if (!result.data || !Array.isArray(result.data)) {
        throw new Error("Invalid data format received from server")
      }

      if (result.data.length === 0) {
        setData([])
        setLoading(false)
        return
      }

      // RRD data contains rate (bytes/second), we need to calculate traffic per interval
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
        } else if (timeframe === "year") {
          timeLabel = date.toLocaleString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
          })
        } else {
          timeLabel = date.toLocaleString("en-US", {
            month: "short",
            day: "numeric",
          })
        }

        // Calculate time interval between data points (in seconds)
        let intervalSeconds = 60 // Default to 1 minute
        if (index > 0) {
          intervalSeconds = item.time - result.data[index - 1].time
        }

        // Convert rate (bytes/second) to traffic in this interval (GB)
        // netin and netout are in bytes/second, multiply by interval to get total bytes
        const netInBytes = (item.netin || 0) * intervalSeconds
        const netOutBytes = (item.netout || 0) * intervalSeconds

        return {
          time: timeLabel,
          timestamp: item.time,
          netIn: Number((netInBytes / 1024 / 1024 / 1024).toFixed(4)),
          netOut: Number((netOutBytes / 1024 / 1024 / 1024).toFixed(4)),
        }
      })

      setData(transformedData)

      const totalReceived = transformedData.reduce((sum: number, item: NetworkMetricsData) => sum + item.netIn, 0)
      const totalSent = transformedData.reduce((sum: number, item: NetworkMetricsData) => sum + item.netOut, 0)

      if (onTotalsCalculated) {
        onTotalsCalculated({ received: totalReceived, sent: totalSent })
      }
    } catch (err: any) {
      console.error("[v0] Error fetching network metrics:", err)
      setError(err.message || "Error loading metrics")
    } finally {
      setLoading(false)
    }
  }

  const tickInterval = Math.ceil(data.length / 8)

  const handleLegendClick = (dataKey: string) => {
    setVisibleLines((prev) => ({
      ...prev,
      [dataKey]: !prev[dataKey as keyof typeof prev],
    }))
  }

  const renderLegend = (props: any) => {
    const { payload } = props
    return (
      <div className="flex justify-center gap-4 pb-2 flex-wrap">
        {payload.map((entry: any, index: number) => {
          const isVisible = visibleLines[entry.dataKey as keyof typeof visibleLines]
          return (
            <div
              key={`legend-${index}`}
              className="flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
              onClick={() => handleLegendClick(entry.dataKey)}
              style={{ opacity: isVisible ? 1 : 0.4 }}
            >
              <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: entry.color }} />
              <span className="text-sm text-foreground">{entry.value}</span>
            </div>
          )
        })}
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[200px]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-[200px] gap-2">
        <p className="text-muted-foreground text-sm">Network metrics not available yet</p>
        <p className="text-xs text-red-500">{error}</p>
      </div>
    )
  }

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px]">
        <p className="text-muted-foreground text-sm">No network metrics available</p>
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data} margin={{ bottom: 40, left: 10, right: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
        <XAxis
          dataKey="time"
          stroke="currentColor"
          className="text-foreground"
          tick={{ fill: "currentColor", fontSize: 12 }}
          angle={-45}
          textAnchor="end"
          height={40}
          interval={tickInterval}
        />
        <YAxis
          stroke="currentColor"
          className="text-foreground"
          tick={{ fill: "currentColor", fontSize: 12 }}
          label={{ value: "GB", angle: -90, position: "insideLeft", fill: "currentColor" }}
          domain={[0, "auto"]}
        />
        <Tooltip content={<CustomNetworkTooltip />} />
        <Legend verticalAlign="top" height={36} content={renderLegend} />
        <Area
          type="monotone"
          dataKey="netIn"
          stroke="#10b981"
          strokeWidth={2}
          fill="#10b981"
          fillOpacity={0.3}
          name="Received"
          hide={!visibleLines.netIn}
        />
        <Area
          type="monotone"
          dataKey="netOut"
          stroke="#3b82f6"
          strokeWidth={2}
          fill="#3b82f6"
          fillOpacity={0.3}
          name="Sent"
          hide={!visibleLines.netOut}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
