"use client"

import { Card, CardContent } from "./ui/card"
import { Badge } from "./ui/badge"
import { Wifi, Zap } from 'lucide-react'
import { useState, useEffect } from "react"
import { fetchApi } from "../lib/api-config"
import { formatNetworkTraffic, getNetworkUnit } from "../lib/format-network"
import { useT } from "../lib/i18n/provider"

type TFunction = (key: string, params?: Record<string, string | number>) => string

interface NetworkCardProps {
  interface_: {
    name: string
    type: string
    status: string
    speed: number
    duplex?: string
    mtu?: number
    mac_address: string | null
    addresses: Array<{
      ip: string
      netmask: string
    }>
    bytes_sent?: number
    bytes_recv?: number
    bridge_physical_interface?: string
    bridge_bond_slaves?: string[]
    vmid?: number
    vm_name?: string
    vm_type?: string
  }
  timeframe: "hour" | "day" | "week" | "month" | "year"
  onClick?: () => void
}

const getInterfaceTypeBadge = (type: string, t: TFunction) => {
  switch (type) {
    case "physical":
      return { color: "bg-blue-500/10 text-blue-500 border-blue-500/20", label: t("network.interfaceTypes.physical") }
    case "bridge":
      return { color: "bg-green-500/10 text-green-500 border-green-500/20", label: t("network.interfaceTypes.bridge") }
    case "bond":
      return { color: "bg-purple-500/10 text-purple-500 border-purple-500/20", label: t("network.interfaceTypes.bond") }
    case "vlan":
      return { color: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20", label: t("network.interfaceTypes.vlan") }
    case "vm_lxc":
      return { color: "bg-orange-500/10 text-orange-500 border-orange-500/20", label: t("network.interfaceTypes.virtual") }
    case "virtual":
      return { color: "bg-orange-500/10 text-orange-500 border-orange-500/20", label: t("network.interfaceTypes.virtual") }
    default:
      return { color: "bg-gray-500/10 text-gray-500 border-gray-500/20", label: t("common.unknown") }
  }
}

const getVMTypeBadge = (vmType: string | undefined, t: TFunction) => {
  if (vmType === "lxc") {
    return { color: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20", label: "LXC" }
  } else if (vmType === "vm") {
    return { color: "bg-purple-500/10 text-purple-500 border-purple-500/20", label: "VM" }
  }
  return { color: "bg-gray-500/10 text-gray-500 border-gray-500/20", label: t("common.unknown") }
}

const formatInterfaceStatus = (status: string | undefined, t: TFunction): string => {
  const normalized = (status || "").toLowerCase()
  if (normalized === "up") return t("network.status.up")
  if (normalized === "down") return t("network.status.down")
  return status || t("common.unknown")
}

const formatSpeed = (speed: number, unavailable = "N/A"): string => {
  if (speed === 0) return unavailable
  if (speed >= 1000) return `${(speed / 1000).toFixed(1)} Gbps`
  return `${speed} Mbps`
}

export function NetworkCard({ interface_, timeframe, onClick }: NetworkCardProps) {
  const t = useT()
  const typeBadge = getInterfaceTypeBadge(interface_.type, t)
  const vmTypeBadge = interface_.vm_type ? getVMTypeBadge(interface_.vm_type, t) : null

  const [networkUnit, setNetworkUnit] = useState<"Bytes" | "Bits">(getNetworkUnit())

  const [trafficData, setTrafficData] = useState<{ received: number; sent: number }>({
    received: 0,
    sent: 0,
  })

  useEffect(() => {
    const handleUnitChange = () => {
      setNetworkUnit(getNetworkUnit())
    }

    window.addEventListener("networkUnitChanged", handleUnitChange)
    window.addEventListener("storage", handleUnitChange)

    return () => {
      window.removeEventListener("networkUnitChanged", handleUnitChange)
      window.removeEventListener("storage", handleUnitChange)
    }
  }, [])

  useEffect(() => {
    const fetchTrafficData = async () => {
      try {
        const data = await fetchApi(`/api/network/${interface_.name}/metrics?timeframe=${timeframe}`)

        if (data.data && data.data.length > 0) {
          const lastPoint = data.data[data.data.length - 1]
          const firstPoint = data.data[0]

          const receivedGB = Math.max(0, (lastPoint.netin || 0) - (firstPoint.netin || 0))
          const sentGB = Math.max(0, (lastPoint.netout || 0) - (firstPoint.netout || 0))

          setTrafficData({
            received: receivedGB,
            sent: sentGB,
          })
        }
      } catch (error) {
        console.error("Failed to fetch traffic data for card:", error)
        setTrafficData({ received: 0, sent: 0 })
      }
    }

    if (interface_.status.toLowerCase() === "up" && interface_.vm_type !== "vm") {
      fetchTrafficData()

      const interval = setInterval(fetchTrafficData, 60000)
      return () => clearInterval(interval)
    }
  }, [interface_.name, interface_.status, interface_.vm_type, timeframe])

  const getTimeframeLabel = () => {
    switch (timeframe) {
      case "hour":
        return t("network.timeframes.last.hour")
      case "day":
        return t("network.timeframes.last.day")
      case "week":
        return t("network.timeframes.last.week")
      case "month":
        return t("network.timeframes.last.month")
      case "year":
        return t("network.timeframes.last.year")
      default:
        return t("network.timeframes.last.day")
    }
  }

  return (
    <Card className="bg-card border-border hover:bg-white/5 transition-colors cursor-pointer" onClick={onClick}>
      <CardContent className="p-4">
        <div className="flex flex-col gap-3">
          {/* First row: Icon, Name, Type Badge, Status */}
          <div className="flex items-center gap-3 flex-wrap">
            <Wifi className="h-5 w-5 text-muted-foreground flex-shrink-0" />
            <div className="flex items-center gap-2 min-w-0 flex-1 flex-wrap">
              <div className="font-medium text-foreground">{interface_.name}</div>
              {vmTypeBadge ? (
                <Badge variant="outline" className={vmTypeBadge.color}>
                  {vmTypeBadge.label}
                </Badge>
              ) : (
                <Badge variant="outline" className={typeBadge.color}>
                  {typeBadge.label}
                </Badge>
              )}
              {interface_.vm_name && (
                <div className="text-sm text-muted-foreground truncate">→ {interface_.vm_name}</div>
              )}
              {interface_.type === "bridge" && interface_.bridge_physical_interface && (
                <div className="text-sm text-blue-500 font-medium flex items-center gap-1 flex-wrap break-all">
                  → {interface_.bridge_physical_interface}
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
              {formatInterfaceStatus(interface_.status, t)}
            </Badge>
          </div>

          {/* Second row: Details - Responsive layout */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <div className="text-muted-foreground text-xs">
                {interface_.type === "vm_lxc" ? "VMID" : t("network.labels.ipAddress")}
              </div>
              <div className="font-medium text-foreground font-mono text-sm truncate">
                {interface_.type === "vm_lxc"
                  ? (interface_.vmid ?? t("common.notAvailable"))
                  : interface_.addresses.length > 0
                    ? interface_.addresses[0].ip
                    : t("common.notAvailable")}
              </div>
            </div>

            <div>
              <div className="text-muted-foreground text-xs">{t("network.labels.speed")}</div>
              <div className="font-medium text-foreground flex items-center gap-1 text-xs">
                <Zap className="h-3 w-3" />
                {formatSpeed(interface_.speed, t("common.notAvailable"))}
              </div>
            </div>

            <div className="col-span-2 md:col-span-1">
              <div className="text-muted-foreground text-xs">{getTimeframeLabel()}</div>
              <div className="font-medium text-foreground text-xs">
                {interface_.status.toLowerCase() === "up" && interface_.vm_type !== "vm" ? (
                  <>
                    <span className="text-green-500">↓ {formatNetworkTraffic(trafficData.received * 1024 * 1024 * 1024, networkUnit)}</span>
                    {" / "}
                    <span className="text-blue-500">↑ {formatNetworkTraffic(trafficData.sent * 1024 * 1024 * 1024, networkUnit)}</span>
                  </>
                ) : (
                  <>
                    <span className="text-green-500">↓ {formatNetworkTraffic(interface_.bytes_recv || 0, networkUnit)}</span>
                    {" / "}
                    <span className="text-blue-500">↑ {formatNetworkTraffic(interface_.bytes_sent || 0, networkUnit)}</span>
                  </>
                )}
              </div>
            </div>

            {interface_.mac_address && (
              <div className="col-span-2 md:col-span-1">
                <div className="text-muted-foreground text-xs">MAC</div>
                <div className="font-medium text-foreground font-mono text-xs truncate">{interface_.mac_address}</div>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
