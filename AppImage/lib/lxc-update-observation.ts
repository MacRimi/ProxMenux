import { fetchApi } from "./api-config"

interface UpdateObservation {
  last_check?: string | null
  stale?: boolean
  stale_after_seconds?: number
}

export function isLxcUpdateStale(observation?: UpdateObservation, now = Date.now()): boolean {
  if (!observation || observation.stale === true) return true
  const checked = Date.parse(observation.last_check || "")
  const age = now - checked
  const limit = (observation.stale_after_seconds ?? 86400) * 1000
  return !Number.isFinite(checked) || age < 0 || age >= limit
}

// Called only by the OS section's explicit button. Uses installed package
// state and existing indexes; fetching this never upgrades or refreshes APT.
export function checkLxcUpdates<T>(vmid: number): Promise<T> {
  return fetchApi<T>(`/api/vms/${vmid}/updates/check`, { method: "POST" })
}
