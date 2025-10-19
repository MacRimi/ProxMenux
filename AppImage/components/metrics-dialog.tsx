"use client"

import { useState, useEffect } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ArrowLeft, Loader2 } from "lucide-react"
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts"

interface MetricsDialogProps {
  open: boolean
  onClose: () => void
  vmid: number
  vmName: string
  vmType: "qemu" | "lxc"
  metricType: "cpu" | "memory" | "network" | "disk"
}

const TIMEFRAME_OPTIONS = [
  { value: "hour", label: "1 Hora" },
  { value: "day", label: "24 Horas" },
  { value: "week", label: "7 Días" },
  { value: "month", label: "30 Días" },
  { value: "year", label: "1 Año" },
]

const METRIC_TITLES = {
  cpu: "Uso de CPU",
  memory: "Uso de Memoria",
  network: "Tráfico de Red",
  disk: "I/O de Disco",
}

export function MetricsDialog({ open, onClose, vmid, vmName, vmType, metricType }: MetricsDialogProps) {
  const [timeframe, setTimeframe] = useState("week")
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      fetchMetrics()
    }
  }, [open, vmid, timeframe])

  const fetchMetrics = async () => {
    setLoading(true)
    setError(null)

    try {
      const response = await fetch(`http://localhost:8008/api/vms/${vmid}/metrics?timeframe=${timeframe}`)

      if (!response.ok) {
        throw new Error("Failed to fetch metrics")
      }

      const result = await response.json()

      // Transform data for charts
      const transformedData = result.data.map((item: any) => ({
        time: new Date(item.time * 1000).toLocaleString("es-ES", {
          month: "short",
          day: "numeric",
          hour: timeframe === "hour" ? "2-digit" : undefined,
          minute: timeframe === "hour" ? "2-digit" : undefined,
        }),
        timestamp: item.time,
        cpu: item.cpu ? (item.cpu * 100).toFixed(2) : 0,
        memory: item.mem ? ((item.mem / item.maxmem) * 100).toFixed(2) : 0,
        memoryMB: item.mem ? (item.mem / 1024 / 1024).toFixed(0) : 0,
        maxMemoryMB: item.maxmem ? (item.maxmem / 1024 / 1024).toFixed(0) : 0,
        netin: item.netin ? (item.netin / 1024 / 1024).toFixed(2) : 0,
        netout: item.netout ? (item.netout / 1024 / 1024).toFixed(2) : 0,
        diskread: item.diskread ? (item.diskread / 1024 / 1024).toFixed(2) : 0,
        diskwrite: item.diskwrite ? (item.diskwrite / 1024 / 1024).toFixed(2) : 0,
      }))

      setData(transformedData)
    } catch (err) {
      console.error("[v0] Error fetching metrics:", err)
      setError("Error al cargar las métricas")
    } finally {
      setLoading(false)
    }
  }

  const renderChart = () => {
    if (loading) {
      return (
        <div className="flex items-center justify-center h-96">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      )
    }

    if (error) {
      return (
        <div className="flex items-center justify-center h-96">
          <p className="text-destructive">{error}</p>
        </div>
      )
    }

    if (data.length === 0) {
      return (
        <div className="flex items-center justify-center h-96">
          <p className="text-muted-foreground">No hay datos disponibles</p>
        </div>
      )
    }

    switch (metricType) {
      case "cpu":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis stroke="hsl(var(--muted-foreground))" label={{ value: "%", angle: -90, position: "insideLeft" }} />
              <Tooltip
                contentStyle={{ backgroundColor: "hsl(var(--background))", border: "1px solid hsl(var(--border))" }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Legend />
              <Line type="monotone" dataKey="cpu" stroke="#3b82f6" name="CPU %" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )

      case "memory":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis stroke="hsl(var(--muted-foreground))" label={{ value: "%", angle: -90, position: "insideLeft" }} />
              <Tooltip
                contentStyle={{ backgroundColor: "hsl(var(--background))", border: "1px solid hsl(var(--border))" }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Legend />
              <Line type="monotone" dataKey="memory" stroke="#10b981" name="Memoria %" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )

      case "network":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis
                stroke="hsl(var(--muted-foreground))"
                label={{ value: "MB", angle: -90, position: "insideLeft" }}
              />
              <Tooltip
                contentStyle={{ backgroundColor: "hsl(var(--background))", border: "1px solid hsl(var(--border))" }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Legend />
              <Line type="monotone" dataKey="netin" stroke="#3b82f6" name="Entrada (MB)" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="netout" stroke="#8b5cf6" name="Salida (MB)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )

      case "disk":
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
              <YAxis
                stroke="hsl(var(--muted-foreground))"
                label={{ value: "MB", angle: -90, position: "insideLeft" }}
              />
              <Tooltip
                contentStyle={{ backgroundColor: "hsl(var(--background))", border: "1px solid hsl(var(--border))" }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="diskread"
                stroke="#10b981"
                name="Lectura (MB)"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="diskwrite"
                stroke="#f59e0b"
                name="Escritura (MB)"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )
    }
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col p-0">
        {/* Fixed Header */}
        <DialogHeader className="p-6 pb-4 border-b">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Button variant="ghost" size="icon" onClick={onClose}>
                <ArrowLeft className="h-5 w-5" />
              </Button>
              <div>
                <DialogTitle className="text-xl">
                  {METRIC_TITLES[metricType]} - {vmName}
                </DialogTitle>
                <p className="text-sm text-muted-foreground mt-1">
                  VMID: {vmid} • Tipo: {vmType.toUpperCase()}
                </p>
              </div>
            </div>
            <Select value={timeframe} onValueChange={setTimeframe}>
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIMEFRAME_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </DialogHeader>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-6">{renderChart()}</div>
      </DialogContent>
    </Dialog>
  )
}
