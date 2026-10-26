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
type AppWatchState = {
  id: string
  state_revision?: number
  managed_oci_app_id?: string | null
  checked_at?: string | null
  [key: string]: any
}
const observedStates = new Map<number, AppWatchState[]>()
const listeners = new Map<number, Set<(bundle: LxcAppsBundle) => void>>()
const stateFields = [
  "installed_version", "latest_version", "latest_published_at",
  "update_available", "error", "checked_at",
] as const

function withObservedStates(vmid: number, sidecar: any): any {
  if (!Array.isArray(sidecar?.apps)) return sidecar
  const observations = new Map((observedStates.get(vmid) || []).map(item => [item.id, item]))
  let changed = false
  let revision = sidecar._revision || 0
  const apps = sidecar.apps.map((app: any) => {
    const observed = observations.get(app.id)
    if (!observed || observed.managed_oci_app_id) return app
    if (observed.state_revision && sidecar._revision && observed.state_revision < sidecar._revision) return app
    // Docker metadata can finish after the app's version probe. It arrives
    // on the same VM feed but must not wait for a new sidecar revision.
    if (app.update_via === "docker" && observed.update_via === "docker" && app.container_name === observed.container_name) {
      for (const field of ["docker_available_version", "docker_update_available", "docker_image_reference", "docker_binding_error"]) {
        if (field in observed && observed[field] !== app[field]) {
          app = { ...app, [field]: observed[field] }
          changed = true
        }
      }
    }
    if (observed.state_revision && sidecar._revision) {
      if (observed.state_revision < sidecar._revision) return app
    } else if (!observed.checked_at || (app.state?.checked_at && observed.checked_at < app.state.checked_at)) {
      return app
    }
    const state = { ...app.state }
    let stateChanged = false
    for (const field of stateFields) {
      if (field in observed && observed[field] !== state[field]) {
        state[field] = observed[field]
        stateChanged = true
      }
    }
    revision = Math.max(revision, observed.state_revision || 0)
    if (!stateChanged) return app
    changed = true
    return { ...app, state }
  })
  return changed || revision !== (sidecar._revision || 0)
    ? { ...sidecar, apps, _revision: revision }
    : sidecar
}

function publish(vmid: number, bundle: LxcAppsBundle): void {
  dataCache.set(vmid, bundle)
  listeners.get(vmid)?.forEach(listener => listener(bundle))
}

export function subscribeLxcApps(vmid: number, listener: (bundle: LxcAppsBundle) => void): () => void {
  const subscribers = listeners.get(vmid) || new Set()
  subscribers.add(listener)
  listeners.set(vmid, subscribers)
  const current = dataCache.get(vmid)
  if (current) listener(current)
  return () => {
    subscribers.delete(listener)
    if (!subscribers.size) listeners.delete(vmid)
  }
}

// Reuse the existing VM-list feed; this never starts a detection or an HTTP request.
export function syncLxcAppsState(vmid: number, watches: AppWatchState[]): void {
  const previous = observedStates.get(vmid) || []
  const previousRevision = Math.max(0, ...previous.map(item => item.state_revision || 0))
  const nextRevision = Math.max(0, ...watches.map(item => item.state_revision || 0))
  if (nextRevision && nextRevision < previousRevision) return
  observedStates.set(vmid, watches)
  const current = dataCache.get(vmid)
  if (!current) return
  const sidecar = withObservedStates(vmid, current.sidecar)
  if (sidecar === current.sidecar) return
  cacheRevision.set(vmid, (cacheRevision.get(vmid) || 0) + 1)
  publish(vmid, { ...current, sidecar })
}

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
    sidecar: withObservedStates(vmid, sidecar),
    suggestions: suggestions === undefined
      ? (current?.suggestions ?? null)
      : suggestions,
  }
  publish(vmid, bundle)
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
      const bundle: LxcAppsBundle = { sidecar: withObservedStates(vmid, sc), suggestions: sug }
      // A successful write may have completed while these GETs were in
      // flight. Never let that older response overwrite the mutation result.
      if ((cacheRevision.get(vmid) || 0) !== startedRevision) {
        return dataCache.get(vmid) ?? null
      }
      publish(vmid, bundle)
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
  observedStates.delete(vmid)
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
  publish(vmid, { sidecar: withObservedStates(vmid, sidecar), suggestions: suggestions ?? null })
}
