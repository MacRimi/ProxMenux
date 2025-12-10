"use client"

import type React from "react"
import { useState, useEffect, useRef, useCallback } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Loader2, Activity, GripHorizontal } from "lucide-react"
import { API_PORT } from "../lib/api-config"
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
  open: isOpen,
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

  const [modalHeight, setModalHeight] = useState(600)
  const [isResizing, setIsResizing] = useState(false)
  const resizeHandlersRef = useRef<{
    handleMove: ((e: MouseEvent | TouchEvent) => void) | null
    handleEnd: (() => void) | null
  }>({ handleMove: null, handleEnd: null })

  const terminalContainerRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node || !isOpen || termRef.current) {
        return
      }

      console.log("[v0] Terminal container mounted, initializing...")

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
        term.open(node)

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

        resizeObserver.observe(node)
      }

      initializeTerminal()
    },
    [isOpen, scriptPath, params],
  )

  useEffect(() => {
    const savedHeight = localStorage.getItem("scriptModalHeight")
    if (savedHeight) {
      setModalHeight(Number.parseInt(savedHeight, 10))
    }

    if (!isOpen) {
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
      if (resizeHandlersRef.current.handleMove) {
        document.removeEventListener("mousemove", resizeHandlersRef.current.handleMove as any)
        document.removeEventListener("touchmove", resizeHandlersRef.current.handleMove as any)
      }
      if (resizeHandlersRef.current.handleEnd) {
        document.removeEventListener("mouseup", resizeHandlersRef.current.handleEnd)
        document.removeEventListener("touchend", resizeHandlersRef.current.handleEnd)
      }
      resizeHandlersRef.current = { handleMove: null, handleEnd: null }

      sessionIdRef.current = Math.random().toString(36).substring(2, 8)
      setIsComplete(false)
      setExitCode(null)
      setInteractionInput("")
      setCurrentInteraction(null)
      setIsWaitingNextInteraction(false)
      setIsConnected(false)
    }
  }, [isOpen])

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
    }, 50)
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
    e.preventDefault()
    e.stopPropagation()

    setIsResizing(true)
    const startY = "clientY" in e ? e.clientY : e.touches[0].clientY
    const startHeight = modalHeight

    const handleMove = (moveEvent: MouseEvent | TouchEvent) => {
      const currentY = moveEvent instanceof MouseEvent ? moveEvent.clientY : moveEvent.touches[0].clientY
      const deltaY = currentY - startY
      const newHeight = Math.max(300, Math.min(2400, startHeight + deltaY))

      setModalHeight(newHeight)

      if (fitAddonRef.current && termRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
        try {
          setTimeout(() => {
            fitAddonRef.current.fit()
            wsRef.current?.send(
              JSON.stringify({
                type: "resize",
                cols: termRef.current.cols,
                rows: termRef.current.rows,
              }),
            )
          }, 10)
        } catch (err) {
          // Ignore
        }
      }
    }

    const handleEnd = () => {
      setIsResizing(false)

      localStorage.setItem("scriptModalHeight", modalHeight.toString())

      if (fitAddonRef.current && termRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
        try {
          setTimeout(() => {
            fitAddonRef.current.fit()
            wsRef.current?.send(
              JSON.stringify({
                type: "resize",
                cols: termRef.current.cols,
                rows: termRef.current.rows,
              }),
            )
          }, 50)
        } catch (err) {
          // Ignore
        }
      }

      document.removeEventListener("mousemove", handleMove as any)
      document.removeEventListener("touchmove", handleMove as any)
      document.removeEventListener("mouseup", handleEnd)
      document.removeEventListener("touchend", handleEnd)

      resizeHandlersRef.current = { handleMove: null, handleEnd: null }
    }

    resizeHandlersRef.current = { handleMove, handleEnd }

    document.addEventListener("mousemove", handleMove as any)
    document.addEventListener("touchmove", handleMove as any, { passive: false })
    document.addEventListener("mouseup", handleEnd)
    document.addEventListener("touchend", handleEnd)
  }

  return (
    <>
      <Dialog open={isOpen} onOpenChange={onClose}>
        <DialogContent
          className="max-w-7xl p-0 flex flex-col gap-0 overflow-hidden"
          style={{ height: isMobile ? "80vh" : `${modalHeight}px`, maxHeight: "none" }}
          onInteractOutside={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => e.preventDefault()}
        >
          <DialogTitle className="sr-only">{title}</DialogTitle>

          <div className="flex items-center gap-2 p-4 border-b">
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
              className={`h-2 cursor-ns-resize flex items-center justify-center transition-all duration-150 ${
                isResizing ? "bg-blue-500 h-3" : "bg-zinc-800 hover:bg-blue-500/50"
              }`}
              onMouseDown={handleResizeStart}
              onTouchStart={handleResizeStart}
            >
              <GripHorizontal
                className={`h-4 w-4 transition-all duration-150 ${isResizing ? "text-white scale-110" : "text-zinc-500"}`}
              />
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
            className="max-w-4xl max-h-[80vh] overflow-y-auto animate-in fade-in-0 zoom-in-95 duration-100"
            onInteractOutside={(e) => e.preventDefault()}
            onEscapeKeyDown={(e) => e.preventDefault()}
            hideClose
          >
            <DialogTitle>{currentInteraction.title}</DialogTitle>
            <div className="space-y-4">
              <p
                className="whitespace-pre-wrap"
                dangerouslySetInnerHTML={{
                  __html: currentInteraction.message.replace(/\\n/g, "<br/>").replace(/\n/g, "<br/>"),
                }}
              />

              {currentInteraction.type === "yesno" && (
                <div className="flex gap-2">
                  <Button
                    onClick={() => handleInteractionResponse("yes")}
                    className="flex-1 bg-blue-600 hover:bg-blue-700 text-white transition-all duration-150"
                  >
                    Yes
                  </Button>
                  <Button
                    onClick={() => handleInteractionResponse("cancel")}
                    variant="outline"
                    className="flex-1 hover:bg-red-600 hover:text-white hover:border-red-600 transition-all duration-150"
                  >
                    Cancel
                  </Button>
                </div>
              )}

              {currentInteraction.type === "menu" && currentInteraction.options && (
                <div className="space-y-2">
                  {currentInteraction.options.map((option, index) => (
                    <Button
                      key={option.value}
                      onClick={() => handleInteractionResponse(option.value)}
                      variant="outline"
                      className="w-full justify-start hover:bg-blue-600 hover:text-white transition-all duration-100 animate-in fade-in-0 slide-in-from-left-2"
                      style={{ animationDelay: `${index * 30}ms` }}
                    >
                      {option.label}
                    </Button>
                  ))}
                  <Button
                    onClick={() => handleInteractionResponse("cancel")}
                    variant="outline"
                    className="w-full hover:bg-red-600 hover:text-white hover:border-red-600 transition-all duration-150"
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
                    className="transition-all duration-150"
                  />
                  <div className="flex gap-2">
                    <Button
                      onClick={() => handleInteractionResponse(interactionInput)}
                      className="flex-1 bg-blue-600 hover:bg-blue-700 transition-all duration-150"
                    >
                      Submit
                    </Button>
                    <Button
                      onClick={() => handleInteractionResponse("cancel")}
                      variant="outline"
                      className="flex-1 hover:bg-red-600 hover:text-white hover:border-red-600 transition-all duration-150"
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
                    className="flex-1 bg-blue-600 hover:bg-blue-700 transition-all duration-150"
                  >
                    OK
                  </Button>
                  <Button
                    onClick={() => handleInteractionResponse("cancel")}
                    variant="outline"
                    className="flex-1 hover:bg-red-600 hover:text-white hover:border-red-600 transition-all duration-150"
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
