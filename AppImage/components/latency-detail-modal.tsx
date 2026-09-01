"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Button } from "./ui/button"
import { Badge } from "./ui/badge"
import { Activity, TrendingDown, TrendingUp, Minus, RefreshCw, Wifi, FileText, Square } from "lucide-react"
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line } from "recharts"
import { useIsMobile } from "../hooks/use-mobile"
import { fetchApi } from "@/lib/api-config"
import { useT } from "../lib/i18n/provider"

type TFunction = (key: string, params?: Record<string, string | number>) => string

const TIMEFRAME_OPTIONS = [
  { value: "hour", labelKey: "network.latency.timeframes.hour" },
  { value: "6hour", labelKey: "network.latency.timeframes.sixHours" },
  { value: "day", labelKey: "network.latency.timeframes.day" },
  { value: "3day", labelKey: "network.latency.timeframes.threeDays" },
  { value: "week", labelKey: "network.latency.timeframes.week" },
]

const TARGET_OPTIONS = [
  { value: "gateway", labelKey: "network.latency.targets.gateway", shortLabelKey: "network.latency.targets.gatewayShort", realtime: false },
  { value: "cloudflare", labelKey: "network.latency.targets.cloudflare", shortLabelKey: "network.latency.targets.cloudflareShort", realtime: true },
  { value: "google", labelKey: "network.latency.targets.google", shortLabelKey: "network.latency.targets.googleShort", realtime: true },
  ]

// Realtime test configuration
const REALTIME_TEST_DURATION = 120 // 2 minutes in seconds
const REALTIME_TEST_INTERVAL = 5 // 5 seconds between tests

interface LatencyHistoryPoint {
  timestamp: number
  value: number
  min?: number
  max?: number
  packet_loss?: number
}

interface LatencyStats {
  min: number
  max: number
  avg: number
  current: number
}

interface RealtimeResult {
  target: string
  target_ip: string
  latency_avg: number | null
  latency_min: number | null
  latency_max: number | null
  packet_loss: number
  status: string
  timestamp?: number
}

interface LatencyDetailModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentLatency?: number
}

const getLatencyTimeframeLabel = (value: string, t: TFunction): string =>
  TIMEFRAME_OPTIONS.find((option) => option.value === value)
    ? t(TIMEFRAME_OPTIONS.find((option) => option.value === value)!.labelKey)
    : value

const getLatencyTargetLabel = (value: string, t: TFunction): string =>
  TARGET_OPTIONS.find((option) => option.value === value)
    ? t(TARGET_OPTIONS.find((option) => option.value === value)!.labelKey)
    : value

const getLatencyTargetShortLabel = (value: string, t: TFunction): string =>
  TARGET_OPTIONS.find((option) => option.value === value)
    ? t(TARGET_OPTIONS.find((option) => option.value === value)!.shortLabelKey)
    : value

const CustomTooltip = ({ active, payload, label, t }: any) => {
  if (active && payload && payload.length) {
    const entry = payload[0]
    const data = entry?.payload
    const packetLoss = data?.packet_loss
    const hasMinMax = data?.min !== undefined && data?.max !== undefined && data?.min !== data?.max
    
    return (
      <div className="bg-gray-900/95 backdrop-blur-sm border border-gray-700 rounded-lg p-3 shadow-xl">
        <p className="text-sm font-semibold text-white mb-2">{label}</p>
        <div className="space-y-1.5">
          {hasMinMax ? (
            // Show min/avg/max when downsampled data is available
            <>
              <div className="flex items-center gap-2">
                <div className="w-2.5 h-2.5 rounded-full flex-shrink-0 bg-green-500" />
                <span className="text-xs text-gray-300 min-w-[60px]">{t("network.labels.min")}:</span>
                <span className="text-sm font-semibold text-green-400">{data.min} ms</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-2.5 h-2.5 rounded-full flex-shrink-0 bg-blue-500" />
                <span className="text-xs text-gray-300 min-w-[60px]">{t("network.labels.avg")}:</span>
                <span className="text-sm font-semibold text-white">{data.value} ms</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-2.5 h-2.5 rounded-full flex-shrink-0 bg-red-500" />
                <span className="text-xs text-gray-300 min-w-[60px]">{t("network.labels.max")}:</span>
                <span className="text-sm font-semibold text-red-400">{data.max} ms</span>
              </div>
            </>
          ) : (
            // Simple latency display for single data points
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full flex-shrink-0 bg-blue-500" />
              <span className="text-xs text-gray-300 min-w-[60px]">{t("network.labels.latency")}:</span>
              <span className="text-sm font-semibold text-white">{entry.value} ms</span>
            </div>
          )}
          {packetLoss !== undefined && packetLoss > 0 && (
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full flex-shrink-0 bg-orange-500" />
              <span className="text-xs text-gray-300 min-w-[60px]">{t("network.labels.packetLossShort")}:</span>
              <span className="text-sm font-semibold text-orange-400">{packetLoss}%</span>
            </div>
          )}
        </div>
      </div>
    )
  }
  return null
}

const getStatusColor = (latency: number) => {
  if (latency >= 200) return "#ef4444"
  if (latency >= 100) return "#f59e0b"
  return "#22c55e"
}

