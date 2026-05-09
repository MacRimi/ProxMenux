// Shared accessor for the user-configurable health thresholds.
//
// The backend exposes the full tree at `GET /api/health/thresholds`.
// Several frontend components need *just* the disk-temperature pair
// per drive class to color badges, chart bands, and SVG bands in the
// SMART report — copy-pasting the numbers around led to two
// inconsistent versions diverging from the backend (see Sprint 14.5).
//
// This module memoises the last fetched payload (TTL 30s) and exposes:
//
//   * `getDiskTempThresholdsSync(diskType)` — synchronous read with a
//     conservative fallback to the backend defaults. Safe to call from
//     anywhere, including a render path that can't await.
//   * `loadDiskTempThresholds()` — async fetch + cache update. Returns
//     the cached map; call once on mount of any component that uses
//     the sync getter to ensure the cache is warm.
//   * `useDiskTempThresholds()` — React hook that fires the fetch on
//     mount, re-renders when fresh data arrives, and returns the
//     current map (defaults until the first fetch lands).
//
// The cache is shared across components so opening multiple disk
// modals in quick succession doesn't re-hit the API for each.

import { useEffect, useState } from "react"
import { fetchApi } from "./api-config"

export type DiskClass = "HDD" | "SSD" | "NVMe" | "SAS"

export interface DiskTempThreshold {
  warn: number
  hot: number
}

export type DiskTempMap = Record<DiskClass, DiskTempThreshold>

// Fallback values when the API hasn't responded yet (or fails). These
// match the recommended defaults baked into `health_thresholds.py`.
// Keeping them duplicated here is intentional: the alternative is
// blocking every render until the API comes back, which is worse UX.
export const DEFAULT_DISK_TEMP: DiskTempMap = {
  HDD: { warn: 60, hot: 65 },
  SSD: { warn: 70, hot: 75 },
  NVMe: { warn: 80, hot: 85 },
  SAS: { warn: 55, hot: 65 },
}

const CACHE_TTL_MS = 30_000

// Module-level cache — shared by every component that imports this.
let cached: DiskTempMap = DEFAULT_DISK_TEMP
let cachedAt = 0
let inflight: Promise<DiskTempMap> | null = null

// Subscribers are notified when a fresh fetch lands, so the
// `useDiskTempThresholds` hook can re-render. Plain JS pub/sub —
// nothing fancier needed here.
const subscribers = new Set<(map: DiskTempMap) => void>()

interface ApiThresholdsResponse {
  success: boolean
  thresholds?: {
    disk_temperature?: {
      hdd?: { warning?: { value: number }; critical?: { value: number } }
      ssd?: { warning?: { value: number }; critical?: { value: number } }
      nvme?: { warning?: { value: number }; critical?: { value: number } }
      sas?: { warning?: { value: number }; critical?: { value: number } }
    }
  }
}

function pick(node: any, key: string, fallback: number): number {
  const v = node?.[key]?.value
  return typeof v === "number" && isFinite(v) ? v : fallback
}

function parse(payload: ApiThresholdsResponse): DiskTempMap {
  const dt = payload?.thresholds?.disk_temperature
  if (!dt) return { ...DEFAULT_DISK_TEMP }
  return {
    HDD: {
      warn: pick(dt.hdd, "warning", DEFAULT_DISK_TEMP.HDD.warn),
      hot: pick(dt.hdd, "critical", DEFAULT_DISK_TEMP.HDD.hot),
    },
    SSD: {
      warn: pick(dt.ssd, "warning", DEFAULT_DISK_TEMP.SSD.warn),
      hot: pick(dt.ssd, "critical", DEFAULT_DISK_TEMP.SSD.hot),
    },
    NVMe: {
      warn: pick(dt.nvme, "warning", DEFAULT_DISK_TEMP.NVMe.warn),
      hot: pick(dt.nvme, "critical", DEFAULT_DISK_TEMP.NVMe.hot),
    },
    SAS: {
      warn: pick(dt.sas, "warning", DEFAULT_DISK_TEMP.SAS.warn),
      hot: pick(dt.sas, "critical", DEFAULT_DISK_TEMP.SAS.hot),
    },
  }
}

export async function loadDiskTempThresholds(force = false): Promise<DiskTempMap> {
  const now = Date.now()
  if (!force && cachedAt && now - cachedAt < CACHE_TTL_MS) return cached
  if (inflight) return inflight
  inflight = (async () => {
    try {
      const res = await fetchApi<ApiThresholdsResponse>("/api/health/thresholds")
      if (res?.success) {
        cached = parse(res)
        cachedAt = Date.now()
        subscribers.forEach((cb) => cb(cached))
      }
    } catch {
      // Leave previous cache in place; defaults are good enough.
    } finally {
      inflight = null
    }
    return cached
  })()
  return inflight
}

export function getDiskTempThresholdsSync(diskType: string | undefined): DiskTempThreshold {
  const t = (diskType || "").toUpperCase()
  if (t === "HDD") return cached.HDD
  if (t === "SSD") return cached.SSD
  if (t === "NVME") return cached.NVMe
  if (t === "SAS") return cached.SAS
  // Unknown class — assume SSD-ish numbers (mid-range).
  return cached.SSD
}

/** React hook: triggers a load on mount, re-renders on cache update. */
export function useDiskTempThresholds(): DiskTempMap {
  const [map, setMap] = useState<DiskTempMap>(cached)
  useEffect(() => {
    let alive = true
    const sub = (m: DiskTempMap) => { if (alive) setMap(m) }
    subscribers.add(sub)
    loadDiskTempThresholds().then((m) => { if (alive) setMap(m) })
    return () => { alive = false; subscribers.delete(sub) }
  }, [])
  return map
}

/** Imperative invalidate — call after the user saves new thresholds. */
export function invalidateDiskTempThresholdsCache() {
  cachedAt = 0
}
