"use client"

import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Cpu, MemoryStick, HardDrive, Network, Monitor, Thermometer, Fan, Battery, Server } from "lucide-react"
import useSWR from "swr"

const fetcher = (url: string) => fetch(url).then((res) => res.json())

interface CPUInfo {
  model?: string
  total_threads?: number
  cores_per_socket?: number
  sockets?: number
  current_mhz?: number
  max_mhz?: number
  virtualization?: string
  l1d_cache?: string
  l2_cache?: string
  l3_cache?: string
}

interface MotherboardInfo {
  manufacturer?: string
  model?: string
  version?: string
  serial?: string
  bios?: {
    vendor?: string
    version?: string
    date?: string
  }
}

interface MemoryModule {
  size: string
  type: string
  speed: string
  manufacturer?: string
  slot?: string
}

interface StorageDevice {
  name: string
  size: string
  model: string
  temperature: number
  health: string
  power_on_hours: number
  rotation_rate: number
}

interface NetworkCard {
  name: string
  type: string
}

interface GraphicsCard {
  name: string
  memory?: string
  temperature?: number
  power_draw?: string
  vendor: string
}

interface TemperatureSensor {
  name: string
  current: number
  high?: number
  critical?: number
}

interface FanSensor {
  name: string
  current_rpm: number
}

interface UPSInfo {
  model?: string
  status?: string
  battery_charge?: string
  time_left?: string
  load_percent?: string
  line_voltage?: string
}

interface HardwareData {
  cpu: CPUInfo
  motherboard: MotherboardInfo
  memory_modules: MemoryModule[]
  storage_devices: StorageDevice[]
  network_cards: NetworkCard[]
  graphics_cards: GraphicsCard[]
  sensors: {
    temperatures: TemperatureSensor[]
    fans: FanSensor[]
  }
  power: UPSInfo
}

