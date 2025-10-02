"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { HardDrive, Database, AlertTriangle, CheckCircle2, XCircle, Thermometer } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"

interface DiskInfo {
  name: string
  size?: string
  temperature: number
  health: string
  power_on_hours?: number
  smart_status?: string
  model?: string
  serial?: string
  mountpoint?: string
  fstype?: string
  total?: number
  used?: number
  available?: number
  usage_percent?: number
}

interface ZFSPool {
  name: string
  size: string
  allocated: string
  free: string
  health: string
}

interface StorageData {
  total: number
  used: number
  available: number
  disks: DiskInfo[]
  zfs_pools: ZFSPool[]
  error?: string
}

export function StorageOverview() {
  const [storageData, setStorageData] = useState<StorageData | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchStorageData = async () => {
    try {
      const baseUrl =
        typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""
      const response = await fetch(`${baseUrl}/api/storage`)
      const data = await response.json()
      setStorageData(data)
    } catch (error) {
      console.error("Error fetching storage data:", error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStorageData()
    const interval = setInterval(fetchStorageData, 15000) // Update every 15 seconds
    return () => clearInterval(interval)
  }, [])

  const getHealthIcon = (health: string) => {
    switch (health.toLowerCase()) {
      case "healthy":
      case "passed":
      case "online":
        return <CheckCircle2 className="h-5 w-5 text-green-500" />
      case "warning":
        return <AlertTriangle className="h-5 w-5 text-yellow-500" />
      case "critical":
      case "failed":
      case "degraded":
        return <XCircle className="h-5 w-5 text-red-500" />
      default:
        return <AlertTriangle className="h-5 w-5 text-gray-500" />
    }
  }

  const getHealthBadge = (health: string) => {
    switch (health.toLowerCase()) {
      case "healthy":
      case "passed":
      case "online":
        return <Badge className="bg-green-500/10 text-green-500 border-green-500/20">Healthy</Badge>
      case "warning":
        return <Badge className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">Warning</Badge>
      case "critical":
      case "failed":
      case "degraded":
        return <Badge className="bg-red-500/10 text-red-500 border-red-500/20">Critical</Badge>
      default:
        return <Badge className="bg-gray-500/10 text-gray-500 border-gray-500/20">Unknown</Badge>
    }
  }

  const getTempColor = (temp: number) => {
    if (temp === 0) return "text-gray-500"
    if (temp < 45) return "text-green-500"
    if (temp < 60) return "text-yellow-500"
    return "text-red-500"
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-muted-foreground">Loading storage information...</div>
      </div>
    )
  }

  if (!storageData || storageData.error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-red-500">Error loading storage data: {storageData?.error || "Unknown error"}</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Storage Summary */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Storage</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{storageData.total} GB</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Used Storage</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{storageData.used} GB</div>
            <p className="text-xs text-muted-foreground mt-1">
              {storageData.total > 0 ? Math.round((storageData.used / storageData.total) * 100) : 0}% used
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Available Storage</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{storageData.available} GB</div>
          </CardContent>
        </Card>
      </div>

      {/* ZFS Pools */}
      {storageData.zfs_pools && storageData.zfs_pools.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              ZFS Pools
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {storageData.zfs_pools.map((pool) => (
                <div key={pool.name} className="border rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <h3 className="font-semibold text-lg">{pool.name}</h3>
                      {getHealthBadge(pool.health)}
                    </div>
                    {getHealthIcon(pool.health)}
                  </div>
                  <div className="grid grid-cols-3 gap-4 text-sm">
                    <div>
                      <p className="text-muted-foreground">Size</p>
                      <p className="font-medium">{pool.size}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Allocated</p>
                      <p className="font-medium">{pool.allocated}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Free</p>
                      <p className="font-medium">{pool.free}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Physical Disks */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <HardDrive className="h-5 w-5" />
            Physical Disks & SMART Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {storageData.disks.map((disk) => (
              <div key={disk.name} className="border rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <HardDrive className="h-5 w-5 text-muted-foreground" />
                    <div>
                      <h3 className="font-semibold">/dev/{disk.name}</h3>
                      {disk.model && disk.model !== "Unknown" && (
                        <p className="text-sm text-muted-foreground">{disk.model}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {disk.temperature > 0 && (
                      <div className="flex items-center gap-1">
                        <Thermometer className={`h-4 w-4 ${getTempColor(disk.temperature)}`} />
                        <span className={`text-sm font-medium ${getTempColor(disk.temperature)}`}>
                          {disk.temperature}°C
                        </span>
                      </div>
                    )}
                    {getHealthBadge(disk.health)}
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                  {disk.size && (
                    <div>
                      <p className="text-muted-foreground">Size</p>
                      <p className="font-medium">{disk.size}</p>
                    </div>
                  )}
                  {disk.smart_status && disk.smart_status !== "unknown" && (
                    <div>
                      <p className="text-muted-foreground">SMART Status</p>
                      <p className="font-medium capitalize">{disk.smart_status}</p>
                    </div>
                  )}
                  {disk.power_on_hours && disk.power_on_hours > 0 && (
                    <div>
                      <p className="text-muted-foreground">Power On Hours</p>
                      <p className="font-medium">{disk.power_on_hours.toLocaleString()}h</p>
                    </div>
                  )}
                  {disk.serial && disk.serial !== "Unknown" && (
                    <div>
                      <p className="text-muted-foreground">Serial</p>
                      <p className="font-medium text-xs">{disk.serial}</p>
                    </div>
                  )}
                </div>

                {disk.mountpoint && (
                  <div className="mt-3 pt-3 border-t">
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-sm">
                        <span className="text-muted-foreground">Mounted at: </span>
                        <span className="font-medium">{disk.mountpoint}</span>
                        {disk.fstype && <span className="text-muted-foreground ml-2">({disk.fstype})</span>}
                      </div>
                      {disk.usage_percent !== undefined && (
                        <span className="text-sm font-medium">{disk.usage_percent}%</span>
                      )}
                    </div>
                    {disk.usage_percent !== undefined && <Progress value={disk.usage_percent} className="h-2" />}
                    {disk.total && disk.used && disk.available && (
                      <div className="flex justify-between text-xs text-muted-foreground mt-1">
                        <span>{disk.used} GB used</span>
                        <span>
                          {disk.available} GB free of {disk.total} GB
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
