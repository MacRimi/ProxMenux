"use client"

import { useState, useEffect } from "react"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Loader2, CheckCircle2, AlertTriangle, XCircle, Activity } from "lucide-react"

interface HealthCheck {
  category: string
  name: string
  status: "healthy" | "warning" | "critical"
  value: string
  message: string
  details: any
}

interface HealthDetails {
  overall: {
    status: "healthy" | "warning" | "critical"
    critical_count: number
    warning_count: number
    healthy_count: number
    total_checks: number
  }
  checks: HealthCheck[]
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
      setHealthData(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error")
    } finally {
      setLoading(false)
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "healthy":
        return <CheckCircle2 className="h-5 w-5 text-green-500" />
      case "warning":
        return <AlertTriangle className="h-5 w-5 text-yellow-500" />
      case "critical":
        return <XCircle className="h-5 w-5 text-red-500" />
      default:
        return <Activity className="h-5 w-5 text-gray-500" />
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "healthy":
        return <Badge className="bg-green-500">Healthy</Badge>
      case "warning":
        return <Badge className="bg-yellow-500">Warning</Badge>
      case "critical":
        return <Badge className="bg-red-500">Critical</Badge>
      default:
        return <Badge>Unknown</Badge>
    }
  }

  const groupedChecks =
    healthData?.checks && Array.isArray(healthData.checks)
      ? healthData.checks.reduce(
          (acc, check) => {
            if (!acc[check.category]) {
              acc[check.category] = []
            }
            acc[check.category].push(check)
            return acc
          },
          {} as Record<string, HealthCheck[]>,
        )
      : {}

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
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">
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
                  {getStatusBadge(healthData.overall.status)}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-4 gap-4 text-center">
                  <div>
                    <div className="text-2xl font-bold">{healthData.overall.total_checks}</div>
                    <div className="text-sm text-muted-foreground">Total Checks</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-green-500">{healthData.overall.healthy_count}</div>
                    <div className="text-sm text-muted-foreground">Healthy</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-yellow-500">{healthData.overall.warning_count}</div>
                    <div className="text-sm text-muted-foreground">Warnings</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-red-500">{healthData.overall.critical_count}</div>
                    <div className="text-sm text-muted-foreground">Critical</div>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Grouped Health Checks */}
            {groupedChecks &&
              Object.entries(groupedChecks).map(([category, checks]) => (
                <Card key={category}>
                  <CardHeader>
                    <CardTitle className="text-lg">{category}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      {checks.map((check, index) => (
                        <div
                          key={index}
                          className="flex items-start gap-3 rounded-lg border p-3 hover:bg-muted/50 transition-colors"
                        >
                          <div className="mt-0.5">{getStatusIcon(check.status)}</div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between gap-2">
                              <p className="font-medium">{check.name}</p>
                              <span className="text-sm font-mono text-muted-foreground whitespace-nowrap">
                                {check.value}
                              </span>
                            </div>
                            <p className="text-sm text-muted-foreground mt-1">{check.message}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
