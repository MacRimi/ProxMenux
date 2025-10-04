"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog"
import { Wifi, Globe, Shield, Activity, Network, Router, AlertCircle, Zap } from "lucide-react"

interface NetworkData {
  interfaces: NetworkInterface[]
  traffic: {
    bytes_sent: number
    bytes_recv: number
    packets_sent?: number
    packets_recv?: number
  }
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
    case "virtual":
      return { color: "bg-orange-500/10 text-orange-500 border-orange-500/20", label: "Virtual" }
    default:
      return { color: "bg-gray-500/10 text-gray-500 border-gray-500/20", label: "Unknown" }
  }
}

const formatBytes = (bytes: number | undefined): string => {
  if (!bytes || bytes === 0) return "0 B"
  const k = 1024
  const sizes = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
}

const formatSpeed = (speed: number): string => {
  if (speed === 0) return "N/A"
  if (speed >= 1000) return `${(speed / 1000).toFixed(1)} Gbps`
  return `${speed} Mbps`
}

const fetchNetworkData = async (): Promise<NetworkData | null> => {
  try {
    console.log("[v0] Fetching network data from Flask server...")
    const response = await fetch("/api/network", {
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
    console.log("[v0] Successfully fetched network data from Flask:", data)
    return data
  } catch (error) {
    console.error("[v0] Failed to fetch network data from Flask server:", error)
    return null
  }
}

export function NetworkMetrics() {
  const [networkData, setNetworkData] = useState<NetworkData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedInterface, setSelectedInterface] = useState<NetworkInterface | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      setError(null)
      const result = await fetchNetworkData()

      if (!result) {
        setError("Flask server not available. Please ensure the server is running.")
      } else {
        setNetworkData(result)
      }

      setLoading(false)
    }

    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [])

  if (loading) {
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
                  {error || "Unable to connect to the Flask server. Please ensure the server is running and try again."}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const trafficInMB = (networkData.traffic.bytes_recv / (1024 * 1024)).toFixed(1)
  const trafficOutMB = (networkData.traffic.bytes_sent / (1024 * 1024)).toFixed(1)

  return (
    <div className="space-y-6">
      {/* Network Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Network Traffic</CardTitle>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{trafficInMB} MB</div>
            <div className="flex items-center space-x-2 mt-2">
              <span className="text-xs text-green-500">↓ {trafficInMB} MB</span>
              <span className="text-xs text-blue-500">↑ {trafficOutMB} MB</span>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Total data transferred</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Active Interfaces</CardTitle>
            <Network className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">
              {networkData.interfaces.filter((i) => i.status === "up").length}
            </div>
            <div className="flex items-center mt-2">
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                Online
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">{networkData.interfaces.length} total interfaces</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Firewall Status</CardTitle>
            <Shield className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">Active</div>
            <div className="flex items-center mt-2">
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                Protected
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">System protected</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Globe className="h-5 w-5 mr-2" />
              Packets
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">
              {networkData.traffic.packets_recv ? (networkData.traffic.packets_recv / 1000).toFixed(0) : "N/A"}K
            </div>
            <div className="flex items-center mt-2">
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                Received
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Total packets received</p>
          </CardContent>
        </Card>
      </div>

      {/* Network Interfaces */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-foreground flex items-center">
            <Router className="h-5 w-5 mr-2" />
            Network Interfaces
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {networkData.interfaces.map((interface_, index) => {
              const typeBadge = getInterfaceTypeBadge(interface_.type)

              return (
                <div
                  key={index}
                  className="flex flex-col gap-3 p-4 rounded-lg border border-border bg-card/50 hover:bg-card/80 transition-colors cursor-pointer"
                  onClick={() => setSelectedInterface(interface_)}
                >
                  {/* First row: Icon, Name, Type Badge */}
                  <div className="flex items-center gap-3">
                    <Wifi className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                    <div className="flex items-center gap-2 min-w-0 flex-1">
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

                  {/* Second row: Details */}
                  <div className="flex items-center justify-between gap-6 text-sm">
                    <div className="flex items-center gap-6">
                      <div>
                        <div className="text-muted-foreground">IP Address</div>
                        <div className="font-medium text-foreground font-mono">
                          {interface_.addresses.length > 0 ? interface_.addresses[0].ip : "N/A"}
                        </div>
                      </div>

                      <div>
                        <div className="text-muted-foreground">Speed</div>
                        <div className="font-medium text-foreground flex items-center gap-1">
                          <Zap className="h-3 w-3" />
                          {formatSpeed(interface_.speed)}
                        </div>
                      </div>

                      <div>
                        <div className="text-muted-foreground">Traffic</div>
                        <div className="font-medium text-foreground">
                          <span className="text-green-500">↓ {formatBytes(interface_.bytes_recv)}</span>
                          {" / "}
                          <span className="text-blue-500">↑ {formatBytes(interface_.bytes_sent)}</span>
                        </div>
                      </div>

                      {interface_.mac_address && (
                        <div>
                          <div className="text-muted-foreground">MAC</div>
                          <div className="font-medium text-foreground font-mono text-xs">{interface_.mac_address}</div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Interface Details Modal */}
      <Dialog open={!!selectedInterface} onOpenChange={() => setSelectedInterface(null)}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Router className="h-5 w-5" />
              {selectedInterface?.name} - Interface Details
            </DialogTitle>
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

              {/* Traffic Statistics */}
              <div>
                <h3 className="text-sm font-semibold text-muted-foreground mb-3">Traffic Statistics</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-sm text-muted-foreground">Bytes Received</div>
                    <div className="font-medium text-green-500">{formatBytes(selectedInterface.bytes_recv)}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">Bytes Sent</div>
                    <div className="font-medium text-blue-500">{formatBytes(selectedInterface.bytes_sent)}</div>
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
                </div>
              </div>

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
                    <div className="text-sm text-muted-foreground mb-2">Member Interfaces</div>
                    <div className="flex flex-wrap gap-2">
                      {selectedInterface.bridge_members.length > 0 ? (
                        selectedInterface.bridge_members.map((member, idx) => (
                          <Badge
                            key={idx}
                            variant="outline"
                            className="bg-green-500/10 text-green-500 border-green-500/20"
                          >
                            {member}
                          </Badge>
                        ))
                      ) : (
                        <div className="text-sm text-muted-foreground">No members</div>
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
