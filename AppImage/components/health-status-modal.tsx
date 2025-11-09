"use client"

import type React from "react"

import { useState, useEffect } from "react"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Activity,
  Cpu,
  MemoryStick,
  HardDrive,
  Disc,
  Network,
  Box,
  Settings,
  FileText,
  RefreshCw,
  Shield,
  X,
} from "lucide-react"

interface CategoryCheck {
  status: string
  reason?: string
  details?: any
  [key: string]: any
}

interface HealthDetails {
  overall: string
  summary: string
  details: {
    cpu: CategoryCheck
    memory: CategoryCheck
    storage: CategoryCheck
    disks: CategoryCheck
    network: CategoryCheck
    vms: CategoryCheck
    services: CategoryCheck
    logs: CategoryCheck
    updates: CategoryCheck
    security: CategoryCheck
  }
  timestamp: string
}

interface HealthStatusModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  getApiUrl: (path: string) => string
}

const CATEGORIES = [
  { key: "cpu", label: "CPU Usage & Temperature", Icon: Cpu },
  { key: "memory", label: "Memory & Swap", Icon: MemoryStick },
  { key: "storage", label: "Storage Mounts & Space", Icon: HardDrive },
  { key: "disks", label: "Disk I/O & Errors", Icon: Disc },
  { key: "network", label: "Network Interfaces", Icon: Network },
  { key: "vms", label: "VMs & Containers", Icon: Box },
  { key: "services", label: "PVE Services", Icon: Settings },
  { key: "logs", label: "System Logs", Icon: FileText },
  { key: "updates", label: "System Updates", Icon: RefreshCw },
  { key: "security", label: "Security & Certificates", Icon: Shield },
]

