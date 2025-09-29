import { type NextRequest, NextResponse } from "next/server"

export async function GET(request: NextRequest) {
  try {
    console.log("[v0] API route /api/vms called")

    // Try to connect to Flask server on port 8008
    const flaskUrl = "http://localhost:8008/api/vms"
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

    console.log("[v0] Flask VMs response status:", response.status)
    console.log("[v0] Flask VMs response headers:", Object.fromEntries(response.headers.entries()))

    if (!response.ok) {
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const data = await response.json()
    console.log("[v0] Flask VMs data received:", data)

    return NextResponse.json(data)
  } catch (error) {
    console.error("[v0] Error connecting to Flask server for VMs:", error)

    // Return fallback VM data if Flask server is not available
    const fallbackData = [
      {
        vmid: 100,
        name: "web-server-01",
        status: "running",
        cpu: 0.45,
        mem: 8589934592, // 8GB in bytes
        maxmem: 17179869184, // 16GB in bytes
        disk: 53687091200, // 50GB in bytes
        maxdisk: 107374182400, // 100GB in bytes
        uptime: 1324800, // seconds
      },
      {
        vmid: 101,
        name: "database-server",
        status: "running",
        cpu: 0.23,
        mem: 4294967296, // 4GB in bytes
        maxmem: 8589934592, // 8GB in bytes
        disk: 26843545600, // 25GB in bytes
        maxdisk: 53687091200, // 50GB in bytes
        uptime: 864000, // seconds
      },
      {
        vmid: 102,
        name: "backup-server",
        status: "stopped",
        cpu: 0,
        mem: 0,
        maxmem: 4294967296, // 4GB in bytes
        disk: 10737418240, // 10GB in bytes
        maxdisk: 21474836480, // 20GB in bytes
        uptime: 0,
      },
      {
        vmid: 103,
        name: "test-server",
        status: "stopped",
        cpu: 0,
        mem: 0,
        maxmem: 2147483648, // 2GB in bytes
        disk: 5368709120, // 5GB in bytes
        maxdisk: 10737418240, // 10GB in bytes
        uptime: 0,
      },
    ]

    console.log("[v0] Returning fallback VM data:", fallbackData)
    return NextResponse.json(fallbackData)
  }
}
