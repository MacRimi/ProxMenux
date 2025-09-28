"use client"

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts"
import { Wifi, Globe, Shield, Activity, Network, Router } from "lucide-react"

const networkTraffic = [
  { time: "00:00", incoming: 45, outgoing: 32 },
  { time: "04:00", incoming: 52, outgoing: 28 },
  { time: "08:00", incoming: 78, outgoing: 65 },
  { time: "12:00", incoming: 65, outgoing: 45 },
  { time: "16:00", incoming: 82, outgoing: 58 },
  { time: "20:00", incoming: 58, outgoing: 42 },
  { time: "24:00", incoming: 43, outgoing: 35 },
]

const connectionData = [
  { time: "00:00", connections: 1250 },
  { time: "04:00", connections: 980 },
  { time: "08:00", connections: 1850 },
  { time: "12:00", connections: 1650 },
  { time: "16:00", connections: 2100 },
  { time: "20:00", connections: 1580 },
  { time: "24:00", connections: 1320 },
]

export function NetworkMetrics() {
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
            <div className="text-2xl font-bold text-foreground">156 MB/s</div>
            <div className="flex items-center space-x-2 mt-2">
              <span className="text-xs text-green-500">↓ 89 MB/s</span>
              <span className="text-xs text-blue-500">↑ 67 MB/s</span>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Peak: 245 MB/s at 16:30</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Active Connections</CardTitle>
            <Network className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">1,847</div>
            <div className="flex items-center mt-2">
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                Normal
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              <span className="text-green-500">↑ 12%</span> from last hour
            </p>
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
            <p className="text-xs text-muted-foreground mt-2">247 blocked attempts today</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Globe className="h-5 w-5 mr-2" />
              Latency
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">12ms</div>
            <div className="flex items-center mt-2">
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                Excellent
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Avg response time</p>
          </CardContent>
        </Card>
      </div>

      {/* Network Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Activity className="h-5 w-5 mr-2" />
              Network Traffic (24h)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={networkTraffic}>
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
                  formatter={(value, name) => [`${value} MB/s`, name === "incoming" ? "Incoming" : "Outgoing"]}
                />
                <Area
                  type="monotone"
                  dataKey="incoming"
                  stackId="1"
                  stroke="#10b981"
                  fill="#10b981"
                  fillOpacity={0.6}
                />
                <Area
                  type="monotone"
                  dataKey="outgoing"
                  stackId="1"
                  stroke="#3b82f6"
                  fill="#3b82f6"
                  fillOpacity={0.6}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Network className="h-5 w-5 mr-2" />
              Active Connections (24h)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={connectionData}>
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
                  formatter={(value) => [`${value}`, "Connections"]}
                />
                <Line
                  type="monotone"
                  dataKey="connections"
                  stroke="#8b5cf6"
                  strokeWidth={3}
                  dot={{ fill: "#8b5cf6", strokeWidth: 2, r: 5 }}
                />
              </LineChart>
            </ResponsiveContainer>
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
            {[
              {
                name: "vmbr0",
                type: "Bridge",
                status: "up",
                ip: "192.168.1.100/24",
                speed: "1000 Mbps",
                rx: "2.3 GB",
                tx: "1.8 GB",
              },
              {
                name: "enp1s0",
                type: "Physical",
                status: "up",
                ip: "192.168.1.101/24",
                speed: "1000 Mbps",
                rx: "1.2 GB",
                tx: "890 MB",
              },
              {
                name: "vmbr1",
                type: "Bridge",
                status: "up",
                ip: "10.0.0.1/24",
                speed: "1000 Mbps",
                rx: "456 MB",
                tx: "234 MB",
              },
              {
                name: "tap101i0",
                type: "TAP",
                status: "up",
                ip: "10.0.0.101/24",
                speed: "1000 Mbps",
                rx: "123 MB",
                tx: "89 MB",
              },
            ].map((interface_, index) => (
              <div
                key={index}
                className="flex items-center justify-between p-4 rounded-lg border border-border bg-card/50"
              >
                <div className="flex items-center space-x-4">
                  <Wifi className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <div className="font-medium text-foreground">{interface_.name}</div>
                    <div className="text-sm text-muted-foreground">
                      {interface_.type} • {interface_.speed}
                    </div>
                  </div>
                </div>

                <div className="flex items-center space-x-6">
                  <div className="text-center">
                    <div className="text-sm text-muted-foreground">IP Address</div>
                    <div className="text-sm font-medium text-foreground font-mono">{interface_.ip}</div>
                  </div>

                  <div className="text-center">
                    <div className="text-sm text-muted-foreground">RX / TX</div>
                    <div className="text-sm font-medium text-foreground">
                      {interface_.rx} / {interface_.tx}
                    </div>
                  </div>

                  <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
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
