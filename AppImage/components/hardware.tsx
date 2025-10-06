"use client"

import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  Thermometer,
  CpuIcon,
  Zap,
  HardDrive,
  Network,
  FanIcon,
  PowerIcon,
  Battery,
  Cpu,
  MemoryStick,
  Cpu as Gpu,
  Info,
  Activity,
  Gauge,
} from "lucide-react"
import useSWR from "swr"
import { useState } from "react"
import { type HardwareData, type GPU, type NetworkInterfaceDetails, type DiskDetails, fetcher } from "../types/hardware"

const getDeviceTypeColor = (type: string): string => {
  const lowerType = type.toLowerCase()
  if (lowerType.includes("storage") || lowerType.includes("sata") || lowerType.includes("raid")) {
    return "bg-orange-500/10 text-orange-500 border-orange-500/20"
  }
  if (lowerType.includes("usb")) {
    return "bg-purple-500/10 text-purple-500 border-purple-500/20"
  }
  if (lowerType.includes("network") || lowerType.includes("ethernet")) {
    return "bg-blue-500/10 text-blue-500 border-blue-500/20"
  }
  if (lowerType.includes("graphics") || lowerType.includes("vga") || lowerType.includes("display")) {
    return "bg-green-500/10 text-green-500 border-green-500/20"
  }
  return "bg-gray-500/10 text-gray-500 border-gray-500/20"
}

