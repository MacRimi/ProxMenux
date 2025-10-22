"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { HardDrive, Database, Archive, AlertTriangle, CheckCircle, Activity, AlertCircle } from "lucide-react"

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
}

const fetchStorageData = async (): Promise<StorageData | null> => {
  try {
    console.log("[v0] Fetching storage data from Flask server...")
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
    console.log("[v0] Successfully fetched storage data from Flask:", data)
    return data
  } catch (error) {
    console.error("[v0] Failed to fetch storage data from Flask server:", error)
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

  return (
    <div className="space-y-6">
      {/* Storage Overview Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Storage</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">{storageData.total.toFixed(1)} GB</div>
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
            <div className="text-xl lg:text-2xl font-bold text-foreground">{storageData.used.toFixed(1)} GB</div>
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
            <div className="text-xl lg:text-2xl font-bold text-foreground">{storageData.available.toFixed(1)} GB</div>
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
            <div className="text-xl lg:text-2xl font-bold text-foreground">{storageData.disks.length}</div>
            <div className="flex items-center space-x-2 mt-2">
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                {storageData.disks.filter((d) => d.health === "healthy").length} Healthy
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Storage devices</p>
          </CardContent>
        </Card>
      </div>

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
            {storageData.disks.map((disk, index) => (
              <div
                key={index}
                className="flex items-center justify-between p-4 rounded-lg border border-border bg-card/50"
              >
                <div className="flex items-center space-x-4">
                  <HardDrive className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <div className="font-medium text-foreground">{disk.name}</div>
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
                    <div className="text-sm font-medium text-foreground">{disk.temperature}°C</div>
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
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
