"use client"

import { useState, useEffect } from "react"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs"
import { SystemOverview } from "./system-overview"
import { StorageMetrics } from "./storage-metrics"
import { NetworkMetrics } from "./network-metrics"
import { VirtualMachines } from "./virtual-machines"
import { SystemLogs } from "./system-logs"
import { RefreshCw, AlertTriangle, CheckCircle, XCircle, Server } from "lucide-react"
import Image from "next/image"
import { ThemeToggle } from "./theme-toggle"

interface SystemStatus {
  status: "healthy" | "warning" | "critical"
  uptime: string
  lastUpdate: string
  serverName: string
  nodeId: string
}

export function ProxmoxDashboard() {
  const [systemStatus, setSystemStatus] = useState<SystemStatus>({
    status: "healthy",
    uptime: "15d 7h 23m",
    lastUpdate: new Date().toLocaleTimeString(),
    serverName: "proxmox-01",
    nodeId: "pve-node-01",
  })
  const [isRefreshing, setIsRefreshing] = useState(false)

  useEffect(() => {
    const fetchServerInfo = async () => {
      try {
        const response = await fetch("/api/system-info")
        if (response.ok) {
          const data = await response.json()
          setSystemStatus((prev) => ({
            ...prev,
            serverName: data.hostname || "proxmox-01",
            nodeId: data.node_id || "pve-node-01",
          }))
        }
      } catch (error) {
        console.log("[v0] Using default server name due to API error:", error)
      }
    }

    fetchServerInfo()
  }, [])

  const refreshData = async () => {
    setIsRefreshing(true)
    await new Promise((resolve) => setTimeout(resolve, 1000))
    setSystemStatus((prev) => ({
      ...prev,
      lastUpdate: new Date().toLocaleTimeString(),
    }))
    setIsRefreshing(false)
  }

  const getStatusIcon = () => {
    switch (systemStatus.status) {
      case "healthy":
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case "warning":
        return <AlertTriangle className="h-4 w-4 text-yellow-500" />
      case "critical":
        return <XCircle className="h-4 w-4 text-red-500" />
    }
  }

  const getStatusColor = () => {
    switch (systemStatus.status) {
      case "healthy":
        return "bg-green-500/10 text-green-500 border-green-500/20"
      case "warning":
        return "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
      case "critical":
        return "bg-red-500/10 text-red-500 border-red-500/20"
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border bg-background sticky top-0 z-50">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="flex items-center space-x-3">
                <div className="w-10 h-10 relative">
                  <Image
                    src="/images/proxmenux-logo.png"
                    alt="ProxMenux Logo"
                    width={40}
                    height={40}
                    className="object-contain"
                    priority
                  />
                </div>
                <div>
                  <h1 className="text-xl font-semibold">ProxMenux Monitor</h1>
                  <p className="text-sm opacity-70">Proxmox System Dashboard</p>
                </div>
              </div>
              <div className="hidden md:flex items-center ml-6">
                <div className="server-info flex items-center space-x-2">
                  <Server className="h-4 w-4 opacity-70" />
                  <div className="text-sm">
                    <div className="font-medium">{systemStatus.nodeId}</div>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex items-center space-x-4">
              <Badge variant="outline" className={getStatusColor()}>
                {getStatusIcon()}
                <span className="ml-1 capitalize">{systemStatus.status}</span>
              </Badge>

              <div className="text-sm opacity-70">Uptime: {systemStatus.uptime}</div>

              <Button
                variant="outline"
                size="sm"
                onClick={refreshData}
                disabled={isRefreshing}
                className="border-border/50 bg-transparent hover:bg-secondary"
              >
                <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? "animate-spin" : ""}`} />
                Refresh
              </Button>

              <ThemeToggle />
            </div>
          </div>
        </div>
      </header>

      <div className="container mx-auto px-6 py-6">
        <Tabs defaultValue="overview" className="space-y-6">
          <TabsList className="grid w-full grid-cols-5 bg-card border border-border">
            <TabsTrigger
              value="overview"
              className="data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
            >
              Overview
            </TabsTrigger>
            <TabsTrigger
              value="storage"
              className="data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
            >
              Storage
            </TabsTrigger>
            <TabsTrigger
              value="network"
              className="data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
            >
              Network
            </TabsTrigger>
            <TabsTrigger
              value="vms"
              className="data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
            >
              Virtual Machines
            </TabsTrigger>
            <TabsTrigger
              value="logs"
              className="data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
            >
              System Logs
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-6">
            <SystemOverview />
          </TabsContent>

          <TabsContent value="storage" className="space-y-6">
            <StorageMetrics />
          </TabsContent>

          <TabsContent value="network" className="space-y-6">
            <NetworkMetrics />
          </TabsContent>

          <TabsContent value="vms" className="space-y-6">
            <VirtualMachines />
          </TabsContent>

          <TabsContent value="logs" className="space-y-6">
            <SystemLogs />
          </TabsContent>
        </Tabs>

        <footer className="mt-12 pt-6 border-t border-border text-center text-sm text-muted-foreground">
          <p>Last updated: {systemStatus.lastUpdate} • ProxMenux Monitor v1.0.0</p>
        </footer>
      </div>
    </div>
  )
}
