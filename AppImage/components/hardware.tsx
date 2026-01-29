"use client"

import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Cpu, HardDrive, Thermometer, Zap, Loader2, CpuIcon, Cpu as Gpu, Network, MemoryStick, PowerIcon, FanIcon, Battery } from "lucide-react"
import { Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import useSWR from "swr"
import { useState, useEffect } from "react"
import {
  type HardwareData,
  type GPU,
  type PCIDevice,
  type StorageDevice,
  fetcher as swrFetcher,
} from "../types/hardware"
import { fetchApi } from "@/lib/api-config"
import { ScriptTerminalModal } from "./script-terminal-modal"

const parseLsblkSize = (sizeStr: string | undefined): number => {
  if (!sizeStr) return 0

  // Remove spaces and convert to uppercase
  const cleaned = sizeStr.trim().toUpperCase()

  // Extract number and unit
  const match = cleaned.match(/^([\d.]+)([KMGT]?)$/)
  if (!match) return 0

  const value = Number.parseFloat(match[1])
  const unit = match[2] || "K" // Default to KB if no unit

  // Convert to KB
  switch (unit) {
    case "K":
      return value
    case "M":
      return value * 1024
    case "G":
      return value * 1024 * 1024
    case "T":
      return value * 1024 * 1024 * 1024
    default:
      return value
  }
}

const formatMemory = (memoryKB: number | string): string => {
  const kb = typeof memoryKB === "string" ? Number.parseFloat(memoryKB) : memoryKB

  if (isNaN(kb)) return "N/A"

  // Convert KB to MB
  const mb = kb / 1024

  // Convert to TB if >= 1024 GB
  if (mb >= 1024 * 1024) {
    const tb = mb / (1024 * 1024)
    return `${tb.toFixed(1)} TB`
  }

  if (mb >= 1024) {
    const gb = mb / 1024
    // If GB value is greater than 999, convert to TB
    if (gb > 999) {
      return `${(gb / 1024).toFixed(2)} TB`
    }
    return `${gb.toFixed(1)} GB`
  }

  // Keep in MB if < 1024 MB
  return `${mb.toFixed(0)} MB`
}

const formatClock = (clockString: string | number): string => {
  let mhz: number

  if (typeof clockString === "number") {
    mhz = clockString
  } else {
    // Extract numeric value from string like "1138.179107 MHz"
    const match = clockString.match(/([\d.]+)\s*MHz/i)
    if (!match) return clockString
    mhz = Number.parseFloat(match[1])
  }

  if (isNaN(mhz)) return String(clockString)

  // Convert to GHz if >= 1000 MHz
  if (mhz >= 1000) {
    const ghz = mhz / 1000
    return `${ghz.toFixed(2)} GHz`
  }

  // Keep in MHz if < 1000 MHz
  return `${mhz.toFixed(0)} MHz`
}

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
    return "To get extended GPU monitoring information for AMD GPUs, please install amdgpu_top. You can download it from: https://github.com/Umio-Yasuno/amdgpu_top"
  }
  return "To get extended GPU monitoring information, please install the appropriate GPU monitoring tools for your hardware."
}

const groupAndSortTemperatures = (temperatures: any[]) => {
  const groups = {
    CPU: [] as any[],
    GPU: [] as any[],
    NVME: [] as any[],
    PCI: [] as any[],
    OTHER: [] as any[],
  }

  temperatures.forEach((temp) => {
    const nameLower = temp.name.toLowerCase()
    const adapterLower = temp.adapter?.toLowerCase() || ""

    if (nameLower.includes("cpu") || nameLower.includes("core") || nameLower.includes("package")) {
      groups.CPU.push(temp)
    } else if (nameLower.includes("gpu") || adapterLower.includes("gpu")) {
      groups.GPU.push(temp)
    } else if (nameLower.includes("nvme") || adapterLower.includes("nvme")) {
      groups.NVME.push(temp)
    } else if (adapterLower.includes("pci")) {
      groups.PCI.push(temp)
    } else {
      groups.OTHER.push(temp)
    }
  })

  return groups
}

