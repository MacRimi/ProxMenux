"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts"
import { Loader2, TrendingUp, MemoryStick } from "lucide-react"
import { useIsMobile } from "../hooks/use-mobile"
import { fetchApi } from "@/lib/api-config"

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

const CustomCpuTooltip = ({ active, payload, label }: any) => {
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

interface MetricsError {
  headline: string
  details?: string
  suggestion?: string
}

// AVG / MAX / MIN chip row for the chart card headers. Values come
// from the backend `period_stats` (calculated over the raw RRD points
// BEFORE downsampling), not from the displayed chart points — that's
// what makes a 1-minute CPU spike still appear in the 24h MAX even
// though the chart shows 5-min bucket averages.
//
// Colour choice: all three values render in the same foreground tone.
// The previous red(max)/green(min) scheme misread as severity (a
// healthy 10 % CPU max showed in red and looked like an alert).
//
// Responsive: on ≥sm the chips sit to the right of the title; on
// mobile they wrap below in their own row (the parent CardHeader uses
// `flex-col sm:flex-row`). Smaller text + tabular-nums keeps the
// chips compact enough that they don't crowd long titles.
type PeriodStat = { avg: number; max: number; min: number } | null
function ChartStatsHeader({
  stats,
  suffix = "",
}: {
  stats: PeriodStat
  suffix?: string
}) {
  if (!stats) return null
  const fmt = (n: number) => (n >= 100 ? n.toFixed(0) : n.toFixed(1))
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm tabular-nums">
      <span>
        <span className="font-semibold text-foreground">{fmt(stats.avg)}{suffix}</span>
        <span className="ml-1 text-xs uppercase tracking-wide text-muted-foreground">avg</span>
      </span>
      <span>
        <span className="font-semibold text-foreground">{fmt(stats.max)}{suffix}</span>
        <span className="ml-1 text-xs uppercase tracking-wide text-muted-foreground">max</span>
      </span>
      <span>
        <span className="font-semibold text-foreground">{fmt(stats.min)}{suffix}</span>
        <span className="ml-1 text-xs uppercase tracking-wide text-muted-foreground">min</span>
      </span>
    </div>
  )
}


