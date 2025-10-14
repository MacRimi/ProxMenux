"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog"
import {
  HardDrive,
  Database,
  Archive,
  AlertTriangle,
  CheckCircle,
  Activity,
  AlertCircle,
  Thermometer,
  Info,
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
  model?: string
  serial?: string
  smart_status?: string
  power_on_hours?: number
  power_cycles?: number
  reallocated_sectors?: number
  pending_sectors?: number
  crc_errors?: number
  percentage_used?: number // NVMe
  ssd_life_left?: number // SSD
  wear_leveling_count?: number // SSD
  media_wearout_indicator?: number // SSD
  total_lbas_written?: number // Both
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

const getWearStatus = (lifeLeft: number): { status: string; color: string } => {
  if (lifeLeft >= 80) return { status: "Excellent", color: "text-green-500" }
  if (lifeLeft >= 50) return { status: "Good", color: "text-yellow-500" }
  if (lifeLeft >= 20) return { status: "Fair", color: "text-orange-500" }
  return { status: "Poor", color: "text-red-500" }
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
  const [selectedDisk, setSelectedDisk] = useState<DiskInfo | null>(null)
  const [showDiskDetails, setShowDiskDetails] = useState(false)
  const [showTempInfo, setShowTempInfo] = useState(false)

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
    .filter((item) => item.type !== "Unknown")

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

      {/* Temperature cards by disk type */}
      {tempByType.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {tempByType.map(({ type, avgTemp, status, count }) => {
            return (
              <Card key={type} className="bg-card border-border">
                <CardHeader>
                  <CardTitle className="text-foreground flex items-center justify-between">
                    <div className="flex items-center">
                      <Thermometer className="h-5 w-5 mr-2" />
                      Avg Temperature
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className={getDiskTypeBadgeColor(type)}>
                        {type}
                      </Badge>
                      <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setShowTempInfo(true)}>
                        <Info className="h-4 w-4" />
                      </Button>
                    </div>
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
            )
          })}
        </div>
      ) : null}

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

              let lifeLeft: number | null = null
              let wearLabel = ""

              if (diskType === "NVMe" && disk.percentage_used !== undefined && disk.percentage_used !== null) {
                lifeLeft = 100 - disk.percentage_used
                wearLabel = "Life Left"
              } else if (diskType === "SSD") {
                if (disk.ssd_life_left !== undefined && disk.ssd_life_left !== null) {
                  lifeLeft = disk.ssd_life_left
                  wearLabel = "Life Left"
                } else if (disk.media_wearout_indicator !== undefined && disk.media_wearout_indicator !== null) {
                  lifeLeft = disk.media_wearout_indicator
                  wearLabel = "Health"
                } else if (disk.wear_leveling_count !== undefined && disk.wear_leveling_count !== null) {
                  lifeLeft = disk.wear_leveling_count
                  wearLabel = "Wear Level"
                }
              }

              return (
                <div
                  key={index}
                  className="flex items-center justify-between p-4 rounded-lg border border-border bg-card/50 cursor-pointer hover:bg-card/80 transition-colors"
                  onClick={() => {
                    setSelectedDisk(disk)
                    setShowDiskDetails(true)
                  }}
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

                    {lifeLeft !== null && (diskType === "SSD" || diskType === "NVMe") && (
                      <div className="text-center">
                        <div className="text-sm text-muted-foreground">{wearLabel}</div>
                        <div className={`text-sm font-medium ${getWearStatus(lifeLeft).color}`}>
                          {lifeLeft.toFixed(0)}%
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
              )
            })}
          </div>
        </CardContent>
      </Card>

      <Dialog open={showTempInfo} onOpenChange={setShowTempInfo}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Temperature Thresholds by Disk Type</DialogTitle>
            <DialogDescription>
              Recommended operating temperature ranges for different storage devices
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left p-3 font-semibold">Disk Type</th>
                    <th className="text-left p-3 font-semibold">Safe Zone</th>
                    <th className="text-left p-3 font-semibold">Warning Zone</th>
                    <th className="text-left p-3 font-semibold">Critical Zone</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-border">
                    <td className="p-3">
                      <Badge variant="outline" className={getDiskTypeBadgeColor("HDD")}>
                        HDD
                      </Badge>
                    </td>
                    <td className="p-3 text-green-500">≤ 45°C</td>
                    <td className="p-3 text-yellow-500">46 – 55°C</td>
                    <td className="p-3 text-red-500">&gt; 55°C</td>
                  </tr>
                  <tr className="border-b border-border">
                    <td className="p-3">
                      <Badge variant="outline" className={getDiskTypeBadgeColor("SSD")}>
                        SSD
                      </Badge>
                    </td>
                    <td className="p-3 text-green-500">≤ 55°C</td>
                    <td className="p-3 text-yellow-500">56 – 65°C</td>
                    <td className="p-3 text-red-500">&gt; 65°C</td>
                  </tr>
                  <tr>
                    <td className="p-3">
                      <Badge variant="outline" className={getDiskTypeBadgeColor("NVMe")}>
                        NVMe
                      </Badge>
                    </td>
                    <td className="p-3 text-green-500">≤ 60°C</td>
                    <td className="p-3 text-yellow-500">61 – 70°C</td>
                    <td className="p-3 text-red-500">&gt; 70°C</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="text-sm text-muted-foreground">
              These thresholds are based on industry standards and manufacturer recommendations. Operating within the
              safe zone ensures optimal performance and longevity.
            </p>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={showDiskDetails} onOpenChange={setShowDiskDetails}>
        <DialogContent className="max-w-3xl">
          {selectedDisk && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <HardDrive className="h-5 w-5" />
                  Disk Details: {selectedDisk.name}
                </DialogTitle>
                <DialogDescription>Complete SMART information and health status</DialogDescription>
              </DialogHeader>
              <div className="space-y-6">
                {/* Basic Info */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-sm text-muted-foreground">Model</div>
                    <div className="font-medium">{selectedDisk.model || "Unknown"}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Serial Number</div>
                    <div className="font-medium">{selectedDisk.serial || "Unknown"}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Capacity</div>
                    <div className="font-medium">{selectedDisk.total.toFixed(1)}G</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Health Status</div>
                    <Badge
                      variant="outline"
                      className={
                        selectedDisk.health === "healthy"
                          ? "bg-green-500/10 text-green-500 border-green-500/20"
                          : "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                      }
                    >
                      {selectedDisk.health === "healthy" ? "Healthy" : "Warning"}
                    </Badge>
                  </div>
                </div>

                {(selectedDisk.disk_type === "SSD" || selectedDisk.disk_type === "NVMe") && (
                  <div className="border-t border-border pt-4">
                    <h3 className="font-semibold mb-3">Wear & Life Indicators</h3>
                    <div className="grid grid-cols-2 gap-4">
                      {selectedDisk.disk_type === "NVMe" &&
                        selectedDisk.percentage_used !== undefined &&
                        selectedDisk.percentage_used !== null && (
                          <>
                            <div>
                              <div className="text-sm text-muted-foreground">Percentage Used</div>
                              <div
                                className={`text-lg font-bold ${getWearStatus(100 - selectedDisk.percentage_used).color}`}
                              >
                                {selectedDisk.percentage_used}%
                              </div>
                            </div>
                            <div>
                              <div className="text-sm text-muted-foreground">Life Remaining</div>
                              <div
                                className={`text-lg font-bold ${getWearStatus(100 - selectedDisk.percentage_used).color}`}
                              >
                                {(100 - selectedDisk.percentage_used).toFixed(0)}%
                              </div>
                              <Progress value={100 - selectedDisk.percentage_used} className="mt-2" />
                            </div>
                          </>
                        )}
                      {selectedDisk.disk_type === "SSD" && (
                        <>
                          {selectedDisk.ssd_life_left !== undefined && selectedDisk.ssd_life_left !== null && (
                            <div>
                              <div className="text-sm text-muted-foreground">SSD Life Left</div>
                              <div className={`text-lg font-bold ${getWearStatus(selectedDisk.ssd_life_left).color}`}>
                                {selectedDisk.ssd_life_left}%
                              </div>
                              <Progress value={selectedDisk.ssd_life_left} className="mt-2" />
                            </div>
                          )}
                          {selectedDisk.wear_leveling_count !== undefined &&
                            selectedDisk.wear_leveling_count !== null && (
                              <div>
                                <div className="text-sm text-muted-foreground">Wear Leveling Count</div>
                                <div
                                  className={`text-lg font-bold ${getWearStatus(selectedDisk.wear_leveling_count).color}`}
                                >
                                  {selectedDisk.wear_leveling_count}
                                </div>
                              </div>
                            )}
                          {selectedDisk.media_wearout_indicator !== undefined &&
                            selectedDisk.media_wearout_indicator !== null && (
                              <div>
                                <div className="text-sm text-muted-foreground">Media Wearout Indicator</div>
                                <div
                                  className={`text-lg font-bold ${getWearStatus(selectedDisk.media_wearout_indicator).color}`}
                                >
                                  {selectedDisk.media_wearout_indicator}%
                                </div>
                                <Progress value={selectedDisk.media_wearout_indicator} className="mt-2" />
                              </div>
                            )}
                        </>
                      )}
                      {selectedDisk.total_lbas_written !== undefined && selectedDisk.total_lbas_written !== null && (
                        <div>
                          <div className="text-sm text-muted-foreground">Total Data Written</div>
                          <div className="font-medium">{(selectedDisk.total_lbas_written / 1000000).toFixed(2)} TB</div>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* SMART Attributes */}
                <div className="border-t border-border pt-4">
                  <h3 className="font-semibold mb-3">SMART Attributes</h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-sm text-muted-foreground">Temperature</div>
                      <div
                        className={`font-medium ${getTempColor(getTempStatus(selectedDisk.temperature, selectedDisk.disk_type || "HDD"))}`}
                      >
                        {selectedDisk.temperature}°C
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Power On Hours</div>
                      <div className="font-medium">
                        {selectedDisk.power_on_hours
                          ? `${selectedDisk.power_on_hours}h (${Math.floor(selectedDisk.power_on_hours / 24)}d)`
                          : "N/A"}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Rotation Rate</div>
                      <div className="font-medium">{selectedDisk.disk_type || "Unknown"}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Power Cycles</div>
                      <div className="font-medium">{selectedDisk.power_cycles || 0}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">SMART Status</div>
                      <div className="font-medium">{selectedDisk.smart_status === "passed" ? "Passed" : "Unknown"}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Reallocated Sectors</div>
                      <div className="font-medium">{selectedDisk.reallocated_sectors || 0}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Pending Sectors</div>
                      <div className="font-medium">{selectedDisk.pending_sectors || 0}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">CRC Errors</div>
                      <div className="font-medium">{selectedDisk.crc_errors || 0}</div>
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
