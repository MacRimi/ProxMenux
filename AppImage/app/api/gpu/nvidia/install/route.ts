import { NextResponse } from "next/server"
import { exec } from "child_process"
import { promisify } from "util"

const execAsync = promisify(exec)

export async function POST() {
  try {
    const scriptPath = "/usr/local/share/proxmenux/scripts/gpu_tpu/nvidia_installer.sh"
    const webLogPath = "/tmp/nvidia_web_install.log"

    const { stdout, stderr } = await execAsync(`EXECUTION_MODE=web WEB_LOG=${webLogPath} bash ${scriptPath}`, {
      env: {
        ...process.env,
        EXECUTION_MODE: "web",
        WEB_LOG: webLogPath,
      },
      maxBuffer: 10 * 1024 * 1024, // 10MB buffer
    })

    return NextResponse.json({
      success: true,
      message: "NVIDIA drivers installation completed",
      output: stdout,
      log_file: webLogPath,
    })
  } catch (error: any) {
    console.error("[v0] NVIDIA installation error:", error)
    return NextResponse.json(
      {
        success: false,
        error: error.message || "Installation failed",
        output: error.stdout || "",
        stderr: error.stderr || "",
      },
      { status: 500 },
    )
  }
}
