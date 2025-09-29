import { type NextRequest, NextResponse } from "next/server"

export async function GET(request: NextRequest) {
  try {
    console.log("[v0] API route /api/system-info called")

    // Try to connect to Flask server on port 8008
    const flaskUrl = "http://localhost:8008/api/system-info"
    console.log("[v0] Attempting to fetch from Flask server:", flaskUrl)

    const response = await fetch(flaskUrl, {
      method: "GET",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      // Add timeout
      signal: AbortSignal.timeout(5000),
    })

    console.log("[v0] Flask system-info response status:", response.status)

    if (!response.ok) {
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const data = await response.json()
    console.log("[v0] Flask system-info data received:", data)

    return NextResponse.json(data)
  } catch (error) {
    console.error("[v0] Error connecting to Flask server for system-info:", error)

    // Return fallback system info if Flask server is not available
    const fallbackData = {
      hostname: "proxmox-01",
      node_id: "pve-node-01",
      pve_version: "PVE 8.1.3",
      status: "online",
      timestamp: new Date().toISOString(),
      source: "fallback",
    }

    console.log("[v0] Returning fallback system-info data:", fallbackData)
    return NextResponse.json(fallbackData)
  }
}
