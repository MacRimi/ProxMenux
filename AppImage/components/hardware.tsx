"use client"

import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Thermometer, CpuIcon, ChevronDown, ChevronUp, Zap } from "lucide-react"
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

      {/* Network Summary */}

      {/* Storage Summary */}

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
                          <span className="font-mono text-sm">{device.driver}</span>
                        </div>
                      )}

                      {device.kernel_module && (
                        <div className="flex justify-between border-b border-border/50 pb-2">
                          <span className="text-sm font-medium text-muted-foreground">Kernel Module</span>
                          <span className="font-mono text-sm">{device.kernel_module}</span>
                        </div>
                      )}

                      {device.irq && (
                        <div className="flex justify-between border-b border-border/50 pb-2">
                          <span className="text-sm font-medium text-muted-foreground">IRQ</span>
                          <span className="font-mono text-sm">{device.irq}</span>
                        </div>
                      )}

                      {device.memory_address && (
                        <div className="flex justify-between border-b border-border/50 pb-2">
                          <span className="text-sm font-medium text-muted-foreground">Memory Address</span>
                          <span className="font-mono text-sm">{device.memory_address}</span>
                        </div>
                      )}

                      {device.link_speed && (
                        <div className="flex justify-between border-b border-border/50 pb-2">
                          <span className="text-sm font-medium text-muted-foreground">Link Speed</span>
                          <span className="font-mono text-sm">{device.link_speed}</span>
                        </div>
                      )}

                      {device.capabilities && device.capabilities.length > 0 && (
                        <div className="space-y-2 border-b border-border/50 pb-2">
                          <span className="text-sm font-medium text-muted-foreground">Capabilities</span>
                          <div className="flex flex-wrap gap-2">
                            {device.capabilities.map((cap, idx) => (
                              <Badge key={idx} variant="secondary" className="text-xs">
                                {cap}
                              </Badge>
                            ))}
                          </div>
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

      {/* ... existing code for Fans, Power Supply, UPS sections ... */}
    </div>
  )
}
