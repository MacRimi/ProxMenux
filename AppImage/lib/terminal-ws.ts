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

import { fetchApi } from "@/lib/api-config"

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
