"use client"

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Progress } from "./ui/progress"
import { Badge } from "./ui/badge"
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts"
import { HardDrive, Database, Archive, AlertTriangle, CheckCircle, Activity } from "lucide-react"

const storageData = [
  { name: "Used", value: 1250, color: "#3b82f6" }, // Blue
  { name: "Available", value: 750, color: "#10b981" }, // Green
]

const diskPerformance = [
  { disk: "sda", read: 45, write: 32, iops: 1250 },
  { disk: "sdb", read: 67, write: 28, iops: 980 },
  { disk: "sdc", read: 23, write: 45, iops: 1100 },
  { disk: "nvme0n1", read: 156, write: 89, iops: 3400 },
]

export function StorageMetrics() {
  return (
    <div className="space-y-6">
      {/* Storage Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total Storage</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">2.0 TB</div>
            <Progress value={62.5} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2">1.25 TB used • 750 GB available</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">VM & LXC Storage</CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">890 GB</div>
            <Progress value={71.2} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2">71.2% of allocated space</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Archive className="h-5 w-5 mr-2" />
              Backups
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">245 GB</div>
            <div className="flex items-center mt-2">
              <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/20">
                12 Backups
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Last backup: 2h ago</p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Activity className="h-5 w-5 mr-2" />
              IOPS
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">6.7K</div>
            <div className="flex items-center space-x-2 mt-2">
              <span className="text-xs text-green-500">Read: 4.2K</span>
              <span className="text-xs text-blue-500">Write: 2.5K</span>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Average operations/sec</p>
          </CardContent>
        </Card>
      </div>

      {/* Storage Distribution and Performance */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <HardDrive className="h-5 w-5 mr-2" />
              Storage Distribution
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-foreground font-medium">Used Storage</span>
                  <span className="text-muted-foreground">1.25 TB (62.5%)</span>
                </div>
                <div className="w-full bg-muted rounded-full h-3">
                  <div
                    className="bg-blue-500 h-3 rounded-full transition-all duration-300"
                    style={{ width: "62.5%" }}
                  ></div>
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-foreground font-medium">Available Storage</span>
                  <span className="text-muted-foreground">750 GB (37.5%)</span>
                </div>
                <div className="w-full bg-muted rounded-full h-3">
                  <div
                    className="bg-green-500 h-3 rounded-full transition-all duration-300"
                    style={{ width: "37.5%" }}
                  ></div>
                </div>
              </div>

              <div className="pt-4 border-t border-border">
                <div className="grid grid-cols-2 gap-4 text-center">
                  <div className="space-y-1">
                    <div className="flex items-center justify-center">
                      <div className="w-3 h-3 bg-blue-500 rounded-full mr-2"></div>
                      <span className="text-sm font-medium text-foreground">Used</span>
                    </div>
                    <div className="text-lg font-bold text-foreground">1.25 TB</div>
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-center">
                      <div className="w-3 h-3 bg-green-500 rounded-full mr-2"></div>
                      <span className="text-sm font-medium text-foreground">Available</span>
                    </div>
                    <div className="text-lg font-bold text-foreground">750 GB</div>
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground flex items-center">
              <Activity className="h-5 w-5 mr-2" />
              Disk Performance
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={diskPerformance}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="disk" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                    color: "hsl(var(--foreground))",
                  }}
                />
                <Bar dataKey="read" fill="#3b82f6" name="Read MB/s" />
                <Bar dataKey="write" fill="#10b981" name="Write MB/s" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Disk Details */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-foreground flex items-center">
            <Database className="h-5 w-5 mr-2" />
            Storage Devices
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {[
              { name: "/dev/sda", type: "HDD", size: "1TB", used: "650GB", health: "healthy", temp: "42°C" },
              { name: "/dev/sdb", type: "HDD", size: "1TB", used: "480GB", health: "healthy", temp: "38°C" },
              { name: "/dev/sdc", type: "SSD", size: "500GB", used: "120GB", health: "healthy", temp: "35°C" },
              { name: "/dev/nvme0n1", type: "NVMe", size: "1TB", used: "340GB", health: "warning", temp: "55°C" },
            ].map((disk, index) => (
              <div
                key={index}
                className="flex items-center justify-between p-4 rounded-lg border border-border bg-card/50"
              >
                <div className="flex items-center space-x-4">
                  <HardDrive className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <div className="font-medium text-foreground">{disk.name}</div>
                    <div className="text-sm text-muted-foreground">
                      {disk.type} • {disk.size}
                    </div>
                  </div>
                </div>

                <div className="flex items-center space-x-6">
                  <div className="text-right">
                    <div className="text-sm font-medium text-foreground">
                      {disk.used} / {disk.size}
                    </div>
                    <Progress
                      value={(Number.parseInt(disk.used) / Number.parseInt(disk.size)) * 100}
                      className="w-24 mt-1"
                    />
                  </div>

                  <div className="text-center">
                    <div className="text-sm text-muted-foreground">Temp</div>
                    <div className="text-sm font-medium text-foreground">{disk.temp}</div>
                  </div>

                  <Badge
                    variant="outline"
                    className={
                      disk.health === "healthy"
                        ? "bg-green-500/10 text-green-500 border-green-500/20"
                        : "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"
                    }
                  >
                    {disk.health === "healthy" ? (
                      <CheckCircle className="h-3 w-3 mr-1" />
                    ) : (
                      <AlertTriangle className="h-3 w-3 mr-1" />
                    )}
                    {disk.health}
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
