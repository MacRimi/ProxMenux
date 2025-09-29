"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Wifi, Globe, Shield, Activity, Network, Router, AlertCircle } from "lucide-react"

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
  status: string
  addresses: Array<{
    ip: string
    netmask: string
  }>
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
            {networkData.interfaces.map((interface_, index) => (
              <div
                key={index}
                className="flex items-center justify-between p-4 rounded-lg border border-border bg-card/50"
              >
                <div className="flex items-center space-x-4">
                  <Wifi className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <div className="font-medium text-foreground">{interface_.name}</div>
                    <div className="text-sm text-muted-foreground">Network Interface</div>
                  </div>
                </div>

                <div className="flex items-center space-x-6">
                  <div className="text-center">
                    <div className="text-sm text-muted-foreground">IP Address</div>
                    <div className="text-sm font-medium text-foreground font-mono">
                      {interface_.addresses.length > 0 ? interface_.addresses[0].ip : "N/A"}
                    </div>
                  </div>

                  <div className="text-center">
                    <div className="text-sm text-muted-foreground">Netmask</div>
                    <div className="text-sm font-medium text-foreground">
                      {interface_.addresses.length > 0 ? interface_.addresses[0].netmask : "N/A"}
                    </div>
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
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
