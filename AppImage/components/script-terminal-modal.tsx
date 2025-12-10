"use client"

import type React from "react"
import { useState, useEffect, useRef, useCallback } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Loader2, Activity, GripHorizontal } from "lucide-react"
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
  const resizeHandlersRef = useRef<{
    handleMouseMove: ((e: MouseEvent) => void) | null
    handleMouseUp: (() => void) | null
    handleTouchMove: ((e: TouchEvent) => void) | null
    handleTouchEnd: (() => void) | null
  }>({
    handleMouseMove: null,
    handleMouseUp: null,
    handleTouchMove: null,
    handleTouchEnd: null,
  })

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
      if (resizeHandlersRef.current.handleMouseMove) {
        document.removeEventListener("mousemove", resizeHandlersRef.current.handleMouseMove)
      }
      if (resizeHandlersRef.current.handleMouseUp) {
        document.removeEventListener("mouseup", resizeHandlersRef.current.handleMouseUp)
      }
      if (resizeHandlersRef.current.handleTouchMove) {
        document.removeEventListener("touchmove", resizeHandlersRef.current.handleTouchMove)
      }
      if (resizeHandlersRef.current.handleTouchEnd) {
        document.removeEventListener("touchend", resizeHandlersRef.current.handleTouchEnd)
      }
      resizeHandlersRef.current = {
        handleMouseMove: null,
        handleMouseUp: null,
        handleTouchMove: null,
        handleTouchEnd: null,
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

  const handleResizeStart = (e: React.MouseEvent | React.TouchEvent) => {
    e.preventDefault()
    e.stopPropagation()

    setIsResizing(true)
    const startY = "clientY" in e ? e.clientY : e.touches[0].clientY
    const startHeight = modalHeight

    const handleMove = (moveEvent: MouseEvent | TouchEvent) => {
      moveEvent.preventDefault()
      const currentY = moveEvent instanceof MouseEvent ? moveEvent.clientY : moveEvent.touches[0].clientY
      const deltaY = currentY - startY
      const newHeight = Math.max(300, Math.min(2400, startHeight + deltaY))

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

      localStorage.setItem("scriptModalHeight", modalHeight.toString())

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
        }, 50)
      }

      document.removeEventListener("mousemove", handleMove)
      document.removeEventListener("touchmove", handleMove)
      document.removeEventListener("mouseup", handleEnd)
      document.removeEventListener("touchend", handleEnd)

      resizeHandlersRef.current = {
        handleMouseMove: null,
        handleMouseUp: null,
        handleTouchMove: null,
        handleTouchEnd: null,
      }
    }

    resizeHandlersRef.current = {
      handleMouseMove: handleMove as any,
      handleMouseUp: handleEnd,
      handleTouchMove: handleMove as any,
      handleTouchEnd: handleEnd,
    }

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
          style={{ height: isMobile || isTablet ? "80vh" : `${modalHeight}px`, maxHeight: "none" }}
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

          {(isMobile || isTablet) && (
            <div className="flex flex-wrap gap-1.5 justify-center items-center px-1 bg-zinc-900 text-sm rounded-b-md border-t border-zinc-700 py-1.5">
              <Button
                onClick={() => sendKey("escape")}
                variant="outline"
                size="sm"
                className="px-2.5 py-2 text-xs h-9 bg-zinc-800 hover:bg-zinc-700 border-zinc-700"
              >
                ESC
              </Button>
              <Button
                onClick={() => sendKey("tab")}
                variant="outline"
                size="sm"
                className="px-2.5 py-2 text-xs h-9 bg-zinc-800 hover:bg-zinc-700 border-zinc-700"
              >
                TAB
              </Button>
              <Button
                onClick={() => sendKey("up")}
                variant="outline"
                size="sm"
                className="px-3 py-2 text-base h-9 bg-zinc-800 hover:bg-zinc-700 border-zinc-700"
              >
                ↑
              </Button>
              <Button
                onClick={() => sendKey("down")}
                variant="outline"
                size="sm"
                className="px-3 py-2 text-base h-9 bg-zinc-800 hover:bg-zinc-700 border-zinc-700"
              >
                ↓
              </Button>
              <Button
                onClick={() => sendKey("left")}
                variant="outline"
                size="sm"
                className="px-3 py-2 text-base h-9 bg-zinc-800 hover:bg-zinc-700 border-zinc-700"
              >
                ←
              </Button>
              <Button
                onClick={() => sendKey("right")}
                variant="outline"
                size="sm"
                className="px-3 py-2 text-base h-9 bg-zinc-800 hover:bg-zinc-700 border-zinc-700"
              >
                →
              </Button>
              <Button
                onClick={() => sendKey("enter")}
                variant="outline"
                size="sm"
                className="px-3 py-2 text-base h-9 bg-zinc-800 hover:bg-zinc-700 border-zinc-700"
              >
                ↵
              </Button>
              <Button
                onClick={() => sendKey("ctrlc")}
                variant="outline"
                size="sm"
                className="px-2 py-2 text-xs h-9 bg-zinc-800 hover:bg-zinc-700 border-zinc-700"
              >
                CTRL+C
              </Button>
            </div>
          )}

          {(isTablet || (!isMobile && !isTablet)) && (
            <div
              className={`h-2 cursor-ns-resize flex items-center justify-center transition-all duration-150 ${
                isResizing ? "bg-blue-500 h-3" : "bg-zinc-800 hover:bg-blue-500/50"
              }`}
              onMouseDown={handleResizeStart}
              onTouchStart={handleResizeStart}
              style={{ touchAction: "none" }}
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
