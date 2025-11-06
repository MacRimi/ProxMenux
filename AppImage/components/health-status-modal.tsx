"use client"

import { useState, useEffect } from "react"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Loader2, CheckCircle2, AlertTriangle, XCircle, Activity } from "lucide-react"

interface HealthDetail {
  status: string
  reason?: string
  [key: string]: any
}

interface HealthDetails {
  overall: string
  summary: string
  details: {
    [category: string]: HealthDetail | { [key: string]: HealthDetail }
  }
  timestamp: string
}

interface HealthStatusModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  getApiUrl: (path: string) => string
}

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

  const getHealthStats = () => {
    if (!healthData?.details) {
      return { total: 0, healthy: 0, warnings: 0, critical: 0 }
    }

    let healthy = 0
    let warnings = 0
    let critical = 0
    let total = 0

    const countStatus = (detail: any) => {
      if (detail && typeof detail === "object" && detail.status) {
        total++
        const status = detail.status.toUpperCase()
        if (status === "OK") healthy++
        else if (status === "WARNING") warnings++
        else if (status === "CRITICAL") critical++
      }
    }

    Object.values(healthData.details).forEach((categoryData) => {
      if (categoryData && typeof categoryData === "object") {
        if ("status" in categoryData) {
          countStatus(categoryData)
        } else {
          Object.values(categoryData).forEach(countStatus)
        }
      }
    })

    return { total, healthy, warnings, critical }
  }

  const getGroupedChecks = () => {
    if (!healthData?.details) return {}

    const grouped: { [key: string]: Array<{ name: string; status: string; reason?: string; details?: any }> } = {}

    Object.entries(healthData.details).forEach(([category, categoryData]) => {
      if (!categoryData || typeof categoryData !== "object") return

      const categoryName = category.charAt(0).toUpperCase() + category.slice(1)
      grouped[categoryName] = []

      if ("status" in categoryData) {
        grouped[categoryName].push({
          name: categoryName,
          status: categoryData.status,
          reason: categoryData.reason,
          details: categoryData,
        })
      } else {
        Object.entries(categoryData).forEach(([subKey, subData]: [string, any]) => {
          if (subData && typeof subData === "object" && "status" in subData) {
            grouped[categoryName].push({
              name: subKey,
              status: subData.status,
              reason: subData.reason,
              details: subData,
            })
          }
        })
      }
    })

    return grouped
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
        return <Badge className="bg-green-500">Healthy</Badge>
      case "WARNING":
        return <Badge className="bg-yellow-500">Warning</Badge>
      case "CRITICAL":
        return <Badge className="bg-red-500">Critical</Badge>
      default:
        return <Badge>Unknown</Badge>
    }
  }

  const stats = getHealthStats()
  const groupedChecks = getGroupedChecks()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Activity className="h-6 w-6" />
            System Health Status
          </DialogTitle>
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
          <div className="space-y-6">
            {/* Overall Status Summary */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <span>Overall Status</span>
                  {getStatusBadge(healthData.overall)}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {healthData.summary && <p className="text-sm text-muted-foreground mb-4">{healthData.summary}</p>}
                <div className="grid grid-cols-4 gap-4 text-center">
                  <div>
                    <div className="text-2xl font-bold">{stats.total}</div>
                    <div className="text-sm text-muted-foreground">Total Checks</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-green-500">{stats.healthy}</div>
                    <div className="text-sm text-muted-foreground">Healthy</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-yellow-500">{stats.warnings}</div>
                    <div className="text-sm text-muted-foreground">Warnings</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-red-500">{stats.critical}</div>
                    <div className="text-sm text-muted-foreground">Critical</div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Grouped Health Checks */}
            {Object.entries(groupedChecks).map(([category, checks]) => (
              <Card key={category}>
                <CardHeader>
                  <CardTitle className="text-lg">{category}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    {checks.map((check, index) => (
                      <div
                        key={`${category}-${index}`}
                        className="flex items-start gap-3 rounded-lg border p-3 hover:bg-muted/50 transition-colors"
                      >
                        <div className="mt-0.5">{getStatusIcon(check.status)}</div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-2">
                            <p className="font-medium">{check.name}</p>
                            <Badge variant="outline" className="shrink-0">
                              {check.status}
                            </Badge>
                          </div>
                          {check.reason && <p className="text-sm text-muted-foreground mt-1">{check.reason}</p>}
                          {check.details && (
                            <div className="text-xs text-muted-foreground mt-2 space-y-0.5">
                              {Object.entries(check.details).map(([key, value]) => {
                                if (key === "status" || key === "reason" || typeof value === "object") return null
                                return (
                                  <div key={key} className="font-mono">
                                    {key}: {String(value)}
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}

            {healthData.timestamp && (
              <div className="text-xs text-muted-foreground text-center">
                Last updated: {new Date(healthData.timestamp).toLocaleString()}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
