"use client"

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts"
import { Cpu, MemoryStick, Thermometer, Users, Activity, Server, Zap } from "lucide-react"

const cpuData = [
  { time: "00:00", value: 45 },
  { time: "04:00", value: 52 },
  { time: "08:00", value: 78 },
  { time: "12:00", value: 65 },
  { time: "16:00", value: 82 },
  { time: "20:00", value: 58 },
  { time: "24:00", value: 43 },
]

const memoryData = [
  { time: "00:00", used: 12.5, available: 19.5 },
  { time: "04:00", used: 14.2, available: 17.8 },
  { time: "08:00", used: 18.7, available: 13.3 },
  { time: "12:00", used: 16.3, available: 15.7 },
  { time: "16:00", used: 21.1, available: 10.9 },
  { time: "20:00", used: 15.8, available: 16.2 },
  { time: "24:00", used: 13.2, available: 18.8 },
]

export function SystemOverview() {
  return (
    <div className="space-y-6">
      {/* Key Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border metric-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">CPU Usage</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground metric-value">67.3%</div>
            <Progress value={67.3} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2 metric-label">
              <span className="text-green-500">↓ 2.1%</span> from last hour
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Memory Usage</CardTitle>
            <MemoryStick className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground metric-value">15.8 GB</div>
            <Progress value={49.4} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2 metric-label">
              49.4% of 32 GB • <span className="text-yellow-500">↑ 1.2 GB</span>
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Temperature</CardTitle>
            <Thermometer className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground metric-value">52°C</div>
            <div className="flex items-center mt-2">
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                Normal
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2 metric-label">Max: 78°C • Avg: 48°C</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Active VMs & LXC</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground metric-value">15</div>
            <div className="vm-badges mt-2">
              <Badge variant="outline" className="vm-badge bg-green-500/10 text-green-500 border-green-500/20">
                8 Running VMs
              </Badge>
              <Badge variant="outline" className="vm-badge bg-blue-500/10 text-blue-500 border-blue-500/20">
                3 Running LXC
              </Badge>
              <Badge variant="outline" className="vm-badge bg-yellow-500/10 text-yellow-500 border-yellow-500/20">
                4 Stopped
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2 metric-label">Total: 12 VMs • 6 LXC configured</p>
          </CardContent>
        </Card>
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-card border-border metric-card">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Activity className="h-5 w-5 mr-2" />
              CPU Usage (24h)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={cpuData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                    color: "hsl(var(--foreground))",
                  }}
                />
                <Area type="monotone" dataKey="value" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.2} />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <MemoryStick className="h-5 w-5 mr-2" />
              Memory Usage (24h)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={memoryData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                    color: "hsl(var(--foreground))",
                  }}
                />
                <Area type="monotone" dataKey="used" stackId="1" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.6} />
                <Area
                  type="monotone"
                  dataKey="available"
                  stackId="1"
                  stroke="#10b981"
                  fill="#10b981"
                  fillOpacity={0.6}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* System Information */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="bg-card border-border metric-card">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Server className="h-5 w-5 mr-2" />
              System Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Hostname:</span>
              <span className="text-foreground font-mono metric-value">proxmox-01</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Version:</span>
              <span className="text-foreground metric-value">PVE 8.1.3</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Kernel:</span>
              <span className="text-foreground font-mono metric-value">6.5.11-7-pve</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Architecture:</span>
              <span className="text-foreground metric-value">x86_64</span>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Users className="h-5 w-5 mr-2" />
              Active Sessions
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-muted-foreground metric-label">Web Console:</span>
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                3 active
              </Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-muted-foreground metric-label">SSH Sessions:</span>
              <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">
                1 active
              </Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">API Calls:</span>
              <span className="text-foreground metric-value">247/hour</span>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border metric-card">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Zap className="h-5 w-5 mr-2" />
              Power & Performance
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Power State:</span>
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                Running
              </Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Load Average:</span>
              <span className="text-foreground font-mono metric-value">1.23, 1.45, 1.67</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground metric-label">Boot Time:</span>
              <span className="text-foreground metric-value">2.3s</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
