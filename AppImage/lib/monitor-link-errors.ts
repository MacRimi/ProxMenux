type Translate = (key: string, params?: Record<string, string | number>) => string

const ERROR_KEYS: Record<string, string> = {
  monitor_link_address_required: "addressRequired",
  monitor_link_invalid_address: "invalidAddress",
  monitor_link_address_credentials: "addressCredentials",
  monitor_link_invalid_port: "invalidPort",
  monitor_link_invalid_request: "invalidRequest",
  monitor_link_duplicate: "duplicate",
  monitor_link_not_found: "notFound",
  monitor_link_detected_remove: "detectedRemove",
}

// fetchApi preserves the structured response on Error.body. Never expose raw
// server/network messages or treat arbitrary error codes as translation keys.
export function monitorLinkError(error: unknown, t: Translate): string {
  const fallback = () => t("monitorLinks.saveFailed")
  if (!error || typeof error !== "object" || !("body" in error)) return fallback()
  const body = error.body
  if (!body || typeof body !== "object" || !("code" in body) || typeof body.code !== "string") return fallback()
  if (body.code === "monitor_link_limit") {
    const params = "params" in body ? body.params : null
    const count = params && typeof params === "object" && "count" in params ? params.count : null
    return typeof count === "number" && Number.isSafeInteger(count) && count > 0
      ? t("monitorLinks.errors.limit", { count }) : fallback()
  }
  return Object.prototype.hasOwnProperty.call(ERROR_KEYS, body.code)
    ? t(`monitorLinks.errors.${ERROR_KEYS[body.code]}`) : fallback()
}
