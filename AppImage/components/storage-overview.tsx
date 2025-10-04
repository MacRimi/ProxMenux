"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { HardDrive, Database, AlertTriangle, CheckCircle2, XCircle, Thermometer, Info } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"

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
  reallocated_sectors?: number
  pending_sectors?: number
  crc_errors?: number
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
  disk_count: number
  healthy_disks: number
  warning_disks: number
  critical_disks: number
  error?: string
}

export function StorageOverview() {
  const [storageData, setStorageData] = useState<StorageData | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedDisk, setSelectedDisk] = useState<DiskInfo | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)

  const fetchStorageData = async () => {
    try {
      const baseUrl =
        typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8008` : ""
      const response = await fetch(`${baseUrl}/api/storage`)
      const data = await response.json()
      console.log("[v0] Storage data received:", data)
      setStorageData(data)
    } catch (error) {
      console.error("Error fetching storage data:", error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStorageData()
    const interval = setInterval(fetchStorageData, 30000) // Update every 30 seconds
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

  const formatHours = (hours: number) => {
    if (hours === 0) return "N/A"
    const years = Math.floor(hours / 8760)
    const days = Math.floor((hours % 8760) / 24)
    if (years > 0) {
      return `${years}y ${days}d`
    }
    return `${days}d`
  }

  const handleDiskClick = (disk: DiskInfo) => {
    setSelectedDisk(disk)
    setDetailsOpen(true)
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

  const disksWithTemp = storageData.disks.filter((disk) => disk.temperature > 0)
  const avgTemp =
    disksWithTemp.length > 0
      ? Math.round(disksWithTemp.reduce((sum, disk) => sum + disk.temperature, 0) / disksWithTemp.length)
      : 0

  const usagePercent =
    storageData.total > 0 ? ((storageData.used / (storageData.total * 1024)) * 100).toFixed(2) : "0.00"

  return (
    <div className="space-y-6">
      {/* Storage Summary */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Storage</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{storageData.total.toFixed(1)} TB</div>
            <p className="text-xs text-muted-foreground mt-1">{storageData.disk_count} physical disks</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Used Storage</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{storageData.used.toFixed(1)} GB</div>
            <p className="text-xs text-muted-foreground mt-1">{usagePercent}% used</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Disk Health</CardTitle>
            <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-500">{storageData.healthy_disks}</div>
            <p className="text-xs text-muted-foreground mt-1">
              {storageData.warning_disks > 0 && (
                <span className="text-yellow-500">{storageData.warning_disks} warning </span>
              )}
              {storageData.critical_disks > 0 && (
                <span className="text-red-500">{storageData.critical_disks} critical</span>
              )}
              {storageData.warning_disks === 0 && storageData.critical_disks === 0 && "All disks healthy"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Thermometer className="h-5 w-5" />
              Avg Temperature
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${getTempColor(avgTemp)}`}>{avgTemp > 0 ? `${avgTemp}°C` : "N/A"}</div>
            <p className="text-xs text-muted-foreground mt-1">Across all disks</p>
          </CardContent>
        </Card>
      </div>

      {storageData.disks.some((disk) => disk.mountpoint) && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              Mounted Partitions
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {storageData.disks
                .filter((disk) => disk.mountpoint)
                .map((disk) => (
                  <div key={disk.name} className="border rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <h3 className="font-semibold">{disk.mountpoint}</h3>
                        <p className="text-sm text-muted-foreground">
                          /dev/{disk.name} ({disk.fstype})
                        </p>
                      </div>
                      {disk.usage_percent !== undefined && (
                        <span className="text-sm font-medium">{disk.usage_percent}%</span>
                      )}
                    </div>
                    {disk.usage_percent !== undefined && (
                      <div className="space-y-1">
                        <Progress
                          value={disk.usage_percent}
                          className={`h-2 ${
                            disk.usage_percent > 90
                              ? "[&>div]:bg-red-500"
                              : disk.usage_percent > 75
                                ? "[&>div]:bg-yellow-500"
                                : "[&>div]:bg-blue-500"
                          }`}
                        />
                        <div className="flex justify-between text-xs text-muted-foreground">
                          <span
                            className={
                              disk.usage_percent > 90
                                ? "text-red-400"
                                : disk.usage_percent > 75
                                  ? "text-yellow-400"
                                  : "text-blue-400"
                            }
                          >
                            {disk.used} GB used
                          </span>
                          <span className="text-green-400">
                            {disk.available} GB free of {disk.total} GB
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
      )}

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
              <div
                key={disk.name}
                className="border rounded-lg p-4 cursor-pointer hover:bg-accent/50 transition-colors"
                onClick={() => handleDiskClick(disk)}
              >
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
                    <Info className="h-4 w-4 text-muted-foreground" />
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
                  {disk.power_on_hours !== undefined && disk.power_on_hours > 0 && (
                    <div>
                      <p className="text-muted-foreground">Power On Time</p>
                      <p className="font-medium">{formatHours(disk.power_on_hours)}</p>
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
                    {disk.usage_percent !== undefined && (
                      <div className="space-y-1">
                        <Progress value={disk.usage_percent} className="h-2" />
                        <div className="flex justify-between text-xs text-muted-foreground">
                          <span className="text-blue-400">{disk.used} GB used</span>
                          <span className="text-green-400">
                            {disk.available} GB free of {disk.total} GB
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Disk Details Dialog */}
      <Dialog open={detailsOpen} onOpenChange={setDetailsOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <HardDrive className="h-5 w-5" />
              Disk Details: /dev/{selectedDisk?.name}
            </DialogTitle>
            <DialogDescription>Complete SMART information and health status</DialogDescription>
          </DialogHeader>
          {selectedDisk && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Model</p>
                  <p className="font-medium">{selectedDisk.model}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Serial Number</p>
                  <p className="font-medium">{selectedDisk.serial}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Capacity</p>
                  <p className="font-medium">{selectedDisk.size}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Health Status</p>
                  <div className="mt-1">{getHealthBadge(selectedDisk.health)}</div>
                </div>
              </div>

              <div className="border-t pt-4">
                <h4 className="font-semibold mb-3">SMART Attributes</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Temperature</p>
                    <p className={`font-medium ${getTempColor(selectedDisk.temperature)}`}>
                      {selectedDisk.temperature > 0 ? `${selectedDisk.temperature}°C` : "N/A"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Power On Hours</p>
                    <p className="font-medium">
                      {selectedDisk.power_on_hours && selectedDisk.power_on_hours > 0
                        ? `${selectedDisk.power_on_hours.toLocaleString()}h (${formatHours(selectedDisk.power_on_hours)})`
                        : "N/A"}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">SMART Status</p>
                    <p className="font-medium capitalize">{selectedDisk.smart_status}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Reallocated Sectors</p>
                    <p
                      className={`font-medium ${selectedDisk.reallocated_sectors && selectedDisk.reallocated_sectors > 0 ? "text-yellow-500" : ""}`}
                    >
                      {selectedDisk.reallocated_sectors ?? 0}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Pending Sectors</p>
                    <p
                      className={`font-medium ${selectedDisk.pending_sectors && selectedDisk.pending_sectors > 0 ? "text-yellow-500" : ""}`}
                    >
                      {selectedDisk.pending_sectors ?? 0}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">CRC Errors</p>
                    <p
                      className={`font-medium ${selectedDisk.crc_errors && selectedDisk.crc_errors > 0 ? "text-yellow-500" : ""}`}
                    >
                      {selectedDisk.crc_errors ?? 0}
                    </p>
                  </div>
                </div>
              </div>

              {selectedDisk.mountpoint && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">Mount Information</h4>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Mount Point:</span>
                      <span className="font-medium">{selectedDisk.mountpoint}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Filesystem:</span>
                      <span className="font-medium">{selectedDisk.fstype}</span>
                    </div>
                    {selectedDisk.total && (
                      <>
                        <div className="flex justify-between text-sm">
                          <span className="text-muted-foreground">Total:</span>
                          <span className="font-medium">{selectedDisk.total} GB</span>
                        </div>
                        <div className="flex justify-between text-sm">
                          <span className="text-muted-foreground">Used:</span>
                          <span className="font-medium text-blue-400">{selectedDisk.used} GB</span>
                        </div>
                        <div className="flex justify-between text-sm">
                          <span className="text-muted-foreground">Available:</span>
                          <span className="font-medium text-green-400">{selectedDisk.available} GB</span>
                        </div>
                        {selectedDisk.usage_percent !== undefined && (
                          <div className="mt-2">
                            <Progress value={selectedDisk.usage_percent} className="h-2" />
                            <p className="text-xs text-muted-foreground text-center mt-1">
                              {selectedDisk.usage_percent}% used
                            </p>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
