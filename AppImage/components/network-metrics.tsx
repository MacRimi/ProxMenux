"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog"
import { Wifi, Activity, Network, Router, AlertCircle, Zap } from "lucide-react"
import useSWR from "swr"
import { NetworkTrafficChart } from "./network-traffic-chart"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"

interface NetworkData {
  interfaces: NetworkInterface[]
  physical_interfaces?: NetworkInterface[]
  bridge_interfaces?: NetworkInterface[]
  vm_lxc_interfaces?: NetworkInterface[]
  traffic: {
    bytes_sent: number
    bytes_recv: number
    packets_sent?: number
    packets_recv?: number
    packet_loss_in?: number
    packet_loss_out?: number
    dropin?: number
    dropout?: number
    errin?: number
    errout?: number
  }
  active_count?: number
  total_count?: number
  physical_active_count?: number
  physical_total_count?: number
  bridge_active_count?: number
  bridge_total_count?: number
  vm_lxc_active_count?: number
  vm_lxc_total_count?: number
}

interface NetworkInterface {
  name: string
  type: string
  status: string
  speed: number
  duplex: string
  mtu: number
  mac_address: string | null
  addresses: Array<{
    ip: string
    netmask: string
  }>
  bytes_sent?: number
  bytes_recv?: number
  packets_sent?: number
  packets_recv?: number
  errors_in?: number
  errors_out?: number
  drops_in?: number
  drops_out?: number
  bond_mode?: string
  bond_slaves?: string[]
  bond_active_slave?: string | null
  bridge_members?: string[]
  bridge_physical_interface?: string
  bridge_bond_slaves?: string[]
  packet_loss_in?: number
  packet_loss_out?: number
  vmid?: number
  vm_name?: string
  vm_type?: string
  vm_status?: string
}

interface FirewallStatus {
  service_active: boolean
  firewall_enabled: boolean
  active: boolean
  rules_count: number
  status: string
}

interface DNSConfig {
  dns_servers: string[]
  search_domains: string[]
  dns_working: boolean
  primary_dns: string | null
  secondary_dns: string | null
}

