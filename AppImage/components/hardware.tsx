"use client"

import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Cpu, MemoryStick, HardDrive, Network, Thermometer, Fan, Battery, Server, CpuIcon } from "lucide-react"
import useSWR from "swr"
import { useState } from "react"

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

interface PCIDevice {
  slot: string
  type: string
  vendor: string
  device: string
  class: string
  driver?: string
  kernel_module?: string
  irq?: string
  memory_address?: string
  link_speed?: string
  capabilities?: string[]
}

interface HardwareData {
  cpu: CPUInfo
  motherboard: MotherboardInfo
  memory_modules: MemoryModule[]
  storage_devices: StorageDevice[]
  network_cards: NetworkCard[]
  graphics_cards: GraphicsCard[]
  pci_devices: PCIDevice[]
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

  const [selectedPCIDevice, setSelectedPCIDevice] = useState<PCIDevice | null>(null)

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
      const sizeMatch = disk.size.match(/(\d+\.?\d*)\s*([KMGT]?B?)/)
      if (sizeMatch) {
        let sizeInTB = Number.parseFloat(sizeMatch[1])
        const unit = sizeMatch[2]
        if (unit === "TB" || unit === "T") sizeInTB *= 1
        else if (unit === "GB" || unit === "G") sizeInTB /= 1024
        else if (unit === "MB" || unit === "M") sizeInTB /= 1024 * 1024
        else if (unit === "KB" || unit === "K") sizeInTB /= 1024 * 1024 * 1024
        acc.totalCapacity += sizeInTB
      }

      if (disk.rotation_rate === 0) acc.ssd++
      else if (disk.rotation_rate > 0) acc.hdd++

      return acc
    },
    { totalCapacity: 0, ssd: 0, hdd: 0 },
  )

  const networkControllers = hardwareData.pci_devices?.filter((device) => device.type === "Network Controller") || []

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

      {/* Storage Summary */}
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
              <p className="text-2xl font-semibold">
                {storageSummary.totalCapacity >= 1
                  ? `${storageSummary.totalCapacity.toFixed(1)} TB`
                  : `${(storageSummary.totalCapacity * 1024).toFixed(1)} GB`}
              </p>
            </div>

            {storageSummary.ssd > 0 && (
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">SSD/NVMe Drives</p>
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

      {/* Network Summary */}
      {networkControllers.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Network className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Network Summary</h2>
            <Badge variant="outline" className="ml-auto">
              {networkControllers.length} interfaces
            </Badge>
          </div>

          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {networkControllers.map((nic, index) => (
              <div
                key={index}
                className="flex items-center justify-between rounded-lg border border-border/30 bg-background/50 p-3"
              >
                <span className="font-mono text-sm">{nic.device}</span>
                <Badge variant="outline" className="text-xs">
                  Ethernet
                </Badge>
              </div>
            ))}
          </div>

          <p className="mt-4 text-xs text-muted-foreground">
            For detailed network information, see the Network section
          </p>
        </Card>
      )}

      {/* PCI Devices */}
      {hardwareData.pci_devices && hardwareData.pci_devices.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <CpuIcon className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">PCI Devices</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.pci_devices.length} devices
            </Badge>
          </div>

          <div className="space-y-3">
            {hardwareData.pci_devices.map((device, index) => (
              <div
                key={index}
                onClick={() => setSelectedPCIDevice(device)}
                className="flex cursor-pointer items-start justify-between rounded-lg border border-border/30 bg-background/50 p-4 transition-colors hover:border-primary/50 hover:bg-background/80"
              >
                <div className="flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs">
                      {device.type}
                    </Badge>
                    <span className="font-mono text-xs text-muted-foreground">{device.slot}</span>
                  </div>
                  <p className="font-medium text-sm">{device.device}</p>
                  <p className="text-xs text-muted-foreground">{device.vendor}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Thermal Monitoring */}
      {hardwareData.sensors.temperatures.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Thermometer className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Thermal Monitoring</h2>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
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
                <Progress
                  value={getTempProgress(sensor.current, sensor.critical)}
                  className="h-1.5 [&>div]:bg-blue-500"
                />
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Fan Monitoring */}
      {hardwareData.sensors.fans.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Fan className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Fan Monitoring</h2>
          </div>

          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {hardwareData.sensors.fans.map((fan, index) => (
              <div
                key={index}
                className="flex items-center justify-between rounded-lg border border-border/30 bg-background/50 p-3"
              >
                <div className="flex items-center gap-2">
                  <Fan className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">{fan.name}</span>
                </div>
                <span className="font-mono font-medium text-sm">{fan.current_rpm} RPM</span>
              </div>
            ))}
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

      {/* PCI Device Details Modal */}
      <Dialog open={!!selectedPCIDevice} onOpenChange={() => setSelectedPCIDevice(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>PCI Device Details</DialogTitle>
            <DialogDescription>Detailed information about the selected PCI device</DialogDescription>
          </DialogHeader>

          {selectedPCIDevice && (
            <div className="space-y-4">
              <div className="grid gap-3">
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Device Type</span>
                  <Badge variant="outline">{selectedPCIDevice.type}</Badge>
                </div>

                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">PCI Slot</span>
                  <span className="font-mono text-sm">{selectedPCIDevice.slot}</span>
                </div>

                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Device Name</span>
                  <span className="text-sm text-right">{selectedPCIDevice.device}</span>
                </div>

                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Vendor</span>
                  <span className="text-sm">{selectedPCIDevice.vendor}</span>
                </div>

                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Class</span>
                  <span className="font-mono text-sm">{selectedPCIDevice.class}</span>
                </div>

                {selectedPCIDevice.driver && (
                  <div className="flex justify-between border-b border-border/50 pb-2">
                    <span className="text-sm font-medium text-muted-foreground">Driver</span>
                    <span className="font-mono text-sm">{selectedPCIDevice.driver}</span>
                  </div>
                )}

                {selectedPCIDevice.kernel_module && (
                  <div className="flex justify-between border-b border-border/50 pb-2">
                    <span className="text-sm font-medium text-muted-foreground">Kernel Module</span>
                    <span className="font-mono text-sm">{selectedPCIDevice.kernel_module}</span>
                  </div>
                )}

                {selectedPCIDevice.irq && (
                  <div className="flex justify-between border-b border-border/50 pb-2">
                    <span className="text-sm font-medium text-muted-foreground">IRQ</span>
                    <span className="font-mono text-sm">{selectedPCIDevice.irq}</span>
                  </div>
                )}

                {selectedPCIDevice.memory_address && (
                  <div className="flex justify-between border-b border-border/50 pb-2">
                    <span className="text-sm font-medium text-muted-foreground">Memory Address</span>
                    <span className="font-mono text-sm">{selectedPCIDevice.memory_address}</span>
                  </div>
                )}

                {selectedPCIDevice.link_speed && (
                  <div className="flex justify-between border-b border-border/50 pb-2">
                    <span className="text-sm font-medium text-muted-foreground">Link Speed</span>
                    <span className="font-mono text-sm">{selectedPCIDevice.link_speed}</span>
                  </div>
                )}

                {selectedPCIDevice.capabilities && selectedPCIDevice.capabilities.length > 0 && (
                  <div className="space-y-2 border-b border-border/50 pb-2">
                    <span className="text-sm font-medium text-muted-foreground">Capabilities</span>
                    <div className="flex flex-wrap gap-2">
                      {selectedPCIDevice.capabilities.map((cap, idx) => (
                        <Badge key={idx} variant="secondary" className="text-xs">
                          {cap}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
