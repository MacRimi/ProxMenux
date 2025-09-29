import { type NextRequest, NextResponse } from "next/server"

export async function GET(request: NextRequest) {
  console.log("[v0] API route /api/system-info called")

  try {
    const response = await fetch("http://localhost:8008/api/system-info", {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      signal: AbortSignal.timeout(5000),
    })

    if (!response.ok) {
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const systemInfo = await response.json()
    console.log("[v0] Successfully fetched real system info from Flask:", systemInfo)

    return NextResponse.json({
      ...systemInfo,
      source: "flask",
    })
  } catch (error) {
    console.error("[v0] Failed to fetch system info from Flask server:", error)

    const fallbackData = {
      hostname: "proxmox-server",
      node_id: "pve-node",
      pve_version: "PVE Unknown",
      status: "offline",
      timestamp: new Date().toISOString(),
      source: "fallback",
      error: "Flask server unavailable",
    }

    console.log("[v0] Returning fallback system info:", fallbackData)
    return NextResponse.json(fallbackData, { status: 503 })
  }
}
