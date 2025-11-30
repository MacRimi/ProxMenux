import { exec } from "child_process"
import { promisify } from "util"

const execAsync = promisify(exec)

interface ScriptExecutorOptions {
  env?: Record<string, string>
  timeout?: number
}

interface ScriptResult {
  stdout: string
  stderr: string
  exitCode: number
}

export async function executeScript(scriptPath: string, options: ScriptExecutorOptions = {}): Promise<ScriptResult> {
  const { env = {}, timeout = 300000 } = options // 5 minutes default timeout

  try {
    const { stdout, stderr } = await execAsync(`bash ${scriptPath}`, {
      env: { ...process.env, ...env },
      timeout,
      maxBuffer: 1024 * 1024 * 10, // 10MB buffer
    })

    return {
      stdout,
      stderr,
      exitCode: 0,
    }
  } catch (error: any) {
    return {
      stdout: error.stdout || "",
      stderr: error.stderr || error.message || "Unknown error",
      exitCode: error.code || 1,
    }
  }
}
