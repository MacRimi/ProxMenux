"use client"

import { useState, useEffect } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { AlertCircle, CheckCircle2 } from "lucide-react"
import { io, type Socket } from "socket.io-client"

interface ScriptTerminalModalProps {
  open: boolean
  onClose: () => void
  scriptPath: string
  scriptName: string
  params?: Record<string, string>
  title: string
  description: string
}

interface WebInteraction {
  type: "yesno" | "menu" | "msgbox" | "input"
  id: string
  title: string
  text: string
  options?: string[]
}

export function ScriptTerminalModal({
  open,
  onClose,
  scriptPath,
  scriptName,
  params = {},
  title,
  description,
}: ScriptTerminalModalProps) {
  const [socket, setSocket] = useState<Socket | null>(null)
  const [sessionId] = useState(() => Math.random().toString(36).substring(7))
  const [terminalOutput, setTerminalOutput] = useState<string>("")
  const [isRunning, setIsRunning] = useState(false)
  const [isComplete, setIsComplete] = useState(false)
  const [exitCode, setExitCode] = useState<number | null>(null)
  const [interaction, setInteraction] = useState<WebInteraction | null>(null)

  useEffect(() => {
    if (!open) return

    const newSocket = io("http://localhost:8008", {
      transports: ["websocket"],
      reconnection: true,
    })

    newSocket.on("connect", () => {
      console.log("[v0] WebSocket connected")
      // Ejecutar el script
      newSocket.emit("execute_script", {
        session_id: sessionId,
        script_path: scriptPath,
        script_name: scriptName,
        params,
      })
      setIsRunning(true)
    })

    newSocket.on("script_output", (data: { line: string }) => {
      setTerminalOutput((prev) => prev + data.line + "\n")
    })

    newSocket.on("web_interaction", (data: WebInteraction) => {
      console.log("[v0] Web interaction received:", data)
      setInteraction(data)
    })

    newSocket.on("script_complete", (data: { exit_code: number }) => {
      console.log("[v0] Script complete, exit code:", data.exit_code)
      setIsRunning(false)
      setIsComplete(true)
      setExitCode(data.exit_code)
    })

    setSocket(newSocket)

    return () => {
      newSocket.disconnect()
    }
  }, [open, sessionId, scriptPath, scriptName, params])

  const handleInteractionResponse = (value: string) => {
    if (!socket || !interaction) return

    console.log("[v0] Sending interaction response:", value)
    socket.emit("interaction_response", {
      session_id: sessionId,
      interaction_id: interaction.id,
      value,
    })

    // Escribir la respuesta en la terminal
    setTerminalOutput((prev) => prev + `\n> ${value}\n`)
    setInteraction(null)
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onClose}>
        <DialogContent className="max-w-4xl h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {isRunning && <span className="animate-spin">⚙️</span>}
              {isComplete && exitCode === 0 && <CheckCircle2 className="w-5 h-5 text-green-500" />}
              {isComplete && exitCode !== 0 && <AlertCircle className="w-5 h-5 text-red-500" />}
              {title}
            </DialogTitle>
            <p className="text-sm text-muted-foreground">{description}</p>
          </DialogHeader>

          <div className="flex-1 bg-black rounded-md p-4 overflow-auto font-mono text-sm text-green-400">
            <pre className="whitespace-pre-wrap">{terminalOutput}</pre>
            {isRunning && <span className="animate-pulse">_</span>}
          </div>

          {isComplete && (
            <div
              className={`p-3 rounded-md ${exitCode === 0 ? "bg-green-500/10 text-green-500" : "bg-red-500/10 text-red-500"}`}
            >
              {exitCode === 0 ? "✓ Script completed successfully" : `✗ Script failed with exit code ${exitCode}`}
            </div>
          )}

          <div className="flex justify-between items-center">
            <span className="text-sm text-muted-foreground">Session ID: {sessionId}</span>
            <Button onClick={onClose} disabled={isRunning}>
              {isRunning ? "Running..." : "Close"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {interaction && (
        <Dialog open={true} onOpenChange={() => setInteraction(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{interaction.title}</DialogTitle>
            </DialogHeader>
            <p className="text-sm">{interaction.text}</p>

            <div className="flex gap-2 justify-end">
              {interaction.type === "yesno" && (
                <>
                  <Button variant="outline" onClick={() => handleInteractionResponse("no")}>
                    No
                  </Button>
                  <Button onClick={() => handleInteractionResponse("yes")}>Yes</Button>
                </>
              )}
              {interaction.type === "msgbox" && <Button onClick={() => handleInteractionResponse("ok")}>OK</Button>}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
