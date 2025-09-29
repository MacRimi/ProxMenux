import { type NextRequest, NextResponse } from "next/server"

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const endpoint = searchParams.get("endpoint")

  console.log(`[v0] Flask bridge API called for endpoint: ${endpoint}`)

  try {
    const flaskUrl = `http://localhost:8008/api/${endpoint || "info"}`

    const response = await fetch(flaskUrl, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      signal: AbortSignal.timeout(10000),
    })

    if (!response.ok) {
      throw new Error(`Flask server responded with status: ${response.status}`)
    }

    const data = await response.json()
    console.log(`[v0] Successfully fetched data from Flask endpoint ${endpoint}:`, data)

    return NextResponse.json({
      ...data,
      source: "flask",
      endpoint: endpoint,
    })
  } catch (error) {
    console.error(`[v0] Failed to fetch from Flask server endpoint ${endpoint}:`, error)

    return NextResponse.json(
      {
        error: "Flask server unavailable",
        endpoint: endpoint,
        message: error instanceof Error ? error.message : "Unknown error",
        source: "error",
      },
      { status: 503 },
    )
  }
}