export default function Hardware() {
  // Static data - load once without refresh
  const {
    data: staticHardwareData,
    error: staticError,
    isLoading: staticLoading,
  } = useSWR<HardwareData>("/api/hardware", swrFetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    refreshInterval: 0, // No auto-refresh for static data
  })

  // Dynamic data - refresh every 5 seconds for temperatures, fans, power, ups
  const {
    data: dynamicHardwareData,
    error: dynamicError,
    isLoading: dynamicLoading,
  } = useSWR<HardwareData>("/api/hardware", swrFetcher, {
    refreshInterval: 7000,
  })

  // Merge static and dynamic data, preferring static for CPU/memory/PCI/disks
  const hardwareData = staticHardwareData
    ? {
        ...dynamicHardwareData,
        // Keep static data from initial load
        cpu: staticHardwareData.cpu,
        motherboard: staticHardwareData.motherboard,
        memory_modules: staticHardwareData.memory_modules,
        pci_devices: staticHardwareData.pci_devices,
        storage_devices: staticHardwareData.storage_devices,
        gpus: staticHardwareData.gpus,
        // Use dynamic data for these
        temperatures: dynamicHardwareData?.temperatures,
        fans: dynamicHardwareData?.fans,
        power_meter: dynamicHardwareData?.power_meter,
        power_supplies: dynamicHardwareData?.power_supplies,
        ups: dynamicHardwareData?.ups,
      }
    : undefined

  const error = staticError || dynamicError
  const isLoading = staticLoading

  useEffect(() => {
    if (hardwareData?.storage_devices) {
      console.log("[v0] Storage devices data from backend:", hardwareData.storage_devices)
      hardwareData.storage_devices.forEach((device) => {
        if (device.name.startsWith("nvme")) {
          console.log(`[v0] NVMe device ${device.name}:`, {
            pcie_gen: device.pcie_gen,
            pcie_width: device.pcie_width,
            pcie_max_gen: device.pcie_max_gen,
            pcie_max_width: device.pcie_max_width,
          })
        }
      })
    }
  }, [hardwareData])

  const [selectedGPU, setSelectedGPU] = useState<GPU | null>(null)
  const [realtimeGPUData, setRealtimeGPUData] = useState<any>(null)
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [selectedPCIDevice, setSelectedPCIDevice] = useState<PCIDevice | null>(null)
  const [selectedDisk, setSelectedDisk] = useState<StorageDevice | null>(null)
  const [selectedNetwork, setSelectedNetwork] = useState<PCIDevice | null>(null)
  const [selectedUPS, setSelectedUPS] = useState<any>(null)
  const [showNvidiaInstaller, setShowNvidiaInstaller] = useState(false)
  const [installingNvidiaDriver, setInstallingNvidiaDriver] = useState(false)
  const [showAmdInstaller, setShowAmdInstaller] = useState(false)

  const fetcher = async (url: string) => {
    const data = await fetchApi(url)
    return data
  }

  const {
    data: hardwareDataSWR,
    error: swrError,
    isLoading: swrLoading,
    mutate: mutateHardware,
  } = useSWR<HardwareData>("/api/hardware", fetcher, {
    refreshInterval: 30000,
    revalidateOnFocus: false,
  })

  const handleInstallNvidiaDriver = () => {
    console.log("[v0] Opening NVIDIA installer terminal")
    setShowNvidiaInstaller(true)
  }

  const handleInstallAmdTools = () => {
    console.log("[v0] Opening AMD GPU tools installer terminal")
    setShowAmdInstaller(true)
  }

  useEffect(() => {
    if (!selectedGPU) return

    const pciDevice = findPCIDeviceForGPU(selectedGPU)
    const fullSlot = pciDevice?.slot || selectedGPU.slot

    if (!fullSlot) return

    const abortController = new AbortController()

    const fetchRealtimeData = async () => {
      try {
        const data = await fetchApi(`/api/gpu/${fullSlot}/realtime`)
        setRealtimeGPUData(data)
        setDetailsLoading(false)
      } catch (error) {
        if (error instanceof Error && error.name !== "AbortError") {
          console.error("[v0] Error fetching GPU realtime data:", error)
        }
        setRealtimeGPUData({ has_monitoring_tool: false })
        setDetailsLoading(false)
      }
    }

    fetchRealtimeData()
    const interval = setInterval(fetchRealtimeData, 3000)

    return () => {
      clearInterval(interval)
      abortController.abort()
    }
  }, [selectedGPU])

  const handleGPUClick = async (gpu: GPU) => {
    setSelectedGPU(gpu)
    setDetailsLoading(true)
    setRealtimeGPUData(null)
  }

  const findPCIDeviceForGPU = (gpu: GPU): PCIDevice | null => {
    if (!hardwareDataSWR?.pci_devices || !gpu.slot) return null

    // Try to find exact match first (e.g., "00:02.0")
    let pciDevice = hardwareDataSWR.pci_devices.find((d) => d.slot === gpu.slot)

    // If not found, try to match by partial slot (e.g., "00" matches "00:02.0")
    if (!pciDevice && gpu.slot.length <= 2) {
      pciDevice = hardwareDataSWR.pci_devices.find(
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

    // Esto permite mostrar datos incluso cuando la GPU está inactiva (valores en 0 o null)
    return realtimeGPUData.has_monitoring_tool === true
  }

  if (swrLoading) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8">
          <div className="text-lg font-medium text-foreground mb-2">Loading hardware data...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* System Information - CPU & Motherboard */}
      {(hardwareDataSWR?.cpu || hardwareDataSWR?.motherboard) && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Cpu className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">System Information</h2>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            {/* CPU Info */}
            {hardwareDataSWR?.cpu && Object.keys(hardwareDataSWR.cpu).length > 0 && (
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <CpuIcon className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">CPU</h3>
                </div>
                <div className="space-y-2">
                  {hardwareDataSWR.cpu.model && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Model</span>
                      <span className="font-medium text-right">{hardwareDataSWR.cpu.model}</span>
                    </div>
                  )}
                  {hardwareDataSWR.cpu.cores_per_socket && hardwareDataSWR.cpu.sockets && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Cores</span>
                      <span className="font-medium">
                        {hardwareDataSWR.cpu.sockets} × {hardwareDataSWR.cpu.cores_per_socket} ={" "}
                        {hardwareDataSWR.cpu.sockets * hardwareDataSWR.cpu.cores_per_socket} cores
                      </span>
                    </div>
                  )}
                  {hardwareDataSWR.cpu.total_threads && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Threads</span>
                      <span className="font-medium">{hardwareDataSWR.cpu.total_threads}</span>
                    </div>
                  )}
                  {hardwareDataSWR.cpu.l3_cache && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">L3 Cache</span>
                      <span className="font-medium">{hardwareDataSWR.cpu.l3_cache}</span>
                    </div>
                  )}
                  {hardwareDataSWR.cpu.virtualization && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Virtualization</span>
                      <span className="font-medium">{hardwareDataSWR.cpu.virtualization}</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Motherboard Info */}
            {hardwareDataSWR?.motherboard && Object.keys(hardwareDataSWR.motherboard).length > 0 && (
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <Cpu className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">Motherboard</h3>
                </div>
                <div className="space-y-2">
                  {hardwareDataSWR.motherboard.manufacturer && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Manufacturer</span>
                      <span className="font-medium text-right">{hardwareDataSWR.motherboard.manufacturer}</span>
                    </div>
                  )}
                  {hardwareDataSWR.motherboard.model && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Model</span>
                      <span className="font-medium text-right">{hardwareDataSWR.motherboard.model}</span>
                    </div>
                  )}
                  {hardwareDataSWR.motherboard.bios?.vendor && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">BIOS</span>
                      <span className="font-medium text-right">{hardwareDataSWR.motherboard.bios.vendor}</span>
                    </div>
                  )}
                  {hardwareDataSWR.motherboard.bios?.version && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Version</span>
                      <span className="font-medium">{hardwareDataSWR.motherboard.bios.version}</span>
                    </div>
                  )}
                  {hardwareDataSWR.motherboard.bios?.date && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Date</span>
                      <span className="font-medium">{hardwareDataSWR.motherboard.bios.date}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Memory Modules */}
      {hardwareDataSWR?.memory_modules && hardwareDataSWR.memory_modules.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <MemoryStick className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Memory Modules</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareDataSWR.memory_modules.length} installed
            </Badge>
          </div>

          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {hardwareDataSWR.memory_modules.map((module, index) => (
              <div key={index} className="rounded-lg border border-border/30 bg-background/60 p-4">
                <div className="mb-2 font-medium text-sm">{module.slot}</div>
                <div className="space-y-1">
                  {module.size && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Size</span>
                      <span className="font-medium text-green-500">{formatMemory(module.size)}</span>
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
      {hardwareDataSWR?.temperatures && hardwareDataSWR.temperatures.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Thermometer className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Thermal Monitoring</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareDataSWR.temperatures.length} sensors
            </Badge>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            {/* CPU Sensors */}
            {groupAndSortTemperatures(hardwareDataSWR.temperatures).CPU.length > 0 && (
              <div className="md:col-span-2">
                <div className="mb-3 flex items-center gap-2">
                  <CpuIcon className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">CPU</h3>
                  <Badge variant="outline" className="text-xs">
                    {groupAndSortTemperatures(hardwareDataSWR.temperatures).CPU.length}
                  </Badge>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  {groupAndSortTemperatures(hardwareDataSWR.temperatures).CPU.map((temp, index) => {
                    const percentage =
                      temp.critical > 0 ? (temp.current / temp.critical) * 100 : (temp.current / 100) * 100
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
              </div>
            )}

            {/* GPU Sensors */}
            {groupAndSortTemperatures(hardwareDataSWR.temperatures).GPU.length > 0 && (
              <div
                className={groupAndSortTemperatures(hardwareDataSWR.temperatures).GPU.length > 1 ? "md:col-span-2" : ""}
              >
                <div className="mb-3 flex items-center gap-2">
                  <Gpu className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">GPU</h3>
                  <Badge variant="outline" className="text-xs">
                    {groupAndSortTemperatures(hardwareDataSWR.temperatures).GPU.length}
                  </Badge>
                </div>
                <div
                  className={`grid gap-4 ${groupAndSortTemperatures(hardwareDataSWR.temperatures).GPU.length > 1 ? "md:grid-cols-2" : ""}`}
                >
                  {groupAndSortTemperatures(hardwareDataSWR.temperatures).GPU.map((temp, index) => {
                    const percentage =
                      temp.critical > 0 ? (temp.current / temp.critical) * 100 : (temp.current / 100) * 100
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
              </div>
            )}

            {/* NVME Sensors */}
            {groupAndSortTemperatures(hardwareDataSWR.temperatures).NVME.length > 0 && (
              <div
                className={
                  groupAndSortTemperatures(hardwareDataSWR.temperatures).NVME.length > 1 ? "md:col-span-2" : ""
                }
              >
                <div className="mb-3 flex items-center gap-2">
                  <HardDrive className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">NVME</h3>
                  <Badge variant="outline" className="text-xs">
                    {groupAndSortTemperatures(hardwareDataSWR.temperatures).NVME.length}
                  </Badge>
                </div>
                <div
                  className={`grid gap-4 ${groupAndSortTemperatures(hardwareDataSWR.temperatures).NVME.length > 1 ? "md:grid-cols-2" : ""}`}
                >
                  {groupAndSortTemperatures(hardwareDataSWR.temperatures).NVME.map((temp, index) => {
                    const percentage =
                      temp.critical > 0 ? (temp.current / temp.critical) * 100 : (temp.current / 100) * 100
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
              </div>
            )}

            {/* PCI Sensors */}
            {groupAndSortTemperatures(hardwareDataSWR.temperatures).PCI.length > 0 && (
              <div
                className={groupAndSortTemperatures(hardwareDataSWR.temperatures).PCI.length > 1 ? "md:col-span-2" : ""}
              >
                <div className="mb-3 flex items-center gap-2">
                  <CpuIcon className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">PCI</h3>
                  <Badge variant="outline" className="text-xs">
                    {groupAndSortTemperatures(hardwareDataSWR.temperatures).PCI.length}
                  </Badge>
                </div>
                <div
                  className={`grid gap-4 ${groupAndSortTemperatures(hardwareDataSWR.temperatures).PCI.length > 1 ? "md:grid-cols-2" : ""}`}
                >
                  {groupAndSortTemperatures(hardwareDataSWR.temperatures).PCI.map((temp, index) => {
                    const percentage =
                      temp.critical > 0 ? (temp.current / temp.critical) * 100 : (temp.current / 100) * 100
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
              </div>
            )}

            {/* OTHER Sensors */}
            {groupAndSortTemperatures(hardwareDataSWR.temperatures).OTHER.length > 0 && (
              <div
                className={
                  groupAndSortTemperatures(hardwareDataSWR.temperatures).OTHER.length > 1 ? "md:col-span-2" : ""
                }
              >
                <div className="mb-3 flex items-center gap-2">
                  <Thermometer className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">OTHER</h3>
                  <Badge variant="outline" className="text-xs">
                    {groupAndSortTemperatures(hardwareDataSWR.temperatures).OTHER.length}
                  </Badge>
                </div>
                <div
                  className={`grid gap-4 ${groupAndSortTemperatures(hardwareDataSWR.temperatures).OTHER.length > 1 ? "md:grid-cols-2" : ""}`}
                >
                  {groupAndSortTemperatures(hardwareDataSWR.temperatures).OTHER.map((temp, index) => {
                    const percentage =
                      temp.critical > 0 ? (temp.current / temp.critical) * 100 : (temp.current / 100) * 100
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
              </div>
            )}
          </div>
        </Card>
      )}

      {/* GPU Information - Enhanced with on-demand data fetching */}
      {hardwareDataSWR?.gpus && hardwareDataSWR.gpus.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Gpu className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Graphics Cards</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareDataSWR.gpus.length} GPU{hardwareDataSWR.gpus.length > 1 ? "s" : ""}
            </Badge>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {hardwareDataSWR.gpus.map((gpu, index) => {
              const pciDevice = findPCIDeviceForGPU(gpu)
              const fullSlot = pciDevice?.slot || gpu.slot

              return (
                <div
                  key={index}
                  onClick={() => handleGPUClick(gpu)}
                  className="cursor-pointer rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 p-4 transition-colors"
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

      {/* GPU Detail Modal - Shows immediately with basic info, then loads real-time data */}
      <Dialog open={!!selectedGPU} onOpenChange={(open) => !open && setSelectedGPU(null)}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          {selectedGPU && (
            <>
              <DialogHeader className="pb-4 border-b border-border">
                <DialogTitle>{selectedGPU.name}</DialogTitle>
                <DialogDescription>GPU Real-Time Monitoring</DialogDescription>
              </DialogHeader>

              <div className="space-y-6 py-4">
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                    Basic Information
                  </h3>
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
                      <span className="font-mono text-sm">
                        {findPCIDeviceForGPU(selectedGPU)?.slot || selectedGPU.slot}
                      </span>
                    </div>
                    {(findPCIDeviceForGPU(selectedGPU)?.driver || selectedGPU.pci_driver) && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Driver</span>
                        {/* CHANGE: Added monitoring availability indicator */}
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm text-green-500">
                            {findPCIDeviceForGPU(selectedGPU)?.driver || selectedGPU.pci_driver}
                          </span>
                          {realtimeGPUData?.has_monitoring_tool === true && (
                            <Badge className="bg-green-500/10 text-green-500 border-green-500/20 text-xs px-1.5 py-0">
                              {realtimeGPUData?.driver_version ? `✓ v${realtimeGPUData.driver_version}` : "✓"}
                            </Badge>
                          )}
                        </div>
                      </div>
                    )}
                    {(findPCIDeviceForGPU(selectedGPU)?.kernel_module || selectedGPU.pci_kernel_module) && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Kernel Module</span>
                        <span className="font-mono text-sm">
                          {findPCIDeviceForGPU(selectedGPU)?.kernel_module || selectedGPU.pci_kernel_module}
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                {detailsLoading ? (
                  <div className="text-center py-8 text-muted-foreground">
                    <Loader2 className="h-8 w-8 animate-spin mx-auto mb-2 text-primary" />
                    <p className="text-sm">Loading real-time data...</p>
                  </div>
                ) : realtimeGPUData?.has_monitoring_tool === true ? (
                  <>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                      <span>Updating every 3 seconds</span>
                    </div>

                    <div>
                      <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                        Real-Time Metrics
                      </h3>
                      <div className="grid gap-3 md:grid-cols-2">
                        {realtimeGPUData.clock_graphics && (
                          <div className="flex justify-between border-b border-border/50 pb-2">
                            <span className="text-sm text-muted-foreground">Graphics Clock</span>
                            <span className="text-sm font-medium">{formatClock(realtimeGPUData.clock_graphics)}</span>
                          </div>
                        )}
                        {realtimeGPUData.clock_memory && (
                          <div className="flex justify-between border-b border-border/50 pb-2">
                            <span className="text-sm text-muted-foreground">Memory Clock</span>
                            <span className="text-sm font-medium">{formatClock(realtimeGPUData.clock_memory)}</span>
                          </div>
                        )}
                        {realtimeGPUData.power_draw && realtimeGPUData.power_draw !== "0.00 W" && (
                          <div className="flex justify-between border-b border-border/50 pb-2">
                            <span className="text-sm text-muted-foreground">Power Draw</span>
                            <span className="text-sm font-medium text-blue-500">{realtimeGPUData.power_draw}</span>
                          </div>
                        )}
                        {realtimeGPUData.temperature !== undefined && realtimeGPUData.temperature !== null && (
                          <div className="flex justify-between border-b border-border/50 pb-2">
                            <span className="text-sm text-muted-foreground">Temperature</span>
                            <span className="text-sm font-semibold text-green-500">
                              {realtimeGPUData.temperature}°C
                            </span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Engine Utilization (Intel/AMD) */}
                    {(realtimeGPUData.engine_render !== undefined ||
                      realtimeGPUData.engine_blitter !== undefined ||
                      realtimeGPUData.engine_video !== undefined ||
                      realtimeGPUData.engine_video_enhance !== undefined) && (
                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                          Engine Utilization (Total)
                        </h3>
                        <div className="grid gap-3">
                          {realtimeGPUData.engine_render !== undefined && (
                            <div className="space-y-1">
                              <div className="flex justify-between">
                                <span className="text-sm text-muted-foreground">Render/3D</span>
                                <span className="text-sm font-medium">
                                  {typeof realtimeGPUData.engine_render === "number"
                                    ? `${realtimeGPUData.engine_render.toFixed(1)}%`
                                    : realtimeGPUData.engine_render}
                                </span>
                              </div>
                              <Progress
                                value={
                                  typeof realtimeGPUData.engine_render === "number"
                                    ? realtimeGPUData.engine_render
                                    : Number.parseFloat(realtimeGPUData.engine_render) || 0
                                }
                                className="h-2 [&>div]:bg-blue-500"
                              />
                            </div>
                          )}
                          {realtimeGPUData.engine_video !== undefined && (
                            <div className="space-y-1">
                              <div className="flex justify-between">
                                <span className="text-sm text-muted-foreground">Video</span>
                                <span className="text-sm font-medium">
                                  {typeof realtimeGPUData.engine_video === "number"
                                    ? `${realtimeGPUData.engine_video.toFixed(1)}%`
                                    : realtimeGPUData.engine_video}
                                </span>
                              </div>
                              <Progress
                                value={
                                  typeof realtimeGPUData.engine_video === "number"
                                    ? realtimeGPUData.engine_video
                                    : Number.parseFloat(realtimeGPUData.engine_video) || 0
                                }
                                className="h-2 [&>div]:bg-blue-500"
                              />
                            </div>
                          )}
                          {realtimeGPUData.engine_blitter !== undefined && (
                            <div className="space-y-1">
                              <div className="flex justify-between">
                                <span className="text-sm text-muted-foreground">Blitter</span>
                                <span className="text-sm font-medium">
                                  {typeof realtimeGPUData.engine_blitter === "number"
                                    ? `${realtimeGPUData.engine_blitter.toFixed(1)}%`
                                    : realtimeGPUData.engine_blitter}
                                </span>
                              </div>
                              <Progress
                                value={
                                  typeof realtimeGPUData.engine_blitter === "number"
                                    ? realtimeGPUData.engine_blitter
                                    : Number.parseFloat(realtimeGPUData.engine_blitter) || 0
                                }
                                className="h-2 [&>div]:bg-blue-500"
                              />
                            </div>
                          )}
                          {realtimeGPUData.engine_video_enhance !== undefined && (
                            <div className="space-y-1">
                              <div className="flex justify-between">
                                <span className="text-sm text-muted-foreground">VideoEnhance</span>
                                <span className="text-sm font-medium">
                                  {typeof realtimeGPUData.engine_video_enhance === "number"
                                    ? `${realtimeGPUData.engine_video_enhance.toFixed(1)}%`
                                    : realtimeGPUData.engine_video_enhance}
                                </span>
                              </div>
                              <Progress
                                value={
                                  typeof realtimeGPUData.engine_video_enhance === "number"
                                    ? realtimeGPUData.engine_video_enhance
                                    : Number.parseFloat(realtimeGPUData.engine_video_enhance) || 0
                                }
                                className="h-2 [&>div]:bg-blue-500"
                              />
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* CHANGE: Changed process name badge from blue to purple to match Intel/AMD */}
                    {realtimeGPUData.processes && realtimeGPUData.processes.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                          Active Processes ({realtimeGPUData.processes.length})
                        </h3>
                        <div className="space-y-3">
                          {realtimeGPUData.processes.map((proc: any, idx: number) => (
                            <div key={idx} className="rounded-lg border border-border/30 bg-background/50 p-4">
                              <div className="flex justify-between items-start mb-3">
                                <div>
                                  <Badge className="bg-purple-500/10 text-purple-500 border-purple-500/20 mb-1">
                                    {proc.name}
                                  </Badge>
                                  <p className="font-mono text-xs text-muted-foreground">PID: {proc.pid}</p>
                                </div>
                                {proc.memory && (
                                  <Badge
                                    variant="outline"
                                    className="font-mono text-xs bg-green-500/10 text-green-500 border-green-500/20"
                                  >
                                    {typeof proc.memory === "object"
                                      ? formatMemory(proc.memory.resident / 1024)
                                      : formatMemory(proc.memory)}
                                  </Badge>
                                )}
                              </div>

                              {proc.engines && Object.keys(proc.engines).length > 0 && (
                                <div className="space-y-2">
                                  <p className="text-xs text-muted-foreground mb-1">Engine Utilization:</p>
                                  {Object.entries(proc.engines).map(([engineName, engineData]: [string, any]) => {
                                    const utilization =
                                      typeof engineData === "object" ? engineData.busy || 0 : engineData
                                    const utilizationNum =
                                      typeof utilization === "string" ? Number.parseFloat(utilization) : utilization

                                    if (utilizationNum === 0 || isNaN(utilizationNum)) return null

                                    return (
                                      <div key={engineName} className="space-y-1">
                                        <div className="flex justify-between">
                                          <span className="text-xs text-muted-foreground">{engineName}</span>
                                          <span className="text-xs font-medium">{utilizationNum.toFixed(1)}%</span>
                                        </div>
                                        <Progress value={utilizationNum} className="h-1.5 [&>div]:bg-blue-500" />
                                      </div>
                                    )
                                  })}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {realtimeGPUData.processes && realtimeGPUData.processes.length === 0 && (
                      <div className="rounded-lg bg-muted/50 p-4 text-center">
                        <p className="text-sm text-muted-foreground">No active processes using the GPU</p>
                      </div>
                    )}

                    {/* Memory Info (NVIDIA) */}
                    {realtimeGPUData.memory_total && (
                      <div>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                          Memory
                        </h3>
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
                              <Progress
                                value={realtimeGPUData.utilization_memory}
                                className="h-2 [&>div]:bg-blue-500"
                              />
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="rounded-lg bg-blue-500/10 p-4 border border-blue-500/20">
                    <div className="flex gap-3">
                      <div className="flex-shrink-0">
                        <svg className="h-5 w-5 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                          <path
                            fillRule="evenodd"
                            d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                            clipRule="evenodd"
                          />
                        </svg>
                      </div>
                      <div className="flex-1">
                        <h4 className="text-sm font-semibold text-blue-500 mb-1">Extended Monitoring Not Available</h4>
                        <p className="text-sm text-muted-foreground mb-3">
                          {getMonitoringToolRecommendation(selectedGPU.vendor)}
                        </p>
                        {selectedGPU.vendor.toLowerCase().includes("nvidia") && (
                          <Button
                            onClick={handleInstallNvidiaDriver}
                            className="w-full bg-blue-600 hover:bg-blue-700 text-white"
                          >
                            <>
                              <Download className="mr-2 h-4 w-4" />
                              Install NVIDIA Drivers
                            </>
                          </Button>
                        )}
                        {(selectedGPU.vendor.toLowerCase().includes("amd") || selectedGPU.vendor.toLowerCase().includes("ati")) && (
                          <Button
                            onClick={handleInstallAmdTools}
                            className="w-full bg-red-600 hover:bg-red-700 text-white"
                          >
                            <>
                              <Download className="mr-2 h-4 w-4" />
                              Install AMD GPU Tools
                            </>
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Power Consumption */}
      {hardwareDataSWR?.power_meter && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Zap className="h-5 w-5 text-blue-500" />
            <h2 className="text-lg font-semibold">Power Consumption</h2>
          </div>

          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-lg border border-border/30 bg-background/60 p-4">
              <div className="space-y-1">
                <p className="text-sm font-medium">{hardwareDataSWR.power_meter.name}</p>
                {hardwareDataSWR.power_meter.adapter && (
                  <p className="text-xs text-muted-foreground">{hardwareDataSWR.power_meter.adapter}</p>
                )}
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold text-blue-500">{hardwareDataSWR.power_meter.watts.toFixed(1)} W</p>
                <p className="text-xs text-muted-foreground">Current Draw</p>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Power Supplies */}
      {hardwareDataSWR?.power_supplies && hardwareDataSWR.power_supplies.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <PowerIcon className="h-5 w-5 text-green-500" />
            <h2 className="text-lg font-semibold">Power Supplies</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareDataSWR.power_supplies.length} PSUs
            </Badge>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {hardwareDataSWR.power_supplies.map((psu, index) => (
              <div key={index} className="rounded-lg border border-border/30 bg-background/60 p-4">
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
      {hardwareDataSWR?.fans && hardwareDataSWR.fans.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <FanIcon className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">System Fans</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareDataSWR.fans.length} fans
            </Badge>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {hardwareDataSWR.fans.map((fan, index) => {
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

      {/* UPS */}
      {hardwareDataSWR?.ups && Array.isArray(hardwareDataSWR.ups) && hardwareDataSWR.ups.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Battery className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">UPS Status</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareDataSWR.ups.length} UPS
            </Badge>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {hardwareDataSWR.ups.map((ups: any, index: number) => {
              const batteryCharge =
                ups.battery_charge_raw || Number.parseFloat(ups.battery_charge?.replace("%", "") || "0")
              const loadPercent = ups.load_percent_raw || Number.parseFloat(ups.load_percent?.replace("%", "") || "0")

              // Determine status badge color
              const getStatusColor = (status: string) => {
                if (!status) return "bg-gray-500/10 text-gray-500 border-gray-500/20"
                const statusUpper = status.toUpperCase()
                if (statusUpper.includes("OL")) return "bg-green-500/10 text-green-500 border-green-500/20"
                if (statusUpper.includes("OB")) return "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                if (statusUpper.includes("LB")) return "bg-red-500/10 text-red-500 border-red-500/20"
                return "bg-blue-500/10 text-blue-500 border-blue-500/20"
              }

              return (
                <div
                  key={index}
                  onClick={() => setSelectedUPS(ups)}
                  className="cursor-pointer rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 p-4 transition-colors"
                >
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium block truncate">{ups.model || ups.name}</span>
                      {ups.is_remote && <span className="text-xs text-muted-foreground">Remote: {ups.host}</span>}
                    </div>
                    <Badge className={getStatusColor(ups.status)}>{ups.status || "Unknown"}</Badge>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    {ups.battery_charge && (
                      <div className="space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-muted-foreground">Battery Charge</span>
                          <span className="text-sm font-semibold text-green-500">{ups.battery_charge}</span>
                        </div>
                        <Progress value={batteryCharge} className="h-2 [&>div]:bg-blue-500" />
                      </div>
                    )}

                    {ups.load_percent && (
                      <div className="space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-muted-foreground">Load</span>
                          <span className="text-sm font-semibold text-green-500">{ups.load_percent}</span>
                        </div>
                        <Progress value={loadPercent} className="h-2 [&>div]:bg-blue-500" />
                      </div>
                    )}

                    {ups.time_left && (
                      <div>
                        <span className="text-xs text-muted-foreground">Runtime</span>
                        <div className="mt-1">
                          <Badge className="bg-green-500/10 text-green-500 border-green-500/20">{ups.time_left}</Badge>
                        </div>
                      </div>
                    )}

                    {ups.input_voltage && (
                      <div>
                        <span className="text-xs text-muted-foreground">Input Voltage</span>
                        <div className="mt-1">
                          <span className="text-sm font-medium text-green-500">{ups.input_voltage}</span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      <Dialog open={selectedUPS !== null} onOpenChange={() => setSelectedUPS(null)}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          {selectedUPS && (
            <>
              <DialogHeader className="pb-4 border-b border-border">
                <DialogTitle>{selectedUPS.model || selectedUPS.name}</DialogTitle>
                <DialogDescription>
                  UPS Detailed Information
                  {selectedUPS.is_remote && ` • Remote: ${selectedUPS.host}`}
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-6 py-4">
                {/* Status Overview */}
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                    Status Overview
                  </h3>
                  <div className="grid gap-2">
                    <div className="flex justify-between border-b border-border/50 pb-2">
                      <span className="text-sm text-muted-foreground">Status</span>
                      <Badge
                        className={
                          selectedUPS.status?.includes("OL")
                            ? "bg-green-500/10 text-green-500 border-green-500/20"
                            : selectedUPS.status?.includes("OB")
                              ? "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                              : selectedUPS.status?.includes("LB")
                                ? "bg-red-500/10 text-red-500 border-red-500/20"
                                : "bg-blue-500/10 text-blue-500 border-blue-500/20"
                        }
                      >
                        {selectedUPS.status || "Unknown"}
                      </Badge>
                    </div>
                    <div className="flex justify-between border-b border-border/50 pb-2">
                      <span className="text-sm text-muted-foreground">Connection</span>
                      <Badge variant="outline">{selectedUPS.connection_type}</Badge>
                    </div>
                    {selectedUPS.host && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Host</span>
                        <span className="text-sm font-medium">{selectedUPS.host}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Battery Information */}
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                    Battery Information
                  </h3>
                  <div className="grid gap-3">
                    {selectedUPS.battery_charge && (
                      <div className="space-y-1">
                        <div className="flex justify-between">
                          <span className="text-sm text-muted-foreground">Charge Level</span>
                          <span className="text-sm font-semibold text-green-500">{selectedUPS.battery_charge}</span>
                        </div>
                        <Progress
                          value={
                            selectedUPS.battery_charge_raw ||
                            Number.parseFloat(selectedUPS.battery_charge.replace("%", ""))
                          }
                          className="h-2 [&>div]:bg-blue-500"
                        />
                      </div>
                    )}
                    {selectedUPS.time_left && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Runtime Remaining</span>
                        <Badge className="bg-green-500/10 text-green-500 border-green-500/20">
                          {selectedUPS.time_left}
                        </Badge>
                      </div>
                    )}
                    {selectedUPS.battery_voltage && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Battery Voltage</span>
                        <span className="text-sm font-medium">{selectedUPS.battery_voltage}</span>
                      </div>
                    )}
                    {selectedUPS.battery_date && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Battery Date</span>
                        <span className="text-sm font-medium">{selectedUPS.battery_date}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Input/Output Information */}
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                    Power Information
                  </h3>
                  <div className="grid gap-2 md:grid-cols-2">
                    {selectedUPS.input_voltage && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Input Voltage</span>
                        <span className="text-sm font-medium text-green-500">{selectedUPS.input_voltage}</span>
                      </div>
                    )}
                    {selectedUPS.output_voltage && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Output Voltage</span>
                        <span className="text-sm font-medium text-green-500">{selectedUPS.output_voltage}</span>
                      </div>
                    )}
                    {selectedUPS.input_frequency && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Input Frequency</span>
                        <span className="text-sm font-medium">{selectedUPS.input_frequency}</span>
                      </div>
                    )}
                    {selectedUPS.output_frequency && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Output Frequency</span>
                        <span className="text-sm font-medium">{selectedUPS.output_frequency}</span>
                      </div>
                    )}
                    {selectedUPS.load_percent && (
                      <div className="md:col-span-2 space-y-1">
                        <div className="flex justify-between">
                          <span className="text-sm text-muted-foreground">Load</span>
                          <span className="text-sm font-semibold text-green-500">{selectedUPS.load_percent}</span>
                        </div>
                        <Progress
                          value={
                            selectedUPS.load_percent_raw || Number.parseFloat(selectedUPS.load_percent.replace("%", ""))
                          }
                          className="h-2 [&>div]:bg-blue-500"
                        />
                      </div>
                    )}
                    {selectedUPS.real_power && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Real Power</span>
                        <span className="text-sm font-medium text-blue-500">{selectedUPS.real_power}</span>
                      </div>
                    )}
                    {selectedUPS.apparent_power && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm text-muted-foreground">Apparent Power</span>
                        <span className="text-sm font-medium text-blue-500">{selectedUPS.apparent_power}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Device Information */}
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                    Device Information
                  </h3>
                  <div className="grid gap-2">
                    {selectedUPS.manufacturer && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm font-medium text-muted-foreground">Manufacturer</span>
                        <span className="text-sm font-medium">{selectedUPS.manufacturer}</span>
                      </div>
                    )}
                    {selectedUPS.model && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm font-medium text-muted-foreground">Model</span>
                        <span className="text-sm font-medium">{selectedUPS.model}</span>
                      </div>
                    )}
                    {selectedUPS.serial && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm font-medium text-muted-foreground">Serial Number</span>
                        <span className="font-mono text-sm">{selectedUPS.serial}</span>
                      </div>
                    )}
                    {selectedUPS.firmware && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm font-medium text-muted-foreground">Firmware</span>
                        <span className="text-sm font-medium">{selectedUPS.firmware}</span>
                      </div>
                    )}
                    {selectedUPS.driver && (
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm font-medium text-muted-foreground">Driver</span>
                        <span className="font-mono text-sm text-green-500">{selectedUPS.driver}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* PCI Devices - Changed to modal */}
      {hardwareDataSWR?.pci_devices && hardwareDataSWR.pci_devices.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <CpuIcon className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">PCI Devices</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareDataSWR.pci_devices.length} devices
            </Badge>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hardwareDataSWR.pci_devices.map((device, index) => (
              <div
                key={index}
                onClick={() => setSelectedPCIDevice(device)}
                className="cursor-pointer rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 p-3 transition-colors"
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

      {/* Network Summary - Clickable */}
      {hardwareDataSWR?.pci_devices &&
        hardwareDataSWR.pci_devices.filter((d) => d.type.toLowerCase().includes("network")).length > 0 && (
          <Card className="border-border/50 bg-card/50 p-6">
            <div className="mb-4 flex items-center gap-2">
              <Network className="h-5 w-5 text-primary" />
              <h2 className="text-lg font-semibold">Network Summary</h2>
              <Badge variant="outline" className="ml-auto">
                {hardwareDataSWR.pci_devices.filter((d) => d.type.toLowerCase().includes("network")).length} interfaces
              </Badge>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {hardwareDataSWR.pci_devices
                .filter((d) => d.type.toLowerCase().includes("network"))
                .map((device, index) => (
                  <div
                    key={index}
                    onClick={() => setSelectedNetwork(device)}
                    className="cursor-pointer rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 p-3 transition-colors"
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span className="text-sm font-medium line-clamp-2 break-words flex-1">{device.device}</span>
                      <Badge
                        className={
                          device.network_subtype === "Wireless"
                            ? "bg-purple-500/10 text-purple-500 border-purple-500/20 px-2.5 py-0.5 shrink-0"
                            : "bg-blue-500/10 text-blue-500 border-blue-500/20 px-2.5 py-0.5 shrink-0"
                        }
                      >
                        {device.network_subtype || "Ethernet"}
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
      {hardwareDataSWR?.storage_devices && hardwareDataSWR.storage_devices.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <HardDrive className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Storage Summary</h2>
            <Badge variant="outline" className="ml-auto">
              {
                hardwareDataSWR.storage_devices.filter(
                  (device) =>
                    device.type === "disk" && !device.name.startsWith("zd") && !device.name.startsWith("loop"),
                ).length
              }{" "}
              devices
            </Badge>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hardwareDataSWR.storage_devices
              .filter(
                (device) => device.type === "disk" && !device.name.startsWith("zd") && !device.name.startsWith("loop"),
              )
              .map((device, index) => {
                const getDiskTypeBadge = (diskName: string, rotationRate: number | string | undefined) => {
                  let diskType = "HDD"

                  // Check if it's NVMe
                  if (diskName.startsWith("nvme")) {
                    diskType = "NVMe"
                  }
                  // Check rotation rate for SSD vs HDD
                  else if (rotationRate !== undefined && rotationRate !== null) {
                    // Handle both number and string formats
                    const rateNum = typeof rotationRate === "string" ? Number.parseInt(rotationRate) : rotationRate
                    if (rateNum === 0 || isNaN(rateNum)) {
                      diskType = "SSD"
                    }
                  }
                  // If rotation_rate is "Solid State Device" string
                  else if (typeof rotationRate === "string" && rotationRate.includes("Solid State")) {
                    diskType = "SSD"
                  }

                  const badgeStyles: Record<string, { className: string; label: string }> = {
                    NVMe: {
                      className: "bg-purple-500/10 text-purple-500 border-purple-500/20",
                      label: "NVMe SSD",
                    },
                    SSD: {
                      className: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
                      label: "SSD",
                    },
                    HDD: {
                      className: "bg-blue-500/10 text-blue-500 border-blue-500/20",
                      label: "HDD",
                    },
                  }
                  return badgeStyles[diskType]
                }

                const diskBadge = getDiskTypeBadge(device.name, device.rotation_rate)

                const getLinkSpeedInfo = (device: StorageDevice) => {
                  // NVMe PCIe information
                  if (device.name.startsWith("nvme") && (device.pcie_gen || device.pcie_width)) {
                    const current = `${device.pcie_gen || ""} ${device.pcie_width || ""}`.trim()
                    const max =
                      device.pcie_max_gen && device.pcie_max_width
                        ? `${device.pcie_max_gen} ${device.pcie_max_width}`.trim()
                        : null

                    const isLowerSpeed = max && current !== max

                    return {
                      text: current || null,
                      maxText: max,
                      isWarning: isLowerSpeed,
                      color: isLowerSpeed ? "text-orange-500" : "text-blue-500",
                    }
                  }

                  // SATA information
                  if (device.sata_version) {
                    return {
                      text: device.sata_version,
                      maxText: null,
                      isWarning: false,
                      color: "text-blue-500",
                    }
                  }

                  // SAS information
                  if (device.sas_version || device.sas_speed) {
                    const text = [device.sas_version, device.sas_speed].filter(Boolean).join(" ")
                    return {
                      text: text || null,
                      maxText: null,
                      isWarning: false,
                      color: "text-blue-500",
                    }
                  }

                  // Generic link speed
                  if (device.link_speed) {
                    return {
                      text: device.link_speed,
                      maxText: null,
                      isWarning: false,
                      color: "text-blue-500",
                    }
                  }

                  return null
                }

                const linkSpeed = getLinkSpeedInfo(device)

                return (
                  <div
                    key={index}
                    onClick={() => setSelectedDisk(device)}
                    className="cursor-pointer rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 p-3 transition-colors"
                  >
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-sm font-medium truncate flex-1">{device.name}</span>
                      <Badge className={`${diskBadge.className} px-2.5 py-0.5 shrink-0`}>{diskBadge.label}</Badge>
                    </div>
                    {device.size && <p className="text-sm font-medium">{formatMemory(parseLsblkSize(device.size))}</p>}
                    {device.model && (
                      <p className="text-xs text-muted-foreground line-clamp-2 break-words">{device.model}</p>
                    )}
                    {linkSpeed && (
                      <div className="mt-1 flex items-center gap-1">
                        <span className={`text-xs font-medium ${linkSpeed.color}`}>{linkSpeed.text}</span>
                        {linkSpeed.maxText && linkSpeed.isWarning && (
                          <span className="text-xs font-medium text-blue-500">(max: {linkSpeed.maxText})</span>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
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

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Type</span>
                {(() => {
                  const getDiskTypeBadge = (diskName: string, rotationRate: number | string | undefined) => {
                    let diskType = "HDD"

                    if (diskName.startsWith("nvme")) {
                      diskType = "NVMe"
                    } else if (rotationRate !== undefined && rotationRate !== null) {
                      const rateNum = typeof rotationRate === "string" ? Number.parseInt(rotationRate) : rotationRate
                      if (rateNum === 0 || isNaN(rateNum)) {
                        diskType = "SSD"
                      }
                    } else if (typeof rotationRate === "string" && rotationRate.includes("Solid State")) {
                      diskType = "SSD"
                    }

                    const badgeStyles: Record<string, { className: string; label: string }> = {
                      NVMe: {
                        className: "bg-purple-500/10 text-purple-500 border-purple-500/20",
                        label: "NVMe SSD",
                      },
                      SSD: {
                        className: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
                        label: "SSD",
                      },
                      HDD: {
                        className: "bg-blue-500/10 text-blue-500 border-blue-500/20",
                        label: "HDD",
                      },
                    }
                    return badgeStyles[diskType]
                  }

                  const diskBadge = getDiskTypeBadge(selectedDisk.name, selectedDisk.rotation_rate)
                  return <Badge className={diskBadge.className}>{diskBadge.label}</Badge>
                })()}
              </div>

              {selectedDisk.size && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Capacity</span>
                  <span className="text-sm font-medium">{formatMemory(parseLsblkSize(selectedDisk.size))}</span>
                </div>
              )}

              <div className="pt-2">
                <h3 className="text-sm font-semibold text-muted-foreground mb-2 uppercase tracking-wide">
                  Interface Information
                </h3>
              </div>

              {/* NVMe PCIe Information */}
              {selectedDisk.name.startsWith("nvme") && (
                <>
                  {selectedDisk.pcie_gen || selectedDisk.pcie_width ? (
                    <>
                      <div className="flex justify-between border-b border-border/50 pb-2">
                        <span className="text-sm font-medium text-muted-foreground">Current Link Speed</span>
                        <span
                          className={`text-sm font-medium ${
                            selectedDisk.pcie_max_gen &&
                            selectedDisk.pcie_max_width &&
                            `${selectedDisk.pcie_gen} ${selectedDisk.pcie_width}` !==
                              `${selectedDisk.pcie_max_gen} ${selectedDisk.pcie_max_width}`
                              ? "text-orange-500"
                              : "text-blue-500"
                          }`}
                        >
                          {selectedDisk.pcie_gen || "PCIe"} {selectedDisk.pcie_width || ""}
                        </span>
                      </div>
                      {selectedDisk.pcie_max_gen && selectedDisk.pcie_max_width && (
                        <div className="flex justify-between border-b border-border/50 pb-2">
                          <span className="text-sm font-medium text-muted-foreground">Maximum Link Speed</span>
                          <span className="text-sm font-medium text-blue-500">
                            {selectedDisk.pcie_max_gen} {selectedDisk.pcie_max_width}
                          </span>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="flex justify-between border-b border-border/50 pb-2">
                      <span className="text-sm font-medium text-muted-foreground">PCIe Link Speed</span>
                      <span className="text-sm text-muted-foreground italic">Detecting...</span>
                    </div>
                  )}
                </>
              )}

              {/* SATA Information */}
              {!selectedDisk.name.startsWith("nvme") && selectedDisk.sata_version && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">SATA Version</span>
                  <span className="text-sm font-medium text-blue-500">{selectedDisk.sata_version}</span>
                </div>
              )}

              {/* SAS Information */}
              {!selectedDisk.name.startsWith("nvme") && selectedDisk.sas_version && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">SAS Version</span>
                  <span className="text-sm font-medium text-blue-500">{selectedDisk.sas_version}</span>
                </div>
              )}
              {!selectedDisk.name.startsWith("nvme") && selectedDisk.sas_speed && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">SAS Speed</span>
                  <span className="text-sm font-medium text-blue-500">{selectedDisk.sas_speed}</span>
                </div>
              )}

              {/* Generic Link Speed - only show if no specific interface info */}
              {!selectedDisk.name.startsWith("nvme") &&
                selectedDisk.link_speed &&
                !selectedDisk.pcie_gen &&
                !selectedDisk.sata_version &&
                !selectedDisk.sas_version && (
                  <div className="flex justify-between border-b border-border/50 pb-2">
                    <span className="text-sm font-medium text-muted-foreground">Link Speed</span>
                    <span className="text-sm font-medium text-blue-500">{selectedDisk.link_speed}</span>
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

              {selectedDisk.rotation_rate !== undefined && selectedDisk.rotation_rate !== null && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Rotation Rate</span>
                  <div className="text-sm">
                    {typeof selectedDisk.rotation_rate === "number" && selectedDisk.rotation_rate === -1
                      ? "N/A"
                      : typeof selectedDisk.rotation_rate === "number" && selectedDisk.rotation_rate > 0
                        ? `${selectedDisk.rotation_rate} rpm`
                        : typeof selectedDisk.rotation_rate === "string"
                          ? selectedDisk.rotation_rate
                          : "Solid State Device"}
                  </div>
                </div>
              )}

              {selectedDisk.form_factor && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Form Factor</span>
                  <span className="text-sm">{selectedDisk.form_factor}</span>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* NVIDIA Installation Monitor */}
      {/* <HybridScriptMonitor
        sessionId={nvidiaSessionId}
        title="NVIDIA Driver Installation"
        description="Installing NVIDIA proprietary drivers for GPU monitoring..."
        onClose={() => {
          setNvidiaSessionId(null)
          mutateHardware()
        }}
        onComplete={(success) => {
          console.log("[v0] NVIDIA installation completed:", success ? "success" : "failed")
          if (success) {
            mutateHardware()
          }
        }}
      /> */}
      <ScriptTerminalModal
        open={showNvidiaInstaller}
        onClose={() => {
          setShowNvidiaInstaller(false)
          mutateHardware()
        }}
        scriptPath="/usr/local/share/proxmenux/scripts/gpu_tpu/nvidia_installer.sh"
        scriptName="nvidia_installer"
        params={{
          EXECUTION_MODE: "web",
        }}
        title="NVIDIA Driver Installation"
        description="Installing NVIDIA proprietary drivers for GPU monitoring..."
      />
      <ScriptTerminalModal
        open={showAmdInstaller}
        onClose={() => {
          setShowAmdInstaller(false)
          mutateHardware()
        }}
        scriptPath="/usr/local/share/proxmenux/scripts/gpu_tpu/amd_gpu_tools.sh"
        scriptName="amd_gpu_tools"
        params={{
          EXECUTION_MODE: "web",
        }}
        title="AMD GPU Tools Installation"
        description="Installing amdgpu_top for AMD GPU monitoring..."
      />
    </div>
  )
}
