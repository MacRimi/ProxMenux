/**
 * API Configuration for ProxMenux Monitor
 * Handles API URL generation with automatic proxy detection
 */

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
    // Direct access - use explicit port 8008
    return `${protocol}//${hostname}:8008`
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
 * Fetches data from an API endpoint with error handling
 *
 * @param endpoint - API endpoint path
 * @param options - Fetch options
 * @returns Promise with the response data
 */
export async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = getApiUrl(endpoint)

  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
    cache: "no-store",
  })

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`)
  }

  return response.json()
}
