import { NextResponse } from "next/server"
import { executeScript } from "@/lib/script-executor"

export async function POST() {
  try {
    // Execute the NVIDIA installer script
    const result = await executeScript("/usr/local/share/proxmenux/scripts/gpu_tpu/nvidia_installer.sh", {
      env: {
        EXECUTION_MODE: "web",
        WEB_LOG: "/tmp/nvidia_web_install.log",
      },
    })

    if (result.exitCode === 0) {
      return NextResponse.json({
        success: true,
        message: "NVIDIA drivers installed successfully",
        output: result.stdout,
      })
    } else {
      return NextResponse.json(
        {
          success: false,
          error: "Installation failed",
          output: result.stderr || result.stdout,
        },
        { status: 500 },
      )
    }
  } catch (error) {
    console.error("NVIDIA installation error:", error)
    return NextResponse.json(
      {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      },
      { status: 500 },
    )
  }
}
