import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Cpu } from "@/components/icons/cpu" // Added import for Cpu
import type { PCIDevice } from "../types/hardware" // Fixed import to use relative path instead of alias
import { Progress } from "@/components/ui/progress"

function GPUCard({ device }: { device: PCIDevice }) {
  const hasMonitoring = device.gpu_temperature !== undefined || device.gpu_utilization !== undefined

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Cpu className="h-5 w-5" />
          {device.device}
        </CardTitle>
        <CardDescription>{device.vendor}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <div className="text-muted-foreground">Slot</div>
            <div className="font-medium">{device.slot}</div>
          </div>
          {device.driver && (
            <div>
              <div className="text-muted-foreground">Driver</div>
              <div className="font-medium">{device.driver}</div>
            </div>
          )}
          {device.gpu_driver_version && (
            <div>
              <div className="text-muted-foreground">Driver Version</div>
              <div className="font-medium">{device.gpu_driver_version}</div>
            </div>
          )}
          {device.gpu_memory && (
            <div>
              <div className="text-muted-foreground">Memory</div>
              <div className="font-medium">{device.gpu_memory}</div>
            </div>
          )}
          {device.gpu_compute_capability && (
            <div>
              <div className="text-muted-foreground">Compute Capability</div>
              <div className="font-medium">{device.gpu_compute_capability}</div>
            </div>
          )}
        </div>

        {hasMonitoring && (
          <div className="space-y-3 pt-4 border-t">
            <h4 className="text-sm font-semibold">Real-time Monitoring</h4>

            {device.gpu_temperature !== undefined && (
              <div className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Temperature</span>
                  <span className="font-medium">{device.gpu_temperature}°C</span>
                </div>
                <Progress value={(device.gpu_temperature / 100) * 100} className="h-2" />
              </div>
            )}

            {device.gpu_utilization !== undefined && (
              <div className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">GPU Utilization</span>
                  <span className="font-medium">{device.gpu_utilization}%</span>
                </div>
                <Progress value={device.gpu_utilization} className="h-2" />
              </div>
            )}

            {device.gpu_memory_used && device.gpu_memory_total && (
              <div className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">Memory Usage</span>
                  <span className="font-medium">
                    {device.gpu_memory_used} / {device.gpu_memory_total}
                  </span>
                </div>
                <Progress
                  value={(Number.parseInt(device.gpu_memory_used) / Number.parseInt(device.gpu_memory_total)) * 100}
                  className="h-2"
                />
              </div>
            )}

            {device.gpu_power_draw && (
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Power Draw</span>
                <span className="font-medium">{device.gpu_power_draw}</span>
              </div>
            )}

            {device.gpu_clock_speed && (
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">GPU Clock</span>
                <span className="font-medium">{device.gpu_clock_speed}</span>
              </div>
            )}

            {device.gpu_memory_clock && (
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Memory Clock</span>
                <span className="font-medium">{device.gpu_memory_clock}</span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
