"use client"

import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Cpu, HardDrive, Thermometer, Zap, Loader2, CpuIcon, Cpu as Gpu, Network, MemoryStick, PowerIcon, FanIcon, Battery, Usb, BrainCircuit, AlertCircle } from "lucide-react"
import { Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import useSWR from "swr"
import { useState, useEffect } from "react"
import {
  type HardwareData,
  type GPU,
  type PCIDevice,
  type StorageDevice,
  type CoralTPU,
  type UsbDevice,
  fetcher as swrFetcher,
} from "../types/hardware"
import { fetchApi } from "@/lib/api-config"
import { ScriptTerminalModal } from "./script-terminal-modal"
import { GpuSwitchModeIndicator } from "./gpu-switch-mode-indicator"
import { Settings2, CheckCircle2 } from "lucide-react"

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

  // UPS / battery — amber: warm orange-yellow, distinct from the orange used
  // for Storage and avoids the "warning" connotation of pure yellow.
  if (lowerType === "ups" || lowerType.includes("battery")) {
    return "bg-amber-500/10 text-amber-500 border-amber-500/20"
  }

  // Storage family — orange (Mass Storage USB class + PCI storage controllers)
  if (lowerType.includes("storage") || lowerType.includes("sata") || lowerType.includes("raid")) {
    return "bg-orange-500/10 text-orange-500 border-orange-500/20"
  }

  // Printer — rose, unmistakable
  if (lowerType.includes("printer")) {
    return "bg-rose-500/10 text-rose-500 border-rose-500/20"
  }

  // Audio family — teal (Audio, Audio/Video); placed before video so that
  // combined "Audio/Video" class labels read as audio-family.
  if (lowerType.includes("audio")) {
    return "bg-teal-500/10 text-teal-500 border-teal-500/20"
  }

  // Graphics / Video / Imaging — green (cameras, webcams, displays, GPUs).
  if (
    lowerType.includes("graphics") ||
    lowerType.includes("vga") ||
    lowerType.includes("display") ||
    lowerType.includes("video") ||
    lowerType.includes("imaging")
  ) {
    return "bg-green-500/10 text-green-500 border-green-500/20"
  }

  // Network family — blue (Ethernet / Wi-Fi PCI controllers, USB Communications,
  // CDC Data, Wireless Controllers like Bluetooth dongles).
  if (
    lowerType.includes("network") ||
    lowerType.includes("ethernet") ||
    lowerType.includes("communications") ||
    lowerType.includes("wireless") ||
    lowerType === "cdc data"
  ) {
    return "bg-blue-500/10 text-blue-500 border-blue-500/20"
  }

  // HID — purple: keyboards, mice, game controllers.
  if (lowerType === "hid") {
    return "bg-purple-500/10 text-purple-500 border-purple-500/20"
  }

  // USB host controllers (PCI-level) keep the existing purple identity.
  if (lowerType.includes("usb")) {
    return "bg-purple-500/10 text-purple-500 border-purple-500/20"
  }

  // Smart Card, Billboard, Diagnostic, Hub, Physical, Content Security,
  // Personal Healthcare, Miscellaneous, Application/Vendor Specific, unknown.
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
  // Static data - loaded once on mount. Static fields (CPU, motherboard, memory
  // modules, PCI, disks, GPU list) don't change at runtime, so no auto-refresh.
  // `mutateStatic` is triggered explicitly after GPU switch-mode changes.
  const {
    data: staticHardwareData,
    error: staticError,
    isLoading: staticLoading,
    mutate: mutateStatic,
  } = useSWR<HardwareData>("/api/hardware", swrFetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    refreshInterval: 0,
  })

  // Live data - only temperatures, fans, power, UPS. Polled every 5s.
  // Backend /api/hardware/live uses cached ipmitool output (10s) so this is cheap.
  const {
    data: dynamicHardwareData,
    error: dynamicError,
  } = useSWR<HardwareData>("/api/hardware/live", swrFetcher, {
    refreshInterval: 5000,
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    dedupingInterval: 2000,
  })

  // Merge: static fields from initial load, live fields from the 5s poll.
  // coral_tpus and usb_devices live in the dynamic payload so that the
  // "Install Drivers" button disappears immediately after install_coral.sh
  // finishes, without requiring a page reload.
  const hardwareData = staticHardwareData
    ? {
        ...staticHardwareData,
        temperatures: dynamicHardwareData?.temperatures ?? staticHardwareData.temperatures,
        fans: dynamicHardwareData?.fans ?? staticHardwareData.fans,
        power_meter: dynamicHardwareData?.power_meter ?? staticHardwareData.power_meter,
        power_supplies: dynamicHardwareData?.power_supplies ?? staticHardwareData.power_supplies,
        ups: dynamicHardwareData?.ups ?? staticHardwareData.ups,
        coral_tpus: dynamicHardwareData?.coral_tpus ?? staticHardwareData.coral_tpus,
        usb_devices: dynamicHardwareData?.usb_devices ?? staticHardwareData.usb_devices,
      }
    : undefined

  const error = staticError || dynamicError
  const isLoading = staticLoading

  useEffect(() => {
    if (hardwareData?.storage_devices) {
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

  const [managedInstalls, setManagedInstalls] = useState<Array<{
    id: string
    type: string
    name?: string
    current_version?: string | null
    menu_label?: string | null
    update_check?: {
      available: boolean
      latest?: string | null
      last_check?: string | null
      error?: string | null
    } | null
  }>>([])
  useEffect(() => {
    let cancelled = false
    fetchApi<{ success: boolean; items: any[] }>("/api/managed-installs")
      .then((res) => {
        if (cancelled) return
        if (res?.success && Array.isArray(res.items)) {
          setManagedInstalls(res.items)
        }
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])
  const nvidiaInstall = managedInstalls.find((it) => it.type === "nvidia_xfree86")

  const formatLastChecked = (iso?: string | null): string => {
    if (!iso) return "never"
    const d = new Date(iso)
    if (isNaN(d.getTime())) return "unknown"
    const now = Date.now()
    const ageMs = now - d.getTime()
    const sameDay = new Date(now).toDateString() === d.toDateString()
    const yesterday = new Date(now - 86_400_000).toDateString() === d.toDateString()
    const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    if (sameDay) return time
    if (yesterday) return `yesterday ${time}`
    if (ageMs < 7 * 86_400_000) {
      return d.toLocaleDateString([], { weekday: "short" }) + " " + time
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" })
  }

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
  const [showIntelInstaller, setShowIntelInstaller] = useState(false)
  const [showCoralInstaller, setShowCoralInstaller] = useState(false)
  const [selectedCoral, setSelectedCoral] = useState<CoralTPU | null>(null)
  const [selectedUsbDevice, setSelectedUsbDevice] = useState<UsbDevice | null>(null)
  
  // GPU Switch Mode states
  const [editingSwitchModeGpu, setEditingSwitchModeGpu] = useState<string | null>(null) // GPU slot being edited
  const [pendingSwitchModes, setPendingSwitchModes] = useState<Record<string, "lxc" | "vm">>({})
  const [showSwitchModeModal, setShowSwitchModeModal] = useState(false)
  const [switchModeParams, setSwitchModeParams] = useState<{ gpuSlot: string; targetMode: "lxc" | "vm" } | null>(null)

  // Determine GPU mode based on driver (vfio-pci = VM, native driver = LXC).
  // SR-IOV short-circuits the driver check: if the GPU is either a VF or a
  // PF with active VFs, the slot is in a hardware-partitioned state that
  // ProxMenux does not manage from the UI, so it's surfaced as its own mode.
  const getGpuSwitchMode = (gpu: GPU): "lxc" | "vm" | "sriov" | "unknown" => {
    if (gpu.sriov_role === "vf" || gpu.sriov_role === "pf-active") return "sriov"

    const driver = gpu.pci_driver?.toLowerCase() || ""
    const kernelModule = gpu.pci_kernel_module?.toLowerCase() || ""

    // Check driver first
    if (driver === "vfio-pci") return "vm"
    if (driver === "nvidia" || driver === "amdgpu" || driver === "radeon" || driver === "i915" || driver === "xe" || driver === "nouveau" || driver === "mgag200") return "lxc"
    if (driver && driver !== "none" && driver !== "") return "lxc"
    
    // Fallback to kernel module if no driver
    if (kernelModule.includes("vfio")) return "vm"
    if (kernelModule.includes("nvidia") || kernelModule.includes("amdgpu") || kernelModule.includes("radeon") || kernelModule.includes("i915") || kernelModule.includes("xe") || kernelModule.includes("nouveau") || kernelModule.includes("mgag200")) return "lxc"
    if (kernelModule && kernelModule !== "none" && kernelModule !== "") return "lxc"
    
    return "unknown"
  }

  const handleSwitchModeEdit = (gpuSlot: string, e: React.MouseEvent) => {
    e.stopPropagation() // Prevent opening GPU modal
    setEditingSwitchModeGpu(gpuSlot)
  }

  const handleSwitchModeToggle = (gpu: GPU, e?: React.MouseEvent) => {
    const slot = gpu.slot
    const currentMode = getGpuSwitchMode(gpu)
    const pendingMode = pendingSwitchModes[slot]
    
    // Toggle between modes
    if (pendingMode) {
      // Already has pending - toggle it
      const newMode = pendingMode === "lxc" ? "vm" : "lxc"
      if (newMode === currentMode) {
        // Back to original - remove pending
        const newPending = { ...pendingSwitchModes }
        delete newPending[slot]
        setPendingSwitchModes(newPending)
      } else {
        setPendingSwitchModes({ ...pendingSwitchModes, [slot]: newMode })
      }
    } else {
      // No pending - set opposite of current
      const newMode = currentMode === "lxc" ? "vm" : "lxc"
      setPendingSwitchModes({ ...pendingSwitchModes, [slot]: newMode })
    }
  }

  const handleSwitchModeSave = (gpuSlot: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const pendingMode = pendingSwitchModes[gpuSlot]
    const gpu = hardwareData?.gpus?.find(g => g.slot === gpuSlot)
    const currentMode = gpu ? getGpuSwitchMode(gpu) : "unknown"
    
    if (pendingMode && pendingMode !== currentMode && gpu) {
      // Mode has changed - save params and launch the script
      setSwitchModeParams({
        gpuSlot: gpu.slot,
        targetMode: pendingMode
      })
      setShowSwitchModeModal(true)
    }
    setEditingSwitchModeGpu(null)
  }

  const handleSwitchModeCancel = (gpuSlot: string, e: React.MouseEvent) => {
    e.stopPropagation()
    // Remove pending change for this GPU
    const newPending = { ...pendingSwitchModes }
    delete newPending[gpuSlot]
    setPendingSwitchModes(newPending)
    setEditingSwitchModeGpu(null)
  }

  const handleSwitchModeModalClose = () => {
    setShowSwitchModeModal(false)
    // Clear params and pending changes after script runs
    setSwitchModeParams(null)
    setPendingSwitchModes({})
    // Refresh hardware data
    mutateStatic()
  }

  const handleInstallNvidiaDriver = () => {
    setShowNvidiaInstaller(true)
  }

  const handleInstallAmdTools = () => {
    setShowAmdInstaller(true)
  }

  const handleInstallIntelTools = () => {
    setShowIntelInstaller(true)
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

    // Esto permite mostrar datos incluso cuando la GPU está inactiva (valores en 0 o null)
    return realtimeGPUData.has_monitoring_tool === true
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <div className="relative">
          <div className="h-12 w-12 rounded-full border-2 border-muted"></div>
          <div className="absolute inset-0 h-12 w-12 rounded-full border-2 border-transparent border-t-primary animate-spin"></div>
        </div>
        <div className="text-sm font-medium text-foreground">Loading hardware data...</div>
        <p className="text-xs text-muted-foreground">Detecting CPU, GPU, storage and PCI devices</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
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
                  {(module.configured_speed || module.max_speed) && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Speed</span>
                      <span className="font-medium">
                        {module.configured_speed && module.max_speed && module.configured_speed !== module.max_speed ? (
                          <span className="flex items-center gap-1.5">
                            <span className={module.configured_speed.replace(/[^0-9]/g, '') < module.max_speed.replace(/[^0-9]/g, '') ? "text-orange-500" : "text-blue-500"}>
                              {module.configured_speed}
                            </span>
                            <span className="text-xs text-muted-foreground">(max: {module.max_speed})</span>
                          </span>
                        ) : (
                          <span>{module.configured_speed || module.max_speed}</span>
                        )}
                      </span>
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

          <div className="grid gap-6 md:grid-cols-2">
            {/* CPU Sensors */}
            {groupAndSortTemperatures(hardwareData.temperatures).CPU.length > 0 && (
              <div className="md:col-span-2">
                <div className="mb-3 flex items-center gap-2">
                  <CpuIcon className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">CPU</h3>
                  <Badge variant="outline" className="text-xs">
                    {groupAndSortTemperatures(hardwareData.temperatures).CPU.length}
                  </Badge>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  {groupAndSortTemperatures(hardwareData.temperatures).CPU.map((temp, index) => {
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
            {groupAndSortTemperatures(hardwareData.temperatures).GPU.length > 0 && (
              <div
                className={groupAndSortTemperatures(hardwareData.temperatures).GPU.length > 1 ? "md:col-span-2" : ""}
              >
                <div className="mb-3 flex items-center gap-2">
                  <Gpu className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">GPU</h3>
                  <Badge variant="outline" className="text-xs">
                    {groupAndSortTemperatures(hardwareData.temperatures).GPU.length}
                  </Badge>
                </div>
                <div
                  className={`grid gap-4 ${groupAndSortTemperatures(hardwareData.temperatures).GPU.length > 1 ? "md:grid-cols-2" : ""}`}
                >
                  {groupAndSortTemperatures(hardwareData.temperatures).GPU.map((temp, index) => {
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
            {groupAndSortTemperatures(hardwareData.temperatures).NVME.length > 0 && (
              <div
                className={
                  groupAndSortTemperatures(hardwareData.temperatures).NVME.length > 1 ? "md:col-span-2" : ""
                }
              >
                <div className="mb-3 flex items-center gap-2">
                  <HardDrive className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">NVME</h3>
                  <Badge variant="outline" className="text-xs">
                    {groupAndSortTemperatures(hardwareData.temperatures).NVME.length}
                  </Badge>
                </div>
                <div
                  className={`grid gap-4 ${groupAndSortTemperatures(hardwareData.temperatures).NVME.length > 1 ? "md:grid-cols-2" : ""}`}
                >
                  {groupAndSortTemperatures(hardwareData.temperatures).NVME.map((temp, index) => {
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
            {groupAndSortTemperatures(hardwareData.temperatures).PCI.length > 0 && (
              <div
                className={groupAndSortTemperatures(hardwareData.temperatures).PCI.length > 1 ? "md:col-span-2" : ""}
              >
                <div className="mb-3 flex items-center gap-2">
                  <CpuIcon className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">PCI</h3>
                  <Badge variant="outline" className="text-xs">
                    {groupAndSortTemperatures(hardwareData.temperatures).PCI.length}
                  </Badge>
                </div>
                <div
                  className={`grid gap-4 ${groupAndSortTemperatures(hardwareData.temperatures).PCI.length > 1 ? "md:grid-cols-2" : ""}`}
                >
                  {groupAndSortTemperatures(hardwareData.temperatures).PCI.map((temp, index) => {
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
            {groupAndSortTemperatures(hardwareData.temperatures).OTHER.length > 0 && (
              <div
                className={
                  groupAndSortTemperatures(hardwareData.temperatures).OTHER.length > 1 ? "md:col-span-2" : ""
                }
              >
                <div className="mb-3 flex items-center gap-2">
                  <Thermometer className="h-4 w-4 text-muted-foreground" />
                  <h3 className="text-sm font-semibold">OTHER</h3>
                  <Badge variant="outline" className="text-xs">
                    {groupAndSortTemperatures(hardwareData.temperatures).OTHER.length}
                  </Badge>
                </div>
                <div
                  className={`grid gap-4 ${groupAndSortTemperatures(hardwareData.temperatures).OTHER.length > 1 ? "md:grid-cols-2" : ""}`}
                >
                  {groupAndSortTemperatures(hardwareData.temperatures).OTHER.map((temp, index) => {
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
  onClick={() => {
    // Don't open modal if we're editing this GPU's switch mode
    if (editingSwitchModeGpu !== fullSlot) {
      handleGPUClick(gpu)
    }
  }}
  className={`rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card p-4 transition-colors ${
    editingSwitchModeGpu === fullSlot 
      ? "cursor-default" 
      : "cursor-pointer sm:hover:bg-white/5"
  }`}
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

                  {gpu.vendor?.toLowerCase().includes("nvidia") &&
                    nvidiaInstall?.current_version &&
                    nvidiaInstall.update_check?.last_check && (
                      <div className="pt-2 mt-2 border-t border-border">
                        {nvidiaInstall.update_check.available ? (
                          <>
                            <div className="text-xs text-muted-foreground">
                              Last checked: {formatLastChecked(nvidiaInstall.update_check.last_check)} ·{" "}
                              <span className="text-purple-400 font-medium">
                                NVIDIA driver v{nvidiaInstall.update_check.latest} available
                              </span>
                            </div>
                            {nvidiaInstall.menu_label && (
                              <div className="text-[11px] text-muted-foreground mt-1">
                                Reinstall via ProxMenux post-install: {nvidiaInstall.menu_label}
                              </div>
                            )}
                          </>
                        ) : (
                          <div className="text-xs text-muted-foreground">
                            Last checked: {formatLastChecked(nvidiaInstall.update_check.last_check)}
                            {` · NVIDIA driver v${nvidiaInstall.current_version}`}
                            {" · "}
                            <span className="text-green-500/80">No updates available</span>
                          </div>
                        )}
                      </div>
                    )}

{/* GPU Switch Mode Indicator */}
  {getGpuSwitchMode(gpu) !== "unknown" && (
  <div className="mt-3 pt-3 border-t border-border/30">
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                          Switch Mode
                        </span>
                        <div className="flex items-center gap-2">
                          {getGpuSwitchMode(gpu) === "sriov" ? (
                            // SR-IOV: edit controls hidden — the state is
                            // hardware-managed and not togglable from here.
                            null
                          ) : editingSwitchModeGpu === fullSlot ? (
                            <>
                              <button
                                className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors text-muted-foreground"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleSwitchModeCancel(fullSlot, e)
                                }}
                              >
                                Cancel
                              </button>
                              <button
                                className="h-7 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors flex items-center gap-1.5"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleSwitchModeSave(fullSlot, e)
                                }}
                              >
                                <CheckCircle2 className="h-3 w-3" />
                                Save
                              </button>
                            </>
                          ) : (
                            <button
                              className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors flex items-center gap-1.5"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleSwitchModeEdit(fullSlot, e)
                              }}
                            >
                              <Settings2 className="h-3 w-3" />
                              Edit
                            </button>
                          )}
                        </div>
                      </div>
                      <GpuSwitchModeIndicator
                        mode={getGpuSwitchMode(gpu)}
                        isEditing={editingSwitchModeGpu === fullSlot}
                        pendingMode={pendingSwitchModes[gpu.slot] || null}
                        onToggle={(e) => handleSwitchModeToggle(gpu, e)}
                        sriovInfo={
                          gpu.sriov_role === "vf" || gpu.sriov_role === "pf-active"
                            ? {
                                role: gpu.sriov_role,
                                physfn: gpu.sriov_physfn,
                                vfCount: gpu.sriov_vf_count,
                                totalvfs: gpu.sriov_totalvfs,
                              }
                            : undefined
                        }
                      />
                    </div>
                  )}
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
                ) : selectedGPU.sriov_role === "vf" ? (
                  // SR-IOV Virtual Function: per-VF telemetry is not exposed
                  // by the kernel, so we skip the metrics panel and show
                  // identity + consumer + a link back to the parent PF.
                  <div className="space-y-4">
                    <div className="rounded-lg bg-teal-500/10 p-4 border border-teal-500/20">
                      <div className="flex gap-3">
                        <div className="flex-shrink-0">
                          <svg className="h-5 w-5 text-teal-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                          </svg>
                        </div>
                        <div className="flex-1">
                          <h4 className="text-sm font-semibold text-teal-500 mb-1">SR-IOV Virtual Function</h4>
                          <p className="text-sm text-muted-foreground">
                            This device is a Virtual Function spawned by a Physical Function. Per-VF
                            telemetry (temperature, utilization, memory) is not exposed by the kernel —
                            open the parent PF to see aggregate GPU metrics.
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="rounded-lg border border-border/50 p-4 space-y-3">
                      <h3 className="text-sm font-semibold text-muted-foreground mb-1 uppercase tracking-wide">
                        Virtual Function Detail
                      </h3>
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-muted-foreground">Parent Physical Function</span>
                        {selectedGPU.sriov_physfn ? (
                          <button
                            className="font-mono text-sm text-teal-500 hover:underline"
                            onClick={(e) => {
                              e.stopPropagation()
                              const pf = hardwareData?.gpus?.find(
                                (g) => g.slot === selectedGPU.sriov_physfn
                              )
                              if (pf) setSelectedGPU(pf)
                            }}
                          >
                            {selectedGPU.sriov_physfn}
                          </button>
                        ) : (
                          <span className="font-mono text-sm text-muted-foreground">unknown</span>
                        )}
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-muted-foreground">Current Driver</span>
                        <span className="font-mono text-sm">
                          {selectedGPU.pci_driver || "none"}
                        </span>
                      </div>
                      <div className="flex justify-between items-start">
                        <span className="text-sm text-muted-foreground">Consumer</span>
                        <div className="text-sm text-right">
                          {realtimeGPUData?.sriov_consumer ? (
                            <span className={cn(
                              "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium",
                              realtimeGPUData.sriov_consumer.running
                                ? "bg-teal-500/10 text-teal-500"
                                : "bg-muted text-muted-foreground"
                            )}>
                              <span className="h-1.5 w-1.5 rounded-full bg-current" />
                              {realtimeGPUData.sriov_consumer.type.toUpperCase()} {realtimeGPUData.sriov_consumer.id}
                              {realtimeGPUData.sriov_consumer.name && ` · ${realtimeGPUData.sriov_consumer.name}`}
                              {` · ${realtimeGPUData.sriov_consumer.running ? "running" : "stopped"}`}
                            </span>
                          ) : (
                            <span className="text-muted-foreground italic">unused</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ) : realtimeGPUData?.has_monitoring_tool === true ? (
                  <>
                    {selectedGPU.sriov_role === "pf-active" && (
                      // SR-IOV Physical Function: metrics below are the
                      // aggregate of the whole GPU (PF + all active VFs).
                      // Flag it explicitly so the reader interprets numbers
                      // correctly.
                      <div className="rounded-lg bg-teal-500/10 p-3 border border-teal-500/20">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-teal-500/15 text-teal-500 text-xs font-semibold">
                            <span className="h-1.5 w-1.5 rounded-full bg-teal-500" />
                            SR-IOV active
                          </span>
                          <span className="text-sm text-muted-foreground">
                            Metrics below reflect the Physical Function (aggregate across
                            {" "}
                            <span className="font-semibold text-foreground">
                              {realtimeGPUData?.sriov_vf_count ?? selectedGPU.sriov_vf_count ?? "N"}
                            </span>
                            {" "}VFs).
                          </span>
                        </div>
                      </div>
                    )}
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
                                        <Progress value={utilizationNum} className="h-2 [&>div]:bg-blue-500" />
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
                    {selectedGPU.sriov_role === "pf-active" &&
                      Array.isArray(realtimeGPUData?.sriov_vfs) &&
                      realtimeGPUData.sriov_vfs.length > 0 && (
                        // Per-VF table: one row per virtfn* under the PF.
                        // Driver is color-coded (teal native / purple vfio-pci
                        // / muted fallback) and consumer pills go green when
                        // the guest is currently running, muted otherwise.
                        <div>
                          <h3 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                            Virtual Functions
                          </h3>
                          <div className="rounded-lg border border-border/50 divide-y divide-border/30 overflow-hidden">
                            {realtimeGPUData.sriov_vfs.map((vf: any) => (
                              <div
                                key={vf.bdf}
                                className="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-muted/30 transition-colors"
                              >
                                <span className="font-mono text-xs text-foreground">{vf.bdf}</span>
                                <div className="flex items-center gap-3 flex-wrap justify-end">
                                  <span
                                    className={cn(
                                      "font-mono text-[11px] px-2 py-0.5 rounded",
                                      vf.driver === "vfio-pci"
                                        ? "bg-purple-500/10 text-purple-500"
                                        : vf.driver === "i915" ||
                                            vf.driver === "xe" ||
                                            vf.driver === "amdgpu" ||
                                            vf.driver === "radeon" ||
                                            vf.driver === "nvidia"
                                          ? "bg-teal-500/10 text-teal-500"
                                          : "bg-muted text-muted-foreground"
                                    )}
                                  >
                                    {vf.driver || "unbound"}
                                  </span>
                                  {vf.consumer ? (
                                    <span
                                      className={cn(
                                        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium",
                                        vf.consumer.running
                                          ? "bg-green-500/10 text-green-500"
                                          : "bg-muted text-muted-foreground"
                                      )}
                                    >
                                      <span className="h-1.5 w-1.5 rounded-full bg-current" />
                                      {vf.consumer.type.toUpperCase()} {vf.consumer.id}
                                      {vf.consumer.name && (
                                        <span className="opacity-70">· {vf.consumer.name}</span>
                                      )}
                                    </span>
                                  ) : (
                                    <span className="text-xs text-muted-foreground italic">
                                      unused
                                    </span>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                  </>
                ) : (findPCIDeviceForGPU(selectedGPU)?.driver === 'vfio-pci' || selectedGPU.pci_driver === 'vfio-pci') ? (
                  <div className="rounded-lg bg-purple-500/10 p-4 border border-purple-500/20">
                    <div className="flex gap-3">
                      <div className="flex-shrink-0">
                        <svg className="h-5 w-5 text-purple-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                        </svg>
                      </div>
                      <div className="flex-1">
                        <h4 className="text-sm font-semibold text-purple-500 mb-1">GPU in Switch Mode VM</h4>
                        <p className="text-sm text-muted-foreground">
                          This GPU is assigned to a virtual machine via VFIO passthrough. Real-time monitoring is not available from the host because the GPU is controlled by the VM.
                        </p>
                      </div>
                    </div>
                  </div>
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
                        {selectedGPU.vendor.toLowerCase().includes("intel") && (
                          <Button
                            onClick={handleInstallIntelTools}
                            className="w-full bg-sky-600 hover:bg-sky-700 text-white"
                          >
                            <>
                              <Download className="mr-2 h-4 w-4" />
                              Install Intel GPU Tools
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

      {/* Coral TPU / AI Accelerators — only rendered when at least one device is detected.
          Unlike GPUs, Coral exposes no temperature/utilization/power counters, so the
          modal shows identity + driver state + an Install CTA when drivers are missing. */}
      {hardwareData?.coral_tpus && hardwareData.coral_tpus.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Coral TPU / AI Accelerators</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.coral_tpus.length} device{hardwareData.coral_tpus.length > 1 ? "s" : ""}
            </Badge>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hardwareData.coral_tpus.map((coral, index) => (
              <div
                key={`coral-${index}-${coral.slot || coral.bus_device}`}
                onClick={() => setSelectedCoral(coral)}
                className="cursor-pointer rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 p-4 transition-colors"
              >
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="text-sm font-medium line-clamp-2 break-words flex-1">
                    {coral.name}
                  </span>
                  <Badge
                    className={
                      coral.type === "usb"
                        ? "bg-purple-500/10 text-purple-500 border-purple-500/20 px-2.5 py-0.5 shrink-0"
                        : "bg-blue-500/10 text-blue-500 border-blue-500/20 px-2.5 py-0.5 shrink-0"
                    }
                  >
                    {coral.type === "usb" ? "USB" : "PCIe"}
                  </Badge>
                </div>

                <div className="space-y-1 text-xs text-muted-foreground">
                  {coral.form_factor && (
                    <div className="flex items-center gap-1.5">
                      <span>{coral.form_factor}</span>
                      {coral.interface_speed && <span className="text-muted-foreground/60">· {coral.interface_speed}</span>}
                    </div>
                  )}
                  <div className="font-mono">
                    {coral.type === "pcie" ? coral.slot : coral.bus_device}
                  </div>
                </div>

                <div className="mt-3 flex items-center gap-2 text-xs">
                  {coral.drivers_ready ? (
                    <>
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                      <span className="text-green-500">Drivers ready</span>
                    </>
                  ) : (
                    <>
                      <AlertCircle className="h-3.5 w-3.5 text-yellow-500" />
                      <span className="text-yellow-500">Drivers not installed</span>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Primary CTA at the section level when ANY of the detected Coral devices
              is missing drivers — avoids a per-card button repetition. */}
          {hardwareData.coral_tpus.some((c) => !c.drivers_ready) && (
            <div className="mt-4 rounded-lg border border-blue-500/20 bg-blue-500/10 p-3 flex items-center justify-between gap-3">
              <div className="flex items-start gap-3 flex-1">
                <AlertCircle className="h-4 w-4 text-blue-500 mt-0.5 shrink-0" />
                <div className="text-sm">
                  <p className="font-medium text-blue-500">Install Coral TPU drivers</p>
                  <p className="text-xs text-muted-foreground">
                    One or more detected Coral devices need drivers. A server reboot is required after installation.
                  </p>
                </div>
              </div>
              <Button
                onClick={() => setShowCoralInstaller(true)}
                className="bg-blue-600 hover:bg-blue-700 text-white shrink-0"
              >
                <Download className="mr-2 h-4 w-4" />
                Install Drivers
              </Button>
            </div>
          )}
        </Card>
      )}

      {/* Coral TPU detail modal */}
      <Dialog open={selectedCoral !== null} onOpenChange={(open) => !open && setSelectedCoral(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{selectedCoral?.name}</DialogTitle>
            <DialogDescription>Coral TPU Device Information</DialogDescription>
          </DialogHeader>

          {selectedCoral && (
            <div className="space-y-3">
              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Connection</span>
                <Badge
                  className={
                    selectedCoral.type === "usb"
                      ? "bg-purple-500/10 text-purple-500 border-purple-500/20"
                      : "bg-blue-500/10 text-blue-500 border-blue-500/20"
                  }
                >
                  {selectedCoral.type === "usb" ? "USB" : "PCIe / M.2"}
                </Badge>
              </div>

              {selectedCoral.form_factor && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Form Factor</span>
                  <span className="text-sm">{selectedCoral.form_factor}</span>
                </div>
              )}

              {selectedCoral.interface_speed && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Link</span>
                  <span className="font-mono text-sm">{selectedCoral.interface_speed}</span>
                </div>
              )}

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">
                  {selectedCoral.type === "usb" ? "Bus:Device" : "PCI Slot"}
                </span>
                <span className="font-mono text-sm">
                  {selectedCoral.type === "usb" ? selectedCoral.bus_device : selectedCoral.slot}
                </span>
              </div>

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Vendor / Product ID</span>
                <span className="font-mono text-sm">
                  {selectedCoral.vendor_id}:{selectedCoral.device_id}
                </span>
              </div>

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Vendor</span>
                <span className="text-sm">{selectedCoral.vendor}</span>
              </div>

              {selectedCoral.type === "pcie" && selectedCoral.kernel_driver && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Kernel Driver</span>
                  <span className={`font-mono text-sm ${selectedCoral.kernel_driver === "apex" ? "text-green-500" : "text-yellow-500"}`}>
                    {selectedCoral.kernel_driver}
                  </span>
                </div>
              )}

              {selectedCoral.kernel_modules && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Kernel Modules</span>
                  <div className="flex gap-2">
                    <Badge variant="outline" className={selectedCoral.kernel_modules.gasket ? "text-green-500 border-green-500/20" : "text-red-500 border-red-500/20"}>
                      gasket {selectedCoral.kernel_modules.gasket ? "✓" : "✗"}
                    </Badge>
                    <Badge variant="outline" className={selectedCoral.kernel_modules.apex ? "text-green-500 border-green-500/20" : "text-red-500 border-red-500/20"}>
                      apex {selectedCoral.kernel_modules.apex ? "✓" : "✗"}
                    </Badge>
                  </div>
                </div>
              )}

              {selectedCoral.device_nodes && selectedCoral.device_nodes.length > 0 && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Device Nodes</span>
                  <span className="font-mono text-xs text-right">
                    {selectedCoral.device_nodes.join(", ")}
                  </span>
                </div>
              )}

              {selectedCoral.type === "usb" && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Runtime State</span>
                  <span className="text-sm">
                    {selectedCoral.programmed ? "Programmed (runtime loaded)" : "Unprogrammed (runtime not loaded)"}
                  </span>
                </div>
              )}

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Edge TPU Runtime</span>
                <span className="text-sm text-right">
                  {selectedCoral.edgetpu_runtime || <span className="text-muted-foreground/60">not installed</span>}
                </span>
              </div>

              {typeof selectedCoral.temperature === "number" && (() => {
                const trips = selectedCoral.temperature_trips
                // Dynamic thresholds when the driver exposes trip points.
                // Otherwise fall back to conservative hardcoded limits.
                // trips are reported warn→critical, so [N-1] is critical (red)
                // and [N-2] is the throttle/warn level (amber).
                const redAt = trips && trips.length >= 1 ? trips[trips.length - 1] : 85
                const amberAt =
                  trips && trips.length >= 2
                    ? trips[trips.length - 2]
                    : trips && trips.length === 1
                      ? redAt - 10
                      : 75
                const color =
                  selectedCoral.temperature >= redAt
                    ? "text-red-500"
                    : selectedCoral.temperature >= amberAt
                      ? "text-amber-500"
                      : "text-green-500"
                return (
                  <div className="flex justify-between border-b border-border/50 pb-2">
                    <span className="text-sm font-medium text-muted-foreground">Temperature</span>
                    <div className="text-right">
                      <span className={`text-sm font-semibold ${color}`}>
                        {selectedCoral.temperature.toFixed(1)} °C
                      </span>
                      {trips && trips.length > 0 && (
                        <div className="text-xs text-muted-foreground mt-0.5">
                          Thresholds: {trips.map((t) => `${t.toFixed(0)}°C`).join(" · ")}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })()}

              {selectedCoral.thermal_warnings && selectedCoral.thermal_warnings.length > 0 && (
                <div className="flex justify-between items-start border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Hardware Warnings</span>
                  <div className="flex flex-col gap-1 items-end">
                    {selectedCoral.thermal_warnings.map((w) => (
                      <div key={w.name} className="flex items-center gap-2">
                        <span className="text-xs font-mono text-muted-foreground">
                          {w.name}
                          {typeof w.threshold_c === "number" && ` @ ${w.threshold_c.toFixed(0)}°C`}
                        </span>
                        <Badge
                          variant="outline"
                          className={
                            w.enabled
                              ? "text-green-500 border-green-500/20"
                              : "text-muted-foreground/70"
                          }
                        >
                          {w.enabled ? "enabled" : "disabled"}
                        </Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {!selectedCoral.drivers_ready && (
                <Button
                  onClick={() => {
                    setSelectedCoral(null)
                    setShowCoralInstaller(true)
                  }}
                  className="w-full bg-blue-600 hover:bg-blue-700 text-white"
                >
                  <Download className="mr-2 h-4 w-4" />
                  Install Coral TPU Drivers
                </Button>
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
            <div className="flex items-center justify-between rounded-lg border border-border/30 bg-background/60 p-4">
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

      {/* UPS */}
      {hardwareData?.ups && Array.isArray(hardwareData.ups) && hardwareData.ups.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Battery className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">UPS Status</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.ups.length} UPS
            </Badge>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {hardwareData.ups.map((ups: any, index: number) => {
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

              {selectedPCIDevice.sdevice && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Product Name</span>
                  <span className="text-sm text-right text-blue-400">{selectedPCIDevice.sdevice}</span>
                </div>
              )}

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
              {
                hardwareData.storage_devices.filter(
                  (device) =>
                    device.type === "disk" && !device.name.startsWith("zd") && !device.name.startsWith("loop"),
                ).length
              }{" "}
              devices
            </Badge>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hardwareData.storage_devices
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

      {/* USB Devices — everything physically plugged into the host's USB ports.
          Root hubs (vendor 1d6b) are already filtered out by the backend. The
          section is hidden on headless servers that have nothing attached. */}
      {hardwareData?.usb_devices && hardwareData.usb_devices.length > 0 && (
        <Card className="border-border/50 bg-card/50 p-6">
          <div className="mb-4 flex items-center gap-2">
            <Usb className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">USB Devices</h2>
            <Badge variant="outline" className="ml-auto">
              {hardwareData.usb_devices.length} device{hardwareData.usb_devices.length > 1 ? "s" : ""}
            </Badge>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hardwareData.usb_devices.map((usb, index) => (
              <div
                key={`usb-${index}-${usb.bus_device}`}
                onClick={() => setSelectedUsbDevice(usb)}
                className="cursor-pointer rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 p-3 transition-colors"
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="text-sm font-medium line-clamp-2 break-words flex-1">
                    {usb.name}
                  </span>
                  <Badge className={getDeviceTypeColor(usb.class_label)}>
                    {usb.class_label}
                  </Badge>
                </div>
                <div className="space-y-0.5 text-xs text-muted-foreground">
                  {usb.speed_label && <div>{usb.speed_label}</div>}
                  <div className="font-mono">
                    {usb.bus_device} · {usb.vendor_id}:{usb.product_id}
                  </div>
                  {usb.driver && (
                    <div className="font-mono text-green-500/80">Driver: {usb.driver}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* USB Device detail modal — mirrors the PCI Device modal for consistency. */}
      <Dialog open={selectedUsbDevice !== null} onOpenChange={(open) => !open && setSelectedUsbDevice(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{selectedUsbDevice?.name}</DialogTitle>
            <DialogDescription>USB Device Information</DialogDescription>
          </DialogHeader>

          {selectedUsbDevice && (
            <div className="space-y-3">
              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Class</span>
                <Badge className={getDeviceTypeColor(selectedUsbDevice.class_label)}>
                  {selectedUsbDevice.class_label}
                </Badge>
              </div>

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Bus:Device</span>
                <span className="font-mono text-sm">{selectedUsbDevice.bus_device}</span>
              </div>

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Device Name</span>
                <span className="text-sm text-right">{selectedUsbDevice.name}</span>
              </div>

              {selectedUsbDevice.vendor && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Vendor</span>
                  <span className="text-sm">{selectedUsbDevice.vendor}</span>
                </div>
              )}

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Vendor / Product ID</span>
                <span className="font-mono text-sm">
                  {selectedUsbDevice.vendor_id}:{selectedUsbDevice.product_id}
                </span>
              </div>

              {selectedUsbDevice.speed_label && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Speed</span>
                  <span className="text-sm">
                    {selectedUsbDevice.speed_label}
                    {selectedUsbDevice.speed_mbps > 0 && (
                      <span className="text-muted-foreground/60 ml-2">({selectedUsbDevice.speed_mbps} Mbps)</span>
                    )}
                  </span>
                </div>
              )}

              <div className="flex justify-between border-b border-border/50 pb-2">
                <span className="text-sm font-medium text-muted-foreground">Class Code</span>
                <span className="font-mono text-sm">0x{selectedUsbDevice.class_code}</span>
              </div>

              {selectedUsbDevice.driver && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Driver</span>
                  <span className="font-mono text-sm text-green-500">{selectedUsbDevice.driver}</span>
                </div>
              )}

              {selectedUsbDevice.serial && (
                <div className="flex justify-between border-b border-border/50 pb-2">
                  <span className="text-sm font-medium text-muted-foreground">Serial</span>
                  <span className="font-mono text-sm text-right break-all">{selectedUsbDevice.serial}</span>
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
          mutateStatic()
        }}
        onComplete={(success) => {
          if (success) {
            mutateStatic()
          }
        }}
      /> */}
      <ScriptTerminalModal
        open={showNvidiaInstaller}
        onClose={() => {
          setShowNvidiaInstaller(false)
          mutateStatic()
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
          mutateStatic()
        }}
        scriptPath="/usr/local/share/proxmenux/scripts/gpu_tpu/amd_gpu_tools.sh"
        scriptName="amd_gpu_tools"
        params={{
          EXECUTION_MODE: "web",
        }}
title="AMD GPU Tools Installation"
  description="Installing amdgpu_top for AMD GPU monitoring..."
  />
  <ScriptTerminalModal
  open={showIntelInstaller}
  onClose={() => {
  setShowIntelInstaller(false)
  mutateStatic()
  }}
  scriptPath="/usr/local/share/proxmenux/scripts/gpu_tpu/intel_gpu_tools.sh"
  scriptName="intel_gpu_tools"
  params={{
  EXECUTION_MODE: "web",
  }}
  title="Intel GPU Tools Installation"
  description="Installing intel-gpu-tools for Intel GPU monitoring..."
  />
  <ScriptTerminalModal
    open={showCoralInstaller}
    onClose={() => {
      setShowCoralInstaller(false)
      mutateStatic()
    }}
    scriptPath="/usr/local/share/proxmenux/scripts/gpu_tpu/install_coral.sh"
    scriptName="install_coral"
    params={{
      EXECUTION_MODE: "web",
    }}
    title="Coral TPU Driver Installation"
    description="Installing gasket + apex kernel modules and Edge TPU runtime..."
  />
  
  {/* GPU Switch Mode Modal */}
  {switchModeParams && (
    <ScriptTerminalModal
      open={showSwitchModeModal}
      onClose={handleSwitchModeModalClose}
      scriptPath="/usr/local/share/proxmenux/scripts/gpu_tpu/switch_gpu_mode_direct.sh"
      scriptName="switch_gpu_mode_direct"
      params={{
        EXECUTION_MODE: "web",
        GPU_SWITCH_PARAMS: `${switchModeParams.gpuSlot}|${switchModeParams.targetMode}`,
      }}
      title={`GPU Switch Mode → ${switchModeParams.targetMode.toUpperCase()}`}
      description={`Switching GPU ${switchModeParams.gpuSlot} to ${switchModeParams.targetMode === "vm" ? "VM (VFIO passthrough)" : "LXC (native driver)"} mode...`}
    />
  )}
  </div>
  )
}
