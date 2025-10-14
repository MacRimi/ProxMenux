"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import {
  HardDrive,
  Database,
  Archive,
  AlertTriangle,
  CheckCircle,
  Activity,
  AlertCircle,
  Thermometer,
} from "lucide-react"

interface StorageData {
  total: number
  used: number
  available: number
  disks: DiskInfo[]
}

interface DiskInfo {
  name: string
  mountpoint: string
  fstype: string
  total: number
  used: number
  available: number
  usage_percent: number
  health: string
  temperature: number
  disk_type?: string
}

const TEMP_THRESHOLDS = {
  HDD: { safe: 45, warning: 55 },
  SSD: { safe: 55, warning: 65 },
  NVMe: { safe: 60, warning: 70 },
}

const getTempStatus = (temp: number, diskType: string): "safe" | "warning" | "critical" => {
  const thresholds = TEMP_THRESHOLDS[diskType as keyof typeof TEMP_THRESHOLDS] || TEMP_THRESHOLDS.HDD
  if (temp <= thresholds.safe) return "safe"
  if (temp <= thresholds.warning) return "warning"
  return "critical"
}

const getTempColor = (status: "safe" | "warning" | "critical"): string => {
  switch (status) {
    case "safe":
      return "text-green-500"
    case "warning":
      return "text-yellow-500"
    case "critical":
      return "text-red-500"
    default:
      return "text-muted-foreground"
  }
}

const getDiskTypeBadgeColor = (diskType: string): string => {
  switch (diskType) {
    case "HDD":
      return "bg-blue-500/10 text-blue-500 border-blue-500/20"
    case "SSD":
      return "bg-purple-500/10 text-purple-500 border-purple-500/20"
    case "NVMe":
      return "bg-orange-500/10 text-orange-500 border-orange-500/20"
    default:
      return "bg-gray-500/10 text-gray-500 border-gray-500/20"
  }
}

