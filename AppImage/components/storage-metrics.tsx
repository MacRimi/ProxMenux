"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "./ui/dialog"
import {
  HardDrive,
  Database,
  Archive,
  AlertTriangle,
  CheckCircle,
  Activity,
  AlertCircle,
  Info,
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
  percentage_used?: number
  ssd_life_left?: number
  wear_leveling_count?: number
  media_wearout_indicator?: number
}

interface DiskGroup {
  type: string
  disks: DiskInfo[]
  avgTemp: number
  status: "safe" | "warning" | "critical"
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
    console.error("[v0] Failed to fetch storage data from Flask server:", error)
    return null
  }
}

const getTempStatus = (temp: number, diskType: string): "safe" | "warning" | "critical" => {
  if (diskType === "HDD") {
    if (temp > 55) return "critical"
    if (temp > 45) return "warning"
    return "safe"
  } else if (diskType === "SSD") {
    if (temp > 65) return "critical"
    if (temp > 55) return "warning"
    return "safe"
  } else if (diskType === "NVMe") {
    if (temp > 70) return "critical"
    if (temp > 60) return "warning"
    return "safe"
  }
  // Umbral genérico
  if (temp > 70) return "critical"
  if (temp > 60) return "warning"
  return "safe"
}

const groupDisksByType = (disks: DiskInfo[]): DiskGroup[] => {
  const groups: { [key: string]: DiskInfo[] } = {}

  disks.forEach((disk) => {
    const type = disk.disk_type || "Unknown"
    if (!groups[type]) {
      groups[type] = []
    }
    groups[type].push(disk)
  })

  return Object.entries(groups).map(([type, disks]) => {
    const temps = disks.map((d) => d.temperature).filter((t) => t > 0)
    const avgTemp = temps.length > 0 ? Math.round(temps.reduce((a, b) => a + b, 0) / temps.length) : 0

    // Determinar el estado más crítico del grupo
    let status: "safe" | "warning" | "critical" = "safe"
    disks.forEach((disk) => {
      const diskStatus = getTempStatus(disk.temperature, type)
      if (diskStatus === "critical") status = "critical"
      else if (diskStatus === "warning" && status !== "critical") status = "warning"
    })

    return { type, disks, avgTemp, status }
  })
}

function TemperatureThresholdsModal() {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2 bg-transparent">
          <Info className="h-4 w-4" />
          Umbrales de temperatura
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Umbrales de temperatura por tipo de disco</DialogTitle>
          <DialogDescription>
            Rangos de temperatura recomendados para cada tipo de dispositivo de almacenamiento
          </DialogDescription>
        </DialogHeader>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left p-3 font-semibold">Tipo de disco</th>
                <th className="text-left p-3 font-semibold">Temperatura de operación</th>
                <th className="text-left p-3 font-semibold">Zona segura</th>
                <th className="text-left p-3 font-semibold">Zona de advertencia</th>
                <th className="text-left p-3 font-semibold">Zona crítica</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-border">
                <td className="p-3 font-medium">HDD</td>
                <td className="p-3">0°C – 60°C (común: 5–55°C)</td>
                <td className="p-3">
                  <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                    ≤ 45°C
                  </Badge>
                </td>
                <td className="p-3">
                  <Badge variant="outline" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                    46 – 55°C
                  </Badge>
                </td>
                <td className="p-3">
                  <Badge variant="outline" className="bg-red-500/10 text-red-500 border-red-500/20">
                    &gt; 55°C
                  </Badge>
                </td>
              </tr>
              <tr className="border-b border-border">
                <td className="p-3 font-medium">SSD</td>
                <td className="p-3">0°C – 70°C</td>
                <td className="p-3">
                  <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                    ≤ 55°C
                  </Badge>
                </td>
                <td className="p-3">
                  <Badge variant="outline" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                    56 – 65°C
                  </Badge>
                </td>
                <td className="p-3">
                  <Badge variant="outline" className="bg-red-500/10 text-red-500 border-red-500/20">
                    &gt; 65°C
                  </Badge>
                </td>
              </tr>
              <tr>
                <td className="p-3 font-medium">NVMe</td>
                <td className="p-3">0°C – 70°C</td>
                <td className="p-3">
                  <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                    ≤ 60°C
                  </Badge>
                </td>
                <td className="p-3">
                  <Badge variant="outline" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                    61 – 70°C
                  </Badge>
                </td>
                <td className="p-3">
                  <Badge variant="outline" className="bg-red-500/10 text-red-500 border-red-500/20">
                    &gt; 70°C
                  </Badge>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </DialogContent>
    </Dialog>
  )
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
  const diskGroups = groupDisksByType(storageData.disks)

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

      {diskGroups.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-foreground">Temperatura por tipo de disco</h3>
            <TemperatureThresholdsModal />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {diskGroups.map((group) => (
              <Card key={group.type} className="bg-card border-border">
                <CardHeader>
                  <CardTitle className="text-foreground flex items-center justify-between">
                    <div className="flex items-center">
                      <Thermometer className="h-5 w-5 mr-2" />
                      {group.type} Temperature
                    </div>
                    <Badge
                      variant="outline"
                      className={
                        group.status === "safe"
                          ? "bg-green-500/10 text-green-500 border-green-500/20"
                          : group.status === "warning"
                            ? "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                            : "bg-red-500/10 text-red-500 border-red-500/20"
                      }
                    >
                      {group.status === "safe" ? "Seguro" : group.status === "warning" ? "Advertencia" : "Crítico"}
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div
                    className={`text-3xl font-bold ${
                      group.status === "safe"
                        ? "text-green-500"
                        : group.status === "warning"
                          ? "text-yellow-500"
                          : "text-red-500"
                    }`}
                  >
                    {group.avgTemp}°C
                  </div>
                  <p className="text-sm text-muted-foreground mt-2">
                    Promedio de {group.disks.length} disco{group.disks.length > 1 ? "s" : ""}
                  </p>
                  <div className="mt-3 space-y-1">
                    {group.disks.map((disk, idx) => (
                      <div key={idx} className="flex items-center justify-between text-xs">
                        <span className="text-muted-foreground">{disk.name}</span>
                        <span
                          className={`font-medium ${
                            getTempStatus(disk.temperature, group.type) === "safe"
                              ? "text-green-500"
                              : getTempStatus(disk.temperature, group.type) === "warning"
                                ? "text-yellow-500"
                                : "text-red-500"
                          }`}
                        >
                          {disk.temperature}°C
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
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
            {storageData.disks.map((disk, index) => (
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
                        <Badge variant="outline" className="text-xs">
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
                    <div
                      className={`text-sm font-medium ${
                        getTempStatus(disk.temperature, disk.disk_type || "Unknown") === "safe"
                          ? "text-green-500"
                          : getTempStatus(disk.temperature, disk.disk_type || "Unknown") === "warning"
                            ? "text-yellow-500"
                            : "text-red-500"
                      }`}
                    >
                      {disk.temperature}°C
                    </div>
                  </div>

                  {(disk.disk_type === "SSD" || disk.disk_type === "NVMe") && disk.ssd_life_left !== undefined && (
                    <div className="text-center">
                      <div className="text-sm text-muted-foreground">Vida útil</div>
                      <div
                        className={`text-sm font-medium ${
                          disk.ssd_life_left >= 80
                            ? "text-green-500"
                            : disk.ssd_life_left >= 50
                              ? "text-yellow-500"
                              : "text-red-500"
                        }`}
                      >
                        {disk.ssd_life_left}%
                      </div>
                    </div>
                  )}

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
