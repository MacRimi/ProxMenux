"use client"

import type React from "react"
import { useState, useEffect, useRef, useCallback } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Loader2,
  Activity,
  ArrowUp,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  CornerDownLeft,
  GripHorizontal,
} from "lucide-react"
import "xterm/css/xterm.css"
import { API_PORT } from "@/lib/api-config"

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
  scriptDescription?: string
  title: string
  description: string
}

export function ScriptTerminalModal({
  open: isOpen,
  onClose,
  scriptPath,
  scriptName,
  scriptDescription,
  title,
  description,
}: ScriptTerminalModalProps) {
  const termRef = useRef<any>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitAddonRef = useRef<any>(null)
  const sessionIdRef = useRef<string>(Math.random().toString(36).substring(2, 8))

  const [connectionStatus, setConnectionStatus] = useState<"connecting" | "online" | "offline">("connecting")
  const [isComplete, setIsComplete] = useState(false)
  const [exitCode, setExitCode] = useState<number | null>(null)
  const [currentInteraction, setCurrentInteraction] = useState<WebInteraction | null>(null)
  const [interactionInput, setInteractionInput] = useState("")
  const checkConnectionInterval = useRef<NodeJS.Timeout | null>(null)
  const [isMobile, setIsMobile] = useState(false)
  const [isTablet, setIsTablet] = useState(false)

  const [isWaitingNextInteraction, setIsWaitingNextInteraction] = useState(false)
  const waitingTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  const [modalHeight, setModalHeight] = useState(600)
  const [isResizing, setIsResizing] = useState(false)
  const resizeBarRef = useRef<HTMLDivElement>(null)

  const terminalContainerRef = useRef<HTMLDivElement>(null)

  const sendKey = useCallback((key: string) => {
    if (!termRef.current) return

    const keyMap: Record<string, string> = {
      escape: "\x1b",
      tab: "\t",
      up: "\x1b[A",
      down: "\x1b[B",
      left: "\x1b[D",
      right: "\x1b[C",
      enter: "\r",
      ctrlc: "\x03",
    }

    const sequence = keyMap[key]
    if (sequence && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "input", data: sequence }))
    }
  }, [])

  const initializeTerminal = async () => {
    const [TerminalClass, FitAddonClass] = await Promise.all([
      import("xterm").then((mod) => mod.Terminal),
      import("xterm-addon-fit").then((mod) => mod.FitAddon),
      import("xterm/css/xterm.css"),
    ])

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
    if (terminalContainerRef.current) {
      term.open(terminalContainerRef.current)
    }

    termRef.current = term
    fitAddonRef.current = fitAddon

    setTimeout(() => {
      if (fitAddonRef.current && termRef.current) {
        fitAddonRef.current.fit()
      }
    }, 100)

    const wsUrl = getScriptWebSocketUrl(sessionIdRef.current)
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      setConnectionStatus("online")

      const initMessage = {
        script_path: scriptPath,
        params: {
          EXECUTION_MODE: "web",
        },
      }

      ws.send(JSON.stringify(initMessage))

      setTimeout(() => {
        if (fitAddonRef.current && termRef.current && ws.readyState === WebSocket.OPEN) {
          const cols = termRef.current.cols
          const rows = termRef.current.rows
          ws.send(
            JSON.stringify({
              type: "resize",
              cols: cols,
              rows: rows,
            }),
          )
        }
      }, 100)
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)

        if (msg.type === "web_interaction" && msg.interaction) {
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
      setConnectionStatus("offline")
      term.writeln("\x1b[31mWebSocket error occurred\x1b[0m")
    }

    ws.onclose = (event) => {
      setConnectionStatus("offline")
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
      if (wsRef.current) {
        setConnectionStatus(
          wsRef.current.readyState === WebSocket.OPEN
            ? "online"
            : wsRef.current.readyState === WebSocket.CONNECTING
              ? "connecting"
              : "offline",
        )
      }
    }, 500)

    let resizeTimeout: NodeJS.Timeout | null = null

    const resizeObserver = new ResizeObserver(() => {
      if (resizeTimeout) clearTimeout(resizeTimeout)
      resizeTimeout = setTimeout(() => {
        if (fitAddonRef.current && termRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
          fitAddonRef.current.fit()
          wsRef.current.send(
            JSON.stringify({
              type: "resize",
              cols: termRef.current.cols,
              rows: termRef.current.rows,
            }),
          )
        }
      }, 100)
    })

    if (terminalContainerRef.current) {
      resizeObserver.observe(terminalContainerRef.current)
    }
  }

  useEffect(() => {
    const savedHeight = localStorage.getItem("scriptModalHeight")
    if (savedHeight) {
      setModalHeight(Number.parseInt(savedHeight, 10))
    }

    if (isOpen) {
      initializeTerminal()
    } else {
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
      setConnectionStatus("connecting")
    }
  }, [isOpen])

  useEffect(() => {
    const updateDeviceType = () => {
      const width = window.innerWidth
      const isTouchDevice = "ontouchstart" in window || navigator.maxTouchPoints > 0
      const isTabletSize = width >= 768 && width <= 1366

      setIsMobile(width < 768)
      setIsTablet(isTouchDevice && isTabletSize)
    }

    updateDeviceType()
    const handleResize = () => updateDeviceType()
    window.addEventListener("resize", handleResize)

    return () => {
      window.removeEventListener("resize", handleResize)
    }
  }, [])

  const getScriptWebSocketUrl = (sid: string): string => {
    if (typeof window === "undefined") {
      return `ws://localhost:${API_PORT}/ws/script/${sid}`
    }

    const { protocol, hostname, port } = window.location
    const isStandardPort = port === "" || port === "80" || port === "443"
    const wsProtocol = protocol === "https:" ? "wss:" : "ws:"

    if (isStandardPort) {
      return `${wsProtocol}//${hostname}/ws/script/${sid}`
    } else {
      return `${wsProtocol}//${hostname}:${API_PORT}/ws/script/${sid}`
    }
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

  const handleResizeStart = (e: React.PointerEvent) => {
    e.preventDefault()
    e.stopPropagation()

    setIsResizing(true)
    const startY = e.clientY
    const startHeight = modalHeight

    const handleMove = (moveEvent: PointerEvent) => {
      moveEvent.preventDefault()
      const currentY = moveEvent.clientY
      const deltaY = currentY - startY

      const newHeight = Math.max(300, Math.min(window.innerHeight - 100, startHeight + deltaY))

      setModalHeight(newHeight)

      if (fitAddonRef.current && termRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
        setTimeout(() => {
          if (fitAddonRef.current && termRef.current) {
            fitAddonRef.current.fit()
            wsRef.current?.send(
              JSON.stringify({
                type: "resize",
                cols: termRef.current.cols,
                rows: termRef.current.rows,
              }),
            )
          }
        }, 10)
      }
    }

    const handleEnd = () => {
      setIsResizing(false)
      document.removeEventListener("pointermove", handleMove)
      document.removeEventListener("pointerup", handleEnd)
      document.removeEventListener("pointercancel", handleEnd)

      localStorage.setItem("scriptModalHeight", modalHeight.toString())
      
      // Release pointer capture
      if (resizeBarRef.current) {
        try {
          resizeBarRef.current.releasePointerCapture(e.pointerId)
        } catch (err) {
          // Ignore if already released
        }
      }
    }

    document.addEventListener("pointermove", handleMove)
    document.addEventListener("pointerup", handleEnd)
    document.addEventListener("pointercancel", handleEnd)

    // Capturar el pointer para asegurar que recibimos todos los eventos
    if (resizeBarRef.current) {
      try {
        resizeBarRef.current.setPointerCapture(e.pointerId)
      } catch (err) {
        // Ignore if capture fails
      }
    }
  }

  const sendCommand = (command: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "input", data: command }))
    }
  }

  return (
    <>
      <Dialog open={isOpen} onOpenChange={onClose}>
        <DialogContent
          className="max-w-7xl p-0 flex flex-col gap-0 overflow-hidden"
          style={{
            height: isMobile || isTablet ? "80vh" : `${modalHeight}px`,
            maxHeight: "none",
          }}
          onInteractOutside={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => e.preventDefault()}
          hideClose
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

          {/* Resize bar - visible en tablet y escritorio */}
          {!isMobile && (
            <div
              ref={resizeBarRef}
              onPointerDown={handleResizeStart}
              className={`h-2 cursor-ns-resize flex items-center justify-center transition-colors z-50 select-none ${
                isResizing ? "bg-blue-500" : "hover:bg-accent"
              }`}
              style={{ 
                touchAction: "none",
                WebkitUserSelect: "none",
                userSelect: "none"
              }}
            >
              <GripHorizontal className={`h-3 w-8 transition-colors ${
                isResizing ? "text-white" : "text-muted-foreground/50"
              } pointer-events-none`} />
            </div>
          )}

          {/* Mobile/Tablet button toolbar */}
          {(isMobile || isTablet) && (
            <div className="flex items-center justify-center gap-1.5 px-1 py-2 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
              <Button
                onPointerDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  sendCommand("\x1b")
                }}
                variant="outline"
                size="sm"
                className="h-8 px-2 text-xs bg-zinc-800 hover:bg-zinc-700 border-zinc-700 text-white min-w-[60px]"
              >
                ESC
              </Button>
              <Button
                onPointerDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  sendCommand("\t")
                }}
                variant="outline"
                size="sm"
                className="h-8 px-2 text-xs bg-zinc-800 hover:bg-zinc-700 border-zinc-700 text-white min-w-[60px]"
              >
                TAB
              </Button>
              <Button
                onPointerDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  sendCommand("\x1b[A")
                }}
                variant="outline"
                size="sm"
                className="h-8 px-2.5 text-xs bg-zinc-800 hover:bg-zinc-700 border-zinc-700 text-white"
              >
                <ArrowUp className="h-4 w-4" />
              </Button>
              <Button
                onPointerDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  sendCommand("\x1b[B")
                }}
                variant="outline"
                size="sm"
                className="h-8 px-2.5 text-xs bg-zinc-800 hover:bg-zinc-700 border-zinc-700 text-white"
              >
                <ArrowDown className="h-4 w-4" />
              </Button>
              <Button
                onPointerDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  sendCommand("\x1b[D")
                }}
                variant="outline"
                size="sm"
                className="h-8 px-2.5 text-xs bg-zinc-800 hover:bg-zinc-700 border-zinc-700 text-white"
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <Button
                onPointerDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  sendCommand("\x1b[C")
                }}
                variant="outline"
                size="sm"
                className="h-8 px-2.5 text-xs bg-zinc-800 hover:bg-zinc-700 border-zinc-700 text-white"
              >
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Button
                onPointerDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  sendCommand("\r")
                }}
                variant="outline"
                size="sm"
                className="h-8 px-2.5 text-xs bg-zinc-800 hover:bg-zinc-700 border-zinc-700 text-white"
              >
                <CornerDownLeft className="h-4 w-4" />
              </Button>
              <Button
                onPointerDown={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  sendCommand("\x03")
                }}
                variant="outline"
                size="sm"
                className="h-8 px-2 text-xs bg-zinc-800 hover:bg-zinc-700 border-zinc-700 text-white min-w-[75px]"
              >
                CTRL+C
              </Button>
            </div>
          )}

          {/* Footer with connection status and close button */}
          <div className="flex items-center justify-between px-4 py-3 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
            <div className="flex items-center gap-3">
              <Activity className="h-5 w-5 text-blue-500" />
              <div
                className={`w-2 h-2 rounded-full ${
                  connectionStatus === "online"
                    ? "bg-green-500"
                    : connectionStatus === "connecting"
                      ? "bg-blue-500"
                      : "bg-red-500"
                }`}
                title={
                  connectionStatus === "online"
                    ? "Connected"
                    : connectionStatus === "connecting"
                      ? "Connecting"
                      : "Disconnected"
                }
              ></div>
              <span className="text-xs text-muted-foreground">
                {connectionStatus === "online"
                  ? "Online"
                  : connectionStatus === "connecting"
                    ? "Connecting..."
                    : "Offline"}
              </span>
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