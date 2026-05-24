/**
 * Helpers for opening WebSocket connections that require a single-use ticket.
 *
 * The browser WebSocket API does not allow custom request headers, so the JWT
 * Bearer token used for REST calls cannot be sent on the handshake. Instead we
 * POST to /api/terminal/ticket (which does require the Bearer token), receive
 * a one-shot ticket with TTL ~5s, and append it to the WebSocket URL as a
 * query parameter. The backend consumes the ticket atomically on handshake.
 *
 * See AppImage/scripts/flask_terminal_routes.py — `_issue_terminal_ticket`,
 * `_consume_terminal_ticket`, `_ws_auth_check`.
 */

import { fetchApi, getApiBaseUrl, API_PORT } from "@/lib/api-config"

/**
 * Build a WebSocket URL for a given path (e.g. "/ws/terminal" or
 * "/ws/script/<id>"). Centralizes the ws:// vs wss:// decision so a
 * single fix benefits every terminal modal in the app.
 *
 * Why not just `window.location.protocol === "https:" ? "wss:" : "ws:"`?
 * On iPad Safari (and some other mobile browsers) with a self-signed
 * cert the user manually accepted, `location.protocol` can report
 * "http:" even though the page was loaded over HTTPS — secure-context
 * downgrade for untrusted certs. The frontend would then open ws://
 * against the HTTPS endpoint; the server replies with SSL handshake
 * errors and the client retries in a loop. We observed this tipping
 * the gevent server into a 4.4 GB RSS spiral on .55 before systemd
 * OOM-killed the AppImage.
 *
 * Resolution: prefer the protocol from the absolute API base URL
 * (which is set up at app init by getApiBaseUrl and is always honest
 * about ws/wss), only falling back to window.location.protocol when
 * the API base is relative (i.e. behind a reverse proxy on a standard
 * port — where the proxy decides the actual scheme anyway).
 */
export function getWsUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`

  if (typeof window === "undefined") {
    return `ws://localhost:${API_PORT}${normalizedPath}`
  }

  // Multi-signal HTTPS detection — any single signal saying https
  // wins. The deliberate bias toward https comes from how the two
  // failure modes differ: wss:// against a plaintext server closes
  // cleanly with one "WebSocket connection error", while ws://
  // against an https server triggers the SSL-handshake loop that
  // OOM-killed gevent on .55. Bias toward wss is the safer
  // direction when in doubt.
  //
  // Signals:
  //   - getApiBaseUrl() absolute URL scheme (typically the most
  //     accurate, but it ultimately derives from
  //     window.location.protocol — included for completeness)
  //   - window.location.protocol  (the obvious one — but iPad Safari
  //     with self-signed certs can report "http:" even when the page
  //     was loaded over HTTPS)
  //   - window.isSecureContext    (true even when protocol misreports;
  //     the browser still treats the page as secure for crypto APIs)
  //   - document.URL / document.baseURI  (the full URL the browser
  //     actually thinks it's at — last-resort cross-check)
  const apiBase = getApiBaseUrl()
  const docUrl =
    typeof document !== "undefined"
      ? (document.URL || document.baseURI || "")
      : ""

  const isHttps =
    apiBase.startsWith("https://") ||
    window.location.protocol === "https:" ||
    (typeof window.isSecureContext === "boolean" && window.isSecureContext) ||
    docUrl.startsWith("https://")

  const proto = isHttps ? "wss:" : "ws:"

  // Pick the host:port to point the WebSocket at:
  //   - If apiBase is absolute, strip its scheme — that's where the
  //     REST API lives, so the WS endpoint lives there too.
  //   - Otherwise (proxy / standard port), reuse the current
  //     window.location.host so the proxy fronts both REST and WS.
  let hostPort: string
  if (apiBase.startsWith("https://")) {
    hostPort = apiBase.slice("https://".length)
  } else if (apiBase.startsWith("http://")) {
    hostPort = apiBase.slice("http://".length)
  } else {
    hostPort = window.location.host
  }

  return `${proto}//${hostPort}${normalizedPath}`
}

type TicketResponse = {
  success?: boolean
  ticket?: string
  ttl_seconds?: number
}

/**
 * Fetch a one-shot terminal ticket from the backend. Returns the ticket string
 * or null if the call fails. Callers should treat null as "open without ticket"
 * — the backend's _ws_auth_check still accepts unticketed handshakes when auth
 * is disabled or declined, so a fresh-install / no-auth setup keeps working.
 */
export async function fetchTerminalTicket(): Promise<string | null> {
  try {
    const res = await fetchApi<TicketResponse>("/api/terminal/ticket", { method: "POST" })
    return typeof res?.ticket === "string" && res.ticket.length > 0 ? res.ticket : null
  } catch {
    return null
  }
}

/**
 * Take a base WebSocket URL (e.g. "ws://host:8008/ws/terminal") and return a
 * URL with `?ticket=<value>` appended. If the ticket fetch fails the original
 * URL is returned unchanged so the handshake can still succeed in unauth mode.
 */
export async function getTicketedWsUrl(baseUrl: string): Promise<string> {
  const ticket = await fetchTerminalTicket()
  if (!ticket) return baseUrl
  const sep = baseUrl.includes("?") ? "&" : "?"
  return `${baseUrl}${sep}ticket=${encodeURIComponent(ticket)}`
}
