"use client"

import type React from "react"
import { useState, useEffect, useRef } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { CheckCircle2, XCircle, Loader2, Activity, GripHorizontal } from "lucide-react"
import { API_PORT } from "@/lib/api-config"
import { useIsMobile } from "@/hooks/use-mobile"

interface WebInteraction {
  type: "yesno" | "menu" | "msgbox" | "input" | "inputbox"
  id: string
  title: string
  message: string
  options?: Array<{ label: string; value: string }>
  default?: string
}

interface ScriptTerminalModalProps {
  open: boolean
  onClose: () => void
  scriptPath: string
  scriptName: string
  params?: Record<string, string>
  title: string
  description: string
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
  const termRef = useRef<any>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitAddonRef = useRef<any>(null)
  const sessionIdRef = useRef<string>(Math.random().toString(36).substring(2, 8))

  const [isConnected, setIsConnected] = useState(false)
  const [isComplete, setIsComplete] = useState(false)
  const [exitCode, setExitCode] = useState<number | null>(null)
  const [currentInteraction, setCurrentInteraction] = useState<WebInteraction | null>(null)
  const [interactionInput, setInteractionInput] = useState("")
  const checkConnectionInterval = useRef<NodeJS.Timeout | null>(null)
  const isMobile = useIsMobile()

  const [isWaitingNextInteraction, setIsWaitingNextInteraction] = useState(false)
  const waitingTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  const [modalHeight, setModalHeight] = useState(80)
  const [isResizing, setIsResizing] = useState(false)
  const startYRef = useRef(0)
  const startHeightRef = useRef(80)

