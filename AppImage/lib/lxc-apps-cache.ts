// Shared cross-component cache for the LXC App-tab payload
// (registered sidecar + auto-detected suggestions). Used by both
// virtual-machines.tsx (which prefetches on modal open and on hover)
// and lxc-app-panel.tsx (which reads the cache first and only fetches
// if empty). The in-flight promise map dedups concurrent requests: if
// the parent already fired a prefetch, the panel awaits the SAME
// promise instead of duplicating the request against the backend —
// no more racing fetches on tab switch during a slow first visit.

import { fetchApi } from "./api-config"

export type LxcAppsBundle = {
  sidecar: any
  suggestions: any | null
}

const dataCache = new Map<number, LxcAppsBundle>()
const inFlight = new Map<number, Promise<LxcAppsBundle | null>>()

export function getLxcAppsCached(vmid: number): LxcAppsBundle | undefined {
  return dataCache.get(vmid)
}

export function fetchLxcApps(vmid: number): Promise<LxcAppsBundle | null> {
  const existing = inFlight.get(vmid)
  if (existing) return existing
  const p = Promise.all([
    fetchApi(`/api/vms/${vmid}/apps`).catch(() => null) as Promise<any>,
    fetchApi(`/api/vms/${vmid}/apps/suggestions`).catch(() => null) as Promise<any>,
  ])
    .then(([sc, sug]) => {
      if (!sc) return null
      const bundle: LxcAppsBundle = { sidecar: sc, suggestions: sug }
      dataCache.set(vmid, bundle)
      return bundle
    })
    .finally(() => {
      inFlight.delete(vmid)
    })
  inFlight.set(vmid, p)
  return p
}

export function invalidateLxcApps(vmid: number): void {
  dataCache.delete(vmid)
}

// Seed the cache with a sidecar payload from the bulk modal-cache
// endpoint. Only the sidecar side is populated — suggestions still
// resolve lazily when the App panel actually mounts (the bulk
// endpoint intentionally excludes them since most guests don't
// need the auto-detected chips and the payload would balloon).
export function seedLxcAppsCache(vmid: number, sidecar: any): void {
  if (!sidecar) return
  const existing = dataCache.get(vmid)
  if (existing) return  // per-panel fetch already ran, don't overwrite
  dataCache.set(vmid, { sidecar, suggestions: null })
}
