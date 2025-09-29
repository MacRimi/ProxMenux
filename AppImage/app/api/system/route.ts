import { type NextRequest, NextResponse } from "next/server"

export async function GET(request: NextRequest) {
  console.log("[v0] API route /api/system called")

  try {
    const response = await fetch("http://localhost:8008/api/system", {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      // Add timeout to prevent hanging
      signal: AbortSignal.timeout(5000),
    })

    if (!response.ok) {
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const systemData = await response.json()
    console.log("[v0] Successfully fetched real system data from Flask:", systemData)

    return NextResponse.json({
      ...systemData,
      source: "flask",
    })
  } catch (error) {
    console.error("[v0] Failed to fetch from Flask server:", error)

    const fallbackData = {
      cpu_usage: 0,
      memory_usage: 0,
      memory_total: 0,
      memory_used: 0,
      temperature: 0,
      uptime: "Unknown",
      load_average: [0, 0, 0],
      hostname: "proxmox-server",
      node_id: "pve-node",
      timestamp: new Date().toISOString(),
      source: "fallback",
      error: "Flask server unavailable",
    }

    console.log("[v0] Returning fallback data:", fallbackData)
    return NextResponse.json(fallbackData, { status: 503 })
  }
}
