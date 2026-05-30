/**
 * API Configuration for ProxMenux Monitor
 * Handles API URL generation with automatic proxy detection
 */

/**
 * API Server Port Configuration
 * Default: 8008 (production)
 * Can be changed to 8009 for beta testing
 * This can also be set via NEXT_PUBLIC_API_PORT environment variable
 */
export const API_PORT = process.env.NEXT_PUBLIC_API_PORT || "8008"

/**
 * Gets the base URL for API calls
 * Automatically detects if running behind a proxy by checking if we're on a standard port
 *
 * @returns Base URL for API endpoints
 */
export function getApiBaseUrl(): string {
  if (typeof window === "undefined") {
    return ""
  }

  const { protocol, hostname, port } = window.location

  // If accessing via standard ports (80/443) or no port, assume we're behind a proxy
  // In this case, use relative URLs so the proxy handles routing
  const isStandardPort = port === "" || port === "80" || port === "443"

  if (isStandardPort) {
    return ""
  } else {
    return `${protocol}//${hostname}:${API_PORT}`
  }
}

/**
 * Constructs a full API URL
 *
 * @param endpoint - API endpoint path (e.g., '/api/system')
 * @returns Full API URL
 */
export function getApiUrl(endpoint: string): string {
  const baseUrl = getApiBaseUrl()

  // Ensure endpoint starts with /
  const normalizedEndpoint = endpoint.startsWith("/") ? endpoint : `/${endpoint}`

  return `${baseUrl}${normalizedEndpoint}`
}

/**
 * Gets the JWT token from localStorage
 *
 * @returns JWT token or null if not authenticated
 */
export function getAuthToken(): string | null {
  if (typeof window === "undefined") {
    return null
  }
  return localStorage.getItem("proxmenux-auth-token")
}

/**
 * Fetches data from an API endpoint with error handling
 *
 * @param endpoint - API endpoint path
 * @param options - Fetch options
 * @returns Promise with the response data
 */
export async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = getApiUrl(endpoint)

  const token = getAuthToken()

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  }

  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }

  const response = await fetch(url, {
    ...options,
    headers,
    cache: "no-store",
  })

    if (!response.ok) {
      if (response.status === 401) {
        // Token is missing, expired, or signed under a previous JWT_SECRET
        // (rotated per-install). Drop the stale token and force a single
        // reload so the page-level auth gate (`app/page.tsx`) can render
        // <Login> instead of cascading 401s from every authenticated
        // component on mount.
        //
        // Only react when we actually had a token to invalidate. A 401
        // without any token in localStorage means the caller is the
        // Login screen itself, or a leftover fetch from a recently
        // unmounted Dashboard — reloading there does nothing but waste
        // the user's keystrokes and can leave the cascade flag set
        // forever, swallowing the very 401 that we'd want to recover
        // from after a successful re-login. The fix: bail out early
        // if we have no token to invalidate.
        if (typeof window !== "undefined") {
          let hadToken = false
          try {
            hadToken = !!localStorage.getItem("proxmenux-auth-token")
          } catch {
            // private browsing — assume yes so we attempt recovery.
            hadToken = true
          }
          if (!hadToken) {
            throw new Error(`Unauthorized: ${endpoint}`)
          }
          try {
            localStorage.removeItem("proxmenux-auth-token")
          } catch {
            // localStorage might be unavailable in private browsing — ignore.
          }
          try {
            if (!sessionStorage.getItem("proxmenux-auth-401-handled")) {
              sessionStorage.setItem("proxmenux-auth-401-handled", "1")
              window.location.reload()
            }
          } catch {
            // sessionStorage unavailable — fall back to a plain reload.
            window.location.reload()
          }
        }
        throw new Error(`Unauthorized: ${endpoint}`)
      }
      // Try to surface the backend's JSON error payload instead of a
      // bare `500 INTERNAL SERVER ERROR`. The Flask routes consistently
      // return `{error: "..."}` on failure (e.g. /api/vms/<id>/control
      // includes the pvesh stderr — telling the user "no space left on
      // device" is infinitely more useful than the raw status text).
      try {
        const ct = response.headers.get("content-type") || ""
        if (ct.includes("application/json")) {
          const body = await response.json()
          const detail =
            (body && (body.error || body.message)) || ""
          if (detail) {
            throw new Error(detail)
          }
        }
      } catch (parseErr) {
        if (parseErr instanceof Error && parseErr.message.includes("API request failed")) {
          throw parseErr
        }
        // JSON parse failed — fall through to the generic message.
      }
      throw new Error(`API request failed: ${response.status} ${response.statusText}`)
    }

    // Check content type to ensure we're getting JSON
    const contentType = response.headers.get("content-type")
    if (!contentType || !contentType.includes("application/json")) {
      const text = await response.text()
      console.error("fetchApi: Expected JSON but got:", contentType, "- Body preview:", text.substring(0, 200))
      throw new Error(`Expected JSON response but got ${contentType || "unknown content type"}`)
    }

    try {
      return await response.json()
    } catch (jsonError) {
      console.error("fetchApi: JSON parse error for", endpoint, "-", jsonError)
      throw new Error(`Invalid JSON response from ${endpoint}`)
    }
}
