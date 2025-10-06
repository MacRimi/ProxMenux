"use client"

import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import {
  Thermometer,
  CpuIcon,
  ChevronDown,
  ChevronUp,
  Zap,
  HardDrive,
  Network,
  FanIcon,
  PowerIcon,
  Battery,
  Cpu,
  MemoryStick,
  Cpu as Gpu,
} from "lucide-react"
import useSWR from "swr"
import { useState } from "react"
import { type HardwareData, fetcher } from "../types/hardware"

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

  const [expandedPCIDevice, setExpandedPCIDevice] = useState<string | null>(null)

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

      {/* Thermal Monitoring - Restored blue progress bars */}
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

      {/* GPU Information - New dedicated GPU section */}
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
              <div key={index} className="rounded-lg border border-border/30 bg-background/50 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <span className="font-medium">{gpu.name}</span>
                  <Badge className={getDeviceTypeColor("graphics")}>{gpu.vendor}</Badge>
                </div>

                <div className="space-y-2">
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

                  {gpu.power_draw && gpu.power_draw !== "N/A" && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Power Draw</span>
                      <span className="font-medium">{gpu.power_draw}</span>
                    </div>
                  )}

                  {gpu.driver_version && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Driver</span>
                      <span className="font-mono text-xs">{gpu.driver_version}</span>
                    </div>
                  )}

                  {gpu.type && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Type</span>
                      <span className="font-medium">{gpu.type}</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* PCI Devices */}
      {hardwareData?.pci_devices && hardwareData.pci_devices.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <CpuIcon className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">PCI Devices</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.pci_devices.length} devices
            </Badge>
          </div>

          <div className="space-y-3">
            {hardwareData.pci_devices.map((device, index) => {
              const deviceKey = `${device.slot}-${index}`
              const isExpanded = expandedPCIDevice === deviceKey

              return (
                <div key={index} className="rounded-lg border border-border/30 bg-background/50">
                  <div
                    onClick={() => setExpandedPCIDevice(isExpanded ? null : deviceKey)}
                    className="flex cursor-pointer items-start justify-between p-4 transition-colors hover:bg-background/80"
                  >
                    <div className="flex-1 space-y-1">
                      <div className="flex items-center gap-2">
                        <Badge className={getDeviceTypeColor(device.type)}>{device.type}</Badge>
                        <span className="font-mono text-xs text-muted-foreground">{device.slot}</span>
                      </div>
                      <p className="font-medium text-sm">{device.device}</p>
                      <p className="text-xs text-muted-foreground">{device.vendor}</p>
                    </div>
                    {isExpanded ? (
                      <ChevronUp className="h-5 w-5 text-muted-foreground" />
                    ) : (
                      <ChevronDown className="h-5 w-5 text-muted-foreground" />
                    )}
                  </div>

                  {isExpanded && (
                    <div className="border-t border-border/30 p-4 space-y-3">
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm font-medium text-muted-foreground">Device Type</span>
                        <Badge className={getDeviceTypeColor(device.type)}>{device.type}</Badge>
                      </div>

                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm font-medium text-muted-foreground">PCI Slot</span>
                        <span className="font-mono text-sm">{device.slot}</span>
                      </div>

                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm font-medium text-muted-foreground">Device Name</span>
                        <span className="text-sm text-right">{device.device}</span>
                      </div>

                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm font-medium text-muted-foreground">Vendor</span>
                        <span className="text-sm">{device.vendor}</span>
                      </div>

                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm font-medium text-muted-foreground">Class</span>
                        <span className="font-mono text-sm">{device.class}</span>
                      </div>

                      {device.driver && (
                        <div className="flex justify-between border-b border-border/50 pb-2">
                          <span className="text-sm font-medium text-muted-foreground">Driver</span>
                          <span className="font-mono text-sm text-green-500">{device.driver}</span>
                        </div>
                      )}

                      {device.kernel_module && (
                        <div className="flex justify-between border-b border-border/50 pb-2">
                          <span className="text-sm font-medium text-muted-foreground">Kernel Module</span>
                          <span className="font-mono text-sm">{device.kernel_module}</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* Power Consumption - Only show if data exists */}
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

      {/* Fans - Only show if data exists */}
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
                    <span className="text-sm font-medium">{fan.name}</span>
                    <span className="text-sm font-semibold text-blue-500">
                      {fan.speed.toFixed(0)} {fan.unit}
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                    <div className="h-full bg-blue-500 transition-all" style={{ width: `${percentage}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* Power Supplies - Only show if data exists */}
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

      {/* UPS - Only show if data exists and has content */}
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

      {/* Network Summary */}
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
                  <div key={index} className="rounded-lg border border-border/30 bg-background/50 p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium truncate">{device.device}</span>
                      <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 text-xs">Ethernet</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground truncate">{device.vendor}</p>
                  </div>
                ))}
            </div>
            <p className="mt-4 text-xs text-muted-foreground">
              For detailed network information, see the Network section
            </p>
          </Card>
        )}

      {/* Storage Summary - Larger badges with blue color */}
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
              <div key={index} className="rounded-lg border border-border/30 bg-background/50 p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium">{device.name}</span>
                  <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 px-2.5 py-0.5">{device.type}</Badge>
                </div>
                {device.size && <p className="text-sm font-medium">{device.size}</p>}
                {device.model && <p className="text-xs text-muted-foreground truncate">{device.model}</p>}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
