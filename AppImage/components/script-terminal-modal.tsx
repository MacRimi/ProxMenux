"use client"

import { useEffect, useRef, useState } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { X, CheckCircle2, XCircle, Loader2 } from "lucide-react"

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
  message: string
  options?: Array<{ label: string; value: string }>
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
  const terminalRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<any>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitAddonRef = useRef<any>(null)
  const [sessionId] = useState(() => Math.random().toString(36).substring(7))

  const [isConnected, setIsConnected] = useState(false)
  const [isComplete, setIsComplete] = useState(false)
  const [exitCode, setExitCode] = useState<number | null>(null)
  const [currentInteraction, setCurrentInteraction] = useState<WebInteraction | null>(null)

  const paramsStr = JSON.stringify(params)

  useEffect(() => {
    if (!open) return

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      console.log("[v0] WebSocket already connected, skipping initialization")
      return
    }

    let term: any = null
    let fitAddon: any = null

    const initTerminal = async () => {
      if (!terminalRef.current) return

      console.log("[v0] Initializing terminal for session:", sessionId)

      // Dynamic import to avoid SSR issues
      const { Terminal } = await import("xterm")
      const { FitAddon } = await import("xterm-addon-fit")

      term = new Terminal({
        cursorBlink: true,
        fontSize: 14,
        fontFamily: 'Menlo, Monaco, "Courier New", monospace',
        theme: {
          background: "#1a1b26",
          foreground: "#a9b1d6",
          cursor: "#c0caf5",
          black: "#32344a",
          red: "#f7768e",
          green: "#9ece6a",
          yellow: "#e0af68",
          blue: "#7aa2f7",
          magenta: "#ad8ee6",
          cyan: "#449dab",
          white: "#787c99",
          brightBlack: "#444b6a",
          brightRed: "#ff7a93",
          brightGreen: "#b9f27c",
          brightYellow: "#ff9e64",
          brightBlue: "#7da6ff",
          brightMagenta: "#bb9af7",
          brightCyan: "#0db9d7",
          brightWhite: "#acb0d0",
        },
      })

      fitAddon = new FitAddon()
      term.loadAddon(fitAddon)
      term.open(terminalRef.current)

      setTimeout(() => {
        fitAddon.fit()
      }, 100)

      termRef.current = term
      fitAddonRef.current = fitAddon

      // Connect to WebSocket
      const wsUrl = getWebSocketUrl()
      console.log("[v0] Connecting to WebSocket:", wsUrl)
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setIsConnected(true)
        term.writeln("\x1b[32mConnected to script execution.\x1b[0m")
        console.log("[v0] WebSocket connected, sending init message")

        const parsedParams = JSON.parse(paramsStr)

        // Flask expects to receive the session info and will start the script
        ws.send(
          JSON.stringify({
            script_path: scriptPath,
            script_name: scriptName,
            params: parsedParams,
          }),
        )
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          console.log("[v0] Received WebSocket message type:", data.type, data)

          if (data.type === "output") {
            // Regular terminal output
            term.write(data.data)
          } else if (data.type === "interaction") {
            // Web interaction detected
            console.log("[v0] Web interaction received:", data.interaction)
            setCurrentInteraction(data.interaction)
          } else if (data.type === "exit") {
            // Script exited, code:
            console.log("[v0] Script exited, code:", data.code)
            setIsComplete(true)
            setExitCode(data.code)
            if (data.code === 0) {
              term.writeln("\r\n\x1b[32m✓ Script completed successfully\x1b[0m")
            } else {
              term.writeln(`\r\n\x1b[31m✗ Script failed with exit code ${data.code}\x1b[0m`)
            }
          }
        } catch (e) {
          // Not JSON, treat as raw output
          console.log("[v0] Received raw data:", event.data)
          term.write(event.data)
        }
      }

      ws.onerror = (error) => {
        console.error("[v0] WebSocket error:", error)
        setIsConnected(false)
        term.writeln("\r\n\x1b[31m[ERROR] WebSocket connection error\x1b[0m")
      }

      ws.onclose = () => {
        console.log("[v0] WebSocket closed")
        setIsConnected(false)
        term.writeln("\r\n\x1b[33m[INFO] Connection closed\x1b[0m")
      }

      // Handle window resize
      const handleResize = () => {
        fitAddon.fit()
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              type: "resize",
              cols: term.cols,
              rows: term.rows,
            }),
          )
        }
      }
      window.addEventListener("resize", handleResize)

      return () => {
        window.removeEventListener("resize", handleResize)
      }
    }

    initTerminal()

    return () => {
      if (!open) {
        console.log("[v0] Cleaning up WebSocket and terminal")
        if (wsRef.current) {
          wsRef.current.close()
          wsRef.current = null
        }
        if (termRef.current) {
          termRef.current.dispose()
          termRef.current = null
        }
      }
    }
  }, [open, sessionId, scriptPath, scriptName, paramsStr])

  function getWebSocketUrl(): string {
    if (typeof window === "undefined") {
      return `ws://localhost:8008/ws/script/${sessionId}`
    }

    const { hostname } = window.location
    const isLocalhost = hostname === "localhost" || hostname === "127.0.0.1"

    if (isLocalhost) {
      return `ws://localhost:8008/ws/script/${sessionId}`
    }

    // Direct access to server
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    return `${wsProtocol}//${hostname}:8008/ws/script/${sessionId}`
  }

  const handleInteractionResponse = (value: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      console.log("[v0] Sending interaction response:", value, "for interaction:", currentInteraction?.id)
      wsRef.current.send(value + "\n")
      setCurrentInteraction(null)

      if (termRef.current) {
        termRef.current.writeln(`\r\n\x1b[36m> ${value}\x1b[0m`)
      }
    }
  }

  const renderInteraction = () => {
    if (!currentInteraction) return null

    const { type, title, message, options } = currentInteraction

    if (type === "yesno") {
      return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <Card className="w-full max-w-md p-6 space-y-4">
            <h3 className="text-lg font-semibold">{title}</h3>
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">{message}</p>
            <div className="flex gap-2 justify-end">
              <Button variant="outline" onClick={() => handleInteractionResponse("no")}>
                No
              </Button>
              <Button onClick={() => handleInteractionResponse("yes")}>Yes</Button>
            </div>
          </Card>
        </div>
      )
    }

    if (type === "menu" && options) {
      return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <Card className="w-full max-w-md p-6 space-y-4 max-h-[80vh] overflow-y-auto">
            <h3 className="text-lg font-semibold">{title}</h3>
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">{message}</p>
            <div className="space-y-2">
              {options.map((option: any) => (
                <Button
                  key={option.value}
                  variant="outline"
                  className="w-full justify-start bg-transparent"
                  onClick={() => handleInteractionResponse(option.value)}
                >
                  {option.label}
                </Button>
              ))}
            </div>
          </Card>
        </div>
      )
    }

    if (type === "msgbox") {
      return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <Card className="w-full max-w-md p-6 space-y-4">
            <h3 className="text-lg font-semibold">{title}</h3>
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">{message}</p>
            <div className="flex justify-end">
              <Button onClick={() => handleInteractionResponse("ok")}>OK</Button>
            </div>
          </Card>
        </div>
      )
    }

    return null
  }

  if (!open) return null

  return (
    <>
      <Dialog open={open} onOpenChange={onClose}>
        <DialogContent className="max-w-4xl h-[80vh] p-0 flex flex-col">
          <DialogTitle className="sr-only">{title}</DialogTitle>

          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b">
            <div className="flex items-center gap-2">
              {isComplete ? (
                exitCode === 0 ? (
                  <CheckCircle2 className="h-5 w-5 text-green-500" />
                ) : (
                  <XCircle className="h-5 w-5 text-red-500" />
                )
              ) : (
                <Loader2 className="h-5 w-5 animate-spin" />
              )}
              <div>
                <h2 className="text-lg font-semibold">{title}</h2>
                {description && <p className="text-sm text-muted-foreground">{description}</p>}
              </div>
            </div>
            <Button variant="ghost" size="icon" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>

          {/* Terminal */}
          <div className="flex-1 overflow-hidden p-4">
            <div ref={terminalRef} className="h-full w-full" />
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between p-4 border-t">
            <div className="text-sm text-muted-foreground">
              Session ID: {sessionId}
              {isConnected && <span className="ml-2 text-green-500">● Connected</span>}
            </div>
            {isComplete && <Button onClick={onClose}>Close</Button>}
          </div>
        </DialogContent>
      </Dialog>

      {/* Interaction Modal */}
      {renderInteraction()}
    </>
  )
}
