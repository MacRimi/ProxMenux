"use client"

import { useState, useEffect } from "react"
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts"
import { Loader2 } from "lucide-react"
import { fetchApi } from "@/lib/api-config"

interface NetworkMetricsData {
  time: string
  timestamp: number
  netIn: number
  netOut: number
}

interface NetworkTrafficChartProps {
  timeframe: string
  interfaceName?: string
  onTotalsCalculated?: (totals: { received: number; sent: number }) => void
  refreshInterval?: number // En milisegundos, por defecto 60000 (60 segundos)
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

export function NetworkTrafficChart({
  timeframe,
  interfaceName,
  onTotalsCalculated,
  refreshInterval = 60000,
}: NetworkTrafficChartProps) {
  const [data, setData] = useState<NetworkMetricsData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isInitialLoad, setIsInitialLoad] = useState(true)
  const [visibleLines, setVisibleLines] = useState({
    netIn: true,
    netOut: true,
  })

  useEffect(() => {
    setIsInitialLoad(true)
    fetchMetrics()
  }, [timeframe, interfaceName])

  useEffect(() => {
    if (refreshInterval > 0) {
      const interval = setInterval(() => {
        fetchMetrics()
      }, refreshInterval)

      return () => clearInterval(interval)
    }
  }, [timeframe, interfaceName, refreshInterval])

  const fetchMetrics = async () => {
    if (isInitialLoad) {
      setLoading(true)
    }
    setError(null)

    try {
      const apiPath = interfaceName
        ? `/api/network/${interfaceName}/metrics?timeframe=${timeframe}`
        : `/api/node/metrics?timeframe=${timeframe}`

      console.log("[v0] Fetching network metrics from:", apiPath)

      const result = await fetchApi<any>(apiPath)

      if (!result.data || !Array.isArray(result.data)) {
        throw new Error("Invalid data format received from server")
      }

      if (result.data.length === 0) {
        setData([])
        setLoading(false)
        return
      }

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

        let intervalSeconds = 60
        if (index > 0) {
          intervalSeconds = item.time - result.data[index - 1].time
        }

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

      if (isInitialLoad) {
        setIsInitialLoad(false)
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
      [dataKey as keyof typeof prev]: !prev[dataKey as keyof typeof prev],
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

  if (loading && isInitialLoad) {
    return (
      <div className="flex items-center justify-center h-[300px]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-[300px] gap-2">
        <p className="text-muted-foreground text-sm">Network metrics not available yet</p>
        <p className="text-xs text-red-500">{error}</p>
      </div>
    )
  }

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[300px]">
        <p className="text-muted-foreground text-sm">No network metrics available</p>
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={data} margin={{ bottom: 80 }}>
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
          isAnimationActive={true}
          animationDuration={300}
          animationEasing="ease-in-out"
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
          isAnimationActive={true}
          animationDuration={300}
          animationEasing="ease-in-out"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
