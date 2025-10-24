"use client"

import type React from "react"

import { useState, useMemo, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Progress } from "./ui/progress"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog"
import {
  Server,
  Play,
  Square,
  Cpu,
  MemoryStick,
  HardDrive,
  Network,
  Power,
  RotateCcw,
  StopCircle,
  Container,
  ChevronDown,
  ChevronUp,
} from "lucide-react"
import useSWR from "swr"
import { MetricsView } from "./metrics-dialog"

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
}

const fetcher = async (url: string) => {
  const response = await fetch(url, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
    signal: AbortSignal.timeout(5000),
  })

  if (!response.ok) {
    throw new Error(`Flask server responded with status: ${response.status}`)
  }

  const data = await response.json()
  return data
}

const formatBytes = (bytes: number | undefined): string => {
  if (!bytes || bytes === 0) return "0 B"
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

const extractIPFromConfig = (config?: VMConfig): string => {
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

const formatStorage = (sizeInGB: number): string => {
  if (sizeInGB < 1) {
    // Less than 1 GB, show in MB
    return `${(sizeInGB * 1024).toFixed(1)} MB`
  } else if (sizeInGB < 1024) {
    // Less than 1024 GB, show in GB
    return `${sizeInGB.toFixed(1)} GB`
  } else {
    // 1024 GB or more, show in TB
    return `${(sizeInGB / 1024).toFixed(1)} TB`
  }
}

const getUsageColor = (percent: number): string => {
  if (percent >= 95) return "text-red-500"
  if (percent >= 86) return "text-orange-500"
  if (percent >= 71) return "text-yellow-500"
  return "text-foreground"
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
    refreshInterval: 30000,
    revalidateOnFocus: false,
    revalidateOnReconnect: true,
  })

  const [selectedVM, setSelectedVM] = useState<VMData | null>(null)
  const [vmDetails, setVMDetails] = useState<VMDetails | null>(null)
  const [controlLoading, setControlLoading] = useState(false)
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [vmConfigs, setVmConfigs] = useState<Record<number, string>>({})
  const [currentView, setCurrentView] = useState<"main" | "metrics">("main")
  const [showAdditionalInfo, setShowAdditionalInfo] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  const [isEditingNotes, setIsEditingNotes] = useState(false)
  const [editedNotes, setEditedNotes] = useState("")
  const [savingNotes, setSavingNotes] = useState(false)
  const [selectedMetric, setSelectedMetric] = useState<string | null>(null)

  useEffect(() => {
    const fetchLXCIPs = async () => {
      if (!vmData) return

      const lxcs = vmData.filter((vm) => vm.type === "lxc")
      const configs: Record<number, string> = {}

      await Promise.all(
        lxcs.map(async (lxc) => {
          try {
            const response = await fetch(`/api/vms/${lxc.vmid}`)
            if (response.ok) {
              const details = await response.json()
              if (details.config) {
                configs[lxc.vmid] = extractIPFromConfig(details.config)
              }
            }
          } catch (error) {
            console.error(`Error fetching config for LXC ${lxc.vmid}:`, error)
          }
        }),
      )

      setVmConfigs(configs)
    }

    fetchLXCIPs()
  }, [vmData])

  const handleVMClick = async (vm: VMData) => {
    setSelectedVM(vm)
    setCurrentView("main")
    setShowAdditionalInfo(false)
    setShowNotes(false)
    setIsEditingNotes(false)
    setEditedNotes("")
    setDetailsLoading(true)
    try {
      const response = await fetch(`/api/vms/${vm.vmid}`)
      if (response.ok) {
        const details = await response.json()
        setVMDetails(details)
      }
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

  const handleVMControl = async (vmid: number, action: string) => {
    setControlLoading(true)
    try {
      const response = await fetch(`/api/vms/${vmid}/control`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action }),
      })

      if (response.ok) {
        mutate()
        setSelectedVM(null)
        setVMDetails(null)
      } else {
        console.error("Failed to control VM")
      }
    } catch (error) {
      console.error("Error controlling VM:", error)
    } finally {
      setControlLoading(false)
    }
  }

  const handleDownloadLogs = async (vmid: number, vmName: string) => {
    try {
      const response = await fetch(`/api/vms/${vmid}/logs`)
      if (response.ok) {
        const data = await response.json()

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
      }
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

  const totalAllocatedMemoryGB = useMemo(() => {
    return (safeVMData.reduce((sum, vm) => sum + (vm.maxmem || 0), 0) / 1024 ** 3).toFixed(1)
  }, [safeVMData])

  const { data: systemData } = useSWR<{ memory_total: number; memory_used: number; memory_usage: number }>(
    "/api/system",
    fetcher,
    {
      refreshInterval: 30000,
      revalidateOnFocus: false,
    },
  )

  const physicalMemoryGB = systemData?.memory_total ?? null
  const usedMemoryGB = systemData?.memory_used ?? null
  const memoryUsagePercent = systemData?.memory_usage ?? null
  const allocatedMemoryGB = Number.parseFloat(totalAllocatedMemoryGB)
  const isMemoryOvercommit = physicalMemoryGB !== null && allocatedMemoryGB > physicalMemoryGB

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
      const response = await fetch(`/api/vms/${selectedVM.vmid}/config`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          description: editedNotes, // Send as-is, pvesh will handle encoding
        }),
      })

      if (response.ok) {
        setVMDetails({
          ...vmDetails,
          config: {
            ...vmDetails.config,
            description: editedNotes, // Store unencoded
          },
        })
        setIsEditingNotes(false)
      } else {
        console.error("Failed to save notes")
        alert("Failed to save notes. Please try again.")
      }
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

            {/* Allocated RAM (configured) */}
            <div className="pt-3 border-t border-border">
              {/* Layout para desktop (sin cambios) */}
              <div className="hidden lg:flex items-center justify-between">
                <div>
                  <div className="text-lg font-semibold text-foreground">{totalAllocatedMemoryGB} GB</div>
                  <div className="text-xs text-muted-foreground">Allocated RAM</div>
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

              {/* Layout para móvil (44.0 GB y Allocated RAM en la misma línea, badge debajo) */}
              <div className="lg:hidden space-y-2">
                <div className="flex items-baseline gap-2">
                  <div className="text-lg font-semibold text-foreground">{totalAllocatedMemoryGB} GB</div>
                  <div className="text-xs text-muted-foreground">Allocated RAM</div>
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
                          <div className="font-semibold text-foreground truncate">{vm.name}</div>
                          <div className="text-[10px] text-muted-foreground">ID: {vm.vmid}</div>
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
                              <span className="text-green-500">↓ {formatBytes(vm.diskread)}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <HardDrive className="h-3 w-3 text-blue-500" />
                              <span className="text-blue-500">↑ {formatBytes(vm.diskwrite)}</span>
                            </div>
                          </div>
                        </div>

                        <div>
                          <div className="text-xs text-muted-foreground mb-1">Network I/O</div>
                          <div className="text-sm font-semibold space-y-0.5">
                            <div className="flex items-center gap-1">
                              <Network className="h-3 w-3 text-green-500" />
                              <span className="text-green-500">↓ {formatBytes(vm.netin)}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Network className="h-3 w-3 text-blue-500" />
                              <span className="text-blue-500">↑ {formatBytes(vm.netout)}</span>
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
        <DialogContent className="max-w-4xl h-[95vh] sm:h-[90vh] flex flex-col p-0 overflow-hidden">
          {currentView === "main" ? (
            <>
              <DialogHeader className="pb-4 border-b border-border px-6 pt-6">
                <DialogTitle className="flex flex-col gap-3">
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
                        </div>
                        {selectedVM.status === "running" && (
                          <span className="text-sm text-muted-foreground ml-auto">
                            Uptime: {formatUptime(selectedVM.uptime)}
                          </span>
                        )}
                      </>
                    )}
                  </div>
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

              <div className="flex-1 overflow-y-auto px-6 py-4">
                <div className="space-y-6">
                  {selectedVM && (
                    <>
                      <div>
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
                                    <span>{((selectedVM.netin || 0) / 1024 ** 2).toFixed(2)} MB</span>
                                  </div>
                                  <div className="text-sm text-blue-500 flex items-center gap-1">
                                    <span>↑</span>
                                    <span>{((selectedVM.netout || 0) / 1024 ** 2).toFixed(2)} MB</span>
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

                      {detailsLoading ? (
                        <div className="text-center py-8 text-muted-foreground">Loading configuration...</div>
                      ) : vmDetails?.config ? (
                        <>
                          <Card className="border border-border bg-card/50">
                            <CardContent className="p-4">
                              <div className="flex items-center justify-between mb-4">
                                <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                                  Resources
                                </h3>
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
                                        <ChevronDown className="h-3 w-3 mr-1" />+ Info
                                      </>
                                    )}
                                  </Button>
                                </div>
                              </div>

                              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
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
                                {selectedVM.type === "lxc" && (
                                  <div>
                                    <div className="text-xs text-muted-foreground mb-1">IP Address</div>
                                    <div
                                      className={`font-semibold ${extractIPFromConfig(vmDetails.config) === "DHCP" ? "text-yellow-500" : "text-green-500"}`}
                                    >
                                      {extractIPFromConfig(vmDetails.config)}
                                    </div>
                                  </div>
                                )}
                              </div>

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
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">Root Filesystem</div>
                                          <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                            {vmDetails.config.rootfs}
                                          </div>
                                        </div>
                                      )}
                                      {vmDetails.config.scsihw && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">SCSI Controller</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.scsihw}</div>
                                        </div>
                                      )}
                                      {Object.keys(vmDetails.config)
                                        .filter((key) => key.match(/^(scsi|sata|ide|virtio)\d+$/))
                                        .map((diskKey) => (
                                          <div key={diskKey}>
                                            <div className="text-xs text-muted-foreground mb-1">
                                              {diskKey.toUpperCase().replace(/(\d+)/, " $1")}
                                            </div>
                                            <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                              {vmDetails.config[diskKey]}
                                            </div>
                                          </div>
                                        ))}
                                      {vmDetails.config.efidisk0 && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">EFI Disk</div>
                                          <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                            {vmDetails.config.efidisk0}
                                          </div>
                                        </div>
                                      )}
                                      {vmDetails.config.tpmstate0 && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">TPM State</div>
                                          <div className="font-medium text-foreground text-sm break-all font-mono bg-muted/50 p-2 rounded">
                                            {vmDetails.config.tpmstate0}
                                          </div>
                                        </div>
                                      )}
                                      {/* Mount points for LXC */}
                                      {Object.keys(vmDetails.config)
                                        .filter((key) => key.match(/^mp\d+$/))
                                        .map((mpKey) => (
                                          <div key={mpKey}>
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
                                      {Object.keys(vmDetails.config)
                                        .filter((key) => key.match(/^net\d+$/))
                                        .map((netKey) => (
                                          <div key={netKey}>
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

                                  {/* PCI Devices Section */}
                                  {Object.keys(vmDetails.config).some((key) => key.match(/^hostpci\d+$/)) && (
                                    <div>
                                      <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        PCI Passthrough
                                      </h4>
                                      <div className="space-y-3">
                                        {Object.keys(vmDetails.config)
                                          .filter((key) => key.match(/^hostpci\d+$/))
                                          .map((pciKey) => (
                                            <div key={pciKey}>
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

                                  {/* USB Devices Section */}
                                  {Object.keys(vmDetails.config).some((key) => key.match(/^usb\d+$/)) && (
                                    <div>
                                      <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        USB Devices
                                      </h4>
                                      <div className="space-y-3">
                                        {Object.keys(vmDetails.config)
                                          .filter((key) => key.match(/^usb\d+$/))
                                          .map((usbKey) => (
                                            <div key={usbKey}>
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

                                  {/* Serial Devices Section */}
                                  {Object.keys(vmDetails.config).some((key) => key.match(/^serial\d+$/)) && (
                                    <div>
                                      <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        Serial Ports
                                      </h4>
                                      <div className="space-y-3">
                                        {Object.keys(vmDetails.config)
                                          .filter((key) => key.match(/^serial\d+$/))
                                          .map((serialKey) => (
                                            <div key={serialKey}>
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

                                  {/* Options Section */}
                                  <div>
                                    <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                      Options
                                    </h4>
                                    <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                                      {vmDetails.config.onboot !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">Start on Boot</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.onboot
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-red-500/10 text-red-500 border-red-500/20"
                                            }
                                          >
                                            {vmDetails.config.onboot ? "Yes" : "No"}
                                          </Badge>
                                        </div>
                                      )}
                                      {vmDetails.config.unprivileged !== undefined && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">Unprivileged</div>
                                          <Badge
                                            variant="outline"
                                            className={
                                              vmDetails.config.unprivileged
                                                ? "bg-green-500/10 text-green-500 border-green-500/20"
                                                : "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                                            }
                                          >
                                            {vmDetails.config.unprivileged ? "Yes" : "No"}
                                          </Badge>
                                        </div>
                                      )}
                                      {vmDetails.config.ostype && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">OS Type</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.ostype}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.arch && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">Architecture</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.arch}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.boot && (
                                        <div>
                                          <div className="text-xs text-muted-foreground mb-1">Boot Order</div>
                                          <div className="font-medium text-foreground">{vmDetails.config.boot}</div>
                                        </div>
                                      )}
                                      {vmDetails.config.features && (
                                        <div className="col-span-2 lg:col-span-3">
                                          <div className="text-xs text-muted-foreground mb-1">Features</div>
                                          <div className="font-medium text-foreground text-sm">
                                            {vmDetails.config.features}
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  </div>

                                  {/* Advanced Section */}
                                  {(vmDetails.config.vmgenid || vmDetails.config.smbios1 || vmDetails.config.meta) && (
                                    <div>
                                      <h4 className="text-sm font-semibold text-muted-foreground mb-3 uppercase tracking-wide">
                                        Advanced
                                      </h4>
                                      <div className="space-y-3">
                                        {vmDetails.config.vmgenid && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">VM Generation ID</div>
                                            <div className="font-medium text-muted-foreground text-sm font-mono">
                                              {vmDetails.config.vmgenid}
                                            </div>
                                          </div>
                                        )}
                                        {vmDetails.config.smbios1 && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">SMBIOS</div>
                                            <div className="font-medium text-muted-foreground text-sm font-mono break-all">
                                              {vmDetails.config.smbios1}
                                            </div>
                                          </div>
                                        )}
                                        {vmDetails.config.meta && (
                                          <div>
                                            <div className="text-xs text-muted-foreground mb-1">Metadata</div>
                                            <div className="font-medium text-muted-foreground text-sm font-mono">
                                              {vmDetails.config.meta}
                                            </div>
                                          </div>
                                        )}
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
                <div className="grid grid-cols-2 gap-3">
                  <Button
                    className="w-full bg-green-600 hover:bg-green-700 text-white"
                    disabled={selectedVM?.status === "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "start")}
                  >
                    <Play className="h-4 w-4 mr-2" />
                    Start
                  </Button>
                  <Button
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "shutdown")}
                  >
                    <Power className="h-4 w-4 mr-2" />
                    Shutdown
                  </Button>
                  <Button
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white"
                    disabled={selectedVM?.status !== "running" || controlLoading}
                    onClick={() => selectedVM && handleVMControl(selectedVM.vmid, "reboot")}
                  >
                    <RotateCcw className="h-4 w-4 mr-2" />
                    Reboot
                  </Button>
                  <Button
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white"
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
    </div>
  )
}
