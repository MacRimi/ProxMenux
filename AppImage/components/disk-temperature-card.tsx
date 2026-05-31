"use client"

import { useEffect, useRef, useState } from "react"
import { Thermometer } from "lucide-react"
import { Badge } from "./ui/badge"
import { AreaChart, Area, ResponsiveContainer, Tooltip } from "recharts"
import { fetchApi } from "@/lib/api-config"
import { useDiskTempThresholds } from "@/lib/health-thresholds"

interface TempPoint {
  timestamp: number
  value: number
}

interface DiskTemperatureCardProps {
  diskName: string
  liveTemperature: number
  /** Disk class — "HDD" | "SSD" | "NVMe" | "SAS". Drives the threshold colors. */
  diskType: string
  /** Click handler — opens the full timeframe-selector modal as drill-down. */
  onOpenDetail?: () => void
}

// Disk-temperature thresholds come from the user-configurable backend
// (lib/health-thresholds.ts). The classifier here takes the resolved
// pair so the consumer can read it from the hook once per render.
function statusFor(temp: number, t: { warn: number; hot: number }) {
  if (temp <= 0) return { label: "N/A", className: "bg-gray-500/10 text-gray-500 border-gray-500/20", color: "#6b7280" }
  if (temp >= t.hot) return { label: "Hot", className: "bg-red-500/10 text-red-500 border-red-500/20", color: "#ef4444" }
  if (temp >= t.warn) return { label: "Warm", className: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20", color: "#f59e0b" }
  return { label: "Normal", className: "bg-green-500/10 text-green-500 border-green-500/20", color: "#22c55e" }
}

const MiniTooltip = ({ active, payload }: any) => {
  if (active && payload && payload.length) {
    const ts = payload[0].payload?.timestamp
    const date = ts ? new Date(ts * 1000) : null
    return (
      <div className="bg-gray-900/95 backdrop-blur-sm border border-gray-700 rounded-md px-2 py-1 shadow-xl">
        {date && (
          <p className="text-[10px] text-gray-300">
            {date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </p>
        )}
        <p className="text-xs font-semibold text-white">{payload[0].value}°C</p>
      </div>
    )
  }
  return null
}

export function DiskTemperatureCard({
  diskName,
  liveTemperature,
  diskType,
  onOpenDetail,
}: DiskTemperatureCardProps) {
  const [data, setData] = useState<TempPoint[]>([])
  const [loading, setLoading] = useState(true)
  const cancelled = useRef(false)

  useEffect(() => {
    cancelled.current = false
    const fetchHistory = async () => {
      setLoading(true)
      try {
        const result = await fetchApi<{ data: TempPoint[] }>(
          `/api/disk/${encodeURIComponent(diskName)}/temperature/history?timeframe=hour`,
        )
        if (cancelled.current) return
        setData(result?.data || [])
      } catch {
        if (!cancelled.current) setData([])
      } finally {
        if (!cancelled.current) setLoading(false)
      }
    }
    fetchHistory()
    // Refresh once a minute so the inline chart tracks the collector
    // without needing the user to reopen the modal.
    const id = setInterval(fetchHistory, 60_000)
    return () => {
      cancelled.current = true
      clearInterval(id)
    }
  }, [diskName])

  const allThresholds = useDiskTempThresholds()
  const dt = (() => {
    const t = (diskType || "").toUpperCase()
    if (t === "HDD") return allThresholds.HDD
    if (t === "NVME") return allThresholds.NVMe
    if (t === "SAS") return allThresholds.SAS
    return allThresholds.SSD
  })()
  const status = statusFor(liveTemperature, dt)
  const lineColor = status.color
  const tempDisplay = liveTemperature > 0 ? `${liveTemperature}°C` : "N/A"
  const samples = data.length

  const interactive = !!onOpenDetail
  const Wrapper: any = interactive ? "button" : "div"

  return (
    <Wrapper
      type={interactive ? "button" : undefined}
      onClick={interactive ? onOpenDetail : undefined}
      className={[
        "w-full text-left border border-white/10 rounded-lg p-3 bg-white/[0.02]",
        interactive ? "cursor-pointer hover:bg-white/[0.04] transition-colors focus:outline-none focus:ring-1 focus:ring-white/20" : "",
      ].join(" ")}
      title={interactive ? "Open temperature history" : undefined}
    >
      <div className="flex items-start justify-between gap-3 mb-1.5">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Temperature</p>
          <p className="text-xl font-bold leading-tight mt-0.5" style={{ color: lineColor }}>
            {tempDisplay}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1 flex-shrink-0">
          <Thermometer className="h-3.5 w-3.5" style={{ color: lineColor }} />
          <Badge variant="outline" className={`${status.className} text-[10px] px-2 py-0`}>
            {status.label}
          </Badge>
        </div>
      </div>

      <div className="h-[40px] -mx-1">
        {loading ? (
          <div className="h-full w-full animate-pulse bg-white/[0.03] rounded" />
        ) : samples < 2 ? (
          <div className="h-full flex items-center justify-center text-[10px] text-muted-foreground">
            Collecting samples — chart populates after ~2 minutes
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 2, right: 4, left: 4, bottom: 0 }}>
              <defs>
                <linearGradient id={`diskTempCardGrad-${diskName}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={lineColor} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={lineColor} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <Tooltip content={<MiniTooltip />} cursor={{ stroke: lineColor, strokeOpacity: 0.3, strokeWidth: 1 }} />
              <Area
                type="monotone"
                dataKey="value"
                stroke={lineColor}
                strokeWidth={1.6}
                fill={`url(#diskTempCardGrad-${diskName})`}
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </Wrapper>
  )
}
