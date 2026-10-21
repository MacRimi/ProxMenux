type Translate = (key: string, params?: Record<string, string | number>) => string

export interface OptimizationSourceError {
  kind: "unavailable" | "loadFailed"
  detail?: string
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
