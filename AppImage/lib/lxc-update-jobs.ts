/** Opaque viewer metadata only; updater commands and credentials stay server-side. */
export type LxcUpdateJob = {
  id: string
  vmid: number
  state: "running" | "finalizing" | "complete"
  target: "os" | "app" | "both"
  ct_name: string
  script_path: string
  created_at: number
  exit_code: number | null
}

const SEEN = "proxmenux-viewed-update-jobs"

export function viewedUpdateJobs(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(SEEN) || "[]")
    return Array.isArray(value) ? value.filter((id) => typeof id === "string").slice(-128) : []
  } catch {
    return []
  }
}

export function markUpdateJobViewed(id: string) {
  try {
    localStorage.setItem(SEEN, JSON.stringify([...new Set([...viewedUpdateJobs(), id])].slice(-128)))
    window.dispatchEvent(new Event("proxmenux-update-jobs-viewed"))
  } catch {
    // Unavailable browser storage never controls or restarts server work.
  }
}