export function HealthStatusModal({ open, onOpenChange, getApiUrl }: HealthStatusModalProps) {
  const [loading, setLoading] = useState(true)
  const [healthData, setHealthData] = useState<HealthDetails | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      fetchHealthDetails()
    }
  }, [open])

  const fetchHealthDetails = async () => {
    setLoading(true)
    setError(null)

    try {
      const response = await fetch(getApiUrl("/api/health/details"))
      if (!response.ok) {
        throw new Error("Failed to fetch health details")
      }
      const data = await response.json()
      console.log("[v0] Health data received:", data)
      setHealthData(data)
    } catch (err) {
      console.error("[v0] Error fetching health data:", err)
      setError(err instanceof Error ? err.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }

  const getStatusIcon = (status: string) => {
    const statusUpper = status?.toUpperCase()
    switch (statusUpper) {
      case "OK":
        return <CheckCircle2 className="h-5 w-5 text-green-500" />
      case "WARNING":
        return <AlertTriangle className="h-5 w-5 text-yellow-500" />
      case "CRITICAL":
        return <XCircle className="h-5 w-5 text-red-500" />
      default:
        return <Activity className="h-5 w-5 text-gray-500" />
    }
  }

  const getStatusBadge = (status: string) => {
    const statusUpper = status?.toUpperCase()
    switch (statusUpper) {
      case "OK":
        return <Badge className="bg-green-500 text-white hover:bg-green-500">OK</Badge>
      case "WARNING":
        return <Badge className="bg-yellow-500 text-white hover:bg-yellow-500">Warning</Badge>
      case "CRITICAL":
        return <Badge className="bg-red-500 text-white hover:bg-red-500">Critical</Badge>
      default:
        return <Badge>Unknown</Badge>
    }
  }

  const getHealthStats = () => {
    if (!healthData?.details) {
      return { total: 0, healthy: 0, warnings: 0, critical: 0 }
    }

    let healthy = 0
    let warnings = 0
    let critical = 0

    CATEGORIES.forEach(({ key }) => {
      const categoryData = healthData.details[key as keyof typeof healthData.details]
      if (categoryData) {
        const status = categoryData.status?.toUpperCase()
        if (status === "OK") healthy++
        else if (status === "WARNING") warnings++
        else if (status === "CRITICAL") critical++
      }
    })

    return { total: CATEGORIES.length, healthy, warnings, critical }
  }

  const stats = getHealthStats()

  const handleCategoryClick = (categoryKey: string, status: string) => {
    if (status === "OK") return // No navegar si está OK

    onOpenChange(false) // Cerrar el modal

    // Mapear categorías a tabs
    const categoryToTab: Record<string, string> = {
      storage: "storage",
      disks: "storage",
      network: "network",
      vms: "vms",
      logs: "logs",
      hardware: "hardware",
      services: "hardware",
    }

    const targetTab = categoryToTab[categoryKey]
    if (targetTab) {
      // Disparar evento para cambiar tab
      const event = new CustomEvent("changeTab", { detail: { tab: targetTab } })
      window.dispatchEvent(event)
    }
  }

  const handleAcknowledge = async (errorKey: string, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent navigation

    try {
      await fetch(getApiUrl(`/api/health/acknowledge/${errorKey}`), {
        method: "POST",
      })
      // Refresh health data
      await fetchHealthDetails()
    } catch (err) {
      console.error("[v0] Error acknowledging:", err)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Activity className="h-6 w-6" />
            System Health Status
          </DialogTitle>
          <div className="mt-4">{healthData && getStatusBadge(healthData.overall)}</div>
          <DialogDescription>Detailed health checks for all system components</DialogDescription>
        </DialogHeader>

        {loading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800 dark:bg-red-950 dark:border-red-800 dark:text-red-200">
            <p className="font-medium">Error loading health status</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {healthData && !loading && (
          <div className="space-y-4">
            {/* Overall Stats Summary */}
            <div className="grid grid-cols-4 gap-3 p-4 rounded-lg bg-muted/30 border">
              <div className="text-center">
                <div className="text-2xl font-bold">{stats.total}</div>
                <div className="text-xs text-muted-foreground">Total Checks</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-green-500">{stats.healthy}</div>
                <div className="text-xs text-muted-foreground">Healthy</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-yellow-500">{stats.warnings}</div>
                <div className="text-xs text-muted-foreground">Warnings</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-red-500">{stats.critical}</div>
                <div className="text-xs text-muted-foreground">Critical</div>
              </div>
            </div>

            {healthData.summary && healthData.summary !== "All systems operational" && (
              <div className="text-sm p-3 rounded-lg bg-muted/20 border">
                <span className="font-medium text-foreground">{healthData.summary}</span>
              </div>
            )}

            <div className="space-y-2">
              {CATEGORIES.map(({ key, label, Icon }) => {
                const categoryData = healthData.details[key as keyof typeof healthData.details]
                const status = categoryData?.status || "UNKNOWN"
                const reason = categoryData?.reason
                const details = categoryData?.details

                return (
                  <div
                    key={key}
                    onClick={() => handleCategoryClick(key, status)}
                    className={`flex items-start gap-3 p-3 rounded-lg border transition-colors ${
                      status === "OK"
                        ? "bg-green-500/5 border-green-500/20 hover:bg-green-500/10"
                        : status === "WARNING"
                          ? "bg-yellow-500/5 border-yellow-500/20 hover:bg-yellow-500/10 cursor-pointer"
                          : status === "CRITICAL"
                            ? "bg-red-500/5 border-red-500/20 hover:bg-red-500/10 cursor-pointer"
                            : "bg-muted/30 hover:bg-muted/50"
                    }`}
                  >
                    <div className="mt-0.5 flex-shrink-0 flex items-center gap-2">
                      <Icon className="h-4 w-4 text-muted-foreground" />
                      {getStatusIcon(status)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <p className="font-medium text-sm">{label}</p>
                        <Badge
                          variant="outline"
                          className={`shrink-0 text-xs ${
                            status === "OK"
                              ? "border-green-500 text-green-500 bg-green-500/5"
                              : status === "WARNING"
                                ? "border-yellow-500 text-yellow-500 bg-yellow-500/5"
                                : status === "CRITICAL"
                                  ? "border-red-500 text-red-500 bg-red-500/5"
                                  : ""
                          }`}
                        >
                          {status}
                        </Badge>
                      </div>
                      {reason && <p className="text-xs text-muted-foreground mt-1">{reason}</p>}
                      {details && typeof details === "object" && (
                        <div className="mt-2 space-y-1">
                          {Object.entries(details).map(([detailKey, detailValue]: [string, any]) => {
                            if (typeof detailValue === "object" && detailValue !== null) {
                              return (
                                <div
                                  key={detailKey}
                                  className="flex items-start justify-between gap-2 text-xs pl-3 border-l-2 border-muted"
                                >
                                  <div>
                                    <span className="font-medium">{detailKey}:</span>
                                    {detailValue.reason && (
                                      <span className="ml-1 text-muted-foreground">{detailValue.reason}</span>
                                    )}
                                  </div>
                                  {status !== "OK" && (
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className="h-5 px-1 hover:bg-red-500/10"
                                      onClick={(e) => handleAcknowledge(detailKey, e)}
                                    >
                                      <X className="h-3 w-3" />
                                    </Button>
                                  )}
                                </div>
                              )
                            }
                            return null
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            {healthData.timestamp && (
              <div className="text-xs text-muted-foreground text-center pt-2">
                Last updated: {new Date(healthData.timestamp).toLocaleString()}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
