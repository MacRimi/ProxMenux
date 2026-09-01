// Shared cross-component cache for the LXC App-tab payload
// (registered sidecar + cached detection suggestions). Used by both
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
const cacheRevision = new Map<number, number>()

export function getLxcAppsCached(vmid: number): LxcAppsBundle | undefined {
  return dataCache.get(vmid)
}

// Write-through after a successful App/Updates mutation.  The API returns the
// complete sidecar, so evicting this entry would throw away newer data and
// make the App tab flash "Loading applications..." on its next mount.  Keep
// the already-fetched suggestions unless the caller explicitly replaces them.
export function setLxcAppsCached(
  vmid: number,
  sidecar: any,
  suggestions?: any | null,
): LxcAppsBundle {
  cacheRevision.set(vmid, (cacheRevision.get(vmid) || 0) + 1)
  const current = dataCache.get(vmid)
  const bundle: LxcAppsBundle = {
    sidecar,
    suggestions: suggestions === undefined
      ? (current?.suggestions ?? null)
      : suggestions,
  }
  dataCache.set(vmid, bundle)
  return bundle
}

export function fetchLxcApps(vmid: number): Promise<LxcAppsBundle | null> {
  const existing = inFlight.get(vmid)
  if (existing) return existing
  const startedRevision = cacheRevision.get(vmid) || 0
  const p = Promise.all([
    fetchApi(`/api/vms/${vmid}/apps`).catch(() => null) as Promise<any>,
    fetchApi(`/api/vms/${vmid}/apps/suggestions`).catch(() => null) as Promise<any>,
  ])
    .then(([sc, sug]) => {
      if (!sc) return null
      const bundle: LxcAppsBundle = { sidecar: sc, suggestions: sug }
      // A successful write may have completed while these GETs were in
      // flight. Never let that older response overwrite the mutation result.
      if ((cacheRevision.get(vmid) || 0) !== startedRevision) {
        return dataCache.get(vmid) ?? null
      }
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
  cacheRevision.set(vmid, (cacheRevision.get(vmid) || 0) + 1)
  dataCache.delete(vmid)
}

// Seed the cache from the bulk modal-cache endpoint. Both registered
// apps and startup detection suggestions are already in memory, so
// opening the App tab never starts a discovery scan.
export function seedLxcAppsCache(
  vmid: number,
  sidecar: any,
  suggestions?: any | null,
): void {
  if (!sidecar) return
  const existing = dataCache.get(vmid)
  if (existing) return  // per-panel fetch already ran, don't overwrite
  dataCache.set(vmid, { sidecar, suggestions: suggestions ?? null })
}