const getInterfaceTypeBadge = (type: string) => {
  switch (type) {
    case "physical":
      return { color: "bg-blue-500/10 text-blue-500 border-blue-500/20", label: "Physical" }
    case "bridge":
      return { color: "bg-green-500/10 text-green-500 border-green-500/20", label: "Bridge" }
    case "bond":
      return { color: "bg-purple-500/10 text-purple-500 border-purple-500/20", label: "Bond" }
    case "vlan":
      return { color: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20", label: "VLAN" }
    case "vm_lxc":
      return { color: "bg-orange-500/10 text-orange-500 border-orange-500/20", label: "Virtual" }
    case "virtual":
      return { color: "bg-orange-500/10 text-orange-500 border-orange-500/20", label: "Virtual" }
    default:
      return { color: "bg-gray-500/10 text-gray-500 border-gray-500/20", label: "Unknown" }
  }
}

const getVMTypeBadge = (vmType: string | undefined) => {
  if (vmType === "lxc") {
    return { color: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20", label: "LXC" }
  } else if (vmType === "vm") {
    return { color: "bg-purple-500/10 text-purple-500 border-purple-500/20", label: "VM" }
  }
  return { color: "bg-gray-500/10 text-gray-500 border-gray-500/20", label: "Unknown" }
}

const formatBytes = (bytes: number | undefined): string => {
  if (!bytes || bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

const formatStorage = (bytes: number): string => {
  if (bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB", "PB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  const value = bytes / Math.pow(k, i)

  // Use 1 decimal place for values >= 10, 2 decimal places for values < 10
  const decimals = value >= 10 ? 1 : 2
  return `${value.toFixed(decimals)} ${sizes[i]}`
}

const formatSpeed = (speed: number): string => {
  if (speed === 0) return "N/A"
  if (speed >= 1000) return `${(speed / 1000).toFixed(1)} Gbps`
  return `${speed} Mbps`
}

const fetcher = async (url: string): Promise<NetworkData> => {
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

  return response.json()
}

export function NetworkMetrics() {
  const {
    data: networkData,
    error,
    isLoading,
  } = useSWR<NetworkData>("/api/network", fetcher, {
    refreshInterval: 30000, // Refresh every 30 seconds
    revalidateOnFocus: false,
    revalidateOnReconnect: true,
  })

  const { data: firewallData } = useSWR<FirewallStatus>("/api/firewall/status", fetcher, {
    refreshInterval: 60000,
    revalidateOnFocus: false,
  })

  const { data: dnsData } = useSWR<DNSConfig>("/api/dns/config", fetcher, {
    refreshInterval: 60000,
    revalidateOnFocus: false,
  })

  const [selectedInterface, setSelectedInterface] = useState<NetworkInterface | null>(null)
  const [timeframe, setTimeframe] = useState<"hour" | "day" | "week" | "month" | "year">("day")
  const [modalTimeframe, setModalTimeframe] = useState<"hour" | "day" | "week" | "month" | "year">("day")
  const [networkTotals, setNetworkTotals] = useState<{ received: number; sent: number }>({ received: 0, sent: 0 })
  const [interfaceTotals, setInterfaceTotals] = useState<{ received: number; sent: number }>({ received: 0, sent: 0 })

  const { data: interfaceHistoricalData } = useSWR<any>(`/api/node/metrics?timeframe=${timeframe}`, fetcher, {
    refreshInterval: 30000,
    revalidateOnFocus: false,
  })

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8">
          <div className="text-lg font-medium text-foreground mb-2">Loading network data...</div>
        </div>
      </div>
    )
  }

  if (error || !networkData) {
    return (
      <div className="space-y-6">
        <Card className="bg-red-500/10 border-red-500/20">
          <CardContent className="p-6">
            <div className="flex items-center gap-3 text-red-600">
              <AlertCircle className="h-6 w-6" />
              <div>
                <div className="font-semibold text-lg mb-1">Flask Server Not Available</div>
                <div className="text-sm">
                  {error?.message ||
                    "Unable to connect to the Flask server. Please ensure the server is running and try again."}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const trafficInFormatted = formatStorage(networkTotals.received * 1024 * 1024 * 1024) // Convert GB to bytes
  const trafficOutFormatted = formatStorage(networkTotals.sent * 1024 * 1024 * 1024)
  const packetsRecvK = networkData.traffic.packets_recv ? (networkData.traffic.packets_recv / 1000).toFixed(0) : "0"

  const totalErrors = (networkData.traffic.errin || 0) + (networkData.traffic.errout || 0)
  const packetLossIn = networkData.traffic.packet_loss_in || 0
  const packetLossOut = networkData.traffic.packet_loss_out || 0
  const avgPacketLoss = ((packetLossIn + packetLossOut) / 2).toFixed(2)

  // Determine health status
  let healthStatus = "Healthy"
  let healthColor = "bg-green-500/10 text-green-500 border-green-500/20"

  if (Number.parseFloat(avgPacketLoss) > 5 || totalErrors > 1000) {
    healthStatus = "Critical"
    healthColor = "bg-red-500/10 text-red-500 border-red-500/20"
  } else if (Number.parseFloat(avgPacketLoss) >= 1 || totalErrors >= 100) {
    healthStatus = "Warning"
    healthColor = "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
  }

  const getTimeframeLabel = () => {
    switch (timeframe) {
      case "hour":
        return "1 Hour"
      case "day":
        return "24 Hours"
      case "week":
        return "7 Days"
      case "month":
        return "30 Days"
      case "year":
        return "1 Year"
      default:
        return "24 Hours"
    }
  }

  return (
    <div className="space-y-6">
      {/* Network Overview Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Network Traffic</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground hidden md:inline">Received:</span>
                <span className="text-base lg:text-xl font-bold text-green-500">↓ {trafficInFormatted}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground hidden md:inline">Sent:</span>
                <span className="text-base lg:text-xl font-bold text-blue-500">↑ {trafficOutFormatted}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Active Interfaces</CardTitle>
            <Network className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-xl lg:text-2xl font-bold text-foreground">
              {(networkData.physical_active_count ?? 0) + (networkData.bridge_active_count ?? 0)}
            </div>
            <div className="flex flex-wrap items-center gap-2 mt-2">
              <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20 text-xs">
                Physical: {networkData.physical_active_count ?? 0}/{networkData.physical_total_count ?? 0}
              </Badge>
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20 text-xs">
                Bridges: {networkData.bridge_active_count ?? 0}/{networkData.bridge_total_count ?? 0}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              {(networkData.physical_total_count ?? 0) + (networkData.bridge_total_count ?? 0)} total interfaces
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Firewall Status</CardTitle>
            <Router className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {firewallData ? (
              <>
                <div
                  className={`text-xl lg:text-2xl font-bold ${firewallData.active ? "text-green-500" : "text-red-500"}`}
                >
                  {firewallData.active ? "Active" : "Inactive"}
                </div>
                <Badge
                  variant="outline"
                  className={
                    firewallData.active
                      ? "bg-green-500/10 text-green-500 border-green-500/20 mt-2"
                      : "bg-red-500/10 text-red-500 border-red-500/20 mt-2"
                  }
                >
                  {firewallData.active ? "Protected" : "Unprotected"}
                </Badge>
                <p className="text-xs text-muted-foreground mt-2">
                  {firewallData.active ? `${firewallData.rules_count} rules active` : "Firewall disabled"}
                </p>
              </>
            ) : (
              <>
                <div className="text-xl lg:text-2xl font-bold text-muted-foreground">Loading...</div>
                <p className="text-xs text-muted-foreground mt-2">Checking status</p>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">DNS Configuration</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {dnsData ? (
              <>
                <Badge
                  variant="outline"
                  className={
                    dnsData.dns_working
                      ? "bg-green-500/10 text-green-500 border-green-500/20"
                      : "bg-red-500/10 text-red-500 border-red-500/20"
                  }
                >
                  {dnsData.dns_working ? "Working" : "Not Working"}
                </Badge>
                <div className="flex flex-col gap-1 mt-2 text-xs">
                  {dnsData.primary_dns && (
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Primary:</span>
                      <span className="font-medium text-foreground font-mono">{dnsData.primary_dns}</span>
                    </div>
                  )}
                  {dnsData.secondary_dns && (
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Secondary:</span>
                      <span className="font-medium text-foreground font-mono">{dnsData.secondary_dns}</span>
                    </div>
                  )}
                  {!dnsData.primary_dns && <div className="text-muted-foreground">No DNS configured</div>}
                </div>
              </>
            ) : (
              <>
                <div className="text-sm text-muted-foreground">Loading...</div>
                <p className="text-xs text-muted-foreground mt-2">Checking DNS</p>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Timeframe Selector */}
      <div className="flex justify-end">
        <Select value={timeframe} onValueChange={(value: any) => setTimeframe(value)}>
          <SelectTrigger className="w-[180px] bg-card border-border">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="hour">1 Hour</SelectItem>
            <SelectItem value="day">24 Hours</SelectItem>
            <SelectItem value="week">7 Days</SelectItem>
            <SelectItem value="month">30 Days</SelectItem>
            <SelectItem value="year">1 Year</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Network Traffic Card with Chart */}
      <Card className="bg-card border-border">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-foreground flex items-center">
            <Activity className="h-5 w-5 mr-2" />
            Network Traffic
          </CardTitle>
        </CardHeader>
        <CardContent>
          <NetworkTrafficChart timeframe={timeframe} onTotalsCalculated={setNetworkTotals} />
        </CardContent>
      </Card>

      {/* Physical Interfaces section */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-foreground flex items-center">
            <Router className="h-5 w-5 mr-2" />
            Physical Interfaces
            <Badge variant="outline" className="ml-3 bg-blue-500/10 text-blue-500 border-blue-500/20">
              {networkData.physical_active_count ?? 0}/{networkData.physical_total_count ?? 0} Active
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {networkData.physical_interfaces.map((interface_, index) => {
              const typeBadge = getInterfaceTypeBadge(interface_.type)

              return (
                <div
                  key={index}
                  className="flex flex-col gap-3 p-4 rounded-lg border border-white/10 bg-white/5 sm:bg-card sm:hover:bg-white/5 transition-colors cursor-pointer"
                  onClick={() => setSelectedInterface(interface_)}
                >
                  {/* First row: Icon, Name, Type Badge, Status */}
                  <div className="flex items-center gap-3 flex-wrap">
                    <Wifi className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                    <div className="flex items-center gap-2 min-w-0 flex-1 flex-wrap">
                      <div className="font-medium text-foreground">{interface_.name}</div>
                      <Badge variant="outline" className={typeBadge.color}>
                        {typeBadge.label}
                      </Badge>
                    </div>
                    <Badge
                      variant="outline"
                      className={
                        interface_.status === "up"
                          ? "bg-green-500/10 text-green-500 border-green-500/20"
                          : "bg-red-500/10 text-red-500 border-red-500/20"
                      }
                    >
                      {interface_.status.toUpperCase()}
                    </Badge>
                  </div>

                  {/* Second row: Details - Responsive layout */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <div className="text-muted-foreground text-xs">IP Address</div>
                      <div className="font-medium text-foreground font-mono text-sm truncate">
                        {interface_.addresses.length > 0 ? interface_.addresses[0].ip : "N/A"}
                      </div>
                    </div>

                    <div>
                      <div className="text-muted-foreground text-xs">Speed</div>
                      <div className="font-medium text-foreground flex items-center gap-1 text-xs">
                        <Zap className="h-3 w-3" />
                        {formatSpeed(interface_.speed)}
                      </div>
                    </div>

                    <div className="col-span-2 md:col-span-1">
                      <div className="text-muted-foreground text-xs">Traffic since last boot</div>
                      <div className="font-medium text-foreground text-xs">
                        <span className="text-green-500">↓ {formatBytes(interface_.bytes_recv)}</span>
                        {" / "}
                        <span className="text-blue-500">↑ {formatBytes(interface_.bytes_sent)}</span>
                      </div>
                    </div>

                    {interface_.mac_address && (
                      <div className="col-span-2 md:col-span-1">
                        <div className="text-muted-foreground text-xs">MAC</div>
                        <div className="font-medium text-foreground font-mono text-xs truncate">
                          {interface_.mac_address}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {networkData.bridge_interfaces && networkData.bridge_interfaces.length > 0 && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Network className="h-5 w-5 mr-2" />
              Bridge Interfaces
              <Badge variant="outline" className="ml-3 bg-green-500/10 text-green-500 border-green-500/20">
                {networkData.bridge_active_count ?? 0}/{networkData.bridge_total_count ?? 0} Active
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {networkData.bridge_interfaces.map((interface_, index) => {
                const typeBadge = getInterfaceTypeBadge(interface_.type)

                return (
                  <div
                    key={index}
                    className="flex flex-col gap-3 p-4 rounded-lg border border-white/10 bg-white/5 sm:bg-card sm:hover:bg-white/5 transition-colors cursor-pointer"
                    onClick={() => setSelectedInterface(interface_)}
                  >
                    {/* First row: Icon, Name, Type Badge, Physical Interface (responsive), Status */}
                    <div className="flex items-center gap-3 flex-wrap">
                      <Wifi className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                      <div className="flex items-center gap-2 min-w-0 flex-1 flex-wrap">
                        <div className="font-medium text-foreground">{interface_.name}</div>
                        <Badge variant="outline" className={typeBadge.color}>
                          {typeBadge.label}
                        </Badge>
                        {interface_.bridge_physical_interface && (
                          <div className="text-sm text-blue-500 font-medium flex items-center gap-1 flex-wrap break-all">
                            → {interface_.bridge_physical_interface}
                            {interface_.bridge_physical_interface.startsWith("bond") &&
                              networkData.physical_interfaces && (
                                <>
                                  {(() => {
                                    const bondInterface = networkData.physical_interfaces.find(
                                      (iface) => iface.name === interface_.bridge_physical_interface,
                                    )
                                    if (bondInterface?.bond_slaves && bondInterface.bond_slaves.length > 0) {
                                      return (
                                        <span className="text-muted-foreground text-xs break-all">
                                          ({bondInterface.bond_slaves.join(", ")})
                                        </span>
                                      )
                                    }
                                    return null
                                  })()}
                                </>
                              )}
                            {interface_.bridge_bond_slaves && interface_.bridge_bond_slaves.length > 0 && (
                              <span className="text-muted-foreground text-xs break-all">
                                ({interface_.bridge_bond_slaves.join(", ")})
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                      <Badge
                        variant="outline"
                        className={
                          interface_.status === "up"
                            ? "bg-green-500/10 text-green-500 border-green-500/20"
                            : "bg-red-500/10 text-red-500 border-red-500/20"
                        }
                      >
                        {interface_.status.toUpperCase()}
                      </Badge>
                    </div>

                    {/* Second row: Details - Responsive layout */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                      <div>
                        <div className="text-muted-foreground text-xs">IP Address</div>
                        <div className="font-medium text-foreground font-mono text-sm truncate">
                          {interface_.addresses.length > 0 ? interface_.addresses[0].ip : "N/A"}
                        </div>
                      </div>

                      <div>
                        <div className="text-muted-foreground text-xs">Speed</div>
                        <div className="font-medium text-foreground flex items-center gap-1">
                          <Zap className="h-3 w-3" />
                          {formatSpeed(interface_.speed)}
                        </div>
                      </div>

                      <div className="col-span-2 md:col-span-1">
                        <div className="text-muted-foreground text-xs">Traffic since last boot</div>
                        <div className="font-medium text-foreground text-xs">
                          <span className="text-green-500">↓ {formatBytes(interface_.bytes_recv)}</span>
                          {" / "}
                          <span className="text-blue-500">↑ {formatBytes(interface_.bytes_sent)}</span>
                        </div>
                      </div>

                      {interface_.mac_address && (
                        <div className="col-span-2 md:col-span-1">
                          <div className="text-muted-foreground text-xs">MAC</div>
                          <div className="font-medium text-foreground font-mono text-xs truncate">
                            {interface_.mac_address}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* VM & LXC Network Interfaces section */}
      {networkData.vm_lxc_interfaces && networkData.vm_lxc_interfaces.length > 0 && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Network className="h-5 w-5 mr-2" />
              VM & LXC Network Interfaces
              <Badge variant="outline" className="ml-3 bg-orange-500/10 text-orange-500 border-orange-500/20">
                {networkData.vm_lxc_active_count ?? 0} / {networkData.vm_lxc_total_count ?? 0} Active
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {networkData.vm_lxc_interfaces.map((interface_, index) => {
                const vmTypeBadge = getVMTypeBadge(interface_.vm_type)

                return (
                  <div
                    key={index}
                    className="flex flex-col gap-3 p-4 rounded-lg border border-white/10 bg-white/5 sm:bg-card sm:hover:bg-white/5 transition-colors cursor-pointer"
                    onClick={() => setSelectedInterface(interface_)}
                  >
                    {/* First row: Icon, Name, VM/LXC Badge, VM Name, Status */}
                    <div className="flex items-center gap-3 flex-wrap">
                      <Wifi className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                      <div className="flex items-center gap-2 min-w-0 flex-1 flex-wrap">
                        <div className="font-medium text-foreground">{interface_.name}</div>
                        <Badge variant="outline" className={vmTypeBadge.color}>
                          {vmTypeBadge.label}
                        </Badge>
                        {interface_.vm_name && (
                          <div className="text-sm text-muted-foreground truncate">→ {interface_.vm_name}</div>
                        )}
                      </div>
                      <Badge
                        variant="outline"
                        className={
                          interface_.status === "up"
                            ? "bg-green-500/10 text-green-500 border-green-500/20"
                            : "bg-red-500/10 text-red-500 border-red-500/20"
                        }
                      >
                        {interface_.status.toUpperCase()}
                      </Badge>
                    </div>

                    {/* Second row: Details - Responsive layout */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                      <div>
                        <div className="text-sm text-muted-foreground">VMID</div>
                        <div className="font-medium">{interface_.vmid ?? "N/A"}</div>
                      </div>

                      <div>
                        <div className="text-sm text-muted-foreground">Speed</div>
                        <div className="font-medium text-foreground flex items-center gap-1">
                          <Zap className="h-3 w-3" />
                          {formatSpeed(interface_.speed)}
                        </div>
                      </div>

                      <div className="col-span-2 md:col-span-1">
                        <div className="text-sm text-muted-foreground">Traffic since last boot</div>
                        <div className="font-medium text-foreground text-xs">
                          <span className="text-green-500">↓ {formatBytes(interface_.bytes_recv)}</span>
                          {" / "}
                          <span className="text-blue-500">↑ {formatBytes(interface_.bytes_sent)}</span>
                        </div>
                      </div>

                      {interface_.mac_address && (
                        <div className="col-span-2 md:col-span-1">
                          <div className="text-sm text-muted-foreground">MAC</div>
                          <div className="font-medium text-foreground font-mono text-xs truncate">
                            {interface_.mac_address}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Interface Details Modal */}
      <Dialog open={!!selectedInterface} onOpenChange={() => setSelectedInterface(null)}>
        <DialogContent className="max-w-6xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Router className="h-5 w-5" />
              {selectedInterface?.name} - Interface Details
            </DialogTitle>
            {selectedInterface?.status.toLowerCase() === "up" && selectedInterface?.vm_type !== "vm" && (
              <div className="flex justify-end pt-2">
                <Select value={modalTimeframe} onValueChange={(value: any) => setModalTimeframe(value)}>
                  <SelectTrigger className="w-[140px] bg-card border-border">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="hour">1 Hour</SelectItem>
                    <SelectItem value="day">24 Hours</SelectItem>
                    <SelectItem value="week">7 Days</SelectItem>
                    <SelectItem value="month">30 Days</SelectItem>
                    <SelectItem value="year">1 Year</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </DialogHeader>

          {selectedInterface && (
            <div className="space-y-6">
              {/* Basic Information */}
              <div>
                <h3 className="text-sm font-semibold text-muted-foreground mb-3">Basic Information</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-sm text-muted-foreground">Interface Name</div>
                    <div className="font-medium">{selectedInterface.name}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Type</div>
                    <Badge variant="outline" className={getInterfaceTypeBadge(selectedInterface.type).color}>
                      {getInterfaceTypeBadge(selectedInterface.type).label}
                    </Badge>
                  </div>
                  {selectedInterface.type === "bridge" && selectedInterface.bridge_physical_interface && (
                    <div className="col-span-2">
                      <div className="text-sm text-muted-foreground">Physical Interface</div>
                      <div className="font-medium text-blue-500 text-lg break-all">
                        {selectedInterface.bridge_physical_interface}
                      </div>
                      {selectedInterface.bridge_physical_interface.startsWith("bond") &&
                        networkData?.physical_interfaces && (
                          <>
                            {(() => {
                              const bondInterface = networkData.physical_interfaces.find(
                                (iface) => iface.name === selectedInterface.bridge_physical_interface,
                              )
                              if (bondInterface?.bond_slaves && bondInterface.bond_slaves.length > 0) {
                                return (
                                  <div className="mt-2">
                                    <div className="text-sm text-muted-foreground mb-2">Bond Members</div>
                                    <div className="flex flex-wrap gap-2">
                                      {bondInterface.bond_slaves.map((slave, idx) => (
                                        <Badge
                                          key={idx}
                                          variant="outline"
                                          className="bg-purple-500/10 text-purple-500 border-purple-500/20"
                                        >
                                          {slave}
                                        </Badge>
                                      ))}
                                    </div>
                                  </div>
                                )
                              }
                              return null
                            })()}
                          </>
                        )}
                      {selectedInterface.bridge_bond_slaves && selectedInterface.bridge_bond_slaves.length > 0 && (
                        <div className="mt-2">
                          <div className="text-sm text-muted-foreground mb-2">Bond Members</div>
                          <div className="flex flex-wrap gap-2">
                            {selectedInterface.bridge_bond_slaves.map((slave, idx) => (
                              <Badge
                                key={idx}
                                variant="outline"
                                className="bg-purple-500/10 text-purple-500 border-purple-500/20"
                              >
                                {slave}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  {selectedInterface.type === "vm_lxc" && selectedInterface.vm_name && (
                    <div className="col-span-2">
                      <div className="text-sm text-muted-foreground">VM/LXC Name</div>
                      <div className="font-medium text-orange-500 text-lg flex items-center gap-2">
                        {selectedInterface.vm_name}
                        {selectedInterface.vm_type && (
                          <Badge variant="outline" className={getVMTypeBadge(selectedInterface.vm_type).color}>
                            {getVMTypeBadge(selectedInterface.vm_type).label}
                          </Badge>
                        )}
                      </div>
                    </div>
                  )}
                  <div>
                    <div className="text-sm text-muted-foreground">Status</div>
                    <Badge
                      variant="outline"
                      className={
                        selectedInterface.status === "up"
                          ? "bg-green-500/10 text-green-500 border-green-500/20"
                          : "bg-red-500/10 text-red-500 border-red-500/20"
                      }
                    >
                      {selectedInterface.status.toUpperCase()}
                    </Badge>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Speed</div>
                    <div className="font-medium">{formatSpeed(selectedInterface.speed)}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Duplex</div>
                    <div className="font-medium capitalize">{selectedInterface.duplex}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">MTU</div>
                    <div className="font-medium">{selectedInterface.mtu}</div>
                  </div>
                  {selectedInterface.mac_address && (
                    <div className="col-span-2">
                      <div className="text-sm text-muted-foreground">MAC Address</div>
                      <div className="font-medium font-mono">{selectedInterface.mac_address}</div>
                    </div>
                  )}
                </div>
              </div>

              {/* IP Addresses */}
              {selectedInterface.addresses.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-3">IP Addresses</h3>
                  <div className="space-y-2">
                    {selectedInterface.addresses.map((addr, idx) => (
                      <div key={idx} className="flex items-center justify-between p-3 rounded-lg bg-muted/50">
                        <div>
                          <div className="font-medium font-mono">{addr.ip}</div>
                          <div className="text-sm text-muted-foreground">Netmask: {addr.netmask}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Network Traffic Statistics - Only show if interface is UP and NOT a VM interface */}
              {selectedInterface.status.toLowerCase() === "up" && selectedInterface.vm_type !== "vm" ? (
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-4">
                    Network Traffic Statistics (
                    {modalTimeframe === "hour"
                      ? "Last Hour"
                      : modalTimeframe === "day"
                        ? "Last 24 Hours"
                        : modalTimeframe === "week"
                          ? "Last 7 Days"
                          : modalTimeframe === "month"
                            ? "Last 30 Days"
                            : "Last Year"}
                    )
                  </h3>
                  <div className="space-y-4">
                    {/* Traffic Data - Top Row */}
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <div className="text-sm text-muted-foreground">Bytes Received</div>
                        <div className="font-medium text-green-500 text-lg">
                          {formatStorage(interfaceTotals.received * 1024 * 1024 * 1024)}
                        </div>
                      </div>
                      <div>
                        <div className="text-sm text-muted-foreground">Bytes Sent</div>
                        <div className="font-medium text-blue-500 text-lg">
                          {formatStorage(interfaceTotals.sent * 1024 * 1024 * 1024)}
                        </div>
                      </div>
                    </div>

                    {/* Network Traffic Chart - Full Width Below */}
                    <div className="bg-muted/30 rounded-lg p-4">
                      <NetworkTrafficChart
                        timeframe={modalTimeframe}
                        interfaceName={selectedInterface.name}
                        onTotalsCalculated={setInterfaceTotals}
                      />
                    </div>
                  </div>
                </div>
              ) : selectedInterface.status.toLowerCase() === "up" && selectedInterface.vm_type === "vm" ? (
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-4">Traffic since last boot</h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-sm text-muted-foreground">Bytes Received</div>
                      <div className="font-medium text-green-500 text-lg">
                        {formatBytes(selectedInterface.bytes_recv)}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Bytes Sent</div>
                      <div className="font-medium text-blue-500 text-lg">
                        {formatBytes(selectedInterface.bytes_sent)}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Packets Received</div>
                      <div className="font-medium">{selectedInterface.packets_recv?.toLocaleString() || "N/A"}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Packets Sent</div>
                      <div className="font-medium">{selectedInterface.packets_sent?.toLocaleString() || "N/A"}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Errors In</div>
                      <div className="font-medium text-red-500">{selectedInterface.errors_in || 0}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Errors Out</div>
                      <div className="font-medium text-red-500">{selectedInterface.errors_out || 0}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Drops In</div>
                      <div className="font-medium text-yellow-500">{selectedInterface.drops_in || 0}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Drops Out</div>
                      <div className="font-medium text-yellow-500">{selectedInterface.drops_out || 0}</div>
                    </div>
                    {selectedInterface.packet_loss_in !== undefined && (
                      <div>
                        <div className="text-sm text-muted-foreground">Packet Loss In</div>
                        <div
                          className={`font-medium ${selectedInterface.packet_loss_in > 1 ? "text-red-500" : "text-green-500"}`}
                        >
                          {selectedInterface.packet_loss_in}%
                        </div>
                      </div>
                    )}
                    {selectedInterface.packet_loss_out !== undefined && (
                      <div>
                        <div className="text-sm text-muted-foreground">Packet Loss Out</div>
                        <div
                          className={`font-medium ${selectedInterface.packet_loss_out > 1 ? "text-red-500" : "text-green-500"}`}
                        >
                          {selectedInterface.packet_loss_out}%
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="bg-muted/30 rounded-lg p-6 text-center">
                  <AlertCircle className="h-12 w-12 text-muted-foreground mx-auto mb-3" />
                  <h3 className="text-lg font-semibold text-foreground mb-2">Interface Inactive</h3>
                  <p className="text-sm text-muted-foreground">
                    This interface is currently down. Network traffic statistics are not available.
                  </p>
                </div>
              )}

              {/* Cumulative Statistics - Only show if interface is UP and NOT a VM interface */}
              {selectedInterface.status.toLowerCase() === "up" && selectedInterface.vm_type !== "vm" && (
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-4">
                    Cumulative Statistics (Since Last Boot)
                  </h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-sm text-muted-foreground">Packets Received</div>
                      <div className="font-medium">{selectedInterface.packets_recv?.toLocaleString() || "N/A"}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Packets Sent</div>
                      <div className="font-medium">{selectedInterface.packets_sent?.toLocaleString() || "N/A"}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Errors In</div>
                      <div className="font-medium text-red-500">{selectedInterface.errors_in || 0}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Errors Out</div>
                      <div className="font-medium text-red-500">{selectedInterface.errors_out || 0}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Drops In</div>
                      <div className="font-medium text-yellow-500">{selectedInterface.drops_in || 0}</div>
                    </div>
                    <div>
                      <div className="text-sm text-muted-foreground">Drops Out</div>
                      <div className="font-medium text-yellow-500">{selectedInterface.drops_out || 0}</div>
                    </div>
                    {selectedInterface.packet_loss_in !== undefined && (
                      <div>
                        <div className="text-sm text-muted-foreground">Packet Loss In</div>
                        <div
                          className={`font-medium ${selectedInterface.packet_loss_in > 1 ? "text-red-500" : "text-green-500"}`}
                        >
                          {selectedInterface.packet_loss_in}%
                        </div>
                      </div>
                    )}
                    {selectedInterface.packet_loss_out !== undefined && (
                      <div>
                        <div className="text-sm text-muted-foreground">Packet Loss Out</div>
                        <div
                          className={`font-medium ${selectedInterface.packet_loss_out > 1 ? "text-red-500" : "text-green-500"}`}
                        >
                          {selectedInterface.packet_loss_out}%
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Bond Information */}
              {selectedInterface.type === "bond" && selectedInterface.bond_slaves && (
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-3">Bond Configuration</h3>
                  <div className="space-y-3">
                    <div>
                      <div className="text-sm text-muted-foreground">Bonding Mode</div>
                      <div className="font-medium">{selectedInterface.bond_mode || "Unknown"}</div>
                    </div>
                    {selectedInterface.bond_active_slave && (
                      <div>
                        <div className="text-sm text-muted-foreground">Active Slave</div>
                        <div className="font-medium">{selectedInterface.bond_active_slave}</div>
                      </div>
                    )}
                    <div>
                      <div className="text-sm text-muted-foreground mb-2">Slave Interfaces</div>
                      <div className="flex flex-wrap gap-2">
                        {selectedInterface.bond_slaves.map((slave, idx) => (
                          <Badge
                            key={idx}
                            variant="outline"
                            className="bg-purple-500/10 text-purple-500 border-purple-500/20"
                          >
                            {slave}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Bridge Information */}
              {selectedInterface.type === "bridge" && selectedInterface.bridge_members && (
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground mb-3">Bridge Configuration</h3>
                  <div>
                    <div className="text-sm text-muted-foreground mb-2">Virtual Member Interfaces</div>
                    <div className="flex flex-wrap gap-2">
                      {selectedInterface.bridge_members.length > 0 ? (
                        selectedInterface.bridge_members
                          .filter(
                            (member) =>
                              !member.startsWith("enp") &&
                              !member.startsWith("eth") &&
                              !member.startsWith("eno") &&
                              !member.startsWith("ens") &&
                              !member.startsWith("wlan") &&
                              !member.startsWith("wlp"),
                          )
                          .map((member, idx) => (
                            <Badge
                              key={idx}
                              variant="outline"
                              className="bg-green-500/10 text-green-500 border-green-500/20"
                            >
                              {member}
                            </Badge>
                          ))
                      ) : (
                        <div className="text-sm text-muted-foreground">No virtual members</div>
                      )}
                    </div>
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
