"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Server, Play, Square, RotateCcw, Monitor, Cpu, MemoryStick } from "lucide-react"

const virtualMachines = [
  {
    id: 100,
    name: "web-server-01",
    type: "vm",
    status: "running",
    os: "Ubuntu 22.04",
    cpu: 4,
    memory: 8192,
    disk: 50,
    uptime: "15d 7h 23m",
    cpuUsage: 45,
    memoryUsage: 62,
    diskUsage: 78,
  },
  {
    id: 101,
    name: "database-01",
    type: "vm",
    status: "running",
    os: "CentOS 8",
    cpu: 8,
    memory: 16384,
    disk: 100,
    uptime: "12d 3h 45m",
    cpuUsage: 78,
    memoryUsage: 85,
    diskUsage: 45,
  },
  {
    id: 102,
    name: "backup-server",
    type: "vm",
    status: "stopped",
    os: "Debian 11",
    cpu: 2,
    memory: 4096,
    disk: 200,
    uptime: "0d 0h 0m",
    cpuUsage: 0,
    memoryUsage: 0,
    diskUsage: 23,
  },
  {
    id: 103,
    name: "dev-environment",
    type: "vm",
    status: "running",
    os: "Ubuntu 20.04",
    cpu: 6,
    memory: 12288,
    disk: 75,
    uptime: "3d 12h 18m",
    cpuUsage: 32,
    memoryUsage: 58,
    diskUsage: 67,
  },
  {
    id: 104,
    name: "monitoring-01",
    type: "vm",
    status: "running",
    os: "Alpine Linux",
    cpu: 2,
    memory: 2048,
    disk: 25,
    uptime: "8d 15h 32m",
    cpuUsage: 15,
    memoryUsage: 34,
    diskUsage: 42,
  },
  {
    id: 105,
    name: "mail-server",
    type: "vm",
    status: "stopped",
    os: "Ubuntu 22.04",
    cpu: 4,
    memory: 8192,
    disk: 60,
    uptime: "0d 0h 0m",
    cpuUsage: 0,
    memoryUsage: 0,
    diskUsage: 56,
  },
  {
    id: 200,
    name: "nginx-proxy",
    type: "lxc",
    status: "running",
    os: "Ubuntu 22.04 LXC",
    cpu: 1,
    memory: 512,
    disk: 8,
    uptime: "25d 14h 12m",
    cpuUsage: 8,
    memoryUsage: 45,
    diskUsage: 32,
  },
  {
    id: 201,
    name: "redis-cache",
    type: "lxc",
    status: "running",
    os: "Alpine Linux LXC",
    cpu: 1,
    memory: 1024,
    disk: 4,
    uptime: "18d 6h 45m",
    cpuUsage: 12,
    memoryUsage: 38,
    diskUsage: 28,
  },
  {
    id: 202,
    name: "log-collector",
    type: "lxc",
    status: "stopped",
    os: "Debian 11 LXC",
    cpu: 1,
    memory: 256,
    disk: 2,
    uptime: "0d 0h 0m",
    cpuUsage: 0,
    memoryUsage: 0,
    diskUsage: 15,
  },
]

export function VirtualMachines() {
  const runningVMs = virtualMachines.filter((vm) => vm.status === "running").length
  const stoppedVMs = virtualMachines.filter((vm) => vm.status === "stopped").length
  const runningLXC = virtualMachines.filter((vm) => vm.type === "lxc" && vm.status === "running").length
  const totalVMs = virtualMachines.filter((vm) => vm.type === "vm").length
  const totalLXC = virtualMachines.filter((vm) => vm.type === "lxc").length
  const totalCPU = virtualMachines.reduce((sum, vm) => sum + vm.cpu, 0)
  const totalMemory = virtualMachines.reduce((sum, vm) => sum + vm.memory, 0)

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
        return <RotateCcw className="h-3 w-3 mr-1" />
    }
  }

  return (
    <div className="space-y-6">
      {/* VM Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total VMs & LXC</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{virtualMachines.length}</div>
            <div className="vm-badges mt-2">
              <Badge variant="outline" className="vm-badge bg-green-500/10 text-green-500 border-green-500/20">
                {runningVMs} VMs
              </Badge>
              <Badge variant="outline" className="vm-badge bg-blue-500/10 text-blue-500 border-blue-500/20">
                {runningLXC} LXC
              </Badge>
              <Badge variant="outline" className="vm-badge bg-red-500/10 text-red-500 border-red-500/20">
                {stoppedVMs} Stopped
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              {totalVMs} VMs • {totalLXC} LXC
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total CPU Cores</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{totalCPU}</div>
            <p className="text-xs text-muted-foreground mt-2">Allocated across all VMs and LXC containers</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Memory</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{(totalMemory / 1024).toFixed(1)} GB</div>
            <p className="text-xs text-muted-foreground mt-2">Allocated RAM across all VMs and LXC containers</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Average Load</CardTitle>
            <Monitor className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">42%</div>
            <p className="text-xs text-muted-foreground mt-2">Average resource utilization</p>
          </CardContent>
        </Card>
      </div>

      {/* Virtual Machines List */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-foreground flex items-center">
            <Server className="h-5 w-5 mr-2" />
            Virtual Machines & LXC Containers
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {virtualMachines.map((vm) => (
              <div key={vm.id} className="p-6 rounded-lg border border-border bg-card/50">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center space-x-4">
                    <Server className="h-6 w-6 text-muted-foreground" />
                    <div>
                      <div className="font-semibold text-foreground text-lg flex items-center">
                        {vm.name}
                        <Badge
                          variant="outline"
                          className={`ml-2 text-xs ${
                            vm.type === "lxc"
                              ? "bg-blue-500/10 text-blue-500 border-blue-500/20"
                              : "bg-purple-500/10 text-purple-500 border-purple-500/20"
                          }`}
                        >
                          {vm.type.toUpperCase()}
                        </Badge>
                      </div>
                      <div className="text-sm text-muted-foreground">
                        ID: {vm.id} • {vm.os}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-3">
                    <Badge variant="outline" className={getStatusColor(vm.status)}>
                      {getStatusIcon(vm.status)}
                      {vm.status.toUpperCase()}
                    </Badge>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                  <div>
                    <div className="text-sm text-muted-foreground mb-2">Resources</div>
                    <div className="space-y-1 text-sm">
                      <div className="flex justify-between">
                        <span>CPU:</span>
                        <span className="font-medium">{vm.cpu} cores</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Memory:</span>
                        <span className="font-medium">{(vm.memory / 1024).toFixed(1)} GB</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Disk:</span>
                        <span className="font-medium">{vm.disk} GB</span>
                      </div>
                    </div>
                  </div>

                  <div>
                    <div className="text-sm text-muted-foreground mb-2">CPU Usage</div>
                    <div className="text-lg font-semibold text-foreground mb-1">{vm.cpuUsage}%</div>
                    <Progress value={vm.cpuUsage} className="h-2" />
                  </div>

                  <div>
                    <div className="text-sm text-muted-foreground mb-2">Memory Usage</div>
                    <div className="text-lg font-semibold text-foreground mb-1">{vm.memoryUsage}%</div>
                    <Progress value={vm.memoryUsage} className="h-2" />
                  </div>

                  <div>
                    <div className="text-sm text-muted-foreground mb-2">Uptime</div>
                    <div className="text-lg font-semibold text-foreground">{vm.uptime}</div>
                    <div className="text-xs text-muted-foreground mt-1">Disk: {vm.diskUsage}% used</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
