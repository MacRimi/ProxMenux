"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Wrench, Package, Ruler } from "lucide-react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { getNetworkUnit } from "../lib/format-network"
import { fetchApi } from "../lib/api-config"

interface ProxMenuxTool {
  key: string
  name: string
  enabled: boolean
}

export function Settings() {
  const [proxmenuxTools, setProxmenuxTools] = useState<ProxMenuxTool[]>([])
  const [loadingTools, setLoadingTools] = useState(true)
  const [networkUnitSettings, setNetworkUnitSettings] = useState<"Bytes" | "Bits">("Bytes")
  const [loadingUnitSettings, setLoadingUnitSettings] = useState(true)

  useEffect(() => {
    loadProxmenuxTools()
    getUnitsSettings()
  }, [])

  const loadProxmenuxTools = async () => {
    try {
      const data = await fetchApi("/api/proxmenux/installed-tools")
      if (data.success) {
        setProxmenuxTools(data.installed_tools || [])
      }
    } catch (err) {
      console.error("Failed to load ProxMenux tools:", err)
    } finally {
      setLoadingTools(false)
    }
  }

  const changeNetworkUnit = (unit: string) => {
    const networkUnit = unit as "Bytes" | "Bits"
    localStorage.setItem("proxmenux-network-unit", networkUnit)
    setNetworkUnitSettings(networkUnit)

    window.dispatchEvent(new CustomEvent("networkUnitChanged", { detail: networkUnit }))

    window.dispatchEvent(new StorageEvent("storage", {
      key: "proxmenux-network-unit",
      newValue: networkUnit,
      url: window.location.href
    }))
  }

  const getUnitsSettings = () => {
    const networkUnit = getNetworkUnit()
    setNetworkUnitSettings(networkUnit)
    setLoadingUnitSettings(false)
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground mt-2">Manage your dashboard preferences</p>
      </div>

      {/* Network Units Settings */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Ruler className="h-5 w-5 text-green-500" />
            <CardTitle>Network Units</CardTitle>
          </div>
          <CardDescription>Change how network traffic is displayed</CardDescription>
        </CardHeader>
        <CardContent>
          {loadingUnitSettings ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin h-8 w-8 border-4 border-green-500 border-t-transparent rounded-full" />
            </div>
          ) : (
            <div className="text-foreground flex items-center justify-between">
              <div className="flex items-center">Network Unit Display</div>
              <Select value={networkUnitSettings} onValueChange={changeNetworkUnit}>
                <SelectTrigger className="w-28 h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="Bytes">Bytes</SelectItem>
                  <SelectItem value="Bits">Bits</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ProxMenux Optimizations */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Wrench className="h-5 w-5 text-orange-500" />
            <CardTitle>ProxMenux Optimizations</CardTitle>
          </div>
          <CardDescription>System optimizations and utilities installed via ProxMenux</CardDescription>
        </CardHeader>
        <CardContent>
          {loadingTools ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin h-8 w-8 border-4 border-orange-500 border-t-transparent rounded-full" />
            </div>
          ) : proxmenuxTools.length === 0 ? (
            <div className="text-center py-8">
              <Package className="h-12 w-12 text-muted-foreground mx-auto mb-3 opacity-50" />
              <p className="text-muted-foreground">No ProxMenux optimizations installed yet</p>
              <p className="text-sm text-muted-foreground mt-1">Run ProxMenux to configure system optimizations</p>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between mb-4 pb-2 border-b border-border">
                <span className="text-sm font-medium text-muted-foreground">Installed Tools</span>
                <span className="text-sm font-semibold text-orange-500">{proxmenuxTools.length} active</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {proxmenuxTools.map((tool) => (
                  <div
                    key={tool.key}
                    className="flex items-center gap-2 p-3 bg-muted/50 rounded-lg border border-border hover:bg-muted transition-colors"
                  >
                    <div className="w-2 h-2 rounded-full bg-green-500 flex-shrink-0" />
                    <span className="text-sm font-medium">{tool.name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
