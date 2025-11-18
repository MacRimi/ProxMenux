"use client"
import { useState, useEffect } from "react"
import { Dialog, DialogContent } from "@radix-ui/react-dialog"
import { getUnitsSettings, formatNetworkTraffic, getNetworkLabel } from "@/lib/network-utils"

export function InterfaceDetailsModal({ interface_, onClose, timeframe }: InterfaceDetailsModalProps) {
  const [metricsData, setMetricsData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [networkUnit, setNetworkUnit] = useState<"Bytes" | "Bits">("Bytes")

  useEffect(() => {
    const settings = getUnitsSettings()
    setNetworkUnit(settings.networkUnit as "Bytes" | "Bits")
    
    const handleSettingsChange = () => {
      const settings = getUnitsSettings()
      setNetworkUnit(settings.networkUnit as "Bytes" | "Bits")
    }
    
    window.addEventListener('storage', handleSettingsChange)
    window.addEventListener('unitsSettingsChanged', handleSettingsChange)
    
    return () => {
      window.removeEventListener('storage', handleSettingsChange)
      window.removeEventListener('unitsSettingsChanged', handleSettingsChange)
    }
  }, [])

  const totalReceived = metricsData.length > 0
    ? Math.max(0, (metricsData[metricsData.length - 1].netin || 0) - (metricsData[0].netin || 0))
    : 0

  const totalSent = metricsData.length > 0
    ? Math.max(0, (metricsData[metricsData.length - 1].netout || 0) - (metricsData[0].netout || 0))
    : 0

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto">

        <div>
          <h3 className="text-sm font-medium text-muted-foreground mb-2">
            Network Traffic Statistics (Last 24 Hours)
          </h3>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <p className="text-sm text-muted-foreground">{getNetworkLabel(networkUnit, "received")}</p>
              <p className="text-2xl font-bold text-green-500">{formatNetworkTraffic(totalReceived, networkUnit)}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">{getNetworkLabel(networkUnit, "sent")}</p>
              <p className="text-2xl font-bold text-blue-500">{formatNetworkTraffic(totalSent, networkUnit)}</p>
            </div>
          </div>

        </div>
      </DialogContent>
    </Dialog>
  )
}
