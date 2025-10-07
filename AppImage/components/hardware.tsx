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
  Loader2,
} from "lucide-react"
import useSWR from "swr"
import { useState } from "react"
import { type HardwareData, type GPU, type PCIDevice, type StorageDevice, fetcher } from "../types/hardware"

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

const getMonitoringToolRecommendation = (vendor: string): string => {
  const lowerVendor = vendor.toLowerCase()
  if (lowerVendor.includes("intel")) {
    return "To get extended GPU monitoring information, please install intel-gpu-tools or igt-gpu-tools package."
  }
  if (lowerVendor.includes("nvidia")) {
    return "For NVIDIA GPUs, real-time monitoring requires the proprietary drivers (nvidia-driver package). Install them only if your GPU is used directly by the host."
  }

  if (lowerVendor.includes("amd") || lowerVendor.includes("ati")) {
    return "To get extended GPU monitoring information, please install radeontop package."
  }
  return "To get extended GPU monitoring information, please install the appropriate GPU monitoring tools for your hardware."
}

export default function Hardware() {
  const { data: hardwareData, error } = useSWR<HardwareData>("/api/hardware", fetcher, {
    refreshInterval: 5000,
  })

  const [selectedGPU, setSelectedGPU] = useState<GPU | null>(null)
  const [realtimeGPUData, setRealtimeGPUData] = useState<any>(null)
  const [loadingGPUData, setLoadingGPUData] = useState(false)
  const [selectedPCIDevice, setSelectedPCIDevice] = useState<PCIDevice | null>(null)
  const [selectedDisk, setSelectedDisk] = useState<StorageDevice | null>(null)
  const [selectedNetwork, setSelectedNetwork] = useState<PCIDevice | null>(null)

  const handleGPUClick = async (gpu: GPU) => {
    setLoadingGPUData(true)
    setSelectedGPU(gpu)
    setRealtimeGPUData(null)

    try {
      console.log("[v0] Fetching real-time GPU data for slot:", gpu.slot)
      const response = await fetch(`http://localhost:8008/api/gpu/${gpu.slot}/realtime`, {
        signal: AbortSignal.timeout(3000),
      })
      if (response.ok) {
        const data = await response.json()
        console.log("[v0] Real-time GPU data received:", data)
        setRealtimeGPUData(data)
      } else {
        console.log("[v0] Failed to fetch real-time GPU data:", response.status)
        setRealtimeGPUData({ has_monitoring_tool: false })
      }
    } catch (error) {
      console.error("[v0] Error fetching real-time GPU data:", error)
      setRealtimeGPUData({ has_monitoring_tool: false })
    } finally {
      setLoadingGPUData(false)
    }
  }

  const findPCIDeviceForGPU = (gpu: GPU): PCIDevice | null => {
    if (!hardwareData?.pci_devices || !gpu.slot) return null

    // Try to find exact match first (e.g., "00:02.0")
    let pciDevice = hardwareData.pci_devices.find((d) => d.slot === gpu.slot)

    // If not found, try to match by partial slot (e.g., "00" matches "00:02.0")
    if (!pciDevice && gpu.slot.length <= 2) {
      pciDevice = hardwareData.pci_devices.find(
        (d) =>
          d.slot.startsWith(gpu.slot + ":") &&
          (d.type.toLowerCase().includes("vga") ||
            d.type.toLowerCase().includes("graphics") ||
            d.type.toLowerCase().includes("display")),
      )
    }

    return pciDevice || null
  }

  const hasRealtimeData = (): boolean => {
    if (!realtimeGPUData) return false

    const result = !!(
      (realtimeGPUData.temperature !== undefined && realtimeGPUData.temperature > 0) ||
      (realtimeGPUData.utilization_gpu !== undefined && realtimeGPUData.utilization_gpu > 0) ||
      realtimeGPUData.memory_total ||
      realtimeGPUData.power_draw ||
      realtimeGPUData.engine_render !== undefined ||
      realtimeGPUData.engine_blitter !== undefined ||
      realtimeGPUData.engine_video !== undefined ||
      realtimeGPUData.engine_video_enhance !== undefined ||
      realtimeGPUData.clock_graphics ||
      realtimeGPUData.clock_memory ||
      realtimeGPUData.utilization_memory !== undefined ||
      (realtimeGPUData.processes !== undefined && realtimeGPUData.processes.length > 0)
    )
    return result
  }

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

      {/* GPU Information - Enhanced with on-demand data fetching */}
      {hardwareData?.gpus && hardwareData.gpus.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Gpu className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Graphics Cards</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.gpus.length} GPU{hardwareData.gpus.length > 1 ? "s" : ""}
            </Badge>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {hardwareData.gpus.map((gpu, index) => {
              const pciDevice = findPCIDeviceForGPU(gpu)
              const fullSlot = pciDevice?.slot || gpu.slot

              return (
                <div
                  key={index}
                  onClick={() => handleGPUClick(gpu)}
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

                    {fullSlot && (
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">PCI Slot</span>
                        <span className="font-mono text-xs">{fullSlot}</span>
                      </div>
                    )}

                    {gpu.pci_driver && (
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">Driver</span>
                        <span className="font-mono text-xs text-green-500">{gpu.pci_driver}</span>
                      </div>
                    )}

                    {gpu.pci_kernel_module && (
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">Kernel Module</span>
                        <span className="font-mono text-xs">{gpu.pci_kernel_module}</span>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      <Dialog
        open={loadingGPUData}
        onOpenChange={() => {
          // Prevent closing while loading
          if (!loadingGPUData) {
            setSelectedGPU(null)
            setRealtimeGPUData(null)
          }
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              Loading GPU Data
            </DialogTitle>
            <DialogDescription>Fetching real-time monitoring information...</DialogDescription>
          </DialogHeader>
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-12 w-12 animate-spin text-primary" />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={selectedGPU !== null && !loadingGPUData && realtimeGPUData !== null}
        onOpenChange={() => {
          setSelectedGPU(null)
          setRealtimeGPUData(null)
        }}
      >
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          {selectedGPU && (
            <>
              {hasRealtimeData()
                ? // Advanced modal with real-time data
                  (() => {
                    const pciDevice = findPCIDeviceForGPU(selectedGPU)

                    return (
                      <>
                        <DialogHeader>
                          <DialogTitle>{selectedGPU.name}</DialogTitle>
                          <DialogDescription>Real-Time GPU Monitoring</DialogDescription>
                        </DialogHeader>

                        <div className="space-y-4">
                          {/* Basic Information */}
                          <div className="space-y-2">
                            <h3 className="font-semibold text-sm">Basic Information</h3>
                            <div className="grid gap-2">
                              <div className="flex justify-between border-b border-border/50 pb-2">
                                <span className="text-sm text-muted-foreground">Vendor</span>
                                <Badge className={getDeviceTypeColor("graphics")}>{selectedGPU.vendor}</Badge>
                              </div>
                              <div className="flex justify-between border-b border-border/50 pb-2">
                                <span className="text-sm text-muted-foreground">Type</span>
                                <span className="text-sm font-medium">{selectedGPU.type}</span>
                              </div>
                              <div className="flex justify-between border-b border-border/50 pb-2">
                                <span className="text-sm text-muted-foreground">PCI Slot</span>
                                <span className="font-mono text-sm">{pciDevice?.slot || selectedGPU.slot}</span>
                              </div>
                              {(pciDevice?.driver || selectedGPU.pci_driver) && (
                                <div className="flex justify-between border-b border-border/50 pb-2">
                                  <span className="text-sm text-muted-foreground">Driver</span>
                                  <span className="font-mono text-sm text-green-500">
                                    {pciDevice?.driver || selectedGPU.pci_driver}
                                  </span>
                                </div>
                              )}
                              {(pciDevice?.kernel_module || selectedGPU.pci_kernel_module) && (
                                <div className="flex justify-between border-b border-border/50 pb-2">
                                  <span className="text-sm text-muted-foreground">Kernel Module</span>
                                  <span className="font-mono text-sm">
                                    {pciDevice?.kernel_module || selectedGPU.pci_kernel_module}
                                  </span>
                                </div>
                              )}
                            </div>
                          </div>

                          {/* Real-Time Metrics */}
                          <div className="space-y-2">
                            <h3 className="font-semibold text-sm">Real-Time Metrics</h3>
                            <div className="grid gap-2">
                              {realtimeGPUData.temperature !== undefined && realtimeGPUData.temperature > 0 && (
                                <div className="space-y-1">
                                  <div className="flex justify-between">
                                    <span className="text-sm text-muted-foreground">Temperature</span>
                                    <span className="text-sm font-semibold text-green-500">
                                      {realtimeGPUData.temperature}°C
                                    </span>
                                  </div>
                                  <Progress value={(realtimeGPUData.temperature / 100) * 100} className="h-2" />
                                </div>
                              )}
                              {realtimeGPUData.utilization_gpu !== undefined && (
                                <div className="space-y-1">
                                  <div className="flex justify-between">
                                    <span className="text-sm text-muted-foreground">GPU Utilization</span>
                                    <span className="text-sm font-medium">{realtimeGPUData.utilization_gpu}%</span>
                                  </div>
                                  <Progress value={realtimeGPUData.utilization_gpu} className="h-2" />
                                </div>
                              )}
                              {realtimeGPUData.clock_graphics && (
                                <div className="flex justify-between border-b border-border/50 pb-2">
                                  <span className="text-sm text-muted-foreground">Graphics Clock</span>
                                  <span className="text-sm font-medium">{realtimeGPUData.clock_graphics}</span>
                                </div>
                              )}
                              {realtimeGPUData.clock_memory && (
                                <div className="flex justify-between border-b border-border/50 pb-2">
                                  <span className="text-sm text-muted-foreground">Memory Clock</span>
                                  <span className="text-sm font-medium">{realtimeGPUData.clock_memory}</span>
                                </div>
                              )}
                              {realtimeGPUData.power_draw && realtimeGPUData.power_draw !== "N/A" && (
                                <div className="flex justify-between border-b border-border/50 pb-2">
                                  <span className="text-sm text-muted-foreground">Power Draw</span>
                                  <span className="text-sm font-medium">{realtimeGPUData.power_draw}</span>
                                </div>
                              )}
                              {realtimeGPUData.power_limit && (
                                <div className="flex justify-between border-b border-border/50 pb-2">
                                  <span className="text-sm text-muted-foreground">Power Limit</span>
                                  <span className="text-sm font-medium">{realtimeGPUData.power_limit}</span>
                                </div>
                              )}
                            </div>
                          </div>

                          {/* Engine Utilization (Intel/AMD) */}
                          {(realtimeGPUData.engine_render !== undefined ||
                            realtimeGPUData.engine_blitter !== undefined ||
                            realtimeGPUData.engine_video !== undefined ||
                            realtimeGPUData.engine_video_enhance !== undefined) && (
                            <div className="space-y-2">
                              <h3 className="font-semibold text-sm">Engine Utilization</h3>
                              <div className="grid gap-2">
                                {realtimeGPUData.engine_render !== undefined && (
                                  <div className="space-y-1">
                                    <div className="flex justify-between">
                                      <span className="text-sm text-muted-foreground">Render/3D</span>
                                      <span className="text-sm font-medium">
                                        {realtimeGPUData.engine_render.toFixed(2)}%
                                      </span>
                                    </div>
                                    <Progress value={realtimeGPUData.engine_render} className="h-2" />
                                  </div>
                                )}
                                {realtimeGPUData.engine_blitter !== undefined && (
                                  <div className="space-y-1">
                                    <div className="flex justify-between">
                                      <span className="text-sm text-muted-foreground">Blitter</span>
                                      <span className="text-sm font-medium">
                                        {realtimeGPUData.engine_blitter.toFixed(2)}%
                                      </span>
                                    </div>
                                    <Progress value={realtimeGPUData.engine_blitter} className="h-2" />
                                  </div>
                                )}
                                {realtimeGPUData.engine_video !== undefined && (
                                  <div className="space-y-1">
                                    <div className="flex justify-between">
                                      <span className="text-sm text-muted-foreground">Video</span>
                                      <span className="text-sm font-medium">
                                        {realtimeGPUData.engine_video.toFixed(2)}%
                                      </span>
                                    </div>
                                    <Progress value={realtimeGPUData.engine_video} className="h-2" />
                                  </div>
                                )}
                                {realtimeGPUData.engine_video_enhance !== undefined && (
                                  <div className="space-y-1">
                                    <div className="flex justify-between">
                                      <span className="text-sm text-muted-foreground">VideoEnhance</span>
                                      <span className="text-sm font-medium">
                                        {realtimeGPUData.engine_video_enhance.toFixed(2)}%
                                      </span>
                                    </div>
                                    <Progress value={realtimeGPUData.engine_video_enhance} className="h-2" />
                                  </div>
                                )}
                              </div>
                            </div>
                          )}

                          {/* Memory Info */}
                          {realtimeGPUData.memory_total && (
                            <div className="space-y-2">
                              <h3 className="font-semibold text-sm">Memory</h3>
                              <div className="grid gap-2">
                                <div className="flex justify-between border-b border-border/50 pb-2">
                                  <span className="text-sm text-muted-foreground">Total</span>
                                  <span className="text-sm font-medium">{realtimeGPUData.memory_total}</span>
                                </div>
                                <div className="flex justify-between border-b border-border/50 pb-2">
                                  <span className="text-sm text-muted-foreground">Used</span>
                                  <span className="text-sm font-medium">{realtimeGPUData.memory_used}</span>
                                </div>
                                <div className="flex justify-between border-b border-border/50 pb-2">
                                  <span className="text-sm text-muted-foreground">Free</span>
                                  <span className="text-sm font-medium">{realtimeGPUData.memory_free}</span>
                                </div>
                                {realtimeGPUData.utilization_memory !== undefined && (
                                  <div className="space-y-1">
                                    <div className="flex justify-between">
                                      <span className="text-sm text-muted-foreground">Memory Utilization</span>
                                      <span className="text-sm font-medium">{realtimeGPUData.utilization_memory}%</span>
                                    </div>
                                    <Progress value={realtimeGPUData.utilization_memory} className="h-2" />
                                  </div>
                                )}
                              </div>
                            </div>
                          )}

                          {/* Running Processes (NVIDIA) */}
                          {realtimeGPUData.processes && realtimeGPUData.processes.length > 0 && (
                            <div className="space-y-2">
                              <h3 className="font-semibold text-sm">Running Processes</h3>
                              <div className="space-y-2">
                                {realtimeGPUData.processes.map((proc: any, idx: number) => (
                                  <div key={idx} className="rounded-lg border border-border/30 bg-background/50 p-3">
                                    <div className="flex justify-between">
                                      <span className="font-mono text-xs">PID: {proc.pid}</span>
                                      <span className="text-xs font-medium">{proc.memory}</span>
                                    </div>
                                    <p className="mt-1 text-sm">{proc.name}</p>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </>
                    )
                  })()
                : // Basic modal without real-time data
                  (() => {
                    const pciDevice = findPCIDeviceForGPU(selectedGPU)

                    return (
                      <>
                        <DialogHeader>
                          <DialogTitle>{selectedGPU.name}</DialogTitle>
                          <DialogDescription>PCI Device Information</DialogDescription>
                        </DialogHeader>

                        <div className="space-y-3">
                          <div className="flex justify-between border-b border-border/50 pb-2">
                            <span className="text-sm font-medium text-muted-foreground">Device Type</span>
                            <Badge className={getDeviceTypeColor("graphics")}>Graphics Card</Badge>
                          </div>

                          <div className="flex justify-between border-b border-border/50 pb-2">
                            <span className="text-sm font-medium text-muted-foreground">PCI Slot</span>
                            <span className="font-mono text-sm">{pciDevice?.slot || selectedGPU.slot}</span>
                          </div>

                          <div className="flex justify-between border-b border-border/50 pb-2">
                            <span className="text-sm font-medium text-muted-foreground">Device Name</span>
                            <span className="text-sm text-right">{selectedGPU.name}</span>
                          </div>

                          <div className="flex justify-between border-b border-border/50 pb-2">
                            <span className="text-sm font-medium text-muted-foreground">Vendor</span>
                            <span className="text-sm">{selectedGPU.vendor}</span>
                          </div>

                          {(pciDevice?.class || selectedGPU.pci_class) && (
                            <div className="flex justify-between border-b border-border/50 pb-2">
                              <span className="text-sm font-medium text-muted-foreground">Class</span>
                              <span className="font-mono text-sm">{pciDevice?.class || selectedGPU.pci_class}</span>
                            </div>
                          )}

                          {(pciDevice?.driver || selectedGPU.pci_driver) && (
                            <div className="flex justify-between border-b border-border/50 pb-2">
                              <span className="text-sm font-medium text-muted-foreground">Driver</span>
                              <span className="font-mono text-sm text-green-500">
                                {pciDevice?.driver || selectedGPU.pci_driver}
                              </span>
                            </div>
                          )}

                          {(pciDevice?.kernel_module || selectedGPU.pci_kernel_module) && (
                            <div className="flex justify-between border-b border-border/50 pb-2">
                              <span className="text-sm font-medium text-muted-foreground">Kernel Module</span>
                              <span className="font-mono text-sm">
                                {pciDevice?.kernel_module || selectedGPU.pci_kernel_module}
                              </span>
                            </div>
                          )}

                          <div className="flex justify-between border-b border-border/50 pb-2">
                            <span className="text-sm font-medium text-muted-foreground">Type</span>
                            <span className="text-sm">{selectedGPU.type}</span>
                          </div>

                          {realtimeGPUData?.has_monitoring_tool === false && (
                            <div className="mt-4 rounded-lg bg-blue-500/10 p-4 border border-blue-500/20">
                              <div className="flex gap-3">
                                <div className="flex-shrink-0">
                                  <svg className="h-5 w-5 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                                    <path
                                      fillRule="evenodd"
                                      d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                                      clipRule="evenodd"
                                    />
                                  </svg>
                                </div>
                                <div>
                                  <h4 className="text-sm font-semibold text-blue-500 mb-1">
                                    Extended Monitoring Not Available
                                  </h4>
                                  <p className="text-sm text-muted-foreground">
                                    {getMonitoringToolRecommendation(selectedGPU.vendor)}
                                  </p>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      </>
                    )
                  })()}
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* PCI Devices - Changed to modal */}
      {hardwareData?.pci_devices && hardwareData.pci_devices.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <CpuIcon className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">PCI Devices</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.pci_devices.length} devices
            </Badge>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hardwareData.pci_devices.map((device, index) => (
              <div
                key={index}
                onClick={() => setSelectedPCIDevice(device)}
                className="cursor-pointer rounded-lg border border-border/30 bg-background/50 p-3 transition-colors hover:bg-background/80"
              >
                <div className="flex items-center justify-between gap-2 mb-2">
                  <Badge className={`${getDeviceTypeColor(device.type)} text-xs shrink-0`}>{device.type}</Badge>
                  <span className="font-mono text-xs text-muted-foreground shrink-0">{device.slot}</span>
                </div>
                <p className="font-medium text-sm line-clamp-2 break-words">{device.device}</p>
                <p className="text-xs text-muted-foreground truncate">{device.vendor}</p>
                {device.driver && (
                  <p className="mt-1 font-mono text-xs text-green-500 truncate">Driver: {device.driver}</p>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* PCI Device Detail Modal */}
      <Dialog open={selectedPCIDevice !== null} onOpenChange={() => setSelectedPCIDevice(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{selectedPCIDevice?.device}</DialogTitle>
            <DialogDescription>PCI Device Information</DialogDescription>
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
            <Zap className="h-5 w-5 text-blue-500" />
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
                <p className="text-2xl font-bold text-blue-500">{hardwareData.power_meter.watts.toFixed(1)} W</p>
                <p className="text-xs text-muted-foreground">Current Draw</p>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Power Supplies */}
      {hardwareData?.power_supplies && hardwareData.power_supplies.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <PowerIcon className="h-5 w-5 text-green-500" />
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
                <p className="mt-2 text-2xl font-bold text-green-500">{psu.watts} W</p>
                <p className="text-xs text-muted-foreground">Current Output</p>
              </div>
            ))}
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
              const isPercentage = fan.unit === "percent" || fan.unit === "%"
              const percentage = isPercentage ? fan.speed : Math.min((fan.speed / 5000) * 100, 100)

              return (
                <div key={index} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{fan.name}</span>
                    <span className="text-sm font-semibold text-blue-500">
                      {isPercentage ? `${fan.speed.toFixed(0)} percent` : `${fan.speed.toFixed(0)} ${fan.unit}`}
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
      {/* This section was moved to be grouped with Power Consumption */}

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

      {/* Network Summary - Clickable */}
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

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {hardwareData.pci_devices
                .filter((d) => d.type.toLowerCase().includes("network"))
                .map((device, index) => (
                  <div
                    key={index}
                    onClick={() => setSelectedNetwork(device)}
                    className="cursor-pointer rounded-lg border border-border/30 bg-background/50 p-3 transition-colors hover:bg-background/80"
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span className="text-sm font-medium line-clamp-2 break-words flex-1">{device.device}</span>
                      <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 text-xs shrink-0">
                        Ethernet
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground truncate">{device.vendor}</p>
                    {device.driver && (
                      <p className="mt-1 font-mono text-xs text-green-500 truncate">Driver: {device.driver}</p>
                    )}
                  </div>
                ))}
            </div>
            <p className="mt-4 text-xs text-muted-foreground">Click on an interface for detailed information</p>
          </Card>
        )}

      {/* Network Detail Modal */}
      <Dialog open={selectedNetwork !== null} onOpenChange={() => setSelectedNetwork(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{selectedNetwork?.device}</DialogTitle>
            <DialogDescription>Network Interface Information</DialogDescription>
          </DialogHeader>

          {selectedNetwork && (
            <div className="space-y-3">
              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Device Type</span>
                <Badge className={getDeviceTypeColor(selectedNetwork.type)}>{selectedNetwork.type}</Badge>
              </div>

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">PCI Slot</span>
                <span className="font-mono text-sm">{selectedNetwork.slot}</span>
              </div>

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Vendor</span>
                <span className="text-sm">{selectedNetwork.vendor}</span>
              </div>

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Class</span>
                <span className="font-mono text-sm">{selectedNetwork.class}</span>
              </div>

              {selectedNetwork.driver && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Driver</span>
                  <span className="font-mono text-sm text-green-500">{selectedNetwork.driver}</span>
                </div>
              )}

              {selectedNetwork.kernel_module && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Kernel Module</span>
                  <span className="font-mono text-sm">{selectedNetwork.kernel_module}</span>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Storage Summary - Clickable */}
      {hardwareData?.storage_devices && hardwareData.storage_devices.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <HardDrive className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Storage Summary</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.storage_devices.length} devices
            </Badge>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hardwareData.storage_devices.map((device, index) => (
              <div
                key={index}
                onClick={() => setSelectedDisk(device)}
                className="cursor-pointer rounded-lg border border-border/30 bg-background/50 p-3 transition-colors hover:bg-background/80"
              >
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="text-sm font-medium truncate flex-1">{device.name}</span>
                  <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 px-2.5 py-0.5 shrink-0">
                    {device.type}
                  </Badge>
                </div>
                {device.size && <p className="text-sm font-medium">{device.size}</p>}
                {device.model && (
                  <p className="text-xs text-muted-foreground line-clamp-2 break-words">{device.model}</p>
                )}
                {device.driver && (
                  <p className="mt-1 font-mono text-xs text-green-500 truncate">Driver: {device.driver}</p>
                )}
              </div>
            ))}
          </div>
          <p className="mt-4 text-xs text-muted-foreground">Click on a device for detailed hardware information</p>
        </Card>
      )}

      {/* Disk Detail Modal */}
      <Dialog open={selectedDisk !== null} onOpenChange={() => setSelectedDisk(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{selectedDisk?.name}</DialogTitle>
            <DialogDescription>Storage Device Hardware Information</DialogDescription>
          </DialogHeader>

          {selectedDisk && (
            <div className="space-y-3">
              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Device Name</span>
                <span className="font-mono text-sm">{selectedDisk.name}</span>
              </div>

              {selectedDisk.type && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Type</span>
                  <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20">{selectedDisk.type}</Badge>
                </div>
              )}

              {selectedDisk.size && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Capacity</span>
                  <span className="text-sm font-medium">{selectedDisk.size}</span>
                </div>
              )}

              {selectedDisk.model && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Model</span>
                  <span className="text-sm text-right">{selectedDisk.model}</span>
                </div>
              )}

              {selectedDisk.family && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Family</span>
                  <span className="text-sm text-right">{selectedDisk.family}</span>
                </div>
              )}

              {selectedDisk.serial && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Serial Number</span>
                  <span className="font-mono text-sm">{selectedDisk.serial}</span>
                </div>
              )}

              {selectedDisk.firmware && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Firmware</span>
                  <span className="font-mono text-sm">{selectedDisk.firmware}</span>
                </div>
              )}

              {selectedDisk.interface && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Interface</span>
                  <span className="text-sm font-medium">{selectedDisk.interface}</span>
                </div>
              )}

              {selectedDisk.driver && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Driver</span>
                  <span className="font-mono text-sm text-green-500">{selectedDisk.driver}</span>
                </div>
              )}

              {selectedDisk.rotation_rate && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Rotation Rate</span>
                  <span className="text-sm">{selectedDisk.rotation_rate}</span>
                </div>
              )}

              {selectedDisk.form_factor && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Form Factor</span>
                  <span className="text-sm">{selectedDisk.form_factor}</span>
                </div>
              )}

              {selectedDisk.sata_version && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">SATA Version</span>
                  <span className="text-sm">{selectedDisk.sata_version}</span>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
