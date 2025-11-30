import { NextResponse } from "next/server"

export async function POST(request: Request) {
  try {
    const requestUrl = new URL(request.url)
    const API_PORT = "8008"

    // Check if request comes through proxy (standard HTTP/HTTPS ports)
    const isProxied = requestUrl.port === "" || requestUrl.port === "80" || requestUrl.port === "443"

    let flaskUrl: string

    if (isProxied) {
      // Behind proxy - use same host but different path
      flaskUrl = `${requestUrl.protocol}//${requestUrl.host}/api/scripts/execute`
    } else {
      // Direct access - use Flask port
      flaskUrl = `${requestUrl.protocol}//${requestUrl.hostname}:${API_PORT}/api/scripts/execute`
    }

    console.log("[v0] Starting NVIDIA driver installation")
    console.log("[v0] Request URL:", requestUrl.href)
    console.log("[v0] Flask URL:", flaskUrl)

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
      const errorText = await response.text()
      console.error("[v0] Flask API error:", response.status, errorText)
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
