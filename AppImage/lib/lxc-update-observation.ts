import { fetchApi } from "./api-config"

interface UpdateObservation {
  last_check?: string | null
  stale?: boolean
  stale_after_seconds?: number
  available?: boolean
  count?: number | null
  error?: string | null
}

export function getLxcOsUpdateState(observation?: UpdateObservation, now = Date.now()): "unknown" | "pending" | "current" {
  if (isLxcUpdateStale(observation, now) || observation?.error
      || typeof observation?.available !== "boolean"
      || !Number.isInteger(observation.count) || (observation.count ?? -1) < 0
      || observation.available !== ((observation.count ?? 0) > 0)) return "unknown"
  return observation.available ? "pending" : "current"
}

export function isLxcUpdateStale(observation?: UpdateObservation, now = Date.now()): boolean {
  if (!observation || observation.stale === true) return true
  const checked = Date.parse(observation.last_check || "")
  const age = now - checked
  const limit = (observation.stale_after_seconds ?? 172800) * 1000
  return !Number.isFinite(checked) || age < 0 || age >= limit
}

// Called only by the OS section's explicit button. Uses installed package
// state and existing indexes; fetching this never upgrades or refreshes APT.
export function checkLxcUpdates<T>(vmid: number): Promise<T> {
  return fetchApi<T>(`/api/vms/${vmid}/updates/check`, { method: "POST" })
}

// Explicit action: refresh indexes and check an already-running CT. The
// backend owns the job even if the browser closes or navigates away.
export async function refreshCheckLxcUpdates<T>(vmid: number): Promise<T> {
  const job = await fetchApi<{ job_id: string }>(`/api/vms/${vmid}/updates/refresh-check`, { method: "POST" })
  const deadline = Date.now() + 8 * 60_000
  while (Date.now() < deadline) {
    const result = await fetchApi<{ state: string; error?: string; update_check?: T }>(
      `/api/vms/${vmid}/updates/refresh-check/${job.job_id}`)
    if (result.state === "failed") throw new Error("osStatusUnavailable")
    if (result.state === "complete") return result.update_check as T
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
  throw new Error("checkStillRunning")
}
