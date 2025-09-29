import { type NextRequest, NextResponse } from "next/server"

export async function GET(request: NextRequest) {
  try {
    console.log("[v0] API route /api/system called")

    // Try to connect to Flask server on port 8008
    const flaskUrl = "http://localhost:8008/api/system"
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

    console.log("[v0] Flask response status:", response.status)
    console.log("[v0] Flask response headers:", Object.fromEntries(response.headers.entries()))

    if (!response.ok) {
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const data = await response.json()
    console.log("[v0] Flask data received:", data)

    return NextResponse.json(data)
  } catch (error) {
    console.error("[v0] Error connecting to Flask server:", error)

    // Return fallback data if Flask server is not available
    const fallbackData = {
      cpu_usage: 67.3,
      memory_usage: 49.4,
      memory_total: 32.0,
      memory_used: 15.8,
      temperature: 52,
      uptime: "15d 7h 23m",
      load_average: [1.23, 1.45, 1.67],
      hostname: "proxmox-01",
      node_id: "pve-node-01",
      timestamp: new Date().toISOString(),
      source: "fallback",
    }

    console.log("[v0] Returning fallback data:", fallbackData)
    return NextResponse.json(fallbackData)
  }
}
