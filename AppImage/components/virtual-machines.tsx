"use client"

import type React from "react"

import { useState, useMemo, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Progress } from "./ui/progress"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "./ui/dialog"
import { Server, Play, Square, Cpu, MemoryStick, HardDrive, Network, Power, RotateCcw, StopCircle, Container, ChevronDown, ChevronUp, Terminal, Archive, Plus, Loader2, Clock, Database, Shield, Bell, FileText, Settings2 } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Checkbox } from "./ui/checkbox"
import { Textarea } from "./ui/textarea"
import { Label } from "./ui/label"
import useSWR from "swr"
import { MetricsView } from "./metrics-dialog"
import { LxcTerminalModal } from "./lxc-terminal-modal"
import { formatStorage } from "../lib/utils"
import { formatNetworkTraffic, getNetworkUnit } from "../lib/format-network"
import { fetchApi } from "../lib/api-config"

interface VMData {
  vmid: number
  name: string
  status: string
  type: string
  cpu: number
  mem: number
  maxmem: number
  disk: number
  maxdisk: number
  uptime: number
  netin?: number
  netout?: number
  diskread?: number
  diskwrite?: number
  ip?: string
}

interface VMConfig {
  cores?: number
  memory?: number
  swap?: number
  rootfs?: string
  net0?: string
  net1?: string
  net2?: string
  nameserver?: string
  searchdomain?: string
  onboot?: number
  unprivileged?: number
  features?: string
  ostype?: string
  arch?: string
  hostname?: string
  // VM specific
  sockets?: number
  scsi0?: string
  ide0?: string
  boot?: string
  description?: string // Added for notes
  // Hardware specific
  numa?: boolean
  bios?: string
  machine?: string
  vga?: string
  agent?: boolean
  tablet?: boolean
  localtime?: boolean
  // Storage specific
  scsihw?: string
  efidisk0?: string
  tpmstate0?: string
  // Mount points for LXC
  mp0?: string
  mp1?: string
  mp2?: string
  mp3?: string
  mp4?: string
  mp5?: string
  // PCI Passthrough
  hostpci0?: string
  hostpci1?: string
  hostpci2?: string
  hostpci3?: string
  hostpci4?: string
  hostpci5?: string
  // USB Devices
  usb0?: string
  usb1?: string
  usb2?: string
  // Serial Devices
  serial0?: string
  serial1?: string
  // Advanced
  vmgenid?: string
  smbios1?: string
  meta?: string
  // CPU
  cpu?: string
  [key: string]: any
}

interface VMDetails extends VMData {
  config?: VMConfig
  node?: string
  vm_type?: string
  os_info?: {
    id?: string
    version_id?: string
    name?: string
    pretty_name?: string
  }
  hardware_info?: {
    privileged?: boolean | null
    gpu_passthrough?: string[]
    devices?: string[]
  }
  lxc_ip_info?: {
    all_ips: string[]
    real_ips: string[]
    docker_ips: string[]
    primary_ip: string
  }
}

interface BackupStorage {
  storage: string
  type: string
  content: string
  total: number
  used: number
  avail: number
  total_human?: string
  used_human?: string
  avail_human?: string
}

interface VMBackup {
  volid: string
  storage: string
  type: string
  size: number
  size_human: string
  timestamp: number
  date: string
  notes?: string
}

const fetcher = async (url: string) => {
  return fetchApi(url)
}

