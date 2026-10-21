type Translate = (key: string, params?: Record<string, string | number>) => string

const SOURCE_TOOLS = new Set([
  "subscription_banner", "time_sync", "apt_languages", "journald", "logrotate",
  "system_limits", "memory_settings", "zram_swap", "kernel_panic", "apt_ipv4",
  "kexec", "rpc", "motd", "system_utils", "network_optimization", "bashrc_custom",
  "figurine", "fastfetch", "log2ram", "zfs_autotrim", "amd_fixes", "persistent_network",
  "vfio_iommu", "lvm_repair", "repo_cleanup", "proxmox_repos", "entropy",
])

export function optimizationSourceName(tool: string, fallback: string, t: Translate): string {
  return SOURCE_TOOLS.has(tool) ? t(`settings.optimizations.sourceToolNames.${tool}`) : fallback
}

export interface OptimizationSourceError {
  kind: "unavailable" | "loadFailed"
  detail?: string
}

export interface OptimizationSourceResponse {
  success?: unknown
  source?: unknown
  function?: unknown
  script?: unknown
  deprecated?: unknown
  error?: unknown
}

// Keep the blueprint's English API contract intact; translate only its display.
export function optimizationSourceError(error: OptimizationSourceError, t: Translate): string {
  const detail = error.detail || ""
  const key = "settings.optimizations."
  if (detail === "Function not found in available scripts") return t(key + "sourceFunctionMissing")
  if (detail.startsWith("Unknown tool: ")) return t(key + "sourceUnknownTool", { tool: detail.slice(14) })
  if (detail.startsWith("No function mapping for ")) return t(key + "sourceNoMapping", { tool: detail.slice(24) })
  if (detail === "Source code not available") return t(key + "sourceUnavailable")
  const message = t(key + (error.kind === "unavailable" ? "sourceUnavailable" : "sourceLoadFailed"))
  return detail ? `${message} ${detail}` : message
}
