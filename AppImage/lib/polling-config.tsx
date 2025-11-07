"use client"

import { createContext, useContext, useState, useEffect, type ReactNode } from "react"

export interface PollingIntervals {
  storage: number
  network: number
  vms: number
  hardware: number
}

// Default intervals in milliseconds
const DEFAULT_INTERVALS: PollingIntervals = {
  storage: 60000, // 60 seconds
  network: 60000, // 60 seconds
  vms: 30000, // 30 seconds
  hardware: 60000, // 60 seconds
}

const STORAGE_KEY = "proxmenux_polling_intervals"

interface PollingConfigContextType {
  intervals: PollingIntervals
  updateInterval: (key: keyof PollingIntervals, value: number) => void
}

const PollingConfigContext = createContext<PollingConfigContextType | undefined>(undefined)

export function PollingConfigProvider({ children }: { children: ReactNode }) {
  const [intervals, setIntervals] = useState<PollingIntervals>(DEFAULT_INTERVALS)

  // Load from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      try {
        const parsed = JSON.parse(stored)
        setIntervals({ ...DEFAULT_INTERVALS, ...parsed })
      } catch (e) {
        console.error("[v0] Failed to parse stored polling intervals:", e)
      }
    }
  }, [])

  const updateInterval = (key: keyof PollingIntervals, value: number) => {
    setIntervals((prev) => {
      const newIntervals = { ...prev, [key]: value }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newIntervals))
      return newIntervals
    })
  }

  return <PollingConfigContext.Provider value={{ intervals, updateInterval }}>{children}</PollingConfigContext.Provider>
}

export function usePollingConfig() {
  const context = useContext(PollingConfigContext)
  if (!context) {
    throw new Error("usePollingConfig must be used within PollingConfigProvider")
  }
  return context
}

// Interval options for the UI (in milliseconds)
export const INTERVAL_OPTIONS = [
  { label: "10 seconds", value: 10000 },
  { label: "30 seconds", value: 30000 },
  { label: "1 minute", value: 60000 },
  { label: "2 minutes", value: 120000 },
  { label: "5 minutes", value: 300000 },
  { label: "10 minutes", value: 600000 },
  { label: "30 minutes", value: 1800000 },
  { label: "1 hour", value: 3600000 },
]