const formatBytes = (bytes: number | undefined, isNetwork: boolean = false): string => {
  if (!bytes || bytes === 0) return isNetwork ? "0 B/s" : "0 B"
  
  if (isNetwork) {
    const networkUnit = getNetworkUnit()
    return formatNetworkTraffic(bytes, networkUnit, 2)
  }
  
  // For non-network (disk), use standard bytes
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

const formatUptime = (seconds: number) => {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${days}d ${hours}h ${minutes}m`
}

const extractIPFromConfig = (config?: VMConfig, lxcIPInfo?: VMDetails["lxc_ip_info"]): string => {
  // Use primary IP from lxc-info if available
  if (lxcIPInfo?.primary_ip) {
    return lxcIPInfo.primary_ip
  }

  if (!config) return "DHCP"

  // Check net0, net1, net2, etc.
  for (let i = 0; i < 10; i++) {
    const netKey = `net${i}`
    const netConfig = config[netKey]

    if (netConfig && typeof netConfig === "string") {
      // Look for ip=x.x.x.x/xx or ip=x.x.x.x pattern
      const ipMatch = netConfig.match(/ip=([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})/)
      if (ipMatch) {
        return ipMatch[1] // Return just the IP without CIDR
      }

      // Check if it's explicitly DHCP
      if (netConfig.includes("ip=dhcp")) {
        return "DHCP"
      }
    }
  }

  return "DHCP"
}

// const formatStorage = (sizeInGB: number): string => {
//   if (sizeInGB < 1) {
//     // Less than 1 GB, show in MB
//     return `${(sizeInGB * 1024).toFixed(1)} MB`
//   } else if (sizeInGB < 1024) {
//     // Less than 1024 GB, show in GB
//     return `${sizeInGB.toFixed(1)} GB`
//   } else {
//     // 1024 GB or more, show in TB
//     return `${(sizeInGB / 1024).toFixed(1)} TB`
//   }
// }

const getUsageColor = (percent: number): string => {
  if (percent >= 95) return "text-red-500"
  if (percent >= 86) return "text-orange-500"
  if (percent >= 71) return "text-yellow-500"
  return "text-foreground"
}

// Generate consistent color for storage names
const storageColors = [
  { bg: "bg-blue-500/20", text: "text-blue-400", border: "border-blue-500/30" },
  { bg: "bg-emerald-500/20", text: "text-emerald-400", border: "border-emerald-500/30" },
  { bg: "bg-purple-500/20", text: "text-purple-400", border: "border-purple-500/30" },
  { bg: "bg-amber-500/20", text: "text-amber-400", border: "border-amber-500/30" },
  { bg: "bg-pink-500/20", text: "text-pink-400", border: "border-pink-500/30" },
  { bg: "bg-cyan-500/20", text: "text-cyan-400", border: "border-cyan-500/30" },
  { bg: "bg-rose-500/20", text: "text-rose-400", border: "border-rose-500/30" },
  { bg: "bg-indigo-500/20", text: "text-indigo-400", border: "border-indigo-500/30" },
]

const getStorageColor = (storageName: string) => {
  // Generate a consistent hash from storage name
  let hash = 0
  for (let i = 0; i < storageName.length; i++) {
    hash = storageName.charCodeAt(i) + ((hash << 5) - hash)
  }
  const index = Math.abs(hash) % storageColors.length
  return storageColors[index]
}

const getIconColor = (percent: number): string => {
  if (percent >= 95) return "text-red-500"
  if (percent >= 86) return "text-orange-500"
  if (percent >= 71) return "text-yellow-500"
  return "text-green-500"
}

const getProgressColor = (percent: number): string => {
  if (percent >= 95) return "[&>div]:bg-red-500"
  if (percent >= 86) return "[&>div]:bg-orange-500"
  if (percent >= 71) return "[&>div]:bg-yellow-500"
  return "[&>div]:bg-blue-500"
}

const getModalProgressColor = (percent: number): string => {
  if (percent >= 95) return "[&>div]:bg-red-500"
  if (percent >= 86) return "[&>div]:bg-orange-500"
  if (percent >= 71) return "[&>div]:bg-yellow-500"
  return "[&>div]:bg-blue-500"
}

const getOSIcon = (osInfo: VMDetails["os_info"] | undefined, vmType: string): React.ReactNode => {
  if (vmType !== "lxc" || !osInfo?.id) {
    return null
  }

  const osId = osInfo.id.toLowerCase()

  switch (osId) {
    case "debian":
      return <img src="/icons/debian.svg" alt="Debian" className="h-16 w-16" />
    case "ubuntu":
      return <img src="/icons/ubuntu.svg" alt="Ubuntu" className="h-16 w-16" />
    case "alpine":
      return <img src="/icons/alpine.svg" alt="Alpine" className="h-16 w-16" />
    case "arch":
      return <img src="/icons/arch.svg" alt="Arch" className="h-16 w-16" />
    default:
      return null
  }
}

export function VirtualMachines() {
  const {
    data: vmData,
    error,
    isLoading,
    mutate,
  } = useSWR<VMData[]>("/api/vms", fetcher, {
    refreshInterval: 23000,
    revalidateOnFocus: false,
    revalidateOnReconnect: true,
    dedupingInterval: 10000,
    errorRetryCount: 2,
  })

  const [selectedVM, setSelectedVM] = useState<VMData | null>(null)
  const [vmDetails, setVMDetails] = useState<VMDetails | null>(null)
  const [controlLoading, setControlLoading] = useState(false)
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [terminalOpen, setTerminalOpen] = useState(false)
  const [terminalVmid, setTerminalVmid] = useState<number | null>(null)
  const [terminalVmName, setTerminalVmName] = useState<string>("")
  const [vmConfigs, setVmConfigs] = useState<Record<number, string>>({})
  const [currentView, setCurrentView] = useState<"main" | "metrics">("main")
  const [showAdditionalInfo, setShowAdditionalInfo] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  const [isEditingNotes, setIsEditingNotes] = useState(false)
  const [editedNotes, setEditedNotes] = useState("")
  const [savingNotes, setSavingNotes] = useState(false)
  const [selectedMetric, setSelectedMetric] = useState<string | null>(null)
  const [ipsLoaded, setIpsLoaded] = useState(false)
  const [loadingIPs, setLoadingIPs] = useState(false)
  const [networkUnit, setNetworkUnit] = useState<"Bytes" | "Bits">("Bytes")
  
  // Backup states
  const [vmBackups, setVmBackups] = useState<VMBackup[]>([])
  const [backupStorages, setBackupStorages] = useState<BackupStorage[]>([])
  const [selectedBackupStorage, setSelectedBackupStorage] = useState<string>("")
  const [loadingBackups, setLoadingBackups] = useState(false)
  const [creatingBackup, setCreatingBackup] = useState(false)
  
  // Backup modal states
  const [showBackupModal, setShowBackupModal] = useState(false)
  const [backupMode, setBackupMode] = useState<string>("snapshot")
  const [backupProtected, setBackupProtected] = useState(false)
  const [backupNotification, setBackupNotification] = useState<string>("auto")
  const [backupNotes, setBackupNotes] = useState<string>("{{guestname}}")
  const [backupPbsChangeMode, setBackupPbsChangeMode] = useState<string>("default")

  useEffect(() => {
    const fetchLXCIPs = async () => {
      // Only fetch if data exists, not already loaded, and not currently loading
      if (!vmData || ipsLoaded || loadingIPs) return

      const lxcs = vmData.filter((vm) => vm.type === "lxc")

      if (lxcs.length === 0) {
        setIpsLoaded(true)
        return
      }

      setLoadingIPs(true)
      const configs: Record<number, string> = {}

      const batchSize = 5
      for (let i = 0; i < lxcs.length; i += batchSize) {
        const batch = lxcs.slice(i, i + batchSize)

        await Promise.all(
          batch.map(async (lxc) => {
            try {
              const controller = new AbortController()
              const timeoutId = setTimeout(() => controller.abort(), 10000)

              const details = await fetchApi(`/api/vms/${lxc.vmid}`)

              clearTimeout(timeoutId)

              if (details.lxc_ip_info?.primary_ip) {
                configs[lxc.vmid] = details.lxc_ip_info.primary_ip
              } else if (details.config) {
                configs[lxc.vmid] = extractIPFromConfig(details.config, details.lxc_ip_info)
              }
            } catch (error) {
              console.log(`[v0] Could not fetch IP for LXC ${lxc.vmid}`)
              configs[lxc.vmid] = "N/A"
            }
          }),
        )

        setVmConfigs((prev) => ({ ...prev, ...configs }))
      }

      setLoadingIPs(false)
      setIpsLoaded(true)
    }

    fetchLXCIPs()
  }, [vmData, ipsLoaded, loadingIPs])

  // Load initial network unit and listen for changes
  useEffect(() => {
    setNetworkUnit(getNetworkUnit())

    const handleNetworkUnitChange = () => {
      setNetworkUnit(getNetworkUnit())
    }

    window.addEventListener("networkUnitChanged", handleNetworkUnitChange)
    window.addEventListener("storage", handleNetworkUnitChange)

    return () => {
      window.removeEventListener("networkUnitChanged", handleNetworkUnitChange)
      window.removeEventListener("storage", handleNetworkUnitChange)
    }
  }, [])

  const handleVMClick = async (vm: VMData) => {
    setSelectedVM(vm)
    setCurrentView("main")
    setShowAdditionalInfo(false)
    setShowNotes(false)
    setIsEditingNotes(false)
    setEditedNotes("")
    setDetailsLoading(true)
    
    // Load backups immediately (independent of config)
    fetchBackupStorages()
    fetchVmBackups(vm.vmid)
    
    try {
      const details = await fetchApi(`/api/vms/${vm.vmid}`)
      setVMDetails(details)
    } catch (error) {
      console.error("Error fetching VM details:", error)
    } finally {
      setDetailsLoading(false)
    }
  }

  const handleMetricsClick = () => {
    setCurrentView("metrics")
  }

  const handleBackToMain = () => {
    setCurrentView("main")
  }

  // Backup functions
  const fetchBackupStorages = async () => {
    try {
      const response = await fetchApi("/api/backup-storages")
      if (response.storages) {
        setBackupStorages(response.storages)
        if (response.storages.length > 0 && !selectedBackupStorage) {
          setSelectedBackupStorage(response.storages[0].storage)
        }
      }
    } catch (error) {
      console.error("Error fetching backup storages:", error)
    }
  }

  const fetchVmBackups = async (vmid: number) => {
    setLoadingBackups(true)
    try {
      const response = await fetchApi(`/api/vms/${vmid}/backups`)
      if (response.backups) {
        setVmBackups(response.backups)
      }
    } catch (error) {
      console.error("Error fetching VM backups:", error)
      setVmBackups([])
    } finally {
      setLoadingBackups(false)
    }
  }

  const openBackupModal = () => {
    // Reset modal to defaults
    setBackupMode("snapshot")
    setBackupProtected(false)
    setBackupNotification("auto")
    setBackupNotes("{{guestname}}")
    setBackupPbsChangeMode("default")
    // Auto-select first storage if none selected
    if (!selectedBackupStorage && backupStorages.length > 0) {
      setSelectedBackupStorage(backupStorages[0].storage)
    }
    setShowBackupModal(true)
  }

  const handleCreateBackup = async () => {
    if (!selectedVM || !selectedBackupStorage) return
    
    setCreatingBackup(true)
    setShowBackupModal(false)
    
    try {
      await fetchApi(`/api/vms/${selectedVM.vmid}/backup`, {
        method: "POST",
        body: JSON.stringify({ 
          storage: selectedBackupStorage,
          mode: backupMode,
          compress: "zstd",
          protected: backupProtected,
          notification: backupNotification,
          notes: backupNotes,
          pbs_change_detection: backupPbsChangeMode
        }),
      })
      setTimeout(() => fetchVmBackups(selectedVM.vmid), 2000)
    } catch (error) {
      console.error("Error creating backup:", error)
    } finally {
      setCreatingBackup(false)
    }
  }

  const handleVMControl = async (vmid: number, action: string) => {
    setControlLoading(true)
    try {
      await fetchApi(`/api/vms/${vmid}/control`, {
        method: "POST",
        body: JSON.stringify({ action }),
      })

      mutate()
      setSelectedVM(null)
      setVMDetails(null)
    } catch (error) {
      console.error("Failed to control VM")
    } finally {
      setControlLoading(false)
    }
  }

  // Open terminal for LXC container
  const openLxcTerminal = (vmid: number, vmName: string) => {
    setTerminalVmid(vmid)
    setTerminalVmName(vmName)
    setTerminalOpen(true)
  }
  
const handleDownloadLogs = async (vmid: number, vmName: string) => {
    try {
      const data = await fetchApi(`/api/vms/${vmid}/logs`)

      // Format logs as plain text
      let logText = `=== Logs for ${vmName} (VMID: ${vmid}) ===\n`
      logText += `Node: ${data.node}\n`
      logText += `Type: ${data.type}\n`
      logText += `Total lines: ${data.log_lines}\n`
      logText += `Generated: ${new Date().toISOString()}\n`
      logText += `\n${"=".repeat(80)}\n\n`

      if (data.logs && Array.isArray(data.logs)) {
        data.logs.forEach((log: any) => {
          if (typeof log === "object" && log.t) {
            logText += `${log.t}\n`
          } else if (typeof log === "string") {
            logText += `${log}\n`
          }
        })
      }

      const blob = new Blob([logText], { type: "text/plain" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `${vmName}-${vmid}-logs.txt`
      a.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error("Error downloading logs:", error)
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case "running":
        return "bg-green-500/10 text-green-500 border-green-500/20"
      case "stopped":
        return "bg-red-500/10 text-red-500 border-red-500/20"
      default:
        return "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "running":
        return <Play className="h-3 w-3" />
      case "stopped":
        return <Square className="h-3 w-3" />
      default:
        return null
    }
  }

  const getTypeBadge = (type: string) => {
    if (type === "lxc") {
      return {
        color: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
        label: "LXC",
        icon: <Container className="h-3 w-3 mr-1" />,
      }
    }
    return {
      color: "bg-purple-500/10 text-purple-500 border-purple-500/20",
      label: "VM",
      icon: <Server className="h-3 w-3 mr-1" />,
    }
  }

  const safeVMData = vmData || []

  // Total allocated RAM for ALL VMs/LXCs (running + stopped)
  const totalAllocatedMemoryGB = useMemo(() => {
    return (safeVMData.reduce((sum, vm) => sum + (vm.maxmem || 0), 0) / 1024 ** 3).toFixed(1)
  }, [safeVMData])

  // Allocated RAM only for RUNNING VMs/LXCs (this is what actually matters for overcommit)
  const runningAllocatedMemoryGB = useMemo(() => {
    return (safeVMData
      .filter((vm) => vm.status === "running")
      .reduce((sum, vm) => sum + (vm.maxmem || 0), 0) / 1024 ** 3).toFixed(1)
  }, [safeVMData])

  const { data: systemData } = useSWR<{ memory_total: number; memory_used: number; memory_usage: number }>(
    "/api/system",
    fetcher,
    {
      refreshInterval: 37000,
      revalidateOnFocus: false,
    },
  )

  const physicalMemoryGB = systemData?.memory_total ?? null
  const usedMemoryGB = systemData?.memory_used ?? null
  const memoryUsagePercent = systemData?.memory_usage ?? null
  const allocatedMemoryGB = Number.parseFloat(totalAllocatedMemoryGB)
  const runningAllocatedGB = Number.parseFloat(runningAllocatedMemoryGB)
  // Overcommit warning should be based on RUNNING VMs allocation, not total
  const isMemoryOvercommit = physicalMemoryGB !== null && runningAllocatedGB > physicalMemoryGB

  const getMemoryUsageColor = (percent: number | null) => {
    if (percent === null) return "bg-blue-500"
    if (percent >= 95) return "bg-red-500"
    if (percent >= 86) return "bg-orange-500"
    if (percent >= 71) return "bg-yellow-500"
    return "bg-blue-500"
  }

  const getMemoryPercentTextColor = (percent: number | null) => {
    if (percent === null) return "text-muted-foreground"
    if (percent >= 95) return "text-red-500"
    if (percent >= 86) return "text-orange-500"
    if (percent >= 71) return "text-yellow-500"
    return "text-green-500"
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8 text-muted-foreground">Loading virtual machines...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8 text-red-500">Error loading virtual machines: {error.message}</div>
      </div>
    )
  }

  const isHTML = (str: string): boolean => {
    const htmlRegex = /<\/?[a-z][\s\S]*>/i
    return htmlRegex.test(str)
  }

  const decodeRecursively = (str: string, maxIterations = 5): string => {
    let decoded = str
    let iteration = 0

    while (iteration < maxIterations) {
      try {
        const nextDecoded = decodeURIComponent(decoded.replace(/%0A/g, "\n"))

        // If decoding didn't change anything, we're done
        if (nextDecoded === decoded) {
          break
        }

        decoded = nextDecoded

        // If there are no more encoded characters, we're done
        if (!/(%[0-9A-F]{2})/i.test(decoded)) {
          break
        }

        iteration++
      } catch (e) {
        // If decoding fails, try manual decoding of common sequences
        try {
          decoded = decoded
            .replace(/%0A/g, "\n")
            .replace(/%20/g, " ")
            .replace(/%3A/g, ":")
            .replace(/%2F/g, "/")
            .replace(/%3D/g, "=")
            .replace(/%3C/g, "<")
            .replace(/%3E/g, ">")
            .replace(/%22/g, '"')
            .replace(/%27/g, "'")
            .replace(/%26/g, "&")
            .replace(/%23/g, "#")
            .replace(/%25/g, "%")
            .replace(/%2B/g, "+")
            .replace(/%2C/g, ",")
            .replace(/%3B/g, ";")
            .replace(/%3F/g, "?")
            .replace(/%40/g, "@")
            .replace(/%5B/g, "[")
            .replace(/%5D/g, "]")
            .replace(/%7B/g, "{")
            .replace(/%7D/g, "}")
            .replace(/%7C/g, "|")
            .replace(/%5C/g, "\\")
            .replace(/%5E/g, "^")
            .replace(/%60/g, "`")
          break
        } catch (manualError) {
          // If manual decoding also fails, return what we have
          break
        }
      }
    }

    return decoded
  }

  const processDescription = (description: string): { html: string; isHtml: boolean; error: boolean } => {
    try {
      const decoded = decodeRecursively(description)

      // Check if it contains HTML
      if (isHTML(decoded)) {
        return { html: decoded, isHtml: true, error: false }
      }

      // If it's plain text, convert \n to <br>
      return { html: decoded.replace(/\n/g, "<br>"), isHtml: false, error: false }
    } catch (error) {
      // If all decoding fails, return error
      console.error("Error decoding description:", error)
      return { html: "", isHtml: false, error: true }
    }
  }

  const handleEditNotes = () => {
    if (vmDetails?.config?.description) {
      const decoded = decodeRecursively(vmDetails.config.description)
      setEditedNotes(decoded)
    } else {
      setEditedNotes("") // Ensure editedNotes is empty if no description exists
    }
    setIsEditingNotes(true)
  }

  const handleSaveNotes = async () => {
    if (!selectedVM || !vmDetails) return

    setSavingNotes(true)
    try {
      await fetchApi(`/api/vms/${selectedVM.vmid}/config`, {
        method: "PUT",
        body: JSON.stringify({
          description: editedNotes, // Send as-is, pvesh will handle encoding
        }),
      })

      setVMDetails({
        ...vmDetails,
        config: {
          ...vmDetails.config,
          description: editedNotes, // Store unencoded
        },
      })
      setIsEditingNotes(false)
    } catch (error) {
      console.error("Error saving notes:", error)
      alert("Error saving notes. Please try again.")
    } finally {
      setSavingNotes(false)
    }
  }

  const handleCancelEditNotes = () => {
    setIsEditingNotes(false)
    setEditedNotes("")
  }

  return (
    <div className="space-y-6">
      <style jsx>{`
        .proxmenux-notes {
          /* Reset any inherited styles */
          all: revert;
          
          /* Ensure links display inline */
          a {
            display: inline-block;
            margin-right: 4px;
            text-decoration: none;
          }
          
          /* Ensure images display inline */
          img {
            display: inline-block;
            vertical-align: middle;
          }
          
          /* Ensure paragraphs with links display inline */
          p {
            margin: 0.5rem 0;
          }
          
          /* Override inline width and center the table */
          table {
            width: auto !important;
            margin: 0 auto;
          }
          
          /* Ensure divs respect centering */
          div[align="center"] {
            text-align: center;
          }
          
          /* Remove border-left since logo already has the line, keep text left-aligned */
          table td:nth-child(2) {
            text-align: left;
            padding-left: 16px;
          }
          
          /* Increase h1 font size for VM name */
          table td:nth-child(2) h1 {
            text-align: left;
            font-size: 2rem;
            font-weight: bold;
            line-height: 1.2;
          }
          
          /* Ensure p in the second cell is left-aligned */
          table td:nth-child(2) p {
            text-align: left;
          }
          
          /* Add separator after tables */
          table + p {
            margin-top: 1rem;
            padding-top: 1rem;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
          }
        }
        
        .proxmenux-notes-plaintext {
          white-space: pre-wrap;
          font-family: monospace;
        }
      `}</style>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total VMs & LXCs</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">{safeVMData.length}</div>
            <div className="vm-badges mt-2">
              <Badge variant="outline" className="vm-badge bg-green-500/10 text-green-500 border-green-500/20">
                {safeVMData.filter((vm) => vm.status === "running").length} Running
              </Badge>
              <Badge variant="outline" className="vm-badge bg-red-500/10 text-red-500 border-red-500/20">
                {safeVMData.filter((vm) => vm.status === "stopped").length} Stopped
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2 hidden lg:block">Virtual machines configured</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total CPU</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">
              {(safeVMData.reduce((sum, vm) => sum + (vm.cpu || 0), 0) * 100).toFixed(0)}%
            </div>
            <p className="text-xs text-muted-foreground mt-2">Allocated CPU usage</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Memory</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Memory Usage (current) */}
            {physicalMemoryGB !== null && usedMemoryGB !== null && memoryUsagePercent !== null ? (
              <div>
                <div className="text-xl lg:text-2xl font-bold text-foreground">{usedMemoryGB.toFixed(1)} GB</div>
                <div className="text-xs text-muted-foreground mt-1">
                  <span className={getMemoryPercentTextColor(memoryUsagePercent)}>
                    {memoryUsagePercent.toFixed(1)}%
                  </span>{" "}
                  of {physicalMemoryGB.toFixed(1)} GB
                </div>
                <Progress value={memoryUsagePercent} className="h-2 [&>div]:bg-blue-500" />
              </div>
            ) : (
              <div>
                <div className="text-xl lg:text-2xl font-bold text-muted-foreground">--</div>
                <div className="text-xs text-muted-foreground mt-1">Loading memory usage...</div>
              </div>
            )}

            {/* Allocated RAM (configured) - Split into Running and Total */}
            <div className="pt-3 border-t border-border">
              {/* Layout para desktop */}
              <div className="hidden lg:flex items-center justify-between">
                <div className="flex gap-6">
                  {/* Running allocation - most important */}
                  <div>
                    <div className="text-lg font-semibold text-foreground">{runningAllocatedMemoryGB} GB</div>
                    <div className="text-xs text-muted-foreground">Running Allocated</div>
                  </div>
                  {/* Total allocation */}
                  <div>
                    <div className="text-lg font-semibold text-muted-foreground">{totalAllocatedMemoryGB} GB</div>
                    <div className="text-xs text-muted-foreground">Total Allocated</div>
                  </div>
                </div>
                {physicalMemoryGB !== null && (
                  <div>
                    {isMemoryOvercommit ? (
                      <Badge variant="outline" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                        Exceeds Physical
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                        Within Limits
                      </Badge>
                    )}
                  </div>
                )}
              </div>

              {/* Layout para movil */}
              <div className="lg:hidden space-y-2">
                <div className="flex gap-4">
                  {/* Running allocation */}
                  <div>
                    <div className="text-lg font-semibold text-foreground">{runningAllocatedMemoryGB} GB</div>
                    <div className="text-xs text-muted-foreground">Running</div>
                  </div>
                  {/* Total allocation */}
                  <div>
                    <div className="text-lg font-semibold text-muted-foreground">{totalAllocatedMemoryGB} GB</div>
                    <div className="text-xs text-muted-foreground">Total</div>
                  </div>
                </div>
                {physicalMemoryGB !== null && (
                  <div>
                    {isMemoryOvercommit ? (
                      <Badge variant="outline" className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                        Exceeds Physical
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                        Within Limits
                      </Badge>
                    )}
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Disk</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">
              {formatStorage(safeVMData.reduce((sum, vm) => sum + (vm.maxdisk || 0), 0) / 1024 ** 3)}
            </div>
            <p className="text-xs text-muted-foreground mt-2">Allocated disk space</p>
          </CardContent>
        </Card>
      </div>

      <Card className="bg-card border-border">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-xl lg:text-2xl font-bold text-foreground">
            <Server className="h-6 w-6" />
            Virtual Machines & Containers
          </CardTitle>
        </CardHeader>
        <CardContent>
          {safeVMData.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">No virtual machines found</div>
          ) : (
            <div className="space-y-3">
              {safeVMData.map((vm) => {
                const cpuPercent = (vm.cpu * 100).toFixed(1)
                const memPercent = vm.maxmem > 0 ? ((vm.mem / vm.maxmem) * 100).toFixed(1) : "0"
                const memGB = (vm.mem / 1024 ** 3).toFixed(1)
                const maxMemGB = (vm.maxmem / 1024 ** 3).toFixed(1)
                const diskPercent = vm.maxdisk > 0 ? ((vm.disk / vm.maxdisk) * 100).toFixed(1) : "0"
                const diskGB = (vm.disk / 1024 ** 3).toFixed(1)
                const maxDiskGB = (vm.maxdisk / 1024 ** 3).toFixed(1)
                const typeBadge = getTypeBadge(vm.type)
                const lxcIP = vm.type === "lxc" ? vmConfigs[vm.vmid] : null

                return (
                  <div key={vm.vmid}>
                    <div
                      className="hidden sm:block p-4 rounded-lg border border-border bg-card hover:bg-black/5 dark:hover:bg-white/5 transition-colors cursor-pointer"
                      onClick={() => handleVMClick(vm)}
                    >
                      <div className="flex items-center gap-2 flex-wrap mb-3">
                        <Badge variant="outline" className={`text-xs flex-shrink-0 ${getStatusColor(vm.status)}`}>
                          {getStatusIcon(vm.status)}
                          {vm.status.toUpperCase()}
                        </Badge>
                        <Badge variant="outline" className={`text-xs flex-shrink-0 ${typeBadge.color}`}>
                          {typeBadge.icon}
                          {typeBadge.label}
                        </Badge>
                        <div className="flex-1 min-w-0">
                          <div className="font-semibold text-foreground truncate">
                            {vm.name}
                            <span className="hidden lg:inline text-sm text-muted-foreground ml-2">ID: {vm.vmid}</span>
                          </div>
                          <div className="text-[10px] text-muted-foreground lg:hidden">ID: {vm.vmid}</div>
                        </div>
                        {lxcIP && (
                          <span className={`text-sm ${lxcIP === "DHCP" ? "text-yellow-500" : "text-green-500"}`}>
                            IP: {lxcIP}
                          </span>
                        )}
                        <span className="text-sm text-muted-foreground ml-auto">Uptime: {formatUptime(vm.uptime)}</span>
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                        <div>
                          <div className="text-xs text-muted-foreground mb-1">CPU Usage</div>
                          <div
                            className="cursor-pointer hover:opacity-80 transition-opacity"
                            onClick={() => {
                              setSelectedMetric("cpu") // undeclared variable fix
                            }}
                          >
                            <div
                              className={`text-sm font-semibold mb-1 ${getUsageColor(Number.parseFloat(cpuPercent))}`}
                            >
                              {cpuPercent}%
                            </div>
                            <Progress
                              value={Number.parseFloat(cpuPercent)}
                              className={`h-1.5 ${getProgressColor(Number.parseFloat(cpuPercent))}`}
                            />
                          </div>
                        </div>

                        <div>
                          <div className="text-xs text-muted-foreground mb-1">Memory</div>
                          <div
                            className="cursor-pointer hover:opacity-80 transition-opacity"
                            onClick={() => {
                              setSelectedMetric("memory")
                            }}
                          >
                            <div
                              className={`text-sm font-semibold mb-1 ${getUsageColor(Number.parseFloat(memPercent))}`}
                            >
                              {memGB} / {maxMemGB} GB
                            </div>
                            <Progress
                              value={Number.parseFloat(memPercent)}
                              className={`h-1.5 ${getProgressColor(Number.parseFloat(memPercent))}`}
                            />
                          </div>
                        </div>

                        <div>
                          <div className="text-xs text-muted-foreground mb-1">Disk Usage</div>
                          <div
                            className="cursor-pointer hover:opacity-80 transition-opacity"
                            onClick={() => {
                              setSelectedMetric("disk")
                            }}
                          >
                            <div
                              className={`text-sm font-semibold mb-1 ${getUsageColor(Number.parseFloat(diskPercent))}`}
                            >
                              {diskGB} / {maxDiskGB} GB
                            </div>
                            <Progress
                              value={Number.parseFloat(diskPercent)}
                              className={`h-1.5 ${getProgressColor(Number.parseFloat(diskPercent))}`}
                            />
                          </div>
                        </div>

                        <div className="hidden md:block">
                          <div className="text-xs text-muted-foreground mb-1">Disk I/O</div>
                          <div className="text-sm font-semibold space-y-0.5">
                            <div className="flex items-center gap-1">
                              <HardDrive className="h-3 w-3 text-green-500" />
                              <span className="text-green-500">↓ {formatBytes(vm.diskread, false)}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <HardDrive className="h-3 w-3 text-blue-500" />
                              <span className="text-blue-500">↑ {formatBytes(vm.diskwrite, false)}</span>
                            </div>
                          </div>
                        </div>

                        <div>
                          <div className="text-xs text-muted-foreground mb-1">Network I/O</div>
                          <div className="text-sm font-semibold space-y-0.5">
                            <div className="flex items-center gap-1">
                              <Network className="h-3 w-3 text-green-500" />
                              <span className="text-green-500">↓ {formatBytes(vm.netin, true)}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Network className="h-3 w-3 text-blue-500" />
                              <span className="text-blue-500">↑ {formatBytes(vm.netout, true)}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div
                      className="sm:hidden p-4 rounded-lg border border-black/10 dark:border-white/10 bg-black/5 dark:bg-white/5 transition-colors cursor-pointer"
                      onClick={() => handleVMClick(vm)}
                    >
                      <div className="flex items-center gap-3">
                        {vm.status === "running" ? (
                          <Play className="h-5 w-5 text-green-500 fill-current flex-shrink-0" />
                        ) : (
                          <Square className="h-5 w-5 text-red-500 fill-current flex-shrink-0" />
                        )}

                        <Badge variant="outline" className={`${getTypeBadge(vm.type).color} flex-shrink-0`}>
                          {getTypeBadge(vm.type).label}
                        </Badge>

                        {/* Name and ID */}
                        <div className="flex-1 min-w-0">
                          <div className="font-semibold text-foreground truncate">{vm.name}</div>
                          <div className="text-[10px] text-muted-foreground">ID: {vm.vmid}</div>
                        </div>

                        <div className="flex items-center gap-3 flex-shrink-0">
                          {/* CPU icon with percentage */}
                          <div className="flex flex-col items-center gap-0.5">
                            {vm.status === "running" && (
                              <span className="text-[10px] font-medium text-muted-foreground">{cpuPercent}%</span>
                            )}
                            <Cpu
                              className={`h-4 w-4 ${
                                vm.status === "stopped" ? "text-gray-500" : getUsageColor(Number.parseFloat(cpuPercent))
                              }`}
                            />
                          </div>

                          {/* Memory icon with percentage */}
                          <div className="flex flex-col items-center gap-0.5">
                            {vm.status === "running" && (
                              <span className="text-[10px] font-medium text-muted-foreground">{memPercent}%</span>
                            )}
                            <MemoryStick
                              className={`h-4 w-4 ${
                                vm.status === "stopped" ? "text-gray-500" : getUsageColor(Number.parseFloat(memPercent))
                              }`}
                            />
                          </div>

                          {/* Disk icon with percentage */}
                          <div className="flex flex-col items-center gap-0.5">
                            {vm.status === "running" && (
                              <span className="text-[10px] font-medium text-muted-foreground">{diskPercent}%</span>
                            )}
                            <HardDrive
                              className={`h-4 w-4 ${
                                vm.status === "stopped"
                                  ? "text-gray-500"
                                  : getUsageColor(Number.parseFloat(diskPercent))
                              }`}
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={!!selectedVM}
        onOpenChange={() => {
          setSelectedVM(null)
          setVMDetails(null)
          setCurrentView("main")
          setSelectedMetric(null)
          setShowAdditionalInfo(false)
          setShowNotes(false)
          setIsEditingNotes(false)
          setEditedNotes("")
        }}
      >
        <DialogContent
          className="max-w-4xl h-[95vh] sm:h-[90vh] flex flex-col p-0 overflow-hidden"
          key={selectedVM?.vmid || "no-vm"}
        >
          {currentView === "main" ? (
            <>
              <DialogHeader className="pb-4 border-b border-border px-6 pt-6">
                <DialogTitle className="flex flex-col gap-3">
                  {/* Desktop layout: Uptime now appears after status badge */}
                  <div className="hidden sm:flex items-center gap-3 flex-wrap">
                    <div className="flex items-center gap-2">
                      <Server className="h-5 w-5 flex-shrink-0" />
                      <span className="text-lg truncate">{selectedVM?.name}</span>
                      {selectedVM && <span className="text-sm text-muted-foreground">ID: {selectedVM.vmid}</span>}
                    </div>
                    {selectedVM && (
                      <>
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge variant="outline" className={`${getTypeBadge(selectedVM.type).color} flex-shrink-0`}>
                            {getTypeBadge(selectedVM.type).icon}
                            {getTypeBadge(selectedVM.type).label}
                          </Badge>
                          <Badge variant="outline" className={`${getStatusColor(selectedVM.status)} flex-shrink-0`}>
                            {selectedVM.status.toUpperCase()}
                          </Badge>
                          {selectedVM.status === "running" && (
                            <span className="text-sm text-muted-foreground">
                              Uptime: {formatUptime(selectedVM.uptime)}
                            </span>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                  {/* Mobile layout unchanged */}
                  <div className="sm:hidden flex flex-col gap-2">
                    <div className="flex items-center gap-2">
                      <Server className="h-5 w-5 flex-shrink-0" />
                      <span className="text-lg truncate">{selectedVM?.name}</span>
                      {selectedVM && <span className="text-sm text-muted-foreground">ID: {selectedVM.vmid}</span>}
                    </div>
                    {selectedVM && (
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant="outline" className={`${getTypeBadge(selectedVM.type).color} flex-shrink-0`}>
                          {getTypeBadge(selectedVM.type).icon}
                          {getTypeBadge(selectedVM.type).label}
                        </Badge>
                        <Badge variant="outline" className={`${getStatusColor(selectedVM.status)} flex-shrink-0`}>
                          {selectedVM.status.toUpperCase()}
                        </Badge>
                        {selectedVM.status === "running" && (
                          <span className="text-sm text-muted-foreground">
                            Uptime: {formatUptime(selectedVM.uptime)}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </DialogTitle>
              </DialogHeader>

              <div className="flex-1 overflow-y-auto px-6 py-4" style={{ maxHeight: 'calc(100vh - 280px)' }}>
                <div className="space-y-4">
                  {selectedVM && (
                    <>
                      <div key={`metrics-${selectedVM.vmid}`}>
                        <Card
                          className="cursor-pointer rounded-lg border border-black/10 dark:border-white/10 sm:border-border max-sm:bg-black/5 max-sm:dark:bg-white/5 sm:bg-card sm:hover:bg-black/5 sm:dark:hover:bg-white/5 transition-colors group"
                          onClick={handleMetricsClick}
                        >
                          <CardContent className="p-4">
                            <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                              {/* CPU Usage */}
                              <div>
                                <div className="text-xs text-muted-foreground mb-2">CPU Usage</div>
                                <div className={`text-base font-semibold mb-2 ${getUsageColor(selectedVM.cpu * 100)}`}>
                                  {(selectedVM.cpu * 100).toFixed(1)}%
                                </div>
                                <Progress
                                  value={selectedVM.cpu * 100}
                                  className={`h-2 max-sm:bg-background sm:group-hover:bg-background/50 transition-colors ${getModalProgressColor(selectedVM.cpu * 100)}`}
                                />
                              </div>

                              {/* Memory */}
                              <div>
                                <div className="text-xs text-muted-foreground mb-2">Memory</div>
                                <div
                                  className={`text-base font-semibold mb-2 ${getUsageColor((selectedVM.mem / selectedVM.maxmem) * 100)}`}
                                >
                                  {(selectedVM.mem / 1024 ** 3).toFixed(1)} /{" "}
                                  {(selectedVM.maxmem / 1024 ** 3).toFixed(1)} GB
                                </div>
                                <Progress
                                  value={(selectedVM.mem / selectedVM.maxmem) * 100}
                                  className={`h-2 max-sm:bg-background sm:group-hover:bg-background/50 transition-colors ${getModalProgressColor((selectedVM.mem / selectedVM.maxmem) * 100)}`}
                                />
                              </div>

                              {/* Disk */}
                              <div>
                                <div className="text-xs text-muted-foreground mb-2">Disk</div>
                                <div
                                  className={`text-base font-semibold mb-2 ${getUsageColor((selectedVM.disk / selectedVM.maxdisk) * 100)}`}
                                >
                                  {(selectedVM.disk / 1024 ** 3).toFixed(1)} /{" "}
                                  {(selectedVM.maxdisk / 1024 ** 3).toFixed(1)} GB
                                </div>
                                <Progress
                                  value={(selectedVM.disk / selectedVM.maxdisk) * 100}
                                  className={`h-2 max-sm:bg-background sm:group-hover:bg-background/50 transition-colors ${getModalProgressColor((selectedVM.disk / selectedVM.maxdisk) * 100)}`}
                                />
                              </div>

                              {/* Disk I/O */}
                              <div>
                                <div className="text-xs text-muted-foreground mb-2">Disk I/O</div>
                                <div className="space-y-1">
                                  <div className="text-sm text-green-500 flex items-center gap-1">
                                    <span>↓</span>
                                    <span>{((selectedVM.diskread || 0) / 1024 ** 2).toFixed(2)} MB</span>
                                  </div>
                                  <div className="text-sm text-blue-500 flex items-center gap-1">
                                    <span>↑</span>
                                    <span>{((selectedVM.diskwrite || 0) / 1024 ** 2).toFixed(2)} MB</span>
                                  </div>
                                </div>
                              </div>

                              {/* Network I/O */}
                              <div>
                                <div className="text-xs text-muted-foreground mb-2">Network I/O</div>
                                <div className="space-y-1">
                                  <div className="text-sm text-green-500 flex items-center gap-1">
                                    <span>↓</span>
                                    <span>{formatNetworkTraffic(selectedVM.netin || 0, networkUnit)}</span>
                                  </div>
                                  <div className="text-sm text-blue-500 flex items-center gap-1">
                                    <span>↑</span>
                                    <span>{formatNetworkTraffic(selectedVM.netout || 0, networkUnit)}</span>
                                  </div>
                                </div>
                              </div>

                              <div className="flex items-center justify-center">
                                {getOSIcon(vmDetails?.os_info, selectedVM.type)}
                              </div>
                            </div>
                          </CardContent>
                        </Card>
                      </div>

                      {/* Backups Section */}
                      <Card className="border border-border bg-card/50">
                        <CardContent className="p-4">
                          <div className="flex items-center justify-between mb-4">
                            <div className="flex items-center gap-2">
                              <div className="p-1.5 rounded-md bg-amber-500/10">
                                <Archive className="h-4 w-4 text-amber-500" />
                              </div>
                              <h3 className="text-sm font-semibold text-foreground">Backups</h3>
                            </div>
                            <Button 
                              size="sm"
                              className="h-7 text-xs bg-amber-600/20 border border-amber-600/50 text-amber-400 hover:bg-amber-600/30 gap-1"
                              onClick={openBackupModal}
                              disabled={creatingBackup}
                            >
                              {creatingBackup ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Plus className="h-3 w-3" />
                              )}
                              <span>Create Backup</span>
                            </Button>
                          </div>
                          
                          {/* Backup List */}
                          <div className="flex items-center justify-between mb-3">
                            <span className="text-xs text-muted-foreground">Available backups</span>
                            <Badge variant="secondary" className="text-xs h-5">{vmBackups.length}</Badge>
                          </div>
                          
                          {loadingBackups ? (
                            <div className="flex items-center justify-center py-6 text-muted-foreground">
                              <Loader2 className="h-4 w-4 animate-spin mr-2" />
                              <span className="text-sm">Loading backups...</span>
                            </div>
                          ) : vmBackups.length === 0 ? (
                            <div className="flex flex-col items-center justify-center py-6 text-muted-foreground">
                              <Archive className="h-8 w-8 mb-2 opacity-30" />
                              <span className="text-sm">No backups found</span>
                            </div>
                          ) : (
                            <div className="space-y-1.5 max-h-[216px] overflow-y-auto">
                              {vmBackups.map((backup, index) => (
                                <div 
                                  key={`backup-${backup.volid}-${index}`}
                                  className="flex items-center justify-between p-2.5 rounded-lg bg-muted/30 hover:bg-muted/50 transition-colors"
                                >
                                  <div className="flex items-center gap-2 flex-1 min-w-0">
                                    <div className="w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0" />
                                    <Clock className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
                                    <span className="text-sm text-foreground">{backup.date}</span>
                                    <Badge 
                                      variant="outline" 
                                      className={`text-xs ml-auto flex-shrink-0 ${getStorageColor(backup.storage).bg} ${getStorageColor(backup.storage).text} ${getStorageColor(backup.storage).border}`}
                                    >
                                      {backup.storage}
                                    </Badge>
                                  </div>
                                  <Badge variant="outline" className="text-xs font-mono ml-2 flex-shrink-0">
                                    {backup.size_human}
                                  </Badge>
                                </div>
                              ))}
                            </div>
                          )}
                        </CardContent>
                      </Card>

                      {detailsLoading ? (
                        <div className="text-center py-8 text-muted-foreground">Loading configuration...</div>
                      ) : vmDetails?.config ? (
                        <>
                          <Card className="border border-border bg-card/50" key={`config-${selectedVM.vmid}`}>
                            <CardContent className="p-4">
                              <div className="flex items-center justify-between mb-4">
                                <div className="flex items-center gap-2">
                                  <div className="p-1.5 rounded-md bg-blue-500/10">
                                    <Cpu className="h-4 w-4 text-blue-500" />
                                  </div>
                                  <h3 className="text-sm font-semibold text-foreground">Resources</h3>
                                </div>
                                <div className="flex gap-2">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setShowNotes(!showNotes)}
                                    className="text-xs max-sm:bg-black/5 max-sm:dark:bg-white/5 sm:bg-transparent sm:hover:bg-black/5 sm:dark:hover:bg-white/5"
                                  >
                                    {showNotes ? (
                                      <>
                                        <ChevronUp className="h-3 w-3 mr-1" />
                                        Hide Notes
                                      </>
                                    ) : (
                                      <>
                                        <ChevronDown className="h-3 w-3 mr-1" />
                                        Notes
                                      </>
                                    )}
                                  </Button>
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setShowAdditionalInfo(!showAdditionalInfo)}
                                    className="text-xs max-sm:bg-black/5 max-sm:dark:bg-white/5 sm:bg-transparent sm:hover:bg-black/5 sm:dark:hover:bg-white/5"
                                  >
                                    {showAdditionalInfo ? (
                                      <>
                                        <ChevronUp className="h-3 w-3 mr-1" />
                                        Less Info
                                      </>
                                    ) : (
                                      <>
                                        <ChevronDown className="h-3 w-3 mr-1" />
                                        + Info
                                      </>
                                    )}
                                  </Button>
                                </div>
                              </div>

                              <div className="grid grid-cols-3 lg:grid-cols-4 gap-3 lg:gap-4">
                                {vmDetails.config.cores && (
                                  <div>
                                    <div className="text-xs text-muted-foreground mb-1">CPU Cores</div>
                                    <div className="font-semibold text-blue-500">{vmDetails.config.cores}</div>
                                  </div>
                                )}
                                {vmDetails.config.memory && (
                                  <div>
                                    <div className="text-xs text-muted-foreground mb-1">Memory</div>
                                    <div className="font-semibold text-blue-500">{vmDetails.config.memory} MB</div>
                                  </div>
                                )}
                                {vmDetails.config.swap && (
                                  <div>
                                    <div className="text-xs text-muted-foreground mb-1">Swap</div>
                                    <div className="font-semibold text-foreground">{vmDetails.config.swap} MB</div>
                                  </div>
                                )}
                              </div>

                              {/* IP Addresses with proper keys */}
                              {selectedVM?.type === "lxc" && vmDetails?.lxc_ip_info && (
                                <div className="mt-4 lg:mt-6 pt-4 lg:pt-6 border-t border-border">
                                  <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                    IP Addresses
                                  </h4>
                                  <div className="flex flex-wrap gap-2">
                                    {vmDetails.lxc_ip_info.real_ips.map((ip, index) => (
                                      <Badge
                                        key={`real-ip-${selectedVM.vmid}-${ip.replace(/[.:/]/g, "-")}-${index}`}
                                        variant="outline"
                                        className="bg-green-500/10 text-green-500 border-green-500/20"
                                      >
                                        {ip}
                                      </Badge>
                                    ))}
                                    {vmDetails.lxc_ip_info.docker_ips.map((ip, index) => (
                                      <Badge
                                        key={`docker-ip-${selectedVM.vmid}-${ip.replace(/[.:/]/g, "-")}-${index}`}
                                        variant="outline"
                                        className="bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                                      >
                                        {ip} (Bridge)
                                      </Badge>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {showNotes && (
                                <div className="mt-6 pt-6 border-t border-border">
                                  <div className="flex items-center justify-between mb-3">
                                    <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                                      Notes
                                    </h4>
                                    {!isEditingNotes && (
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={handleEditNotes}
                                        className="text-xs bg-transparent"
                                      >
                                        Edit
                                      </Button>
                                    )}
                                  </div>
                                  <div className="bg-muted/50 p-4 rounded-lg">
                                    {isEditingNotes ? (
                                      <div className="space-y-3">
                                        <textarea
                                          value={editedNotes}
                                          onChange={(e) => setEditedNotes(e.target.value)}
                                          className="w-full min-h-[200px] p-3 text-sm bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                                          placeholder="Enter notes here..."
                                        />
                                        <div className="flex gap-2 justify-end">
                                          <Button
                                            variant="outline"
                                            size="sm"
                                            onClick={handleCancelEditNotes}
                                            disabled={savingNotes}
                                          >
                                            Cancel
                                          </Button>
                                          <Button
                                            size="sm"
                                            onClick={handleSaveNotes}
                                            disabled={savingNotes}
                                            className="bg-blue-600 hover:bg-blue-700 text-white"
                                          >
                                            {savingNotes ? "Saving..." : "Save"}
                                          </Button>
                                        </div>
                                      </div>
                                    ) : vmDetails.config.description ? (
                                      <>
                                        {(() => {
                                          const processed = processDescription(vmDetails.config.description)
                                          if (processed.error) {
                                            return (
                                              <div className="text-sm text-red-500">
                                                Error decoding notes. Please edit to fix.
                                              </div>
                                            )
                                          }
                                          return (
                                            <div
                                              className={`text-sm text-foreground ${processed.isHtml ? "proxmenux-notes" : "proxmenux-notes-plaintext"}`}
                                              dangerouslySetInnerHTML={{ __html: processed.html }}
                                            />
                                          )
                                        })()}
                                      </>
                                    ) : (
                                      <div className="text-sm text-muted-foreground italic">
                                        No notes yet. Click Edit to add notes.
                                      </div>
                                    )}
                                  </div>
                                </div>
                              )}

                              {showAdditionalInfo && (
                                <div className="mt-6 pt-6 border-t border-border space-y-6">
                                  {selectedVM?.type === "lxc" && vmDetails?.hardware_info && (
                                    <div>
                                      <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        Container Configuration
                                      </h4>
                                      <div className="space-y-4">
                                        {/* Privileged Status */}
                                        {vmDetails.hardware_info.privileged !== null &&
                                          vmDetails.hardware_info.privileged !== undefined && (
                                            <div>
                                              <div className="text-xs text-muted-foreground mb-2">Privilege Level</div>
                                              <Badge
                                                variant="outline"
                                                className={
                                                  vmDetails.hardware_info.privileged
                                                    ? "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                                                    : "bg-green-500/10 text-green-500 border-green-500/20"
                                                }
                                              >
                                                {vmDetails.hardware_info.privileged ? "Privileged" : "Unprivileged"}
                                              </Badge>
                                            </div>
                                          )}

                                        {/* GPU Passthrough with proper keys */}
                                        {vmDetails.hardware_info.gpu_passthrough &&
                                          vmDetails.hardware_info.gpu_passthrough.length > 0 && (
                                            <div>
                                              <div className="text-xs text-muted-foreground mb-2">GPU Passthrough</div>
                                              <div className="flex flex-wrap gap-2">
                                                {vmDetails.hardware_info.gpu_passthrough.map((gpu, index) => (
                                                  <Badge
                                                    key={`gpu-${selectedVM.vmid}-${index}-${gpu.replace(/[^a-zA-Z0-9]/g, "-").substring(0, 30)}`}
                                                    variant="outline"
                                                    className={
                                                      gpu.includes("NVIDIA")
                                                        ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                        : "bg-purple-500/10 text-purple-500 border-purple-500/20"
                                                    }
                                                  >
                                                    {gpu}
                                                  </Badge>
                                                ))}
                                              </div>
                                            </div>
                                          )}

                                        {/* Hardware Devices with proper keys */}
                                        {vmDetails.hardware_info.devices &&
                                          vmDetails.hardware_info.devices.length > 0 && (
                                            <div>
                                              <div className="text-xs text-muted-foreground mb-2">Hardware Devices</div>
                                              <div className="flex flex-wrap gap-2">
                                                {vmDetails.hardware_info.devices.map((device, index) => (
                                                  <Badge
                                                    key={`device-${selectedVM.vmid}-${index}-${device.replace(/[^a-zA-Z0-9]/g, "-").substring(0, 30)}`}
                                                    variant="outline"
                                                    className="bg-blue-500/10 text-blue-500 border-blue-500/20"
                                                  >
                                                    {device}
                                                  </Badge>
                                                ))}
                                              </div>
                                            </div>
                                          )}
                                      </div>
                                    </div>
                                  )}

                                  {/* Hardware Section */}
                                  <div>
                                    <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                      Hardware
                                    </h4>
                                    <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                                      {vmDetails.config.sockets && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">CPU Sockets</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.sockets}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.cpu && (
                                        <div className="col-span-2">
                                          <div className="text-xs text-muted-foreground mb-1">CPU Type</div>
                                          <div className="font-medium text-foreground text-sm font-mono">
                                            {vmDetails.config.cpu}
                                          </div>
                                        </div>
                                      )}
                                      {vmDetails.config.numa !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">NUMA</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.numa
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.numa ? "Enabled" : "Disabled"}
                                          </Badge>
                                        </div>
                                      )}
                                      {vmDetails.config.bios && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">BIOS</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.bios}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.machine && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">Machine Type</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.machine}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.vga && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">VGA</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.vga}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.agent !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">QEMU Agent</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.agent
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.agent ? "Enabled" : "Disabled"}
                                          </Badge>
                                        </div>
                                      )}
                                      {vmDetails.config.tablet !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">Tablet Pointer</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.tablet
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.tablet ? "Enabled" : "Disabled"}
                                          </Badge>
                                        </div>
                                      )}
                                      {vmDetails.config.localtime !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">Local Time</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.localtime
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-gray-500/10 text-gray-500 border-gray-500/20"
                                            }
                                          >
                                            {vmDetails.config.localtime ? "Enabled" : "Disabled"}
                                          </Badge>
                                        </div>
                                      )}
                                    </div>
                                  </div>

                                  {/* Storage Section */}
                                  <div>
                                    <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                      Storage
                                    </h4>
                                    <div className="space-y-3">
                                      {vmDetails.config.rootfs && (
                                        <div key="rootfs">
                                          <div className="text-xs text-muted-foreground mb-1">Root Filesystem</div>
                                          <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                            {vmDetails.config.rootfs}
                                          </div>
                                        </div>
                                      )}
                                      {vmDetails.config.scsihw && (
                                        <div key="scsihw">
                                          <div className="text-xs text-muted-foreground mb-1">SCSI Controller</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.scsihw}</div>
                                        </div>
                                      )}
                                      {/* Disk Storage with proper keys */}
                                      {Object.keys(vmDetails.config)
                                        .filter((key) => key.match(/^(scsi|sata|ide|virtio)\d+$/))
                                        .map((diskKey) => (
                                          <div key={`disk-${selectedVM.vmid}-${diskKey}`}>
                                            <div className="text-xs text-muted-foreground mb-1">
                                              {diskKey.toUpperCase().replace(/(\d+)/, " $1")}
                                            </div>
                                            <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                              {vmDetails.config[diskKey]}
                                            </div>
                                          </div>
                                        ))}
                                      {vmDetails.config.efidisk0 && (
                                        <div key="efidisk0">
                                          <div className="text-xs text-muted-foreground mb-1">EFI Disk</div>
                                          <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                            {vmDetails.config.efidisk0}
                                          </div>
                                        </div>
                                      )}
                                      {vmDetails.config.tpmstate0 && (
                                        <div key="tpmstate0">
                                          <div className="text-xs text-muted-foreground mb-1">TPM State</div>
                                          <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                            {vmDetails.config.tpmstate0}
                                          </div>
                                        </div>
                                      )}
                                      {/* Mount Points with proper keys */}
                                      {Object.keys(vmDetails.config)
                                        .filter((key) => key.match(/^mp\d+$/))
                                        .map((mpKey) => (
                                          <div key={`mp-${selectedVM.vmid}-${mpKey}`}>
                                            <div className="text-xs text-muted-foreground mb-1">
                                              Mount Point {mpKey.replace("mp", "")}
                                            </div>
                                            <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                              {vmDetails.config[mpKey]}
                                            </div>
                                          </div>
                                        ))}
                                    </div>
                                  </div>

                                  {/* Network Section */}
                                  <div>
                                    <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                      Network
                                    </h4>
                                    <div className="space-y-3">
                                      {/* Network Interfaces with proper keys */}
                                      {Object.keys(vmDetails.config)
                                        .filter((key) => key.match(/^net\d+$/))
                                        .map((netKey) => (
                                          <div key={`net-${selectedVM.vmid}-${netKey}`}>
                                            <div className="text-xs text-muted-foreground mb-1">
                                              Network Interface {netKey.replace("net", "")}
                                            </div>
                                            <div className="font-medium text-green-500 text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                              {vmDetails.config[netKey]}
                                            </div>
                                          </div>
                                        ))}
                                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                        {vmDetails.config.nameserver && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">DNS Nameserver</div>
                                            <div className="font-medium text-foreground font-mono">
                                              {vmDetails.config.nameserver}
                                            </div>
                                          </div>
                                        )}
                                        {vmDetails.config.searchdomain && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">Search Domain</div>
                                            <div className="font-medium text-foreground">
                                              {vmDetails.config.searchdomain}
                                            </div>
                                          </div>
                                        )}
                                        {vmDetails.config.hostname && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">Hostname</div>
                                            <div className="font-medium text-foreground">
                                              {vmDetails.config.hostname}
                                            </div>
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  </div>

                                  {/* PCI Devices with proper keys */}
                                  {Object.keys(vmDetails.config).some((key) => key.match(/^hostpci\d+$/)) && (
                                    <div>
                                      <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        PCI Passthrough
                                      </h4>
                                      <div className="space-y-3">
                                        {Object.keys(vmDetails.config)
                                          .filter((key) => key.match(/^hostpci\d+$/))
                                          .map((pciKey) => (
                                            <div key={`pci-${selectedVM.vmid}-${pciKey}`}>
                                              <div className="text-xs text-muted-foreground mb-1">
                                                {pciKey.toUpperCase().replace(/(\d+)/, " $1")}
                                              </div>
                                              <div className="font-medium text-purple-500 text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                                {vmDetails.config[pciKey]}
                                              </div>
                                            </div>
                                          ))}
                                      </div>
                                    </div>
                                  )}

                                  {/* USB Devices with proper keys */}
                                  {Object.keys(vmDetails.config).some((key) => key.match(/^usb\d+$/)) && (
                                    <div>
                                      <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        USB Devices
                                      </h4>
                                      <div className="space-y-3">
                                        {Object.keys(vmDetails.config)
                                          .filter((key) => key.match(/^usb\d+$/))
                                          .map((usbKey) => (
                                            <div key={`usb-${selectedVM.vmid}-${usbKey}`}>
                                              <div className="text-xs text-muted-foreground mb-1">
                                                {usbKey.toUpperCase().replace(/(\d+)/, " $1")}
                                              </div>
                                              <div className="font-medium text-blue-500 text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                                {vmDetails.config[usbKey]}
                                              </div>
                                            </div>
                                          ))}
                                      </div>
                                    </div>
                                  )}

                                  {/* Serial Ports with proper keys */}
                                  {Object.keys(vmDetails.config).some((key) => key.match(/^serial\d+$/)) && (
                                    <div>
                                      <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        Serial Ports
                                      </h4>
                                      <div className="space-y-3">
                                        {Object.keys(vmDetails.config)
                                          .filter((key) => key.match(/^serial\d+$/))
                                          .map((serialKey) => (
                                            <div key={`serial-${selectedVM.vmid}-${serialKey}`}>
                                              <div className="text-xs text-muted-foreground mb-1">
                                                {serialKey.toUpperCase().replace(/(\d+)/, " $1")}
                                              </div>
                                              <div className="font-medium text-foreground font-mono">
                                                {vmDetails.config[serialKey]}
                                              </div>
                                            </div>
                                          ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )}
                            </CardContent>
                          </Card>
                        </>
                      ) : null}
                    </>
                  )}
                </div>
              </div>

              <div className="border-t border-border bg-background px-6 py-4 mt-auto">
                {/* Terminal button for LXC containers - only when running */}
                {selectedVM?.type === "lxc" && selectedVM?.status === "running" && (
                  <div className="mb-3">
                    <Button
                      className="w-full bg-zinc-600/20 border border-zinc-600/50 text-zinc-300 hover:bg-zinc-600/30"
                      onClick={() => selectedVM && openLxcTerminal(selectedVM.vmid, selectedVM.name)}
                    >
                      <Terminal className="h-4 w-4 mr-2" />
                      Open Terminal
                    </Button>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <Button
                    className="w-full bg-green-600/20 border border-green-600/50 text-green-400 hover:bg-green-600/30"
                    disabled={selectedVM?.status === "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "start")}
                  >
                    <Play className="h-4 w-4 mr-2" />
                    Start
                  </Button>
                  <Button
                    className="w-full bg-blue-600/20 border border-blue-600/50 text-blue-400 hover:bg-blue-600/30"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "shutdown")}
                  >
                    <Power className="h-4 w-4 mr-2" />
                    Shutdown
                  </Button>
                  <Button
                    className="w-full bg-blue-600/20 border border-blue-600/50 text-blue-400 hover:bg-blue-600/30"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "reboot")}
                  >
                    <RotateCcw className="h-4 w-4 mr-2" />
                    Reboot
                  </Button>
                  <Button
                    className="w-full bg-red-600/20 border border-red-600/50 text-red-400 hover:bg-red-600/30"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "stop")}
                  >
                    <StopCircle className="h-4 w-4 mr-2" />
                    Force Stop
                  </Button>
                </div>
              </div>
            </>
          ) : (
            selectedVM && (
              <MetricsView
                vmid={selectedVM.vmid}
                vmName={selectedVM.name}
                vmType={selectedVM.type as "qemu" | "lxc"}
                onBack={handleBackToMain}
              />
            )
          )}
        </DialogContent>
      </Dialog>

      {/* Backup Configuration Modal */}
      <Dialog open={showBackupModal} onOpenChange={setShowBackupModal}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-amber-500">
              <Archive className="h-5 w-5" />
              Backup {selectedVM?.type?.toUpperCase()} {selectedVM?.vmid} ({selectedVM?.name})
            </DialogTitle>
            <DialogDescription>
              Configure backup options for this {selectedVM?.type === 'lxc' ? 'container' : 'virtual machine'}
            </DialogDescription>
          </DialogHeader>
          
          <div className="grid gap-4 py-4">
            {/* Storage & Mode Row */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-sm flex items-center gap-1.5">
                  <Database className="h-3.5 w-3.5" />
                  Storage
                </Label>
                <Select value={selectedBackupStorage} onValueChange={setSelectedBackupStorage}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select storage" />
                  </SelectTrigger>
                  <SelectContent>
                    {backupStorages.map((storage) => (
                      <SelectItem key={`modal-storage-${storage.storage}`} value={storage.storage}>
                        {storage.storage} ({storage.avail_human} free)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              
              <div className="space-y-2">
                <Label className="text-sm flex items-center gap-1.5">
                  <Settings2 className="h-3.5 w-3.5" />
                  Mode
                </Label>
                <Select value={backupMode} onValueChange={setBackupMode}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="snapshot">Snapshot</SelectItem>
                    <SelectItem value="suspend">Suspend</SelectItem>
                    <SelectItem value="stop">Stop</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            
            {/* Notification Row */}
            <div className="space-y-2">
              <Label className="text-sm flex items-center gap-1.5">
                <Bell className="h-3.5 w-3.5" />
                Notification
              </Label>
              <Select value={backupNotification} onValueChange={setBackupNotification}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Use global settings</SelectItem>
                  <SelectItem value="always">Always notify</SelectItem>
                  <SelectItem value="failure">Notify on failure</SelectItem>
                  <SelectItem value="never">Never notify</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            {/* Protected Checkbox */}
            <div className="flex items-center space-x-2">
              <Checkbox 
                id="backup-protected" 
                checked={backupProtected}
                onCheckedChange={(checked) => setBackupProtected(checked === true)}
              />
              <Label htmlFor="backup-protected" className="text-sm flex items-center gap-1.5 cursor-pointer">
                <Shield className="h-3.5 w-3.5" />
                Protected (prevent accidental deletion)
              </Label>
            </div>
            
            {/* PBS Change Detection Mode (only for LXC) */}
            {selectedVM?.type === 'lxc' && (
              <div className="space-y-2">
                <Label className="text-sm flex items-center gap-1.5">
                  <Settings2 className="h-3.5 w-3.5" />
                  PBS change detection mode
                  <span className="text-xs text-muted-foreground ml-1">(for PBS storage)</span>
                </Label>
                <Select value={backupPbsChangeMode} onValueChange={setBackupPbsChangeMode}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">Default</SelectItem>
                    <SelectItem value="legacy">Legacy</SelectItem>
                    <SelectItem value="data">Data</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
            
            {/* Notes */}
            <div className="space-y-2">
              <Label className="text-sm flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5" />
                Notes
              </Label>
              <Textarea 
                value={backupNotes}
                onChange={(e) => setBackupNotes(e.target.value)}
                placeholder="{{guestname}}"
                className="min-h-[80px] resize-none"
              />
              <p className="text-xs text-muted-foreground">
                {'Variables: {{cluster}}, {{guestname}}, {{node}}, {{vmid}}'}
              </p>
            </div>
          </div>
          
          <div className="flex items-center gap-3 pt-4">
            <Button 
              variant="outline" 
              onClick={() => setShowBackupModal(false)}
              className="flex-1 bg-zinc-800/50 border-zinc-700 text-zinc-300 hover:bg-zinc-700/50"
            >
              Cancel
            </Button>
            <Button 
              onClick={handleCreateBackup}
              disabled={creatingBackup || !selectedBackupStorage}
              className="flex-1 bg-amber-600/20 border border-amber-600/50 text-amber-400 hover:bg-amber-600/30"
            >
              {creatingBackup ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Creating...
                </>
              ) : (
                <>
                  <Archive className="h-4 w-4 mr-2" />
                  Backup
                </>
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* LXC Terminal Modal */}
      {terminalVmid !== null && (
        <LxcTerminalModal
          open={terminalOpen}
          onClose={() => {
            setTerminalOpen(false)
            setTerminalVmid(null)
            setTerminalVmName("")
          }}
          vmid={terminalVmid}
          vmName={terminalVmName}
        />
      )}
    </div>
  )
}