  const terminalContainerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) {
      if (checkConnectionInterval.current) {
        clearInterval(checkConnectionInterval.current)
      }
      if (waitingTimeoutRef.current) {
        clearTimeout(waitingTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      if (termRef.current) {
        termRef.current.dispose()
        termRef.current = null
      }
      sessionIdRef.current = Math.random().toString(36).substring(2, 8)
      setIsComplete(false)
      setExitCode(null)
      setInteractionInput("")
      setCurrentInteraction(null)
      setIsWaitingNextInteraction(false)
      setIsConnected(false)
    }
  }, [open])

  useEffect(() => {
    const container = terminalContainerRef.current

    console.log("[v0] Script modal useEffect triggered:", {
      open,
      hasContainer: !!container,
      hasExistingTerm: !!termRef.current,
      scriptPath,
      sessionId: sessionIdRef.current,
    })

    if (!open || !container || termRef.current) {
      console.log("[v0] Skipping terminal init")
      return
    }

    console.log("[v0] Starting terminal initialization...")

    const initializeTerminal = async () => {
      console.log("[v0] Loading xterm modules...")
      const [TerminalClass, FitAddonClass] = await Promise.all([
        import("xterm").then((mod) => mod.Terminal),
        import("xterm-addon-fit").then((mod) => mod.FitAddon),
        import("xterm/css/xterm.css"),
      ])

      console.log("[v0] Creating terminal instance...")
      const fontSize = window.innerWidth < 768 ? 12 : 16

      const term = new TerminalClass({
        rendererType: "dom",
        fontFamily: '"Courier", "Courier New", "Liberation Mono", "DejaVu Sans Mono", monospace',
        fontSize: fontSize,
        lineHeight: 1,
        cursorBlink: true,
        scrollback: 2000,
        disableStdin: false,
        customGlyphs: true,
        fontWeight: "500",
        fontWeightBold: "700",
        theme: {
          background: "#000000",
          foreground: "#ffffff",
          cursor: "#ffffff",
          cursorAccent: "#000000",
          black: "#2e3436",
          red: "#cc0000",
          green: "#4e9a06",
          yellow: "#c4a000",
          blue: "#3465a4",
          magenta: "#75507b",
          cyan: "#06989a",
          white: "#d3d7cf",
          brightBlack: "#555753",
          brightRed: "#ef2929",
          brightGreen: "#8ae234",
          brightYellow: "#fce94f",
          brightBlue: "#729fcf",
          brightMagenta: "#ad7fa8",
          brightCyan: "#34e2e2",
          brightWhite: "#eeeeec",
        },
      })

      const fitAddon = new FitAddonClass()
      term.loadAddon(fitAddon)
      console.log("[v0] Opening terminal in container...")
      term.open(container)

      termRef.current = term
      fitAddonRef.current = fitAddon

      setTimeout(() => {
        try {
          fitAddon.fit()
          console.log("[v0] Terminal fitted, cols:", term.cols, "rows:", term.rows)
        } catch (err) {
          console.log("[v0] Fit error:", err)
        }
      }, 50)

      const wsUrl = getScriptWebSocketUrl(sessionIdRef.current)
      console.log("[v0] Connecting to WebSocket:", wsUrl)
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log("[v0] WebSocket connected!")
        setIsConnected(true)

        const initMessage = {
          script_path: scriptPath,
          params: {
            EXECUTION_MODE: "web",
            ...params,
          },
        }

        console.log("[v0] Sending init message:", initMessage)
        ws.send(JSON.stringify(initMessage))

        setTimeout(() => {
          try {
            fitAddon.fit()
            const cols = term.cols
            const rows = term.rows
            console.log("[v0] Sending resize:", { cols, rows })
            ws.send(
              JSON.stringify({
                type: "resize",
                cols: cols,
                rows: rows,
              }),
            )
          } catch (err) {
            console.log("[v0] Resize error:", err)
          }
        }, 100)
      }

      ws.onmessage = (event) => {
        console.log("[v0] WebSocket message received:", event.data.substring(0, 100))
        try {
          const msg = JSON.parse(event.data)

          if (msg.type === "web_interaction" && msg.interaction) {
            console.log("[v0] Web interaction detected:", msg.interaction.type)
            setIsWaitingNextInteraction(false)
            if (waitingTimeoutRef.current) {
              clearTimeout(waitingTimeoutRef.current)
            }
            setCurrentInteraction({
              type: msg.interaction.type,
              id: msg.interaction.id,
              title: msg.interaction.title || "",
              message: msg.interaction.message || "",
              options: msg.interaction.options,
              default: msg.interaction.default,
            })
            return
          }

          if (msg.type === "error") {
            console.log("[v0] Error message:", msg.message)
            term.writeln(`\x1b[31m${msg.message}\x1b[0m`)
            return
          }
        } catch {
          // Not JSON, es output normal de terminal
        }

        term.write(event.data)

        setIsWaitingNextInteraction(false)
        if (waitingTimeoutRef.current) {
          clearTimeout(waitingTimeoutRef.current)
        }
      }

      ws.onerror = (error) => {
        console.log("[v0] WebSocket error:", error)
        setIsConnected(false)
        term.writeln("\x1b[31mWebSocket error occurred\x1b[0m")
      }

      ws.onclose = (event) => {
        console.log("[v0] WebSocket closed:", event.code, event.reason)
        setIsConnected(false)
        term.writeln("\x1b[33mConnection closed\x1b[0m")

        if (!isComplete) {
          setIsComplete(true)
          setExitCode(event.code === 1000 ? 0 : 1)
        }
      }

      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(data)
        }
      })

      checkConnectionInterval.current = setInterval(() => {
        if (ws) {
          setIsConnected(ws.readyState === WebSocket.OPEN)
        }
      }, 500)

      let resizeTimeout: NodeJS.Timeout | null = null

      const resizeObserver = new ResizeObserver(() => {
        if (resizeTimeout) clearTimeout(resizeTimeout)
        resizeTimeout = setTimeout(() => {
          if (fitAddon && term && ws?.readyState === WebSocket.OPEN) {
            try {
              fitAddon.fit()
              ws.send(
                JSON.stringify({
                  type: "resize",
                  cols: term.cols,
                  rows: term.rows,
                }),
              )
            } catch (err) {
              // Ignore
            }
          }
        }, 100)
      })

      resizeObserver.observe(container)
    }

    initializeTerminal()
  }, [open])

  const getScriptWebSocketUrl = (sid: string): string => {
    if (typeof window === "undefined") {
      return `ws://localhost:${API_PORT}/ws/script/${sid}`
    }

    const { hostname, protocol } = window.location
    const wsProtocol = protocol === "https:" ? "wss:" : "ws:"
    return `${wsProtocol}//${hostname}:${API_PORT}/ws/script/${sid}`
  }

  const handleInteractionResponse = (value: string) => {
    if (!wsRef.current || !currentInteraction) {
      return
    }

    if (value === "cancel" || value === "") {
      setCurrentInteraction(null)
      setInteractionInput("")
      handleCloseModal()
      return
    }

    const response = JSON.stringify({
      type: "interaction_response",
      id: currentInteraction.id,
      value: value,
    })

    if (wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(response)
    }

    setCurrentInteraction(null)
    setInteractionInput("")

    waitingTimeoutRef.current = setTimeout(() => {
      setIsWaitingNextInteraction(true)
    }, 300)
  }

  const handleCloseModal = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.close()
    }
    if (checkConnectionInterval.current) {
      clearInterval(checkConnectionInterval.current)
    }
    if (termRef.current) {
      termRef.current.dispose()
    }
    onClose()
  }

  const handleResizeStart = (e: React.MouseEvent | React.TouchEvent) => {
    setIsResizing(true)
    startYRef.current = "clientY" in e ? e.clientY : e.touches[0].clientY
    startHeightRef.current = modalHeight
    document.addEventListener("mousemove", handleResize as any)
    document.addEventListener("touchmove", handleResize as any)
    document.addEventListener("mouseup", handleResizeEnd)
    document.addEventListener("touchend", handleResizeEnd)
  }

  const handleResize = (e: MouseEvent | TouchEvent) => {
    if (!isResizing) return
    const currentY = e instanceof MouseEvent ? e.clientY : e.touches[0].clientY
    const deltaY = currentY - startYRef.current
    const newHeight = startHeightRef.current + (deltaY / window.innerHeight) * 100
    setModalHeight(Math.max(50, Math.min(95, newHeight)))
  }

  const handleResizeEnd = () => {
    setIsResizing(false)
    document.removeEventListener("mousemove", handleResize as any)
    document.removeEventListener("touchmove", handleResize as any)
    document.removeEventListener("mouseup", handleResizeEnd)
    document.removeEventListener("touchend", handleResizeEnd)
  }

  return (
    <>
      <Dialog open={open}>
        <DialogContent
          className="max-w-4xl p-0 flex flex-col"
          style={{ height: isMobile ? "80vh" : `${modalHeight}vh` }}
          onInteractOutside={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => e.preventDefault()}
        >
          <DialogTitle className="sr-only">{title}</DialogTitle>

          <div className="flex items-center gap-2 p-4 border-b">
            {isComplete &&
              (exitCode === 0 ? (
                <CheckCircle2 className="h-5 w-5 text-green-500" />
              ) : (
                <XCircle className="h-5 w-5 text-red-500" />
              ))}
            <div>
              <h2 className="text-lg font-semibold">{title}</h2>
              {description && <p className="text-sm text-muted-foreground">{description}</p>}
            </div>
          </div>

          <div className="overflow-hidden relative flex-1">
            <div ref={terminalContainerRef} className="w-full h-full" />

            {isWaitingNextInteraction && !currentInteraction && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/50 backdrop-blur-sm">
                <div className="flex flex-col items-center gap-3">
                  <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
                  <p className="text-sm text-muted-foreground">Processing...</p>
                </div>
              </div>
            )}
          </div>

          {!isMobile && (
            <div
              className={`h-2 cursor-ns-resize flex items-center justify-center transition-colors ${
                isResizing ? "bg-blue-500" : "bg-zinc-800 hover:bg-blue-500/50"
              }`}
              onMouseDown={handleResizeStart}
              onTouchStart={handleResizeStart}
            >
              <GripHorizontal className={`h-4 w-4 ${isResizing ? "text-white" : "text-zinc-500"}`} />
            </div>
          )}

          <div className="flex items-center justify-between p-4 border-t">
            <div className="flex items-center gap-3">
              <Activity className="h-5 w-5 text-blue-500" />
              <div
                className={`w-2 h-2 rounded-full ${isConnected ? "bg-green-500" : "bg-red-500"}`}
                title={isConnected ? "Connected" : "Disconnected"}
              ></div>
              <span className="text-xs text-muted-foreground">{isConnected ? "Online" : "Offline"}</span>
            </div>

            <Button
              onClick={handleCloseModal}
              variant="outline"
              className="bg-red-600 hover:bg-red-700 border-red-500 text-white"
            >
              Close
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {currentInteraction && (
        <Dialog open={true}>
          <DialogContent
            className="max-w-4xl max-h-[80vh] overflow-y-auto"
            onInteractOutside={(e) => e.preventDefault()}
            onEscapeKeyDown={(e) => e.preventDefault()}
            hideClose
          >
            <DialogTitle>{currentInteraction.title}</DialogTitle>
            <div className="space-y-4">
              <p className="whitespace-pre-wrap">{currentInteraction.message}</p>

              {currentInteraction.type === "yesno" && (
                <div className="flex gap-2">
                  <Button
                    onClick={() => handleInteractionResponse("yes")}
                    className="flex-1 bg-blue-600 hover:bg-blue-700 text-white"
                  >
                    Yes
                  </Button>
                  <Button
                    onClick={() => handleInteractionResponse("cancel")}
                    variant="outline"
                    className="flex-1 hover:bg-red-600 hover:text-white hover:border-red-600"
                  >
                    Cancel
                  </Button>
                </div>
              )}

              {currentInteraction.type === "menu" && currentInteraction.options && (
                <div className="space-y-2">
                  {currentInteraction.options.map((option) => (
                    <Button
                      key={option.value}
                      onClick={() => handleInteractionResponse(option.value)}
                      variant="outline"
                      className="w-full justify-start hover:bg-blue-600 hover:text-white"
                    >
                      {option.label}
                    </Button>
                  ))}
                  <Button
                    onClick={() => handleInteractionResponse("cancel")}
                    variant="outline"
                    className="w-full hover:bg-red-600 hover:text-white hover:border-red-600"
                  >
                    Cancel
                  </Button>
                </div>
              )}

              {(currentInteraction.type === "input" || currentInteraction.type === "inputbox") && (
                <div className="space-y-2">
                  <Label>Your input:</Label>
                  <Input
                    value={interactionInput}
                    onChange={(e) => setInteractionInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        handleInteractionResponse(interactionInput)
                      }
                    }}
                    placeholder={currentInteraction.default || ""}
                  />
                  <div className="flex gap-2">
                    <Button
                      onClick={() => handleInteractionResponse(interactionInput)}
                      className="flex-1 bg-blue-600 hover:bg-blue-700"
                    >
                      Submit
                    </Button>
                    <Button
                      onClick={() => handleInteractionResponse("cancel")}
                      variant="outline"
                      className="flex-1 hover:bg-red-600 hover:text-white hover:border-red-600"
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}

              {currentInteraction.type === "msgbox" && (
                <div className="flex gap-2">
                  <Button
                    onClick={() => handleInteractionResponse("ok")}
                    className="flex-1 bg-blue-600 hover:bg-blue-700"
                  >
                    OK
                  </Button>
                  <Button
                    onClick={() => handleInteractionResponse("cancel")}
                    variant="outline"
                    className="flex-1 hover:bg-red-600 hover:text-white hover:border-red-600"
                  >
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