export function NodeMetricsCharts() {
  const [timeframe, setTimeframe] = useState("day")
  const [data, setData] = useState<NodeMetricsData[]>([])
  // period_stats from the backend — computed over the raw RRD points
  // BEFORE the 5-min downsampling so the chart header's MAX/MIN
  // captures real per-minute extremes (a 1-min CPU spike still shows
  // up on the 24h view's MAX).
  const [periodStats, setPeriodStats] = useState<{
    cpu?: PeriodStat
    memory_used?: PeriodStat
  }>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<MetricsError | null>(null)
  const isMobile = useIsMobile()

  const [visibleLines, setVisibleLines] = useState({
    cpu: { cpu: true, load: true },
    memory: { memoryTotal: true, memoryUsed: true, memoryZfsArc: true, memoryFree: true },
  })

  // Check if ZFS ARC or Free memory have any non-zero values to decide if we should show them
  const hasZfsArc = data.some(d => d.memoryZfsArc > 0)
  const hasMemoryFree = data.some(d => d.memoryFree > 0)

  useEffect(() => {
    fetchMetrics()
  }, [timeframe])

  const fetchMetrics = async () => {
    setLoading(true)
    setError(null)

    try {
      const result = await fetchApi<any>(`/api/node/metrics?timeframe=${timeframe}`)


      if (!result.data || !Array.isArray(result.data)) {
        console.error("Invalid data format - data is not an array:", result)
        throw new Error("Invalid data format received from server")
      }

      if (result.data.length === 0) {
        console.warn("No data points received")
        setData([])
        setLoading(false)
        return
      }

      if (result.data[0]?.loadavg) {
      }

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
            hour12: false,
          })
        } else {
          timeLabel = date.toLocaleString("en-US", {
            month: "short",
            day: "numeric",
          })
        }

        return {
          time: timeLabel,
          timestamp: item.time,
          cpu: item.cpu ? Number((item.cpu * 100).toFixed(2)) : 0,
          load: item.loadavg
            ? typeof item.loadavg === "number"
              ? Number(item.loadavg.toFixed(2))
              : Array.isArray(item.loadavg) && item.loadavg.length > 0
                ? Number(item.loadavg[0].toFixed(2))
                : 0
            : 0,
          memoryTotal: item.memtotal ? Number((item.memtotal / 1024 / 1024 / 1024).toFixed(2)) : 0,
          memoryUsed: item.memused ? Number((item.memused / 1024 / 1024 / 1024).toFixed(2)) : 0,
          memoryFree: item.memfree ? Number((item.memfree / 1024 / 1024 / 1024).toFixed(2)) : 0,
          memoryZfsArc: item.zfsarc ? Number((item.zfsarc / 1024 / 1024 / 1024).toFixed(2)) : 0,
        }
      })

      setData(transformedData)
      setPeriodStats(result.period_stats || {})
    } catch (err: any) {
      console.error("Error fetching node metrics:", err)
      // fetchApi attaches the parsed JSON body to err.body. The metrics
      // endpoint enriches 503 responses with `details` (Proxmox-side
      // diagnostic) and `suggestion` (how to fix). Pull them through so
      // the user sees actionable text instead of a bare "503".
      const body = err?.body
      setError({
        headline: body?.error || err?.message || "Error loading metrics",
        details: body?.details,
        suggestion: body?.suggestion,
      })
    } finally {
      setLoading(false)
    }
  }

  const tickInterval = Math.ceil(data.length / 8)

  const handleLegendClick = (chartType: "cpu" | "memory", dataKey: string) => {
    setVisibleLines((prev) => ({
      ...prev,
      [chartType]: {
        ...prev[chartType],
        [dataKey as keyof (typeof prev)[typeof chartType]]:
          !prev[chartType][dataKey as keyof (typeof prev)[typeof chartType]],
      },
    }))
  }

  const renderLegend = (chartType: "cpu" | "memory") => (props: any) => {
    const { payload } = props
    return (
      <div className="flex justify-center gap-4 pb-2 flex-wrap">
        {payload.map((entry: any, index: number) => {
          // For memory chart, hide ZFS ARC and Free from legend if they have no data
          if (chartType === "memory") {
            if (entry.dataKey === "memoryZfsArc" && !hasZfsArc) return null
            if (entry.dataKey === "memoryFree" && !hasMemoryFree) return null
          }
          const isVisible = visibleLines[chartType][entry.dataKey as keyof (typeof visibleLines)[typeof chartType]]
          return (
            <div
              key={`legend-${index}`}
              className="flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
              onClick={() => handleLegendClick(chartType, entry.dataKey)}
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
    // Both panels carry the same error — render an identical card on
    // each side. The headline is the short cause, the details block
    // explains it's a Proxmox-host issue (not a Monitor bug), and the
    // suggestion is the exact command the operator should run.
    const errorCard = (
      <Card className="bg-card border-border">
        <CardContent className="p-6">
          <div className="flex flex-col items-start justify-center h-[300px] gap-2 px-2 overflow-auto">
            <p className="text-sm font-semibold text-red-400">{error.headline}</p>
            {error.details && (
              <p className="text-xs text-muted-foreground leading-relaxed">{error.details}</p>
            )}
            {error.suggestion && (
              <div className="w-full mt-2">
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
                  Suggested fix on the Proxmox host
                </p>
                <code className="block text-xs bg-background/60 border border-border rounded px-2 py-1.5 font-mono break-all">
                  {error.suggestion}
                </code>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    )
    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {errorCard}
        {errorCard}
      </div>
    )
  }

  if (data.length === 0) {
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
          <CardHeader className="px-4 md:px-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <CardTitle className="text-foreground flex items-center">
                <TrendingUp className="h-5 w-5 mr-2" />
                CPU Usage & Load Average
              </CardTitle>
              <ChartStatsHeader stats={periodStats.cpu ?? null} suffix="%" />
            </div>
          </CardHeader>
          <CardContent className="px-0 md:px-6">
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={data} margin={{ bottom: 60, left: 0, right: 0 }}>
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
                  label={
                    isMobile ? undefined : { value: "CPU %", angle: -90, position: "insideLeft", fill: "currentColor" }
                  }
                  domain={[0, "dataMax"]}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  stroke="currentColor"
                  className="text-foreground"
                  tick={{ fill: "currentColor", fontSize: 12 }}
                  label={
                    isMobile ? undefined : { value: "Load", angle: 90, position: "insideRight", fill: "currentColor" }
                  }
                  domain={[0, "dataMax"]}
                />
                <Tooltip content={<CustomCpuTooltip />} />
                <Legend verticalAlign="top" height={36} content={renderLegend("cpu")} />
                <Area
                  yAxisId="left"
                  type="monotone"
                  dataKey="cpu"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  fill="#3b82f6"
                  fillOpacity={0.3}
                  name="CPU %"
                  hide={!visibleLines.cpu.cpu}
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
                  hide={!visibleLines.cpu.load}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Memory Usage Chart */}
        <Card className="bg-card border-border">
          <CardHeader className="px-4 md:px-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <CardTitle className="text-foreground flex items-center">
                <MemoryStick className="h-5 w-5 mr-2" />
                Memory Usage
              </CardTitle>
              <ChartStatsHeader stats={periodStats.memory_used ?? null} suffix=" GB" />
            </div>
          </CardHeader>
          <CardContent className="px-0 pr-2 md:px-6">
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={data} margin={{ bottom: 60, left: 0, right: 0 }}>
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
                  label={
                    isMobile ? undefined : { value: "GB", angle: -90, position: "insideLeft", fill: "currentColor" }
                  }
                  domain={[0, "dataMax"]}
                />
                <Tooltip content={<CustomMemoryTooltip />} />
                <Legend verticalAlign="top" height={36} content={renderLegend("memory")} />
                <Area
                  type="monotone"
                  dataKey="memoryTotal"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  fill="#3b82f6"
                  fillOpacity={0.1}
                  name="Total"
                  hide={!visibleLines.memory.memoryTotal}
                />
                <Area
                  type="monotone"
                  dataKey="memoryUsed"
                  stroke="#10b981"
                  strokeWidth={2}
                  fill="#10b981"
                  fillOpacity={0.3}
                  name="Used"
                  hide={!visibleLines.memory.memoryUsed}
                />
                {/* Only show ZFS ARC if there's data */}
                {hasZfsArc && (
                  <Area
                    type="monotone"
                    dataKey="memoryZfsArc"
                    stroke="#f59e0b"
                    strokeWidth={2}
                    fill="#f59e0b"
                    fillOpacity={0.3}
                    name="ZFS ARC"
                    hide={!visibleLines.memory.memoryZfsArc}
                  />
                )}
                {/* Only show Free memory if there's data */}
                {hasMemoryFree && (
                  <Area
                    type="monotone"
                    dataKey="memoryFree"
                    stroke="#06b6d4"
                    strokeWidth={2}
                    fill="#06b6d4"
                    fillOpacity={0.3}
                    name="Free"
                    hide={!visibleLines.memory.memoryFree}
                  />
                )}
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