export default function Hardware() {
  const { data: hardwareData, error } = useSWR<HardwareData>("/api/hardware", fetcher, {
    refreshInterval: 5000,
  })

  const [selectedGPU, setSelectedGPU] = useState<GPU | null>(null)
  const [selectedNetworkInterface, setSelectedNetworkInterface] = useState<string | null>(null)
  const [selectedDisk, setSelectedDisk] = useState<string | null>(null)
  const [selectedPCIDevice, setSelectedPCIDevice] = useState<any | null>(null)

  const { data: networkDetails } = useSWR<NetworkInterfaceDetails>(
    selectedNetworkInterface ? `/api/hardware/network/${selectedNetworkInterface}` : null,
    fetcher,
  )

  const { data: diskDetails } = useSWR<DiskDetails>(selectedDisk ? `/api/hardware/disk/${selectedDisk}` : null, fetcher)

  return (
    <div className="space-y-6 p-6">
      {/* System Information - CPU & Motherboard */}
      {(hardwareData?.cpu || hardwareData?.motherboard) && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Cpu className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">System Information</h2>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            {/* CPU Info */}
            {hardwareData?.cpu && Object.keys(hardwareData.cpu).length > 0 && (
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <CpuIcon className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">CPU</h3>
                </div>
                <div className="space-y-2">
                  {hardwareData.cpu.model && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Model</span>
                      <span className="font-medium text-right">{hardwareData.cpu.model}</span>
                    </div>
                  )}
                  {hardwareData.cpu.cores_per_socket && hardwareData.cpu.sockets && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Cores</span>
                      <span className="font-medium">
                        {hardwareData.cpu.sockets} × {hardwareData.cpu.cores_per_socket} ={" "}
                        {hardwareData.cpu.sockets * hardwareData.cpu.cores_per_socket} cores
                      </span>
                    </div>
                  )}
                  {hardwareData.cpu.total_threads && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Threads</span>
                      <span className="font-medium">{hardwareData.cpu.total_threads}</span>
                    </div>
                  )}
                  {hardwareData.cpu.l3_cache && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">L3 Cache</span>
                      <span className="font-medium">{hardwareData.cpu.l3_cache}</span>
                    </div>
                  )}
                  {hardwareData.cpu.virtualization && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Virtualization</span>
                      <span className="font-medium">{hardwareData.cpu.virtualization}</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Motherboard Info */}
            {hardwareData?.motherboard && Object.keys(hardwareData.motherboard).length > 0 && (
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <Cpu className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">Motherboard</h3>
                </div>
                <div className="space-y-2">
                  {hardwareData.motherboard.manufacturer && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Manufacturer</span>
                      <span className="font-medium text-right">{hardwareData.motherboard.manufacturer}</span>
                    </div>
                  )}
                  {hardwareData.motherboard.model && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Model</span>
                      <span className="font-medium text-right">{hardwareData.motherboard.model}</span>
                    </div>
                  )}
                  {hardwareData.motherboard.bios?.vendor && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">BIOS</span>
                      <span className="font-medium text-right">{hardwareData.motherboard.bios.vendor}</span>
                    </div>
                  )}
                  {hardwareData.motherboard.bios?.version && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Version</span>
                      <span className="font-medium">{hardwareData.motherboard.bios.version}</span>
                    </div>
                  )}
                  {hardwareData.motherboard.bios?.date && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Date</span>
                      <span className="font-medium">{hardwareData.motherboard.bios.date}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Memory Modules */}
      {hardwareData?.memory_modules && hardwareData.memory_modules.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <MemoryStick className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Memory Modules</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.memory_modules.length} installed
            </Badge>
          </div>

          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {hardwareData.memory_modules.map((module, index) => (
              <div key={index} className="rounded-lg border border-border/30 bg-background/50 p-4">
                <div className="mb-2 font-medium text-sm">{module.slot}</div>
                <div className="space-y-1">
                  {module.size && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Size</span>
                      <span className="font-medium">{module.size}</span>
                    </div>
                  )}
                  {module.type && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Type</span>
                      <span className="font-medium">{module.type}</span>
                    </div>
                  )}
                  {module.speed && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Speed</span>
                      <span className="font-medium">{module.speed}</span>
                    </div>
                  )}
                  {module.manufacturer && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Manufacturer</span>
                      <span className="font-medium text-right">{module.manufacturer}</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Thermal Monitoring */}
      {hardwareData?.temperatures && hardwareData.temperatures.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Thermometer className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Thermal Monitoring</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.temperatures.length} sensors
            </Badge>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {hardwareData.temperatures.map((temp, index) => {
              const percentage = temp.critical > 0 ? (temp.current / temp.critical) * 100 : (temp.current / 100) * 100
              const isHot = temp.current > (temp.high || 80)
              const isCritical = temp.current > (temp.critical || 90)

              return (
                <div key={index} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{temp.name}</span>
                    <span
                      className={`text-sm font-semibold ${isCritical ? "text-red-500" : isHot ? "text-orange-500" : "text-green-500"}`}
                    >
                      {temp.current.toFixed(1)}°C
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                    <div
                      className="h-full bg-blue-500 transition-all"
                      style={{ width: `${Math.min(percentage, 100)}%` }}
                    />
                  </div>
                  {temp.adapter && <span className="text-xs text-muted-foreground">{temp.adapter}</span>}
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {hardwareData?.gpus && hardwareData.gpus.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Gpu className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Graphics Cards</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.gpus.length} GPU{hardwareData.gpus.length > 1 ? "s" : ""}
            </Badge>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {hardwareData.gpus.map((gpu, index) => (
              <div
                key={index}
                onClick={() => setSelectedGPU(gpu)}
                className="cursor-pointer rounded-lg border border-border/30 bg-background/50 p-4 transition-colors hover:bg-background/80"
              >
                <div className="mb-3 flex items-center justify-between">
                  <span className="font-medium text-sm">{gpu.name}</span>
                  <Badge className={getDeviceTypeColor("graphics")}>{gpu.vendor}</Badge>
                </div>

                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Type</span>
                    <span className="font-medium">{gpu.type}</span>
                  </div>

                  {gpu.driver_version && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Driver</span>
                      <span className="font-mono text-xs">{gpu.driver_version}</span>
                    </div>
                  )}

                  {gpu.memory_total && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Memory</span>
                      <span className="font-medium">
                        {gpu.memory_used} / {gpu.memory_total}
                      </span>
                    </div>
                  )}

                  {gpu.temperature !== undefined && gpu.temperature > 0 && (
                    <div className="space-y-1">
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">Temperature</span>
                        <span className="font-semibold text-green-500">{gpu.temperature}°C</span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                        <div
                          className="h-full bg-blue-500 transition-all"
                          style={{ width: `${Math.min((gpu.temperature / 100) * 100, 100)}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {gpu.utilization !== undefined && (
                    <div className="space-y-1">
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">Utilization</span>
                        <span className="font-medium">{gpu.utilization}%</span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                        <div className="h-full bg-green-500 transition-all" style={{ width: `${gpu.utilization}%` }} />
                      </div>
                    </div>
                  )}
                </div>

                <div className="mt-3 flex items-center gap-1 text-xs text-muted-foreground">
                  <Info className="h-3 w-3" />
                  <span>Click for detailed information</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Dialog open={selectedGPU !== null} onOpenChange={(open) => !open && setSelectedGPU(null)}>
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Gpu className="h-5 w-5" />
              {selectedGPU?.name}
            </DialogTitle>
            <DialogDescription>Detailed GPU information and statistics</DialogDescription>
          </DialogHeader>

          {selectedGPU && (
            <div className="space-y-6">
              {/* Basic Information */}
              <div>
                <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
                  <Info className="h-4 w-4" />
                  Basic Information
                </h3>
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-3">
                    <span className="text-sm text-muted-foreground">Vendor</span>
                    <Badge className={getDeviceTypeColor("graphics")}>{selectedGPU.vendor}</Badge>
                  </div>
                  <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-3">
                    <span className="text-sm text-muted-foreground">Type</span>
                    <span className="text-sm font-medium">{selectedGPU.type}</span>
                  </div>
                  {selectedGPU.slot && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-3">
                      <span className="text-sm text-muted-foreground">PCI Slot</span>
                      <span className="font-mono text-sm">{selectedGPU.slot}</span>
                    </div>
                  )}
                  {selectedGPU.driver_version && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-3">
                      <span className="text-sm text-muted-foreground">Driver Version</span>
                      <span className="font-mono text-sm">{selectedGPU.driver_version}</span>
                    </div>
                  )}
                  {selectedGPU.pcie_gen && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-3">
                      <span className="text-sm text-muted-foreground">PCIe Generation</span>
                      <span className="text-sm font-medium">Gen {selectedGPU.pcie_gen}</span>
                    </div>
                  )}
                  {selectedGPU.pcie_width && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-3">
                      <span className="text-sm text-muted-foreground">PCIe Width</span>
                      <span className="text-sm font-medium">{selectedGPU.pcie_width}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Performance Metrics */}
              {(selectedGPU.utilization !== undefined || selectedGPU.temperature !== undefined) && (
                <div>
                  <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
                    <Activity className="h-4 w-4" />
                    Performance Metrics
                  </h3>
                  <div className="space-y-3">
                    {selectedGPU.utilization !== undefined && (
                      <div className="rounded-lg border border-border/30 bg-background/50 p-3">
                        <div className="mb-2 flex justify-between text-sm">
                          <span className="text-muted-foreground">GPU Utilization</span>
                          <span className="font-semibold">{selectedGPU.utilization}%</span>
                        </div>
                        <Progress value={selectedGPU.utilization} className="h-2" />
                      </div>
                    )}
                    {selectedGPU.memory_utilization !== undefined && (
                      <div className="rounded-lg border border-border/30 bg-background/50 p-3">
                        <div className="mb-2 flex justify-between text-sm">
                          <span className="text-muted-foreground">Memory Utilization</span>
                          <span className="font-semibold">{selectedGPU.memory_utilization}%</span>
                        </div>
                        <Progress value={selectedGPU.memory_utilization} className="h-2" />
                      </div>
                    )}
                    {selectedGPU.temperature !== undefined && selectedGPU.temperature > 0 && (
                      <div className="rounded-lg border border-border/30 bg-background/50 p-3">
                        <div className="mb-2 flex justify-between text-sm">
                          <span className="text-muted-foreground">Temperature</span>
                          <span className="font-semibold text-green-500">{selectedGPU.temperature}°C</span>
                        </div>
                        <Progress value={(selectedGPU.temperature / 100) * 100} className="h-2" />
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Memory Information */}
              {selectedGPU.memory_total && (
                <div>
                  <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
                    <MemoryStick className="h-4 w-4" />
                    Memory Information
                  </h3>
                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="rounded-lg border border-border/30 bg-background/50 p-3">
                      <p className="text-xs text-muted-foreground">Total</p>
                      <p className="text-lg font-semibold">{selectedGPU.memory_total}</p>
                    </div>
                    <div className="rounded-lg border border-border/30 bg-background/50 p-3">
                      <p className="text-xs text-muted-foreground">Used</p>
                      <p className="text-lg font-semibold">{selectedGPU.memory_used}</p>
                    </div>
                    <div className="rounded-lg border border-border/30 bg-background/50 p-3">
                      <p className="text-xs text-muted-foreground">Free</p>
                      <p className="text-lg font-semibold">{selectedGPU.memory_free}</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Clock Speeds */}
              {(selectedGPU.clock_graphics || selectedGPU.clock_memory) && (
                <div>
                  <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
                    <Gauge className="h-4 w-4" />
                    Clock Speeds
                  </h3>
                  <div className="grid gap-3 md:grid-cols-2">
                    {selectedGPU.clock_graphics && (
                      <div className="rounded-lg border border-border/30 bg-background/50 p-3">
                        <p className="text-xs text-muted-foreground">Graphics Clock</p>
                        <p className="text-lg font-semibold">{selectedGPU.clock_graphics}</p>
                      </div>
                    )}
                    {selectedGPU.clock_memory && (
                      <div className="rounded-lg border border-border/30 bg-background/50 p-3">
                        <p className="text-xs text-muted-foreground">Memory Clock</p>
                        <p className="text-lg font-semibold">{selectedGPU.clock_memory}</p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Power Information */}
              {(selectedGPU.power_draw || selectedGPU.power_limit) && (
                <div>
                  <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
                    <Zap className="h-4 w-4" />
                    Power Information
                  </h3>
                  <div className="grid gap-3 md:grid-cols-2">
                    {selectedGPU.power_draw && selectedGPU.power_draw !== "N/A" && (
                      <div className="rounded-lg border border-border/30 bg-background/50 p-3">
                        <p className="text-xs text-muted-foreground">Current Draw</p>
                        <p className="text-lg font-semibold text-yellow-500">{selectedGPU.power_draw}</p>
                      </div>
                    )}
                    {selectedGPU.power_limit && selectedGPU.power_limit !== "N/A" && (
                      <div className="rounded-lg border border-border/30 bg-background/50 p-3">
                        <p className="text-xs text-muted-foreground">Power Limit</p>
                        <p className="text-lg font-semibold">{selectedGPU.power_limit}</p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Running Processes */}
              {selectedGPU.processes && selectedGPU.processes.length > 0 && (
                <div>
                  <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
                    <CpuIcon className="h-4 w-4" />
                    Running Processes
                  </h3>
                  <div className="space-y-2">
                    {selectedGPU.processes.map((process, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between rounded-lg border border-border/30 bg-background/50 p-3"
                      >
                        <div>
                          <p className="text-sm font-medium">{process.name}</p>
                          <p className="text-xs text-muted-foreground">PID: {process.pid}</p>
                        </div>
                        <Badge variant="outline">{process.memory}</Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {hardwareData?.pci_devices && hardwareData.pci_devices.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <CpuIcon className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">PCI Devices</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.pci_devices.length} devices
            </Badge>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {hardwareData.pci_devices.map((device, index) => (
              <div
                key={index}
                onClick={() => setSelectedPCIDevice(device)}
                className="cursor-pointer rounded-lg border border-border/30 bg-background/50 p-4 transition-colors hover:bg-background/80"
              >
                <div className="flex items-center justify-between mb-2">
                  <Badge className={getDeviceTypeColor(device.type)}>{device.type}</Badge>
                  <span className="font-mono text-xs text-muted-foreground">{device.slot}</span>
                </div>
                <p className="font-medium text-sm mb-1">{device.device}</p>
                <p className="text-xs text-muted-foreground">{device.vendor}</p>
                <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                  <Info className="h-3 w-3" />
                  <span>Click for details</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Dialog open={selectedPCIDevice !== null} onOpenChange={(open) => !open && setSelectedPCIDevice(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <CpuIcon className="h-5 w-5" />
              {selectedPCIDevice?.device}
            </DialogTitle>
            <DialogDescription>PCI device information</DialogDescription>
          </DialogHeader>

          {selectedPCIDevice && (
            <div className="space-y-3">
              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Device Type</span>
                <Badge className={getDeviceTypeColor(selectedPCIDevice.type)}>{selectedPCIDevice.type}</Badge>
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
                  <span className="font-mono text-sm text-green-500">{selectedPCIDevice.driver}</span>
                </div>
              )}

              {selectedPCIDevice.kernel_module && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Kernel Module</span>
                  <span className="font-mono text-sm">{selectedPCIDevice.kernel_module}</span>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Power Consumption */}
      {hardwareData?.power_meter && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Zap className="h-5 w-5 text-yellow-500" />
            <h2 className="text-lg font-semibold">Power Consumption</h2>
          </div>

          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-lg border border-border/30 bg-background/50 p-4">
              <div className="space-y-1">
                <p className="text-sm font-medium">{hardwareData.power_meter.name}</p>
                {hardwareData.power_meter.adapter && (
                  <p className="text-xs text-muted-foreground">{hardwareData.power_meter.adapter}</p>
                )}
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold text-yellow-500">{hardwareData.power_meter.watts.toFixed(1)} W</p>
                <p className="text-xs text-muted-foreground">Current Draw</p>
              </div>
            </div>
          </div>
        </Card>
      )}

      {hardwareData?.fans && hardwareData.fans.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <FanIcon className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">System Fans</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.fans.length} fans
            </Badge>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {hardwareData.fans.map((fan, index) => {
              const maxRPM = 5000
              const percentage = Math.min((fan.speed / maxRPM) * 100, 100)

              return (
                <div key={index} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{fan.name}</span>
                      <Badge variant="outline" className="text-xs">
                        {fan.type}
                      </Badge>
                    </div>
                    <span className="text-sm font-semibold text-blue-500">
                      {fan.speed.toFixed(0)} {fan.unit}
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                    <div className="h-full bg-blue-500 transition-all" style={{ width: `${percentage}%` }} />
                  </div>
                  {fan.adapter && <span className="text-xs text-muted-foreground">{fan.adapter}</span>}
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* Power Supplies */}
      {hardwareData?.power_supplies && hardwareData.power_supplies.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <PowerIcon className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Power Supplies</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.power_supplies.length} PSUs
            </Badge>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {hardwareData.power_supplies.map((psu, index) => (
              <div key={index} className="rounded-lg border border-border/30 bg-background/50 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{psu.name}</span>
                  {psu.status && (
                    <Badge variant={psu.status.toLowerCase() === "ok" ? "default" : "destructive"}>{psu.status}</Badge>
                  )}
                </div>
                <p className="mt-2 text-2xl font-bold text-primary">{psu.watts} W</p>
                <p className="text-xs text-muted-foreground">Current Output</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* UPS */}
      {hardwareData?.ups && Object.keys(hardwareData.ups).length > 0 && hardwareData.ups.model && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Battery className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">UPS Status</h2>
          </div>

          <div className="space-y-4">
            <div className="rounded-lg border border-border/30 bg-background/50 p-4">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-medium">{hardwareData.ups.model}</span>
                <Badge variant={hardwareData.ups.status === "OL" ? "default" : "destructive"}>
                  {hardwareData.ups.status}
                </Badge>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                {hardwareData.ups.battery_charge && (
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">Battery Charge</span>
                      <span className="text-sm font-semibold">{hardwareData.ups.battery_charge}</span>
                    </div>
                    <Progress
                      value={Number.parseInt(hardwareData.ups.battery_charge.replace("%", ""))}
                      className="h-2"
                    />
                  </div>
                )}

                {hardwareData.ups.load_percent && (
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">Load</span>
                      <span className="text-sm font-semibold">{hardwareData.ups.load_percent}</span>
                    </div>
                    <Progress value={Number.parseInt(hardwareData.ups.load_percent.replace("%", ""))} className="h-2" />
                  </div>
                )}

                {hardwareData.ups.time_left && (
                  <div>
                    <span className="text-xs text-muted-foreground">Runtime</span>
                    <p className="text-sm font-semibold">{hardwareData.ups.time_left}</p>
                  </div>
                )}

                {hardwareData.ups.line_voltage && (
                  <div>
                    <span className="text-xs text-muted-foreground">Input Voltage</span>
                    <p className="text-sm font-semibold">{hardwareData.ups.line_voltage}</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </Card>
      )}

      {hardwareData?.pci_devices &&
        hardwareData.pci_devices.filter((d) => d.type.toLowerCase().includes("network")).length > 0 && (
          <Card className="border-border/50 bg-card/50 p-6">
            <div className="mb-4 flex items-center gap-2">
              <Network className="h-5 w-5 text-primary" />
              <h2 className="text-lg font-semibold">Network Summary</h2>
              <Badge variant="outline" className="ml-auto">
                {hardwareData.pci_devices.filter((d) => d.type.toLowerCase().includes("network")).length} interfaces
              </Badge>
            </div>

            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {hardwareData.pci_devices
                .filter((d) => d.type.toLowerCase().includes("network"))
                .map((device, index) => (
                  <div
                    key={index}
                    onClick={() => setSelectedNetworkInterface(device.device.split(" ")[0].toLowerCase())}
                    className="cursor-pointer rounded-lg border border-border/30 bg-background/50 p-3 transition-colors hover:bg-background/80"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium truncate">{device.device}</span>
                      <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 text-xs">Ethernet</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground truncate">{device.vendor}</p>
                    <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                      <Info className="h-3 w-3" />
                      <span>Click for details</span>
                    </div>
                  </div>
                ))}
            </div>
          </Card>
        )}

      <Dialog
        open={selectedNetworkInterface !== null}
        onOpenChange={(open) => !open && setSelectedNetworkInterface(null)}
      >
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Network className="h-5 w-5" />
              Network Interface: {selectedNetworkInterface}
            </DialogTitle>
            <DialogDescription>Detailed network interface information</DialogDescription>
          </DialogHeader>

          {networkDetails && (
            <div className="space-y-4">
              {/* Driver Information */}
              <div>
                <h3 className="mb-2 text-sm font-semibold">Driver Information</h3>
                <div className="space-y-2">
                  {networkDetails.driver && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Driver</span>
                      <span className="font-mono text-sm">{networkDetails.driver}</span>
                    </div>
                  )}
                  {networkDetails.driver_version && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Version</span>
                      <span className="font-mono text-sm">{networkDetails.driver_version}</span>
                    </div>
                  )}
                  {networkDetails.firmware_version && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Firmware</span>
                      <span className="font-mono text-sm">{networkDetails.firmware_version}</span>
                    </div>
                  )}
                  {networkDetails.bus_info && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Bus Info</span>
                      <span className="font-mono text-sm">{networkDetails.bus_info}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Connection Status */}
              <div>
                <h3 className="mb-2 text-sm font-semibold">Connection Status</h3>
                <div className="space-y-2">
                  {networkDetails.link_detected && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Link</span>
                      <Badge variant={networkDetails.link_detected === "yes" ? "default" : "destructive"}>
                        {networkDetails.link_detected}
                      </Badge>
                    </div>
                  )}
                  {networkDetails.speed && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Speed</span>
                      <span className="text-sm font-medium">{networkDetails.speed}</span>
                    </div>
                  )}
                  {networkDetails.duplex && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Duplex</span>
                      <span className="text-sm font-medium">{networkDetails.duplex}</span>
                    </div>
                  )}
                  {networkDetails.mtu && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">MTU</span>
                      <span className="text-sm font-medium">{networkDetails.mtu}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Addresses */}
              {(networkDetails.mac_address ||
                (networkDetails.ip_addresses && networkDetails.ip_addresses.length > 0)) && (
                <div>
                  <h3 className="mb-2 text-sm font-semibold">Addresses</h3>
                  <div className="space-y-2">
                    {networkDetails.mac_address && (
                      <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                        <span className="text-sm text-muted-foreground">MAC Address</span>
                        <span className="font-mono text-sm">{networkDetails.mac_address}</span>
                      </div>
                    )}
                    {networkDetails.ip_addresses &&
                      networkDetails.ip_addresses.map((ip, idx) => (
                        <div
                          key={idx}
                          className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2"
                        >
                          <span className="text-sm text-muted-foreground">{ip.type}</span>
                          <span className="font-mono text-sm">{ip.address}</span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* Statistics */}
              {networkDetails.statistics && Object.keys(networkDetails.statistics).length > 0 && (
                <div>
                  <h3 className="mb-2 text-sm font-semibold">Statistics</h3>
                  <div className="grid gap-2 md:grid-cols-2">
                    {networkDetails.statistics.rx_bytes && (
                      <div className="rounded-lg border border-border/30 bg-background/50 p-2">
                        <p className="text-xs text-muted-foreground">RX Bytes</p>
                        <p className="text-sm font-medium">{networkDetails.statistics.rx_bytes}</p>
                      </div>
                    )}
                    {networkDetails.statistics.rx_packets && (
                      <div className="rounded-lg border border-border/30 bg-background/50 p-2">
                        <p className="text-xs text-muted-foreground">RX Packets</p>
                        <p className="text-sm font-medium">{networkDetails.statistics.rx_packets}</p>
                      </div>
                    )}
                    {networkDetails.statistics.tx_bytes && (
                      <div className="rounded-lg border border-border/30 bg-background/50 p-2">
                        <p className="text-xs text-muted-foreground">TX Bytes</p>
                        <p className="text-sm font-medium">{networkDetails.statistics.tx_bytes}</p>
                      </div>
                    )}
                    {networkDetails.statistics.tx_packets && (
                      <div className="rounded-lg border border-border/30 bg-background/50 p-2">
                        <p className="text-xs text-muted-foreground">TX Packets</p>
                        <p className="text-sm font-medium">{networkDetails.statistics.tx_packets}</p>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {hardwareData?.storage_devices && hardwareData.storage_devices.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <HardDrive className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Storage Summary</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.storage_devices.length} devices
            </Badge>
          </div>

          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {hardwareData.storage_devices.map((device, index) => (
              <div
                key={index}
                onClick={() => setSelectedDisk(device.name)}
                className="cursor-pointer rounded-lg border border-border/30 bg-background/50 p-3 transition-colors hover:bg-background/80"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium">{device.name}</span>
                  <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 px-2.5 py-0.5">{device.type}</Badge>
                </div>
                {device.size && <p className="text-sm font-medium">{device.size}</p>}
                {device.model && <p className="text-xs text-muted-foreground truncate">{device.model}</p>}
                <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                  <Info className="h-3 w-3" />
                  <span>Click for details</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Dialog open={selectedDisk !== null} onOpenChange={(open) => !open && setSelectedDisk(null)}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <HardDrive className="h-5 w-5" />
              Disk: {selectedDisk}
            </DialogTitle>
            <DialogDescription>Detailed disk information</DialogDescription>
          </DialogHeader>

          {diskDetails && (
            <div className="space-y-4">
              {/* Basic Information */}
              <div>
                <h3 className="mb-2 text-sm font-semibold">Basic Information</h3>
                <div className="space-y-2">
                  {diskDetails.type && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Type</span>
                      <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20">{diskDetails.type}</Badge>
                    </div>
                  )}
                  {diskDetails.driver && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Driver</span>
                      <span className="font-mono text-sm">{diskDetails.driver}</span>
                    </div>
                  )}
                  {diskDetails.model && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Model</span>
                      <span className="text-sm">{diskDetails.model}</span>
                    </div>
                  )}
                  {diskDetails.serial && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Serial</span>
                      <span className="font-mono text-sm">{diskDetails.serial}</span>
                    </div>
                  )}
                  {diskDetails.size && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Size</span>
                      <span className="text-sm font-medium">{diskDetails.size}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Technical Details */}
              <div>
                <h3 className="mb-2 text-sm font-semibold">Technical Details</h3>
                <div className="space-y-2">
                  {diskDetails.rotational !== undefined && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Rotational</span>
                      <Badge variant={diskDetails.rotational ? "default" : "outline"}>
                        {diskDetails.rotational ? "Yes (HDD)" : "No (SSD)"}
                      </Badge>
                    </div>
                  )}
                  {diskDetails.block_size && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Block Size</span>
                      <span className="text-sm">{diskDetails.block_size} bytes</span>
                    </div>
                  )}
                  {diskDetails.scheduler && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Scheduler</span>
                      <span className="text-sm">{diskDetails.scheduler}</span>
                    </div>
                  )}
                  {diskDetails.removable !== undefined && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Removable</span>
                      <Badge variant={diskDetails.removable ? "default" : "outline"}>
                        {diskDetails.removable ? "Yes" : "No"}
                      </Badge>
                    </div>
                  )}
                  {diskDetails.read_only !== undefined && (
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">Read Only</span>
                      <Badge variant={diskDetails.read_only ? "destructive" : "default"}>
                        {diskDetails.read_only ? "Yes" : "No"}
                      </Badge>
                    </div>
                  )}
                </div>
              </div>

              {/* SMART Information */}
              {diskDetails.smart_available && (
                <div>
                  <h3 className="mb-2 text-sm font-semibold">SMART Information</h3>
                  <div className="space-y-2">
                    <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                      <span className="text-sm text-muted-foreground">SMART Enabled</span>
                      <Badge variant={diskDetails.smart_enabled ? "default" : "outline"}>
                        {diskDetails.smart_enabled ? "Yes" : "No"}
                      </Badge>
                    </div>
                    {diskDetails.smart_health && (
                      <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                        <span className="text-sm text-muted-foreground">Health Status</span>
                        <Badge variant={diskDetails.smart_health === "PASSED" ? "default" : "destructive"}>
                          {diskDetails.smart_health}
                        </Badge>
                      </div>
                    )}
                    {diskDetails.temperature !== undefined && (
                      <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                        <span className="text-sm text-muted-foreground">Temperature</span>
                        <span className="text-sm font-semibold text-green-500">{diskDetails.temperature}°C</span>
                      </div>
                    )}
                    {diskDetails.power_on_hours !== undefined && (
                      <div className="flex justify-between rounded-lg border border-border/30 bg-background/50 p-2">
                        <span className="text-sm text-muted-foreground">Power On Hours</span>
                        <span className="text-sm font-medium">{diskDetails.power_on_hours.toLocaleString()} hours</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Partitions */}
              {diskDetails.partitions && diskDetails.partitions.length > 0 && (
                <div>
                  <h3 className="mb-2 text-sm font-semibold">Partitions</h3>
                  <div className="space-y-2">
                    {diskDetails.partitions.map((partition, idx) => (
                      <div key={idx} className="rounded-lg border border-border/30 bg-background/50 p-3">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-mono text-sm font-medium">{partition.name}</span>
                          {partition.size && <span className="text-sm text-muted-foreground">{partition.size}</span>}
                        </div>
                        <div className="flex items-center gap-2 text-xs">
                          {partition.fstype && <Badge variant="outline">{partition.fstype}</Badge>}
                          {partition.mountpoint && (
                            <span className="text-muted-foreground">→ {partition.mountpoint}</span>
                          )}
                        </div>
                      </div>
                    ))}
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
