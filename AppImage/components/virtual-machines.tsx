"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { Progress } from "./ui/progress"
import { Server, Play, Square, Monitor, Cpu, MemoryStick, AlertCircle } from "lucide-react"

interface VMData {
  vmid: number
  name: string
  status: string
  cpu: number
  mem: number
  maxmem: number
  disk: number
  maxdisk: number
  uptime: number
}

const fetchVMData = async (): Promise<VMData[]> => {
  try {
    console.log("[v0] Fetching VM data from Flask server...")
    const response = await fetch("/api/vms", {
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
    console.log("[v0] Successfully fetched VM data from Flask:", data)
    return Array.isArray(data) ? data : []
  } catch (error) {
    console.error("[v0] Failed to fetch VM data from Flask server:", error)
    throw error
  }
}

export function VirtualMachines() {
  const [vmData, setVmData] = useState<VMData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true)
        setError(null)
        const result = await fetchVMData()
        setVmData(result)
      } catch (err) {
        setError("Flask server not available. Please ensure the server is running.")
      } finally {
        setLoading(false)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="text-center py-8">
          <div className="text-lg font-medium text-foreground mb-2">Loading VM data...</div>
        </div>
      </div>
    )
  }

  if (error) {
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

  const runningVMs = vmData.filter((vm) => vm.status === "running").length
  const stoppedVMs = vmData.filter((vm) => vm.status === "stopped").length
  const totalCPU = vmData.reduce((sum, vm) => sum + (vm.cpu || 0), 0)
  const totalMemory = vmData.reduce((sum, vm) => sum + (vm.maxmem || 0), 0)

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
        return <Play className="h-3 w-3 mr-1" />
      case "stopped":
        return <Square className="h-3 w-3 mr-1" />
      default:
        return null
    }
  }

  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / 86400)
    const hours = Math.floor((seconds % 86400) / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `${days}d ${hours}h ${minutes}m`
  }

  return (
    <div className="space-y-6">
      {/* VM Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total VMs</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{vmData.length}</div>
            <div className="vm-badges mt-2">
              <Badge variant="outline" className="vm-badge bg-green-500/10 text-green-500 border-green-500/20">
                {runningVMs} Running
              </Badge>
              <Badge variant="outline" className="vm-badge bg-red-500/10 text-red-500 border-red-500/20">
                {stoppedVMs} Stopped
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Virtual machines configured</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total CPU</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{(totalCPU * 100).toFixed(0)}%</div>
            <p className="text-xs text-muted-foreground mt-2">Allocated CPU usage</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Memory</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{(totalMemory / 1024 ** 3).toFixed(1)} GB</div>
            <p className="text-xs text-muted-foreground mt-2">Allocated RAM</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Average Load</CardTitle>
            <Monitor className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">
              {runningVMs > 0 ? ((totalCPU / runningVMs) * 100).toFixed(0) : 0}%
            </div>
            <p className="text-xs text-muted-foreground mt-2">Average resource utilization</p>
          </CardContent>
        </Card>
      </div>

      {/* Virtual Machines List */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-foreground flex items-center">
            <Server className="h-5 w-5 mr-2" />
            Virtual Machines
          </CardTitle>
        </CardHeader>
        <CardContent>
          {vmData.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">No virtual machines found</div>
          ) : (
            <div className="space-y-4">
              {vmData.map((vm) => {
                const cpuPercent = (vm.cpu * 100).toFixed(1)
                const memPercent = vm.maxmem > 0 ? ((vm.mem / vm.maxmem) * 100).toFixed(1) : "0"
                const memGB = (vm.mem / 1024 ** 3).toFixed(1)
                const maxMemGB = (vm.maxmem / 1024 ** 3).toFixed(1)

                return (
                  <div key={vm.vmid} className="p-6 rounded-lg border border-border bg-card/50">
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center space-x-4">
                        <Server className="h-6 w-6 text-muted-foreground" />
                        <div>
                          <div className="font-semibold text-foreground text-lg flex items-center">
                            {vm.name}
                            <Badge
                              variant="outline"
                              className="ml-2 text-xs bg-purple-500/10 text-purple-500 border-purple-500/20"
                            >
                              VM
                            </Badge>
                          </div>
                          <div className="text-sm text-muted-foreground">ID: {vm.vmid}</div>
                        </div>
                      </div>

                      <div className="flex items-center space-x-3">
                        <Badge variant="outline" className={getStatusColor(vm.status)}>
                          {getStatusIcon(vm.status)}
                          {vm.status.toUpperCase()}
                        </Badge>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                      <div>
                        <div className="text-sm text-muted-foreground mb-2">CPU Usage</div>
                        <div className="text-lg font-semibold text-foreground mb-1">{cpuPercent}%</div>
                        <Progress value={Number.parseFloat(cpuPercent)} className="h-2" />
                      </div>

                      <div>
                        <div className="text-sm text-muted-foreground mb-2">Memory Usage</div>
                        <div className="text-lg font-semibold text-foreground mb-1">
                          {memGB} GB / {maxMemGB} GB
                        </div>
                        <Progress value={Number.parseFloat(memPercent)} className="h-2" />
                      </div>

                      <div>
                        <div className="text-sm text-muted-foreground mb-2">Uptime</div>
                        <div className="text-lg font-semibold text-foreground">{formatUptime(vm.uptime)}</div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
