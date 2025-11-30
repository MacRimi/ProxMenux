import { NextResponse } from "next/server"

export async function POST() {
  try {
    // Port 8008 is the production port for Flask server
    const API_PORT = "8008"

    // Use window.location from request headers to detect proxy
    let flaskUrl: string

    // For server-side execution, use localhost
    // In production, the request will come with proper headers
    if (typeof window === "undefined") {
      flaskUrl = `http://localhost:${API_PORT}/api/scripts/execute`
    } else {
      const { protocol, hostname, port } = window.location
      const isStandardPort = port === "" || port === "80" || port === "443"

      if (isStandardPort) {
        // Behind proxy - use relative URL
        flaskUrl = "/api/scripts/execute"
      } else {
        // Direct access
        flaskUrl = `${protocol}//${hostname}:${API_PORT}/api/scripts/execute`
      }
    }

    console.log("[v0] Starting NVIDIA driver installation via:", flaskUrl)

    const response = await fetch(flaskUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        script_path: "/usr/local/share/proxmenux/scripts/gpu_tpu/nvidia_installer.sh",
        env: {
          EXECUTION_MODE: "web",
          WEB_LOG: "/tmp/nvidia_web_install.log",
        },
      }),
    })

    if (!response.ok) {
      throw new Error(`Flask API error: ${response.statusText}`)
    }

    const data = await response.json()

    if (!data.success) {
      throw new Error(data.error || "Failed to start installation")
    }

    console.log("[v0] NVIDIA installation started, session_id:", data.session_id)

    return NextResponse.json({
      success: true,
      session_id: data.session_id,
      message: "NVIDIA installation started",
    })
  } catch (error: any) {
    console.error("[v0] NVIDIA installation error:", error)
    return NextResponse.json(
      {
        success: false,
        error: error.message || "Failed to start NVIDIA driver installation. Please try manually.",
      },
      { status: 500 },
    )
  }
}
