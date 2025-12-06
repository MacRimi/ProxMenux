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
    // Behind a proxy - use relative URL
    return ""
  } else {
    // Direct access - use explicit API port
    const baseUrl = `${protocol}//${hostname}:${API_PORT}`
    return baseUrl
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

  try {
    const response = await fetch(url, {
      ...options,
      headers,
      cache: "no-store",
    })

    if (!response.ok) {
      if (response.status === 401) {
        throw new Error(`Unauthorized: ${endpoint}`)
      }
      throw new Error(`API request failed: ${response.status} ${response.statusText}`)
    }

    return response.json()
  } catch (error) {
    console.error("API fetch error for", endpoint, ":", error)
    throw error
  }
}