export default function Hardware() {
  const { data: hardwareData, error } = useSWR<HardwareData>("/api/hardware", fetcher, {
    refreshInterval: 5000,
  })

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/50 bg-red-500/10 p-4">
          <p className="text-sm text-red-500">Failed to load hardware information</p>
        </div>
      </div>
    )
  }

  if (!hardwareData) {
    return (
      <div className="p-6">
        <div className="flex items-center justify-center py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
      </div>
    )
  }

  const getHealthColor = (health: string) => {
    switch (health.toLowerCase()) {
      case "healthy":
        return "text-green-500"
      case "warning":
        return "text-yellow-500"
      case "critical":
      case "failed":
        return "text-red-500"
      default:
        return "text-muted-foreground"
    }
  }

  const getHealthBadge = (health: string) => {
    switch (health.toLowerCase()) {
      case "healthy":
        return <Badge className="bg-green-500/10 text-green-500 border-green-500/20">Healthy</Badge>
      case "warning":
        return <Badge className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">Warning</Badge>
      case "critical":
      case "failed":
        return <Badge className="bg-red-500/10 text-red-500 border-red-500/20">Critical</Badge>
      default:
        return <Badge variant="outline">Unknown</Badge>
    }
  }

  const getTempColor = (temp: number, high?: number, critical?: number) => {
    if (critical && temp >= critical) return "text-red-500"
    if (high && temp >= high) return "text-yellow-500"
    if (temp >= 70) return "text-red-500"
    if (temp >= 60) return "text-yellow-500"
    return "text-green-500"
  }

  const getTempProgress = (temp: number, critical?: number) => {
    const max = critical || 100
    return (temp / max) * 100
  }

  const hasSensors = hardwareData.sensors.temperatures.length > 0 || hardwareData.sensors.fans.length > 0
  const hasUPS = hardwareData.power && Object.keys(hardwareData.power).length > 0

  const storageSummary = hardwareData.storage_devices.reduce(
    (acc, disk) => {
      const sizeMatch = disk.size.match(/(\d+\.?\d*)\s*([KMGT]B)/)
      if (sizeMatch) {
        let sizeInGB = Number.parseFloat(sizeMatch[1])
        const unit = sizeMatch[2]
        if (unit === "TB") sizeInGB *= 1024
        else if (unit === "MB") sizeInGB /= 1024
        else if (unit === "KB") sizeInGB /= 1024 * 1024
        acc.totalCapacity += sizeInGB
      }

      if (disk.rotation_rate === 0) acc.ssd++
      else if (disk.rotation_rate > 0) acc.hdd++

      return acc
    },
    { totalCapacity: 0, ssd: 0, hdd: 0 },
  )

  return (
    <div className="space-y-6 p-6">
      {/* System Information */}
      <Card className="border-border/50 bg-card/50 p-6">
        <div className="mb-4 flex items-center gap-2">
          <Server className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">System Information</h2>
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          {/* CPU */}
          {hardwareData.cpu.model && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Cpu className="h-4 w-4 text-muted-foreground" />
                <h3 className="font-medium">CPU</h3>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Model</span>
                  <span className="font-mono">{hardwareData.cpu.model}</span>
                </div>
                {hardwareData.cpu.sockets && hardwareData.cpu.cores_per_socket && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Cores</span>
                    <span className="font-mono">
                      {hardwareData.cpu.sockets} × {hardwareData.cpu.cores_per_socket} ={" "}
                      {hardwareData.cpu.sockets * hardwareData.cpu.cores_per_socket} cores
                    </span>
                  </div>
                )}
                {hardwareData.cpu.total_threads && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Threads</span>
                    <span className="font-mono">{hardwareData.cpu.total_threads}</span>
                  </div>
                )}
                {hardwareData.cpu.current_mhz && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Frequency</span>
                    <span className="font-mono">{hardwareData.cpu.current_mhz.toFixed(0)} MHz</span>
                  </div>
                )}
                {hardwareData.cpu.l3_cache && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">L3 Cache</span>
                    <span className="font-mono">{hardwareData.cpu.l3_cache}</span>
                  </div>
                )}
                {hardwareData.cpu.virtualization && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Virtualization</span>
                    <span className="font-mono">{hardwareData.cpu.virtualization}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Motherboard */}
          {hardwareData.motherboard.manufacturer && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Server className="h-4 w-4 text-muted-foreground" />
                <h3 className="font-medium">Motherboard</h3>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Manufacturer</span>
                  <span className="font-mono">{hardwareData.motherboard.manufacturer}</span>
                </div>
                {hardwareData.motherboard.model && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Model</span>
                    <span className="font-mono">{hardwareData.motherboard.model}</span>
                  </div>
                )}
                {hardwareData.motherboard.bios && (
                  <>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">BIOS</span>
                      <span className="font-mono">{hardwareData.motherboard.bios.vendor}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Version</span>
                      <span className="font-mono">{hardwareData.motherboard.bios.version}</span>
                    </div>
                    {hardwareData.motherboard.bios.date && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Date</span>
                        <span className="font-mono">{hardwareData.motherboard.bios.date}</span>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Memory Modules */}
      {hardwareData.memory_modules.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <MemoryStick className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Memory Modules</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.memory_modules.length} installed
            </Badge>
          </div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {hardwareData.memory_modules.map((module, index) => (
              <Card key={index} className="border-border/30 bg-background/50 p-4">
                <div className="space-y-2 text-sm">
                  {module.slot && <div className="font-medium">{module.slot}</div>}
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Size</span>
                    <span className="font-mono">{module.size}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Type</span>
                    <span className="font-mono">{module.type}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Speed</span>
                    <span className="font-mono">{module.speed}</span>
                  </div>
                  {module.manufacturer && module.manufacturer !== "Unknown" && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Manufacturer</span>
                      <span className="font-mono text-xs">{module.manufacturer}</span>
                    </div>
                  )}
                </div>
              </Card>
            ))}
          </div>
        </Card>
      )}

      {/* Storage Summary - Simplified */}
      {hardwareData.storage_devices.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <HardDrive className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Storage Summary</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.storage_devices.length} devices
            </Badge>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Total Capacity</p>
              <p className="text-2xl font-semibold">{storageSummary.totalCapacity.toFixed(1)} GB</p>
            </div>

            {storageSummary.ssd > 0 && (
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">SSD Drives</p>
                <p className="text-2xl font-semibold">{storageSummary.ssd}</p>
              </div>
            )}

            {storageSummary.hdd > 0 && (
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">HDD Drives</p>
                <p className="text-2xl font-semibold">{storageSummary.hdd}</p>
              </div>
            )}
          </div>

          <p className="mt-4 text-xs text-muted-foreground">
            For detailed storage information, see the Storage section
          </p>
        </Card>
      )}

      {/* Storage Devices */}
      {hardwareData.storage_devices.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <HardDrive className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Storage Devices</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.storage_devices.length} devices
            </Badge>
          </div>

          <div className="space-y-4">
            {hardwareData.storage_devices.map((disk, index) => (
              <Card key={index} className="border-border/30 bg-background/50 p-4">
                <div className="flex items-start justify-between">
                  <div className="space-y-2 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">/dev/{disk.name}</span>
                      {getHealthBadge(disk.health)}
                      {disk.rotation_rate === 0 && (
                        <Badge variant="outline" className="text-xs">
                          SSD
                        </Badge>
                      )}
                      {disk.rotation_rate > 0 && (
                        <Badge variant="outline" className="text-xs">
                          {disk.rotation_rate} RPM
                        </Badge>
                      )}
                    </div>

                    <div className="grid gap-2 text-sm md:grid-cols-2">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Model</span>
                        <span className="font-mono text-xs">{disk.model}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Size</span>
                        <span className="font-mono">{disk.size}</span>
                      </div>
                      {disk.temperature > 0 && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Temperature</span>
                          <span className={`font-mono ${getTempColor(disk.temperature)}`}>{disk.temperature}°C</span>
                        </div>
                      )}
                      {disk.power_on_hours > 0 && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Power On Hours</span>
                          <span className="font-mono">{disk.power_on_hours.toLocaleString()}h</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </Card>
      )}

      {/* Graphics Cards */}
      {hardwareData.graphics_cards.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Monitor className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Graphics Cards</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.graphics_cards.length} GPU{hardwareData.graphics_cards.length > 1 ? "s" : ""}
            </Badge>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {hardwareData.graphics_cards.map((gpu, index) => (
              <Card key={index} className="border-border/30 bg-background/50 p-4">
                <div className="space-y-2 text-sm">
                  <div className="font-medium">{gpu.name}</div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Vendor</span>
                    <span className="font-mono">{gpu.vendor}</span>
                  </div>
                  {gpu.memory && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Memory</span>
                      <span className="font-mono">{gpu.memory}</span>
                    </div>
                  )}
                  {gpu.temperature && gpu.temperature > 0 && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Temperature</span>
                      <span className={`font-mono ${getTempColor(gpu.temperature)}`}>{gpu.temperature}°C</span>
                    </div>
                  )}
                  {gpu.power_draw && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Power Draw</span>
                      <span className="font-mono">{gpu.power_draw}</span>
                    </div>
                  )}
                </div>
              </Card>
            ))}
          </div>
        </Card>
      )}

      {/* Network Summary - Simplified */}
      {hardwareData.network_cards.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Network className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Network Summary</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.network_cards.length} interfaces
            </Badge>
          </div>

          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {hardwareData.network_cards.map((nic, index) => (
              <div
                key={index}
                className="flex items-center justify-between rounded-lg border border-border/30 bg-background/50 p-3"
              >
                <span className="font-mono text-sm">{nic.name}</span>
                <Badge variant="outline" className="text-xs">
                  {nic.type}
                </Badge>
              </div>
            ))}
          </div>

          <p className="mt-4 text-xs text-muted-foreground">
            For detailed network information, see the Network section
          </p>
        </Card>
      )}

      {/* Network Cards */}
      {hardwareData.network_cards.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Network className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Network Cards</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.network_cards.length} NIC{hardwareData.network_cards.length > 1 ? "s" : ""}
            </Badge>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {hardwareData.network_cards.map((nic, index) => (
              <Card key={index} className="border-border/30 bg-background/50 p-3">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-mono text-xs">{nic.name}</span>
                  <Badge variant="outline" className="text-xs">
                    {nic.type}
                  </Badge>
                </div>
              </Card>
            ))}
          </div>
        </Card>
      )}

      {/* Sensors (Temperature & Fans) */}
      {hasSensors && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Thermometer className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Thermal & Fan Monitoring</h2>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            {/* Temperatures */}
            {hardwareData.sensors.temperatures.length > 0 && (
              <div className="space-y-3">
                <h3 className="text-sm font-medium text-muted-foreground">Temperatures</h3>
                <div className="space-y-3">
                  {hardwareData.sensors.temperatures.map((sensor, index) => (
                    <div key={index} className="space-y-1">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">{sensor.name}</span>
                        <span
                          className={`font-mono font-medium ${getTempColor(sensor.current, sensor.high, sensor.critical)}`}
                        >
                          {sensor.current.toFixed(1)}°C
                        </span>
                      </div>
                      <Progress value={getTempProgress(sensor.current, sensor.critical)} className="h-1.5" />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Fans */}
            {hardwareData.sensors.fans.length > 0 && (
              <div className="space-y-3">
                <h3 className="text-sm font-medium text-muted-foreground">Fans</h3>
                <div className="space-y-3">
                  {hardwareData.sensors.fans.map((fan, index) => (
                    <div key={index} className="flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2">
                        <Fan className="h-4 w-4 text-muted-foreground" />
                        <span className="text-muted-foreground">{fan.name}</span>
                      </div>
                      <span className="font-mono font-medium">{fan.current_rpm} RPM</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Power Supply / UPS */}
      {hasUPS && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Battery className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Power Supply / UPS</h2>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {hardwareData.power.model && (
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Model</span>
                <span className="font-mono">{hardwareData.power.model}</span>
              </div>
            )}
            {hardwareData.power.status && (
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Status</span>
                <Badge variant="outline">{hardwareData.power.status}</Badge>
              </div>
            )}
            {hardwareData.power.battery_charge && (
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Battery Charge</span>
                <span className="font-mono font-medium text-green-500">{hardwareData.power.battery_charge}</span>
              </div>
            )}
            {hardwareData.power.time_left && (
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Time Left</span>
                <span className="font-mono">{hardwareData.power.time_left}</span>
              </div>
            )}
            {hardwareData.power.load_percent && (
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Load</span>
                <span className="font-mono">{hardwareData.power.load_percent}</span>
              </div>
            )}
            {hardwareData.power.line_voltage && (
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Line Voltage</span>
                <span className="font-mono">{hardwareData.power.line_voltage}</span>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}
