"use client"

import { useState, useEffect } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Thermometer, TrendingDown, TrendingUp, Minus } from "lucide-react"
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts"
import { useIsMobile } from "../hooks/use-mobile"
import { fetchApi } from "@/lib/api-config"
import { useDiskTempThresholds, type DiskTempThreshold } from "@/lib/health-thresholds"

const TIMEFRAME_OPTIONS = [
  { value: "hour", label: "1 Hour" },
  { value: "day", label: "24 Hours" },
  { value: "week", label: "7 Days" },
  { value: "month", label: "30 Days" },
]

interface TempHistoryPoint {
  timestamp: number
  value: number
  min?: number
  max?: number
}

interface TempStats {
  min: number
  max: number
  avg: number
  current: number
}

interface DiskTemperatureDetailModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  diskName: string
  diskModel?: string
  liveTemperature?: number
  diskType?: "HDD" | "SSD" | "NVMe" | "SAS" | string
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-900/95 backdrop-blur-sm border border-gray-700 rounded-lg p-3 shadow-xl">
        <p className="text-sm font-semibold text-white mb-2">{label}</p>
        <div className="space-y-1.5">
          {payload.map((entry: any, index: number) => (
            <div key={index} className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: entry.color }} />
              <span className="text-xs text-gray-300 min-w-[60px]">{entry.name}:</span>
              <span className="text-sm font-semibold text-white">{entry.value}°C</span>
            </div>
          ))}
        </div>
      </div>
    )
  }
  return null
}

// Per-disk-class thresholds come from the user-configurable backend
// (lib/health-thresholds.ts), so the chart line color stays in sync
// with whatever the user sets in Settings → Health Monitor Thresholds.
function colorFor(temp: number, t: DiskTempThreshold): string {
  if (temp >= t.hot) return "#ef4444"
  if (temp >= t.warn) return "#f59e0b"
  return "#22c55e"
}

