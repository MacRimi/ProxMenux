// Native Proxmox retention properties, shared by storage and job editors.
export const RETENTION = ["last", "hourly", "daily", "weekly", "monthly", "yearly"] as const

export function parseRetention(prune: string) {
  const fields: Record<string, string> = {}
  let keepAll = false
  for (const part of prune.split(",")) {
    const [key, value] = part.trim().split("=")
    if (key === "keep-all") keepAll = value === "1"
    else if (key?.startsWith("keep-") && Number(value) > 0) fields[key.slice(5)] = String(Number(value))
  }
  return { fields, keepAll }
}

export function buildRetention(fields: Record<string, string>, keepAll: boolean) {
  const parts = RETENTION.filter(key => Number(fields[key]) > 0).map(key => `keep-${key}=${Number(fields[key])}`)
  return parts.length ? parts.join(",") : keepAll ? "keep-all=1" : ""
}