const getStatusInfo = (latency: number | null, t: TFunction) => {
  if (latency === null || latency === 0) return { status: t("common.notAvailable"), color: "bg-gray-500/10 text-gray-500 border-gray-500/20" }
  if (latency < 50) return { status: t("network.latency.status.excellent"), color: "bg-green-500/10 text-green-500 border-green-500/20" }
  if (latency < 100) return { status: t("network.latency.status.good"), color: "bg-green-500/10 text-green-500 border-green-500/20" }
  if (latency < 200) return { status: t("network.latency.status.fair"), color: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20" }
  return { status: t("network.latency.status.poor"), color: "bg-red-500/10 text-red-500 border-red-500/20" }
}

const getStatusKey = (latency: number | null): "na" | "excellent" | "good" | "fair" | "poor" => {
  if (latency === null || latency === 0) return "na"
  if (latency < 50) return "excellent"
  if (latency < 100) return "good"
  if (latency < 200) return "fair"
  return "poor"
}

const getStatusText = (latency: number | null, t: TFunction): string => {
  const key = getStatusKey(latency)
  return key === "na" ? t("common.notAvailable") : t(`network.latency.status.${key}`)
}

const formatReportDuration = (seconds: number | undefined, t: TFunction, compact = false): string => {
  if (!seconds || seconds <= 0) {
    return compact ? t("network.latency.report.realTime") : t("network.latency.report.testPeriod")
  }

  if (seconds < 60) {
    return t(compact ? "network.latency.report.secondsShort" : "network.latency.report.seconds", { count: seconds })
  }

  const minutes = Math.max(1, Math.round(seconds / 60))
  return t(compact ? "network.latency.report.minutesShort" : "network.latency.report.minutes", { count: minutes })
}

interface ReportData {
  target: string
  targetLabel: string
  isRealtime: boolean
  stats: LatencyStats
  realtimeResults: RealtimeResult[]
  data: LatencyHistoryPoint[]
  timeframe: string
  testDuration?: number
}

const generateLatencyReport = (report: ReportData, t: TFunction) => {
  const now = new Date().toLocaleString()
  const logoUrl = `${window.location.origin}/images/proxmenux-logo.png`
  const htmlLang = document.documentElement.lang || "en"
  
  // Calculate stats for realtime results - all values are individual ping measurements in latency_avg
  const validRealtimeValues = report.realtimeResults.filter(r => r.latency_avg !== null).map(r => r.latency_avg!)
  const realtimeStats = validRealtimeValues.length > 0 ? {
    min: Math.min(...validRealtimeValues),
    max: Math.max(...validRealtimeValues),
    avg: validRealtimeValues.reduce((acc, v) => acc + v, 0) / validRealtimeValues.length,
    current: validRealtimeValues[validRealtimeValues.length - 1] ?? null,
    avgPacketLoss: report.realtimeResults.reduce((acc, r) => acc + (r.packet_loss || 0), 0) / report.realtimeResults.length,
  } : null

  const statusText = report.isRealtime 
    ? getStatusText(realtimeStats?.current ?? null, t)
    : getStatusText(report.stats.current, t)
  
  // Colors matching Lynis report
  const statusColorMap: Record<string, string> = {
    excellent: "#16a34a",
    good: "#16a34a",
    fair: "#ca8a04",
    poor: "#dc2626",
    na: "#64748b",
  }
  const statusKey = report.isRealtime
    ? getStatusKey(realtimeStats?.current ?? null)
    : getStatusKey(report.stats.current)
  const statusColor = statusColorMap[statusKey] || "#64748b"

  const timeframeLabel = getLatencyTimeframeLabel(report.timeframe, t)
  const reportId = `PMXL-${Date.now().toString(36).toUpperCase()}`
  const notAvailable = t("common.notAvailable")
  const modeLabel = report.isRealtime
    ? t("network.latency.report.realTimeTest")
    : t("network.latency.report.historicalAnalysis")
  const realtimeDurationText = formatReportDuration(report.testDuration, t)
  const realtimePacketLossText =
    realtimeStats && realtimeStats.avgPacketLoss > 0
      ? `<span style="color:#dc2626">${t("network.latency.report.averagePacketLoss", {
          value: realtimeStats.avgPacketLoss.toFixed(1),
        })}</span>`
      : `<span style="color:#16a34a">${t("network.latency.report.noPacketLoss")}</span>`
  const testPeriodValue = report.isRealtime
    ? formatReportDuration(report.testDuration, t, true)
    : timeframeLabel
  const targetIpLabel =
    report.target === "gateway"
      ? t("network.latency.report.defaultGateway")
      : report.target === "cloudflare"
        ? "1.1.1.1"
        : "8.8.8.8"
  const detailSectionNumber =
    (report.isRealtime && report.realtimeResults.length > 0) || (!report.isRealtime && report.data.length > 0)
      ? "6"
      : "5"

  // Build test results table for realtime mode - each row is now an individual ping measurement
  const realtimeTableRows = report.realtimeResults.map((r, i) => `
    <tr${r.packet_loss > 0 ? ' class="warn"' : ''}>
      <td>${i + 1}</td>
      <td>${new Date(r.timestamp || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</td>
      <td style="font-weight:600;color:${statusColorMap[getStatusKey(r.latency_avg)] || '#64748b'}">${r.latency_avg !== null ? r.latency_avg.toFixed(1) + ' ms' : t("network.latency.report.failed")}</td>
      <td${r.packet_loss > 0 ? ' style="color:#dc2626;font-weight:600;"' : ''}>${r.packet_loss}%</td>
      <td><span class="f-tag" style="background:${statusColorMap[getStatusKey(r.latency_avg)] || '#64748b'}15;color:${statusColorMap[getStatusKey(r.latency_avg)] || '#64748b'}">${getStatusText(r.latency_avg, t)}</span></td>
    </tr>
  `).join('')

  // Build history summary for gateway mode
  const historyStats = report.data.length > 0 ? {
    samples: report.data.length,
    avgPacketLoss: (report.data.reduce((acc, d) => acc + (d.packet_loss || 0), 0) / report.data.length).toFixed(2),
    startTime: new Date(report.data[0].timestamp * 1000).toLocaleString(),
    endTime: new Date(report.data[report.data.length - 1].timestamp * 1000).toLocaleString(),
  } : null

  // Build history table rows for gateway mode (last 20 records)
  const historyTableRows = report.data.slice(-20).map((d, i) => `
    <tr${d.packet_loss && d.packet_loss > 0 ? ' class="warn"' : ''}>
      <td>${i + 1}</td>
      <td>${new Date(d.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
      <td style="font-weight:600;color:${statusColorMap[getStatusKey(d.value)] || '#64748b'}">${d.value !== null ? d.value.toFixed(1) + ' ms' : t("network.latency.report.failed")}</td>
      <td${d.packet_loss && d.packet_loss > 0 ? ' style="color:#dc2626;font-weight:600;"' : ''}>${d.packet_loss?.toFixed(1) ?? 0}%</td>
      <td><span class="f-tag" style="background:${statusColorMap[getStatusKey(d.value)] || '#64748b'}15;color:${statusColorMap[getStatusKey(d.value)] || '#64748b'}">${getStatusText(d.value, t)}</span></td>
    </tr>
  `).join('')

  // Generate chart SVG - data already expanded for realtime
  const chartData = report.isRealtime
    ? report.realtimeResults.filter(r => r.latency_avg !== null).map(r => r.latency_avg!)
    : report.data.map(d => d.value || 0)
  
  let chartSvg = `<p style="text-align:center;color:#64748b;padding:20px;">${t("network.latency.report.notEnoughData")}</p>`
  if (chartData.length >= 2) {
    const rawMin = Math.min(...chartData)
    const rawMax = Math.max(...chartData)
    // Ensure a minimum range of 10ms or 20% of the average to avoid flat lines
    const avgVal = chartData.reduce((a, b) => a + b, 0) / chartData.length
    const minRange = Math.max(10, avgVal * 0.2)
    const range = Math.max(rawMax - rawMin, minRange)
    // Center the data if range was expanded
    const midPoint = (rawMin + rawMax) / 2
    const minVal = midPoint - range / 2
    const maxVal = midPoint + range / 2
    
    const width = 700
    const height = 120
    const padding = 40
    const chartHeight = height - padding * 2
    const chartWidth = width - padding * 2
    
    const points = chartData.map((val, i) => {
      const x = padding + (i / (chartData.length - 1)) * chartWidth
      const y = padding + chartHeight - ((val - minVal) / range) * chartHeight
      return `${x},${y}`
    }).join(' ')
    
    const areaPoints = `${padding},${height - padding} ${points} ${width - padding},${height - padding}`
    
    chartSvg = `
      <svg width="100%" viewBox="0 0 ${width} ${height}" style="display:block;">
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.3"/>
            <stop offset="100%" stop-color="#3b82f6" stop-opacity="0.05"/>
          </linearGradient>
        </defs>
        <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}" stroke="#e2e8f0" stroke-width="1"/>
        <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="#e2e8f0" stroke-width="1"/>
        <line x1="${padding}" y1="${height / 2}" x2="${width - padding}" y2="${height / 2}" stroke="#e2e8f0" stroke-width="1" stroke-dasharray="4"/>
        <text x="${padding - 5}" y="${padding + 4}" font-size="9" fill="#64748b" text-anchor="end">${Math.round(maxVal)}ms</text>
        <text x="${padding - 5}" y="${height / 2 + 3}" font-size="9" fill="#64748b" text-anchor="end">${Math.round((minVal + maxVal) / 2)}ms</text>
        <text x="${padding - 5}" y="${height - padding + 4}" font-size="9" fill="#64748b" text-anchor="end">${Math.round(minVal)}ms</text>
        <polygon points="${areaPoints}" fill="url(#areaGrad)"/>
        <polyline points="${points}" fill="none" stroke="#3b82f6" stroke-width="2"/>
        <text x="${width / 2}" y="${height - 5}" font-size="9" fill="#64748b" text-anchor="middle">${t("network.latency.report.samples", { count: chartData.length })}</text>
      </svg>
    `
  }

  const html = `<!DOCTYPE html>
<html lang="${htmlLang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${t("network.latency.report.title")} - ${report.targetLabel}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1a1a2e; background: #fff; font-size: 13px; line-height: 1.5; }
  @page { margin: 10mm; size: A4; }
  @media print {
    html, body { margin: 0 !important; padding: 0 !important; }
    .no-print { display: none !important; }
    .page-break { page-break-before: always; }
    * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
    body { font-size: 11px; padding-top: 0; }
    .section { margin-bottom: 16px; }
    .rpt-header-left p, .rpt-header-right { color: #374151; }
    .rpt-header-right .rid { color: #4b5563; }
    .exec-text p { color: #374151; }
    .score-bar-labels { color: #4b5563; }
    .card-label { color: #4b5563; }
    .card-sub { color: #374151; }
    .chk-tbl th { color: #374151; }
    .rpt-footer { color: #4b5563; }
  }
  @media screen {
    body { max-width: 1000px; margin: 0 auto; padding: 24px 32px; padding-top: 64px; }
  }
  
  /* Top bar for screen only */
  .top-bar {
    position: fixed; top: 0; left: 0; right: 0; background: #0f172a; color: #e2e8f0;
    padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; z-index: 100;
    font-size: 13px;
  }
  .top-bar-left { display: flex; align-items: center; gap: 12px; }
  .top-bar-title { font-weight: 600; }
  .top-bar-subtitle { font-size: 11px; color: #94a3b8; display: none; }
  .top-bar button {
    background: #06b6d4; color: #fff; border: none; padding: 10px 20px; border-radius: 6px;
    font-size: 14px; font-weight: 600; cursor: pointer;
  }
  .top-bar button:hover { background: #0891b2; }
  @media (min-width: 640px) {
    .top-bar { padding: 12px 24px; }
    .top-bar-subtitle { display: block; }
  }
  @media print { .top-bar { display: none; } body { padding-top: 0; } }

  /* Header */
  .rpt-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 0; border-bottom: 3px solid #0f172a; margin-bottom: 22px;
  }
  .rpt-header-left { display: flex; align-items: center; gap: 14px; }
  .rpt-header-left img { height: 44px; width: auto; }
  .rpt-header-left h1 { font-size: 22px; font-weight: 700; color: #0f172a; }
  .rpt-header-left p { font-size: 11px; color: #64748b; }
  .rpt-header-right { text-align: right; font-size: 11px; color: #64748b; line-height: 1.6; }
  .rpt-header-right .rid { font-family: monospace; font-size: 10px; color: #94a3b8; }

  /* Sections */
  .section { margin-bottom: 22px; }
  .section-title {
    font-size: 14px; font-weight: 700; color: #0f172a; text-transform: uppercase;
    letter-spacing: 0.05em; padding-bottom: 5px; border-bottom: 2px solid #e2e8f0; margin-bottom: 12px;
  }

  /* Executive summary */
  .exec-box {
    display: flex; align-items: flex-start; gap: 20px; padding: 20px;
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 16px;
    flex-wrap: wrap;
  }
  .score-ring {
    width: 96px; height: 96px; border-radius: 50%; display: flex; flex-direction: column;
    align-items: center; justify-content: center; border: 4px solid; flex-shrink: 0;
  }
  .score-num { font-size: 32px; font-weight: 800; line-height: 1; }
  .score-unit { font-size: 14px; font-weight: 600; opacity: 0.8; }
  .score-lbl { font-size: 9px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; margin-top: 2px; }
  .exec-text { flex: 1; min-width: 200px; }
  .exec-text h3 { font-size: 16px; margin-bottom: 4px; }
  .exec-text p { font-size: 12px; color: #64748b; line-height: 1.5; }

  /* Latency gauge */
  .latency-gauge {
    display: flex; flex-direction: column; align-items: center; flex-shrink: 0; width: 160px;
  }
  .gauge-value { display: flex; align-items: baseline; gap: 2px; margin-top: -10px; }
  .gauge-num { font-size: 32px; font-weight: 800; line-height: 1; }
  .gauge-unit { font-size: 14px; font-weight: 600; opacity: 0.8; }
  .gauge-status { font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; margin-top: 2px; }
  
  /* Latency range display */
  .latency-range {
    display: flex; gap: 16px; margin-top: 12px; padding-top: 12px; border-top: 1px solid #e2e8f0;
    flex-wrap: wrap;
  }
  .range-item { display: flex; flex-direction: column; gap: 2px; min-width: 60px; }
  .range-label { font-size: 9px; font-weight: 600; color: #94a3b8; text-transform: uppercase; }
  .range-value { font-size: 14px; font-weight: 700; }
  


  /* Grids */
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .grid-4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .card { padding: 10px 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; }
  .card-label { font-size: 10px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 2px; }
  .card-value { font-size: 13px; font-weight: 600; color: #0f172a; }
  .card-c { text-align: center; }
  .card-c .card-value { font-size: 20px; font-weight: 800; }
  .card-c .card-label { margin-top: 3px; margin-bottom: 0; }
  .card-sub { font-size: 9px; color: #64748b; margin-top: 2px; }

  /* Tags */
  .f-tag { font-size: 9px; padding: 2px 6px; border-radius: 4px; font-weight: 600; }

  /* Tables */
  .chk-tbl { width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 14px; }
  .chk-tbl th { text-align: left; padding: 6px 8px; font-size: 10px; color: #64748b; font-weight: 600; border-bottom: 1px solid #e2e8f0; background: #f1f5f9; }
  .chk-tbl td { padding: 5px 8px; border-bottom: 1px solid #f1f5f9; color: #1e293b; }
  .chk-tbl tr.warn { background: #fef2f2; }

  /* Thresholds */
  .threshold-item { 
    display: flex; align-items: center; gap: 10px; padding: 8px 12px;
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; margin-bottom: 6px;
  }
  .threshold-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .threshold-item p { font-size: 11px; color: #374151; }
  .threshold-item strong { color: #0f172a; }

  /* Info box */
  .info-box {
    background: #ecfeff; border: 1px solid #a5f3fc; border-left: 4px solid #06b6d4;
    border-radius: 4px; padding: 12px 14px; margin-top: 12px;
  }
  .info-box h4 { font-size: 11px; font-weight: 700; color: #0891b2; margin-bottom: 4px; }
  .info-box p { font-size: 11px; color: #0e7490; }

  /* Footer */
  .rpt-footer {
    margin-top: 32px; padding-top: 12px; border-top: 1px solid #e2e8f0;
    display: flex; justify-content: space-between; font-size: 10px; color: #94a3b8;
  }

  /* Print styles */
  @media print {
    * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
    body { padding: 10mm; font-size: 10pt; }
    .no-print { display: none !important; }
    .container { max-width: 100%; padding: 0; }
    
    /* Prevent page breaks inside elements */
    .section { page-break-inside: avoid; break-inside: avoid; }
    .exec-box { page-break-inside: avoid; break-inside: avoid; }
    .card { page-break-inside: avoid; break-inside: avoid; }
    .threshold-item { page-break-inside: avoid; break-inside: avoid; }
    .info-box { page-break-inside: avoid; break-inside: avoid; }
    .chk-tbl { page-break-inside: avoid; break-inside: avoid; }
    .latency-gauge { page-break-inside: avoid; break-inside: avoid; }
    .latency-range { page-break-inside: avoid; break-inside: avoid; }
    
    /* Force page breaks before major sections if needed */
    .section { page-break-before: auto; }
    
    /* Keep headers with their content */
    .section-title { page-break-after: avoid; break-after: avoid; }
    
    /* Ensure grids don't break awkwardly */
    .grid-2, .grid-3, .grid-4 { page-break-inside: avoid; break-inside: avoid; }
    
    /* Table rows - try to keep together */
    .chk-tbl tr { page-break-inside: avoid; break-inside: avoid; }
    .chk-tbl thead { display: table-header-group; }
    
    /* Footer always at bottom */
    .rpt-footer { 
      page-break-inside: avoid; break-inside: avoid;
      margin-top: 20px;
    }
    
    /* Reduce spacing for print */
    .section { margin-bottom: 15px; }
    .exec-box { padding: 12px; }
    
    /* Ensure SVG charts print correctly */
    svg { max-width: 100%; height: auto; }
  }

  /* NOTE: No mobile-specific print overrides — print layout is always A4/desktop
     regardless of the device generating the PDF. The @media print block above
     handles all necessary print adjustments. */
</style>
</head>
<body>

<!-- Top bar for screen -->
<div class="top-bar no-print">
  <div class="top-bar-left">
    <div>
      <div class="top-bar-title">${t("network.latency.report.topBarTitle")}</div>
      <div class="top-bar-subtitle">${t("network.latency.report.topBarSubtitle")}</div>
    </div>
  </div>
  <button onclick="window.print()">${t("network.latency.report.printSavePdf")}</button>
</div>

<!-- Header -->
<div class="rpt-header">
  <div class="rpt-header-left">
    <img src="${logoUrl}" alt="ProxMenux" onerror="this.style.display='none'" />
    <div>
      <h1>${t("network.latency.report.title")}</h1>
      <p>${t("network.latency.report.subtitle")}</p>
    </div>
  </div>
  <div class="rpt-header-right">
    <div><strong>${t("network.latency.report.date")}:</strong> ${now}</div>
    <div><strong>${t("network.latency.report.target")}:</strong> ${report.targetLabel}</div>
    <div><strong>${t("network.latency.report.mode")}:</strong> ${modeLabel}</div>
    <div class="rid">ID: ${reportId}</div>
  </div>
</div>

<!-- 1. Executive Summary -->
<div class="section">
  <div class="section-title">1. ${t("network.latency.report.executiveSummary")}</div>
  <div class="exec-box">
    <div class="latency-gauge">
      <svg viewBox="0 0 120 90" width="160" height="120">
        <!-- Gauge background arc -->
        <path d="M 10 70 A 50 50 0 0 1 110 70" fill="none" stroke="#e2e8f0" stroke-width="8" stroke-linecap="round"/>
        <!-- Colored segments: Excellent (green), Good (green), Fair (yellow), Poor (red) -->
        <path d="M 10 70 A 50 50 0 0 1 35 28" fill="none" stroke="#16a34a" stroke-width="8" stroke-linecap="round"/>
        <path d="M 35 28 A 50 50 0 0 1 60 20" fill="none" stroke="#22c55e" stroke-width="8"/>
        <path d="M 60 20 A 50 50 0 0 1 85 28" fill="none" stroke="#ca8a04" stroke-width="8"/>
        <path d="M 85 28 A 50 50 0 0 1 110 70" fill="none" stroke="#dc2626" stroke-width="8" stroke-linecap="round"/>
        <!-- Needle -->
        <line x1="60" y1="70" x2="${60 + 40 * Math.cos(Math.PI - (Math.min(300, report.isRealtime ? (realtimeStats?.avg ?? 0) : parseFloat(String(report.stats.avg))) / 300) * Math.PI)}" y2="${70 - 40 * Math.sin(Math.PI - (Math.min(300, report.isRealtime ? (realtimeStats?.avg ?? 0) : parseFloat(String(report.stats.avg))) / 300) * Math.PI)}" stroke="${statusColor}" stroke-width="3" stroke-linecap="round"/>
        <circle cx="60" cy="70" r="6" fill="${statusColor}"/>
        <!-- Labels -->
        <text x="8" y="87" font-size="7" fill="#64748b">0</text>
        <text x="98" y="87" font-size="7" fill="#64748b">300+</text>
      </svg>
      <div class="gauge-value" style="color:${statusColor};">
        <span class="gauge-num">${report.isRealtime ? (realtimeStats?.avg?.toFixed(0) ?? notAvailable) : report.stats.avg}</span>
        <span class="gauge-unit">ms</span>
      </div>
      <div class="gauge-status" style="color:${statusColor};">${statusText}</div>
    </div>
    <div class="exec-text">
      <h3>${t("network.latency.report.assessmentTitle")}${report.isRealtime ? ` (${t("network.latency.report.realTime")})` : ""}</h3>
      <p>
        ${report.isRealtime 
          ? `${t("network.latency.report.realtimeSummary", {
              target: `<strong>${report.targetLabel}</strong>`,
              count: `<strong>${report.realtimeResults.length}</strong>`,
              duration: realtimeDurationText,
              avg: `<strong style="color:${statusColor}">${realtimeStats?.avg?.toFixed(1) ?? notAvailable} ms</strong>`,
            })} ${realtimePacketLossText}`
          : `${t("network.latency.report.historicalSummary", {
              target: t("network.latency.targets.gatewayShort"),
              timeframe: timeframeLabel.toLowerCase(),
              count: report.data.length,
              avg: report.stats.avg,
            })}`
        }
      </p>
      <div class="latency-range">
        <div class="range-item">
          <span class="range-label">${t("network.labels.minimum")}</span>
          <span class="range-value" style="color:#16a34a;">${report.isRealtime ? (realtimeStats?.min?.toFixed(1) ?? notAvailable) : report.stats.min} ms</span>
        </div>
        <div class="range-item">
          <span class="range-label">${t("network.labels.average")}</span>
          <span class="range-value" style="color:${statusColor};">${report.isRealtime ? (realtimeStats?.avg?.toFixed(1) ?? notAvailable) : report.stats.avg} ms</span>
        </div>
        <div class="range-item">
          <span class="range-label">${t("network.labels.maximum")}</span>
          <span class="range-value" style="color:#dc2626;">${report.isRealtime ? (realtimeStats?.max?.toFixed(1) ?? notAvailable) : report.stats.max} ms</span>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- 2. Statistics -->
<div class="section">
  <div class="section-title">2. ${t("network.latency.report.latencyStatistics")}</div>
  <div class="grid-4">
    <div class="card card-c">
      <div class="card-value" style="color:${statusColor};">${report.isRealtime ? (realtimeStats?.current?.toFixed(1) ?? notAvailable) : report.stats.current}<span style="font-size:10px;color:#64748b;"> ms</span></div>
      <div class="card-label">${t("network.labels.current")}</div>
    </div>
    <div class="card card-c">
      <div class="card-value" style="color:#16a34a;">${report.isRealtime ? (realtimeStats?.min?.toFixed(1) ?? notAvailable) : report.stats.min}<span style="font-size:10px;color:#64748b;"> ms</span></div>
      <div class="card-label">${t("network.labels.minimum")}</div>
    </div>
    <div class="card card-c">
      <div class="card-value">${report.isRealtime ? (realtimeStats?.avg?.toFixed(1) ?? notAvailable) : report.stats.avg}<span style="font-size:10px;color:#64748b;"> ms</span></div>
      <div class="card-label">${t("network.labels.average")}</div>
    </div>
    <div class="card card-c">
      <div class="card-value" style="color:#dc2626;">${report.isRealtime ? (realtimeStats?.max?.toFixed(1) ?? notAvailable) : report.stats.max}<span style="font-size:10px;color:#64748b;"> ms</span></div>
      <div class="card-label">${t("network.labels.maximum")}</div>
    </div>
  </div>
  <div class="grid-3">
    <div class="card">
      <div class="card-label">${t("network.latency.report.sampleCount")}</div>
      <div class="card-value">${report.isRealtime ? report.realtimeResults.length : report.data.length}</div>
    </div>
    <div class="card">
      <div class="card-label">${t("network.latency.report.packetLossAvg")}</div>
      <div class="card-value" style="color:${(report.isRealtime ? (realtimeStats?.avgPacketLoss ?? 0) : parseFloat(historyStats?.avgPacketLoss ?? '0')) > 0 ? '#dc2626' : '#16a34a'};">
        ${report.isRealtime ? (realtimeStats?.avgPacketLoss?.toFixed(1) ?? '0') : (historyStats?.avgPacketLoss ?? '0')}%
      </div>
    </div>
    <div class="card">
      <div class="card-label">${t("network.latency.report.testPeriodLabel")}</div>
      <div class="card-value" style="font-size:11px;">
        ${testPeriodValue}
      </div>
    </div>
  </div>
</div>

<!-- 3. Latency Graph (always section 3) -->
<div class="section">
  <div class="section-title">3. ${t("network.latency.report.latencyGraph")}</div>
  <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;">
    ${chartSvg}
  </div>
</div>

<!-- 4. Performance Thresholds (always section 4) -->
<div class="section">
  <div class="section-title">4. ${t("network.latency.report.performanceThresholds")}</div>
  <div class="threshold-item">
    <div class="threshold-dot" style="background:#16a34a;"></div>
    <p><strong>${t("network.latency.status.excellent")} (&lt; 50ms):</strong> ${t("network.latency.report.thresholdExcellent")}</p>
  </div>
  <div class="threshold-item">
    <div class="threshold-dot" style="background:#16a34a;"></div>
    <p><strong>${t("network.latency.status.good")} (50-100ms):</strong> ${t("network.latency.report.thresholdGood")}</p>
  </div>
  <div class="threshold-item">
    <div class="threshold-dot" style="background:#ca8a04;"></div>
    <p><strong>${t("network.latency.status.fair")} (100-200ms):</strong> ${t("network.latency.report.thresholdFair")}</p>
  </div>
  <div class="threshold-item">
    <div class="threshold-dot" style="background:#dc2626;"></div>
    <p><strong>${t("network.latency.status.poor")} (&gt; 200ms):</strong> ${t("network.latency.report.thresholdPoor")}</p>
  </div>
</div>

  ${report.isRealtime && report.realtimeResults.length > 0 ? `
  <!-- 5. Detailed Test Results (for Cloudflare / Google DNS) -->
  <div class="section">
  <div class="section-title">5. ${t("network.latency.report.detailedTestResults")}</div>
  <table class="chk-tbl">
  <thead>
  <tr>
  <th>#</th>
  <th>${t("network.labels.time")}</th>
  <th>${t("network.labels.latency")}</th>
  <th>${t("network.labels.packetLoss")}</th>
  <th>${t("network.labels.status")}</th>
  </tr>
  </thead>
  <tbody>
  ${realtimeTableRows}
  </tbody>
  </table>
</div>
` : ''}

${!report.isRealtime && report.data.length > 0 ? `
<!-- 5. Detailed History (for Gateway) -->
<div class="section">
  <div class="section-title">5. ${t("network.latency.report.latencyHistory", { count: Math.min(20, report.data.length) })}</div>
  <table class="chk-tbl">
  <thead>
  <tr>
  <th>#</th>
  <th>${t("network.labels.time")}</th>
  <th>${t("network.labels.latency")}</th>
  <th>${t("network.labels.packetLoss")}</th>
  <th>${t("network.labels.status")}</th>
  </tr>
  </thead>
  <tbody>
  ${historyTableRows}
  </tbody>
  </table>
</div>
` : ''}

<!-- Methodology -->
<div class="section">
  <div class="section-title">${detailSectionNumber}. ${t("network.latency.report.methodology")}</div>
  <div class="grid-2">
    <div class="card">
      <div class="card-label">${t("network.latency.report.testMethod")}</div>
      <div class="card-value" style="font-size:12px;">${t("network.latency.report.icmpEchoRequest")}</div>
    </div>
    <div class="card">
      <div class="card-label">${t("network.latency.report.samplesPerTest")}</div>
      <div class="card-value" style="font-size:12px;">${t("network.latency.report.threeConsecutivePings")}</div>
    </div>
    <div class="card">
      <div class="card-label">${t("network.latency.report.target")}</div>
      <div class="card-value" style="font-size:12px;">${report.targetLabel}</div>
    </div>
    <div class="card">
      <div class="card-label">${t("network.latency.report.targetIp")}</div>
      <div class="card-value" style="font-size:12px;">${targetIpLabel}</div>
    </div>
  </div>
  <div class="info-box">
    <h4>${t("network.latency.report.performanceAssessment")}</h4>
    <p>${
      statusKey === 'excellent' ? t("network.latency.report.assessmentExcellent") :
      statusKey === 'good' ? t("network.latency.report.assessmentGood") :
      statusKey === 'fair' ? t("network.latency.report.assessmentFair") :
      statusKey === 'poor' ? t("network.latency.report.assessmentPoor") :
      t("network.latency.report.assessmentUnknown")
    }</p>
  </div>
</div>

<!-- Footer -->
<div class="rpt-footer">
  <div>${t("network.latency.report.footerTitle")}</div>
  <div>${t("network.latency.report.generated")}: ${now} | ${t("network.latency.report.reportId")}: ${reportId}</div>
</div>

</body>
</html>`

  // Use Blob URL for Safari-safe preview
  const blob = new Blob([html], { type: "text/html" })
  const url = URL.createObjectURL(blob)
  window.open(url, "_blank")
}

export function LatencyDetailModal({ open, onOpenChange, currentLatency }: LatencyDetailModalProps) {
  const t = useT()
  const [timeframe, setTimeframe] = useState("hour")
  const [target, setTarget] = useState("gateway")
  const [data, setData] = useState<LatencyHistoryPoint[]>([])
  const [stats, setStats] = useState<LatencyStats>({ min: 0, max: 0, avg: 0, current: 0 })
  const [loading, setLoading] = useState(true)
  const [realtimeResults, setRealtimeResults] = useState<RealtimeResult[]>([])
  const [realtimeTesting, setRealtimeTesting] = useState(false)
  const [testProgress, setTestProgress] = useState(0) // 0-100 percentage
  const [testStartTime, setTestStartTime] = useState<number | null>(null)
  const testIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const isMobile = useIsMobile()

  const isRealtime = TARGET_OPTIONS.find(t => t.value === target)?.realtime ?? false

  // Cleanup on unmount or close
  useEffect(() => {
    if (!open) {
      stopRealtimeTest()
    }
    return () => {
      stopRealtimeTest()
    }
  }, [open])

  // Fetch history for gateway
  useEffect(() => {
    if (open && target === "gateway") {
      fetchHistory()
    }
  }, [open, timeframe, target])

  // Auto-start test when switching to realtime target
  useEffect(() => {
    if (open && isRealtime) {
      // Clear previous results and start new test
      setRealtimeResults([])
      startRealtimeTest()
    } else {
      stopRealtimeTest()
    }
  }, [open, target])

  const fetchHistory = async () => {
    setLoading(true)
    try {
      const result = await fetchApi<{ data: LatencyHistoryPoint[]; stats: LatencyStats; target: string }>(
        `/api/network/latency/history?target=${target}&timeframe=${timeframe}`
      )
      if (result && result.data) {
        setData(result.data)
        setStats(result.stats)
      }
    } catch (err) {
      // Silently fail
    } finally {
      setLoading(false)
    }
  }

  const runSingleTest = useCallback(async () => {
    try {
      const result = await fetchApi<RealtimeResult>(`/api/network/latency/current?target=${target}`)
      if (result) {
        const baseTime = Date.now()
        // Expand each ping result into 3 individual samples (min, avg, max) with slightly different timestamps
        // This ensures the graph shows all actual measured values, not just averages
        const samples: RealtimeResult[] = []
        
        if (result.latency_min !== null) {
          samples.push({
            ...result,
            latency_avg: result.latency_min,
            timestamp: baseTime - 200,  // Slightly earlier
          })
        }
        if (result.latency_avg !== null && result.latency_avg !== result.latency_min && result.latency_avg !== result.latency_max) {
          samples.push({
            ...result,
            latency_avg: result.latency_avg,
            timestamp: baseTime,
          })
        }
        if (result.latency_max !== null) {
          samples.push({
            ...result,
            latency_avg: result.latency_max,
            timestamp: baseTime + 200,  // Slightly later
          })
        }
        
        // Fallback if no valid samples
        if (samples.length === 0 && result.latency_avg !== null) {
          samples.push({ ...result, timestamp: baseTime })
        }
        
        setRealtimeResults(prev => [...prev, ...samples])
      }
    } catch (err) {
      // Silently fail
    }
  }, [target])

  const startRealtimeTest = useCallback(() => {
    if (realtimeTesting) return
    
    setRealtimeTesting(true)
    setTestProgress(0)
    setTestStartTime(Date.now())
    
    // Run first test immediately
    runSingleTest()
    
    // Set up interval for subsequent tests
    const totalTests = REALTIME_TEST_DURATION / REALTIME_TEST_INTERVAL
    let testCount = 1
    
    testIntervalRef.current = setInterval(() => {
      testCount++
      const progress = Math.min(100, (testCount / totalTests) * 100)
      setTestProgress(progress)
      
      runSingleTest()
      
      // Stop after duration
      if (testCount >= totalTests) {
        stopRealtimeTest()
      }
    }, REALTIME_TEST_INTERVAL * 1000)
  }, [realtimeTesting, runSingleTest])

  const stopRealtimeTest = useCallback(() => {
    if (testIntervalRef.current) {
      clearInterval(testIntervalRef.current)
      testIntervalRef.current = null
    }
    setRealtimeTesting(false)
    setTestProgress(100)
  }, [])

  const restartRealtimeTest = useCallback(() => {
    // Don't clear results - add to existing data
    startRealtimeTest()
  }, [startRealtimeTest])

  // Format chart data
  const chartData = data.map(point => ({
    ...point,
    time: new Date(point.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  }))

  // Data already expanded to individual ping values - just format for chart
  const realtimeChartData = realtimeResults
    .filter(r => r.latency_avg !== null)
    .map(r => ({
      time: new Date(r.timestamp || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      value: r.latency_avg,
      packet_loss: r.packet_loss
    }))

  // Calculate realtime stats - all values are now individual ping measurements stored in latency_avg
  const validValues = realtimeResults.filter(r => r.latency_avg !== null).map(r => r.latency_avg!)
  const realtimeStats = validValues.length > 0 ? {
    current: validValues[validValues.length - 1],
    min: Math.min(...validValues),
    max: Math.max(...validValues),
    avg: validValues.reduce((acc, v) => acc + v, 0) / validValues.length,
    packetLoss: realtimeResults[realtimeResults.length - 1]?.packet_loss ?? 0,
  } : null

  const displayStats = isRealtime ? {
    current: realtimeStats?.current ?? 0,
    min: realtimeStats?.min ?? 0,
    max: realtimeStats?.max ?? 0,
    avg: Math.round((realtimeStats?.avg ?? 0) * 10) / 10,
  } : stats

  const statusInfo = getStatusInfo(displayStats.current, t)

  // Calculate test duration for report based on first and last result timestamps
  const testDuration = realtimeResults.length >= 2 
    ? Math.round(((realtimeResults[realtimeResults.length - 1].timestamp || Date.now()) - (realtimeResults[0].timestamp || Date.now())) / 1000)
    : realtimeResults.length === 1 
    ? 5 // Single sample = 5 seconds (one test)
    : 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto bg-background border-border">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-foreground">
            <Wifi className="h-5 w-5 text-blue-500" />
            {t("network.cards.latency")}
          </DialogTitle>
        </DialogHeader>
        <div className="flex items-center gap-2 mt-1 flex-nowrap">
          <Select value={target} onValueChange={setTarget}>
            <SelectTrigger className="w-[140px] sm:w-[180px] h-8 text-xs shrink-0">
              <span className="truncate">
                {getLatencyTargetShortLabel(target, t)}
              </span>
            </SelectTrigger>
            <SelectContent>
              {TARGET_OPTIONS.map(opt => (
                <SelectItem key={opt.value} value={opt.value} className="text-xs">
                  {t(opt.labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!isRealtime && (
            <Select value={timeframe} onValueChange={setTimeframe}>
              <SelectTrigger className="w-[100px] h-8 text-xs shrink-0">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIMEFRAME_OPTIONS.map(opt => (
                  <SelectItem key={opt.value} value={opt.value} className="text-xs">
                    {t(opt.labelKey)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {isRealtime && (
            realtimeTesting ? (
              <Button
                variant="outline"
                size="sm"
                onClick={stopRealtimeTest}
                className="gap-1.5 text-red-500 border-red-500/30 hover:bg-red-500/10 shrink-0 h-8 px-3"
              >
                <Square className="h-3 w-3 fill-current" />
                {t("network.latency.actions.stop")}
              </Button>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={restartRealtimeTest}
                className="gap-1.5 shrink-0 h-8 px-3"
              >
                <RefreshCw className="h-3 w-3" />
                {t("network.latency.actions.testAgain")}
              </Button>
            )
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => generateLatencyReport({
              target,
              targetLabel: getLatencyTargetLabel(target, t),
              isRealtime,
              stats,
              realtimeResults,
              data,
              timeframe,
              testDuration: isRealtime ? testDuration : undefined,
            }, t)}
            disabled={isRealtime ? realtimeResults.length === 0 : data.length === 0}
            className="gap-1.5 shrink-0 h-8 px-3"
          >
            <FileText className="h-3.5 w-3.5" />
            {t("network.latency.actions.report")}
          </Button>
        </div>

        {/* Progress bar for realtime test */}
        {isRealtime && realtimeTesting && (
          <div className="mb-4">
            <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
              <span>{t("network.latency.testingProgress", { percent: Math.round(testProgress) })}</span>
              <span>{t("network.latency.secondsRemaining", { seconds: Math.round((REALTIME_TEST_DURATION * (1 - testProgress / 100))) })}</span>
            </div>
            <div className="h-1.5 bg-muted rounded-full overflow-hidden">
              <div 
                className="h-full bg-blue-500 transition-all duration-500 ease-out"
                style={{ width: `${testProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* Stats Cards - Compact single row */}
        <div className="flex items-center justify-between gap-1 mb-2 py-2 px-1 bg-muted/20 rounded-lg">
          <div className="flex items-center gap-1 min-w-0">
            <span className="text-[10px] text-muted-foreground">{t("network.labels.current")}</span>
            <span className="text-base font-bold" style={{ color: getStatusColor(displayStats.current || 0) }}>
              {displayStats.current || '-'}
            </span>
            <span className="text-[10px] text-muted-foreground">ms</span>
          </div>
          <div className="flex items-center gap-1 min-w-0">
            <TrendingDown className="h-3 w-3 text-green-500 shrink-0" />
            <span className="text-[10px] text-muted-foreground">{t("network.labels.min")}</span>
            <span className="text-base font-bold text-green-500">{displayStats.min || '-'}</span>
            <span className="text-[10px] text-muted-foreground">ms</span>
          </div>
          <div className="flex items-center gap-1 min-w-0">
            <Minus className="h-3 w-3 shrink-0" />
            <span className="text-[10px] text-muted-foreground">{t("network.labels.avg")}</span>
            <span className="text-base font-bold">{displayStats.avg || '-'}</span>
            <span className="text-[10px] text-muted-foreground">ms</span>
          </div>
          <div className="flex items-center gap-1 min-w-0">
            <TrendingUp className="h-3 w-3 text-red-500 shrink-0" />
            <span className="text-[10px] text-muted-foreground">{t("network.labels.max")}</span>
            <span className="text-base font-bold text-red-500">{displayStats.max || '-'}</span>
            <span className="text-[10px] text-muted-foreground">ms</span>
          </div>
        </div>

        {/* Status Badge */}
        <div className="flex items-center justify-between mb-4">
          <Badge variant="outline" className={statusInfo.color}>
            {statusInfo.status}
          </Badge>
          {isRealtime && (
            <span className="text-xs text-muted-foreground">
              {t("network.latency.samplesCollected", { count: realtimeResults.length })}
              {realtimeStats?.packetLoss ? ` | ${t("network.latency.packetLossValue", { value: realtimeStats.packetLoss })}` : ""}
            </span>
          )}
        </div>

        {/* Chart */}
        <div className="h-[250px] sm:h-[300px] w-full">
          {isRealtime ? (
            realtimeChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={realtimeChartData}>
                  <defs>
                    <linearGradient id="latencyRealtimeGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.05} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
                  <XAxis 
                    dataKey="time" 
                    stroke="#6b7280" 
                    fontSize={10}
                    tickLine={false}
                    interval="preserveStartEnd"
                  />
                  <YAxis 
                    stroke="#6b7280" 
                    fontSize={10}
                    tickLine={false}
                    domain={['dataMin - 1', 'dataMax + 2']}
                    tickFormatter={(v) => `${Number(v).toFixed(1)}ms`}
                  />
                  <Tooltip content={<CustomTooltip t={t} />} />
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    fill="url(#latencyRealtimeGradient)"
                    dot={{ fill: '#3b82f6', strokeWidth: 0, r: 3 }}
                    activeDot={{ r: 5, fill: '#3b82f6' }}
                    baseValue="dataMin"
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
                <Activity className="h-12 w-12 mb-3 opacity-30" />
                <p className="text-sm">
                  {realtimeTesting ? t("network.latency.collectingData") : t("network.latency.noRealtimeData")}
                </p>
              </div>
            )
          ) : loading ? (
            <div className="h-full flex items-center justify-center">
              <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="latencyGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
                <XAxis 
                  dataKey="time" 
                  stroke="#6b7280" 
                  fontSize={10}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis 
                  stroke="#6b7280" 
                  fontSize={10}
                  tickLine={false}
                  domain={['dataMin - 1', 'dataMax + 2']}
                  tickFormatter={(v) => `${Number(v).toFixed(1)}ms`}
                />
                <Tooltip content={<CustomTooltip t={t} />} />
                {/* For longer timeframes (6h+), show max values to preserve spikes.
                    For 1 hour view, show avg values since there's no downsampling */}
                <Area
                  type="monotone"
                  dataKey={timeframe === "hour" ? "value" : "max"}
                  stroke="#3b82f6"
                  strokeWidth={2}
                  fill="url(#latencyGradient)"
                  baseValue="dataMin"
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
              <Activity className="h-12 w-12 mb-3 opacity-30" />
              <p className="text-sm">{t("network.latency.noDataForPeriod")}</p>
              <p className="text-xs mt-1">{t("network.latency.collectionInterval")}</p>
            </div>
          )}
        </div>

        {/* Info for realtime mode */}
        {isRealtime && (
          <div className="mt-4 p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg">
            <p className="text-xs text-blue-400">
              <strong>{t("network.latency.realTimeMode")}:</strong> {t("network.latency.realTimeModeDescription")}
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
