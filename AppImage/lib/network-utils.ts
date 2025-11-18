export const getUnitsSettings = () => {
  if (typeof window === 'undefined') return { networkUnit: 'Bytes' as const }
  
  try {
    const settings = localStorage.getItem('unitsSettings')
    if (settings) {
      const parsed = JSON.parse(settings)
      return { networkUnit: parsed.networkUnit || 'Bytes' }
    }
  } catch (e) {
    console.error('[v0] Error reading units settings:', e)
  }
  
  return { networkUnit: 'Bytes' as const }
}

export const formatNetworkTraffic = (sizeInGB: number, unit: "Bytes" | "Bits" = "Bytes"): string => {
  if (unit === "Bits") {
    const sizeInGb = sizeInGB * 8 // Convert gigabytes to gigabits
    
    // Use decimal (base 1000) for bits
    if (sizeInGb < 0.001) {
      return `${(sizeInGb * 1000 * 1000).toFixed(2)} Mb`
    } else if (sizeInGb < 1) {
      return `${(sizeInGb * 1000).toFixed(2)} Mb`
    } else if (sizeInGb < 1000) {
      return `${sizeInGb.toFixed(1)} Gb`
    } else if (sizeInGb < 1000000) {
      return `${(sizeInGb / 1000).toFixed(2)} Tb`
    } else {
      return `${(sizeInGb / 1000000).toFixed(2)} Pb`
    }
  } else {
    // Bytes mode - use binary base (1024)
    if (sizeInGB < 1) {
      return `${(sizeInGB * 1024).toFixed(1)} MB`
    } else if (sizeInGB < 1024) {
      return `${sizeInGB.toFixed(1)} GB`
    } else {
      return `${(sizeInGB / 1024).toFixed(1)} TB`
    }
  }
}

export const getNetworkLabel = (unit: "Bytes" | "Bits", type: "received" | "sent"): string => {
  if (unit === "Bits") {
    return type === "received" ? "Bits Received" : "Bits Sent"
  }
  return type === "received" ? "Bytes Received" : "Bytes Sent"
}
