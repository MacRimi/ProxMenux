"use client"

import { useEffect, useState } from "react"
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import useSWR from "swr"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"

interface VMNetworkChartProps {
  vmid: number
  vmType: "qemu" | "lxc"
  initialTimeframe?: "hour" | "day" | "week" | "month" | "year"
}

const fetcher = async (url: string) => {
  const response = await fetch(url, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    signal: AbortSignal.timeout(10000),
  })
  if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)
  return response.json()
}

const formatBytes = (bytes: number): string => {
  if (bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

export function VMNetworkChart({ vmid, vmType, initialTimeframe = "day" }: VMNetworkChartProps) {
  const [timeframe, setTimeframe] = useState<"hour" | "day" | "week" | "month" | "year">(initialTimeframe)
  const [visibleLines, setVisibleLines] = useState({ received: true, sent: true })
  const [chartData, setChartData] = useState<any[]>([])

  const { data: rrdData } = useSWR(`/api/${vmType}/${vmid}/rrddata?timeframe=${timeframe}`, fetcher, {
    refreshInterval: 30000,
    revalidateOnFocus: false,
  })

  useEffect(() => {
    if (!rrdData) return

    const transformedData = rrdData.map((point: any) => {
      const timestamp = new Date(point.time * 1000)
      const hours = timestamp.getHours().toString().padStart(2, "0")
      const minutes = timestamp.getMinutes().toString().padStart(2, "0")
      const month = (timestamp.getMonth() + 1).toString().padStart(2, "0")
      const day = timestamp.getDate().toString().padStart(2, "0")

      let timeLabel = `${hours}:${minutes}`
      if (timeframe === "week" || timeframe === "month") {
        timeLabel = `${month}/${day}`
      } else if (timeframe === "year") {
        timeLabel = `${month}/${day}`
      }

      // Calculate traffic in GB for the interval
      const intervalSeconds = timeframe === "hour" ? 60 : timeframe === "day" ? 60 : timeframe === "week" ? 1800 : 3600
      const receivedGB = ((point.netin || 0) * intervalSeconds) / (1024 * 1024 * 1024)
      const sentGB = ((point.netout || 0) * intervalSeconds) / (1024 * 1024 * 1024)

      return {
        time: timeLabel,
        received: receivedGB,
        sent: sentGB,
      }
    })

    setChartData(transformedData)
  }, [rrdData, timeframe])

  const toggleLine = (line: "received" | "sent") => {
    setVisibleLines((prev) => ({ ...prev, [line]: !prev[line] }))
  }

  const getTimeframeLabel = () => {
    switch (timeframe) {
      case "hour":
        return "1 Hour"
      case "day":
        return "24 Hours"
      case "week":
        return "7 Days"
      case "month":
        return "30 Days"
      case "year":
        return "1 Year"
      default:
        return "24 Hours"
    }
  }

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-background/95 backdrop-blur-sm border border-border rounded-lg p-3 shadow-lg">
          <p className="text-sm font-medium text-foreground mb-2">{payload[0].payload.time}</p>
          {payload.map((entry: any, index: number) => (
            <div key={index} className="flex items-center justify-between gap-4 text-sm">
              <span className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full" style={{ backgroundColor: entry.color }} />
                <span className="text-muted-foreground">{entry.name}:</span>
              </span>
              <span className="font-medium text-foreground">{formatBytes(entry.value * 1024 * 1024 * 1024)}</span>
            </div>
          ))}
        </div>
      )
    }
    return null
  }

  return (
    <div className="space-y-4">
      {/* Timeframe Selector */}
      <div className="flex justify-end">
        <Select value={timeframe} onValueChange={(value: any) => setTimeframe(value)}>
          <SelectTrigger className="w-[180px] bg-card border-border">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="hour">1 Hour</SelectItem>
            <SelectItem value="day">24 Hours</SelectItem>
            <SelectItem value="week">7 Days</SelectItem>
            <SelectItem value="month">30 Days</SelectItem>
            <SelectItem value="year">1 Year</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Interactive Legend */}
      <div className="flex items-center justify-center gap-6 pb-2">
        <button
          onClick={() => toggleLine("received")}
          className={`flex items-center gap-2 transition-opacity ${!visibleLines.received ? "opacity-40" : ""}`}
        >
          <span className="w-3 h-3 rounded-full bg-green-500" />
          <span className="text-sm font-medium">Received</span>
        </button>
        <button
          onClick={() => toggleLine("sent")}
          className={`flex items-center gap-2 transition-opacity ${!visibleLines.sent ? "opacity-40" : ""}`}
        >
          <span className="w-3 h-3 rounded-full bg-blue-500" />
          <span className="text-sm font-medium">Sent</span>
        </button>
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="colorReceived" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="colorSent" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
          <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} />
          <YAxis
            stroke="hsl(var(--muted-foreground))"
            fontSize={12}
            tickLine={false}
            tickFormatter={(value) => {
              if (value === 0) return "0"
              if (value < 0.01) return `${(value * 1024).toFixed(0)} MB`
              return `${value.toFixed(2)} GB`
            }}
            label={{ value: "GB", angle: -90, position: "insideLeft", style: { fill: "hsl(var(--muted-foreground))" } }}
          />
          <Tooltip content={<CustomTooltip />} />
          {visibleLines.received && (
            <Area
              type="monotone"
              dataKey="received"
              stroke="#10b981"
              strokeWidth={2}
              fill="url(#colorReceived)"
              name="Received"
            />
          )}
          {visibleLines.sent && (
            <Area type="monotone" dataKey="sent" stroke="#3b82f6" strokeWidth={2} fill="url(#colorSent)" name="Sent" />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