function statusInfoFor(temp: number, t: DiskTempThreshold) {
  if (temp <= 0) return { status: "N/A", color: "bg-gray-500/10 text-gray-500 border-gray-500/20" }
  if (temp >= t.hot) return { status: "Hot", color: "bg-red-500/10 text-red-500 border-red-500/20" }
  if (temp >= t.warn) return { status: "Warm", color: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20" }
  return { status: "Normal", color: "bg-green-500/10 text-green-500 border-green-500/20" }
}

export function DiskTemperatureDetailModal({
  open,
  onOpenChange,
  diskName,
  diskModel,
  liveTemperature,
  diskType,
}: DiskTemperatureDetailModalProps) {
  const [timeframe, setTimeframe] = useState("day")
  const [data, setData] = useState<TempHistoryPoint[]>([])
  const [stats, setStats] = useState<TempStats>({ min: 0, max: 0, avg: 0, current: 0 })
  const [loading, setLoading] = useState(true)
  const isMobile = useIsMobile()

  useEffect(() => {
    if (open && diskName) {
      fetchHistory()
    }
  }, [open, timeframe, diskName])

  const fetchHistory = async () => {
    setLoading(true)
    try {
      const result = await fetchApi<{ data: TempHistoryPoint[]; stats: TempStats }>(
        `/api/disk/${encodeURIComponent(diskName)}/temperature/history?timeframe=${timeframe}`,
      )
      if (result && result.data) {
        setData(result.data)
        setStats(result.stats)
      } else {
        setData([])
        setStats({ min: 0, max: 0, avg: 0, current: 0 })
      }
    } catch (err) {
      console.error("[ProxMenux] Failed to fetch disk temperature history:", err)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp * 1000)
    if (timeframe === "hour" || timeframe === "day") {
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    }
    return date.toLocaleDateString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
  }

  const chartData = data.map((d) => ({ ...d, time: formatTime(d.timestamp) }))

  const currentTemp = liveTemperature && liveTemperature > 0 ? Math.round(liveTemperature * 10) / 10 : stats.current
  const allThresholds = useDiskTempThresholds()
  const dt: DiskTempThreshold = (() => {
    const t = (diskType || "").toUpperCase()
    if (t === "HDD") return allThresholds.HDD
    if (t === "NVME") return allThresholds.NVMe
    if (t === "SAS") return allThresholds.SAS
    return allThresholds.SSD
  })()
  const chartColor = colorFor(currentTemp, dt)
  const currentStatus = statusInfoFor(currentTemp, dt)

  const values = data.map((d) => d.value)
  const yMin = values.length > 0 ? Math.max(0, Math.floor(Math.min(...values) - 3)) : 0
  const yMax = values.length > 0 ? Math.ceil(Math.max(...values) + 3) : 100

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl bg-card border-border px-3 sm:px-6">
        <DialogHeader>
          {/*
            Header layout mirrors temperature-detail-modal exactly so the
            mobile breakpoints behave the same. Earlier we tried to inline
            the model name in the DialogTitle, but the long WD/Samsung
            strings broke `truncate` and pushed the dialog past the
            viewport — clipping the timeframe selector and the right two
            stat cards. Keeping the title short and parking the model in
            a second line (DialogDescription) lets the standard mobile
            grid render correctly.
          */}
          <div className="flex items-center justify-between pr-6">
            <DialogTitle className="text-foreground flex items-center gap-2">
              <Thermometer className="h-5 w-5" />
              /dev/{diskName}
            </DialogTitle>
            <Select value={timeframe} onValueChange={setTimeframe}>
              <SelectTrigger className="w-[130px] bg-card border-border">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIMEFRAME_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {diskModel && (
            <p className="text-xs text-muted-foreground truncate pr-6 mt-0.5">{diskModel}</p>
          )}
        </DialogHeader>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
          <div className={`rounded-lg p-3 text-center border ${currentStatus.color}`}>
            <div className="text-xs opacity-80 mb-1">Current</div>
            <div className="text-lg font-bold">{currentTemp > 0 ? `${currentTemp}°C` : "N/A"}</div>
          </div>
          <div className="bg-muted/50 rounded-lg p-3 text-center">
            <div className="text-xs text-muted-foreground mb-1 flex items-center justify-center gap-1">
              <TrendingDown className="h-3 w-3" /> Min
            </div>
            <div className="text-lg font-bold text-green-500">{stats.min}°C</div>
          </div>
          <div className="bg-muted/50 rounded-lg p-3 text-center">
            <div className="text-xs text-muted-foreground mb-1 flex items-center justify-center gap-1">
              <Minus className="h-3 w-3" /> Avg
            </div>
            <div className="text-lg font-bold text-foreground">{stats.avg}°C</div>
          </div>
          <div className="bg-muted/50 rounded-lg p-3 text-center">
            <div className="text-xs text-muted-foreground mb-1 flex items-center justify-center gap-1">
              <TrendingUp className="h-3 w-3" /> Max
            </div>
            <div className="text-lg font-bold text-red-500">{stats.max}°C</div>
          </div>
        </div>

        <div className="h-[300px] lg:h-[350px]">
          {loading ? (
            <div className="h-full flex items-center justify-center">
              <div className="space-y-3 w-full animate-pulse">
                <div className="h-4 bg-muted rounded w-1/4 mx-auto" />
                <div className="h-[250px] bg-muted/50 rounded" />
              </div>
            </div>
          ) : chartData.length === 0 ? (
            <div className="h-full flex items-center justify-center text-muted-foreground">
              <div className="text-center">
                <Thermometer className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p>No temperature data yet for this disk</p>
                <p className="text-sm mt-1">Samples are collected every 60 seconds</p>
              </div>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id={`diskTempGradient-${diskName}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={chartColor} stopOpacity={0.3} />
                    <stop offset="100%" stopColor={chartColor} stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-border" />
                <XAxis
                  dataKey="time"
                  stroke="currentColor"
                  className="text-foreground"
                  tick={{ fill: "currentColor", fontSize: isMobile ? 10 : 12 }}
                  interval="preserveStartEnd"
                  minTickGap={isMobile ? 40 : 60}
                />
                <YAxis
                  domain={[yMin, yMax]}
                  stroke="currentColor"
                  className="text-foreground"
                  tick={{ fill: "currentColor", fontSize: isMobile ? 10 : 12 }}
                  tickFormatter={(v) => `${v}°`}
                  width={isMobile ? 40 : 45}
                />
                <Tooltip content={<CustomTooltip />} />
                <Area
                  type="monotone"
                  dataKey="value"
                  name="Temperature"
                  stroke={chartColor}
                  strokeWidth={2}
                  fill={`url(#diskTempGradient-${diskName})`}
                  dot={false}
                  activeDot={{ r: 4, fill: chartColor, stroke: "#fff", strokeWidth: 2 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