const fetchStorageData = async (): Promise<StorageData | null> => {
  try {
    const response = await fetch("/api/storage", {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      signal: AbortSignal.timeout(5000),
    })

    if (!response.ok) {
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const data = await response.json()
    return data
  } catch (error) {
    console.error("Failed to fetch storage data from Flask server:", error)
    return null
  }
}

export function StorageMetrics() {
  const [storageData, setStorageData] = useState<StorageData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      setError(null)
      const result = await fetchStorageData()

      if (!result) {
        setError("Flask server not available. Please ensure the server is running.")
      } else {
        setStorageData(result)
      }

      setLoading(false)
    }

    fetchData()
    const interval = setInterval(fetchData, 60000)
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8">
          <div className="text-lg font-medium text-foreground mb-2">Loading storage data...</div>
        </div>
      </div>
    )
  }

  if (error || !storageData) {
    return (
      <div className="space-y-6">
        <Card className="bg-red-500/10 border-red-500/20">
          <CardContent className="p-6">
            <div className="flex items-center gap-3 text-red-600">
              <AlertCircle className="h-6 w-6" />
              <div>
                <div className="font-semibold text-lg mb-1">Flask Server Not Available</div>
                <div className="text-sm">
                  {error || "Unable to connect to the Flask server. Please ensure the server is running and try again."}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const usagePercent = storageData.total > 0 ? (storageData.used / storageData.total) * 100 : 0

  const disksByType = storageData.disks.reduce(
    (acc, disk) => {
      const type = disk.disk_type || "Unknown"
      if (!acc[type]) {
        acc[type] = []
      }
      acc[type].push(disk)
      return acc
    },
    {} as Record<string, DiskInfo[]>,
  )

  const tempByType = Object.entries(disksByType)
    .map(([type, disks]) => {
      const avgTemp = disks.reduce((sum, disk) => sum + disk.temperature, 0) / disks.length
      const status = getTempStatus(avgTemp, type)
      return { type, avgTemp: Math.round(avgTemp), status, count: disks.length }
    })
    .filter((item) => item.type !== "Unknown") // Filter out unknown types

  return (
    <div className="space-y-6">
      {/* Storage Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Storage</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{storageData.total.toFixed(1)} GB</div>
            <Progress value={usagePercent} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2">
              {storageData.used.toFixed(1)} GB used • {storageData.available.toFixed(1)} GB available
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Used Storage</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{storageData.used.toFixed(1)} GB</div>
            <Progress value={usagePercent} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2">{usagePercent.toFixed(1)}% of total space</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Archive className="h-5 w-5 mr-2" />
              Available
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{storageData.available.toFixed(1)} GB</div>
            <div className="flex items-center mt-2">
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                {((storageData.available / storageData.total) * 100).toFixed(1)}% Free
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Available space</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Activity className="h-5 w-5 mr-2" />
              Disks
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{storageData.disks.length}</div>
            <div className="flex items-center space-x-2 mt-2">
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                {storageData.disks.filter((d) => d.health === "healthy").length} Healthy
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Storage devices</p>
          </CardContent>
        </Card>
      </div>

      {tempByType.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {tempByType.map(({ type, avgTemp, status, count }) => (
            <Card key={type} className="bg-card border-border">
              <CardHeader>
                <CardTitle className="text-foreground flex items-center justify-between">
                  <div className="flex items-center">
                    <Thermometer className="h-5 w-5 mr-2" />
                    Avg Temperature
                  </div>
                  <Badge variant="outline" className={getDiskTypeBadgeColor(type)}>
                    {type}
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className={`text-3xl font-bold ${getTempColor(status)}`}>{avgTemp}°C</div>
                <p className="text-xs text-muted-foreground mt-2">
                  {count} {type} disk{count > 1 ? "s" : ""}
                </p>
                <div className="mt-3">
                  <Badge
                    variant="outline"
                    className={
                      status === "safe"
                        ? "bg-green-500/10 text-green-500 border-green-500/20"
                        : status === "warning"
                          ? "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                          : "bg-red-500/10 text-red-500 border-red-500/20"
                    }
                  >
                    {status === "safe" ? "Optimal" : status === "warning" ? "Warning" : "Critical"}
                  </Badge>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Disk Details */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-foreground flex items-center">
            <Database className="h-5 w-5 mr-2" />
            Storage Devices
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {storageData.disks.map((disk, index) => {
              const diskType = disk.disk_type || "HDD"
              const tempStatus = getTempStatus(disk.temperature, diskType)

              return (
                <div
                  key={index}
                  className="flex items-center justify-between p-4 rounded-lg border border-border bg-card/50"
                >
                  <div className="flex items-center space-x-4">
                    <HardDrive className="h-5 w-5 text-muted-foreground" />
                    <div>
                      <div className="font-medium text-foreground flex items-center gap-2">
                        {disk.name}
                        {disk.disk_type && (
                          <Badge variant="outline" className={getDiskTypeBadgeColor(disk.disk_type)}>
                            {disk.disk_type}
                          </Badge>
                        )}
                      </div>
                      <div className="text-sm text-muted-foreground">
                        {disk.fstype} • {disk.mountpoint}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-6">
                    <div className="text-right">
                      <div className="text-sm font-medium text-foreground">
                        {disk.used.toFixed(1)} GB / {disk.total.toFixed(1)} GB
                      </div>
                      <Progress value={disk.usage_percent} className="w-24 mt-1" />
                    </div>

                    <div className="text-center">
                      <div className="text-sm text-muted-foreground">Temp</div>
                      <div className={`text-sm font-medium ${getTempColor(tempStatus)}`}>{disk.temperature}°C</div>
                    </div>

                    <Badge
                      variant="outline"
                      className={
                        disk.health === "healthy"
                          ? "bg-green-500/10 text-green-500 border-green-500/20"
                          : "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                      }
                    >
                      {disk.health === "healthy" ? (
                        <CheckCircle className="h-3 w-3 mr-1" />
                      ) : (
                        <AlertTriangle className="h-3 w-3 mr-1" />
                      )}
                      {disk.health}
                    </Badge>
                  </div>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
