import { type NextRequest, NextResponse } from "next/server"

export async function GET(request: NextRequest) {
  console.log("[v0] API route /api/vms called")

  try {
    const response = await fetch("http://localhost:8008/api/vms", {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      signal: AbortSignal.timeout(5000),
    })

    if (!response.ok) {
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const vmData = await response.json()
    console.log("[v0] Successfully fetched real VM data from Flask:", vmData)

    return NextResponse.json(vmData)
  } catch (error) {
    console.error("[v0] Failed to fetch VM data from Flask server:", error)

    const fallbackData = []

    console.log("[v0] Returning fallback VM data:", fallbackData)
    return NextResponse.json(fallbackData, { status: 503 })
  }
}
