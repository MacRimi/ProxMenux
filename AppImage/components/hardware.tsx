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
} from "lucide-react"
import useSWR from "swr"
import { useState } from "react"
import { type HardwareData, fetcher } from "@/types/hardware"

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
      {/* CPU & Motherboard Info */}
      {(hardwareData?.cpu || hardwareData?.motherboard) && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Cpu className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">System Information</h2>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            {/* CPU Info */}
            {hardwareData?.cpu && Object.keys(hardwareData.cpu).length > 0 && (
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-muted-foreground">Processor</h3>
                <div className="space-y-2 rounded-lg border border-border/30 bg-background/50 p-4">
                  {hardwareData.cpu.model && (
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Model</span>
                      <span className="text-sm font-medium">{hardwareData.cpu.model}</span>
                    </div>
                  )}
                  {hardwareData.cpu.sockets && (
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Sockets</span>
                      <span className="text-sm font-medium">{hardwareData.cpu.sockets}</span>
                    </div>
                  )}
                  {hardwareData.cpu.cores_per_socket && (
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Cores per Socket</span>
                      <span className="text-sm font-medium">{hardwareData.cpu.cores_per_socket}</span>
                    </div>
                  )}
                  {hardwareData.cpu.total_threads && (
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Total Threads</span>
                      <span className="text-sm font-medium">{hardwareData.cpu.total_threads}</span>
                    </div>
                  )}
                  {hardwareData.cpu.current_mhz && (
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Current Speed</span>
                      <span className="text-sm font-medium">{hardwareData.cpu.current_mhz.toFixed(0)} MHz</span>
                    </div>
                  )}
                  {hardwareData.cpu.max_mhz && (
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Max Speed</span>
                      <span className="text-sm font-medium">{hardwareData.cpu.max_mhz.toFixed(0)} MHz</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Motherboard Info */}
            {hardwareData?.motherboard && Object.keys(hardwareData.motherboard).length > 0 && (
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-muted-foreground">Motherboard</h3>
                <div className="space-y-2 rounded-lg border border-border/30 bg-background/50 p-4">
                  {hardwareData.motherboard.manufacturer && (
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Manufacturer</span>
                      <span className="text-sm font-medium">{hardwareData.motherboard.manufacturer}</span>
                    </div>
                  )}
                  {hardwareData.motherboard.model && (
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Model</span>
                      <span className="text-sm font-medium">{hardwareData.motherboard.model}</span>
                    </div>
                  )}
                  {hardwareData.motherboard.version && (
                    <div className="flex justify-between">
                      <span className="text-sm text-muted-foreground">Version</span>
                      <span className="text-sm font-medium">{hardwareData.motherboard.version}</span>
                    </div>
                  )}
                  {hardwareData.motherboard.bios && (
                    <>
                      <div className="mt-3 border-t border-border/30 pt-2">
                        <span className="text-xs font-semibold text-muted-foreground">BIOS</span>
                      </div>
                      {hardwareData.motherboard.bios.vendor && (
                        <div className="flex justify-between">
                          <span className="text-sm text-muted-foreground">Vendor</span>
                          <span className="text-sm font-medium">{hardwareData.motherboard.bios.vendor}</span>
                        </div>
                      )}
                      {hardwareData.motherboard.bios.version && (
                        <div className="flex justify-between">
                          <span className="text-sm text-muted-foreground">Version</span>
                          <span className="text-sm font-medium">{hardwareData.motherboard.bios.version}</span>
                        </div>
                      )}
                      {hardwareData.motherboard.bios.date && (
                        <div className="flex justify-between">
                          <span className="text-sm text-muted-foreground">Date</span>
                          <span className="text-sm font-medium">{hardwareData.motherboard.bios.date}</span>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}
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
                  <Progress value={percentage} className="h-2" />
                  {temp.adapter && <span className="text-xs text-muted-foreground">{temp.adapter}</span>}
                </div>
              )
            })}
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

      {/* Fans */}
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
                  <Progress value={percentage} className="h-2" />
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

      {/* UPS - Solo mostrar si hay datos */}
      {hardwareData?.ups && Object.keys(hardwareData.ups).length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Battery className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">UPS Status</h2>
          </div>

          <div className="space-y-4">
            <div className="rounded-lg border border-border/30 bg-background/50 p-4">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-medium">{hardwareData.ups.model || "UPS"}</span>
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
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">{device.device}</span>
                      <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20">Ethernet</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{device.vendor}</p>
                  </div>
                ))}
            </div>
            <p className="mt-4 text-xs text-muted-foreground">
              For detailed network information, see the Network section
            </p>
          </Card>
        )}

      {/* Storage Summary */}
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
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{device.name}</span>
                  <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 text-xs px-2 py-1">
                    {device.type}
                  </Badge>
                </div>
                {device.size && <p className="mt-1 text-xs text-muted-foreground">{device.size}</p>}
                {device.model && <p className="mt-1 text-xs text-muted-foreground">{device.model}</p>}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
