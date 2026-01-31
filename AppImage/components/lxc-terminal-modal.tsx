"use client"

import type React from "react"
import { useState, useEffect, useRef, useCallback } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import {
  Activity,
  ArrowUp,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  CornerDownLeft,
  GripHorizontal,
  X,
} from "lucide-react"
import "xterm/css/xterm.css"
import { API_PORT } from "@/lib/api-config"

interface LxcTerminalModalProps {
  open: boolean
  onClose: () => void
  vmid: number
  vmName: string
}

function getWebSocketUrl(): string {
  if (typeof window === "undefined") {
    return "ws://localhost:8008/ws/terminal"
  }

  const { protocol, hostname, port } = window.location
  const isStandardPort = port === "" || port === "80" || port === "443"
  const wsProtocol = protocol === "https:" ? "wss:" : "ws:"

  if (isStandardPort) {
    return `${wsProtocol}//${hostname}/ws/terminal`
  } else {
    return `${wsProtocol}//${hostname}:${API_PORT}/ws/terminal`
  }
}

export function LxcTerminalModal({
  open: isOpen,
  onClose,
  vmid,
  vmName,
}: LxcTerminalModalProps) {
  const termRef = useRef<any>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitAddonRef = useRef<any>(null)
  const terminalContainerRef = useRef<HTMLDivElement>(null)
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [connectionStatus, setConnectionStatus] = useState<"connecting" | "online" | "offline">("connecting")
  const [isMobile, setIsMobile] = useState(false)
  const [isTablet, setIsTablet] = useState(false)

  const [modalHeight, setModalHeight] = useState(500)
  const [isResizing, setIsResizing] = useState(false)
  const resizeBarRef = useRef<HTMLDivElement>(null)
  const modalHeightRef = useRef(500)

  // Detect mobile/tablet
  useEffect(() => {
    const checkDevice = () => {
      const width = window.innerWidth
      setIsMobile(width < 640)
      setIsTablet(width >= 640 && width < 1024)
    }
    checkDevice()
    window.addEventListener("resize", checkDevice)
    return () => window.removeEventListener("resize", checkDevice)
  }, [])

  // Cleanup on close
  useEffect(() => {
    if (!isOpen) {
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
        pingIntervalRef.current = null
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      if (termRef.current) {
        termRef.current.dispose()
        termRef.current = null
      }
      setConnectionStatus("connecting")
    }
  }, [isOpen])

  // Initialize terminal
  useEffect(() => {
    if (!isOpen || !terminalContainerRef.current) return

    const initTerminal = async () => {
      const [TerminalClass, FitAddonClass] = await Promise.all([
        import("xterm").then((mod) => mod.Terminal),
        import("xterm-addon-fit").then((mod) => mod.FitAddon),
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
        fitAddon.fit()
      }

      termRef.current = term
      fitAddonRef.current = fitAddon

      // Connect WebSocket
      const wsUrl = getWebSocketUrl()
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setConnectionStatus("online")

        // Start heartbeat ping
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
          } else {
            if (pingIntervalRef.current) {
              clearInterval(pingIntervalRef.current)
            }
          }
        }, 25000)

        // Sync terminal size
        fitAddon.fit()
        ws.send(JSON.stringify({
          type: "resize",
          cols: term.cols,
          rows: term.rows,
        }))

        // Auto-execute pct enter command after a brief delay
        setTimeout(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(`pct enter ${vmid}\n`)
          }
        }, 500)
      }

      ws.onmessage = (event) => {
        // Filter out pong responses
        if (event.data === '{"type": "pong"}' || event.data === '{"type":"pong"}') {
          return
        }
        term.write(event.data)
      }

      ws.onerror = () => {
        setConnectionStatus("offline")
        term.writeln("\r\n\x1b[31m[ERROR] WebSocket connection error\x1b[0m")
      }

      ws.onclose = () => {
        setConnectionStatus("offline")
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current)
        }
        term.writeln("\r\n\x1b[33m[INFO] Connection closed\x1b[0m")
      }

      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(data)
        }
      })
    }

    initTerminal()

    return () => {
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
      }
      if (termRef.current) {
        termRef.current.dispose()
      }
    }
  }, [isOpen, vmid])

  // Resize handling
  useEffect(() => {
    if (termRef.current && fitAddonRef.current && isOpen) {
      setTimeout(() => {
        fitAddonRef.current?.fit()
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({
            type: "resize",
            cols: termRef.current.cols,
            rows: termRef.current.rows,
          }))
        }
      }, 100)
    }
  }, [modalHeight, isOpen])

  // Resize bar handlers
  const handleResizeStart = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    e.preventDefault()
    setIsResizing(true)
    modalHeightRef.current = modalHeight
  }, [modalHeight])

  useEffect(() => {
    if (!isResizing) return

    const handleMove = (e: MouseEvent | TouchEvent) => {
      const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY
      const windowHeight = window.innerHeight
      const newHeight = windowHeight - clientY - 20
      const clampedHeight = Math.max(300, Math.min(windowHeight - 100, newHeight))
      modalHeightRef.current = clampedHeight
      setModalHeight(clampedHeight)
    }

    const handleEnd = () => {
      setIsResizing(false)
    }

    document.addEventListener("mousemove", handleMove)
    document.addEventListener("mouseup", handleEnd)
    document.addEventListener("touchmove", handleMove)
    document.addEventListener("touchend", handleEnd)

    return () => {
      document.removeEventListener("mousemove", handleMove)
      document.removeEventListener("mouseup", handleEnd)
      document.removeEventListener("touchmove", handleMove)
      document.removeEventListener("touchend", handleEnd)
    }
  }, [isResizing])

  // Send key helpers for mobile/tablet
  const sendKey = useCallback((key: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(key)
    }
  }, [])

  const sendCtrlC = useCallback(() => sendKey("\x03"), [sendKey])
  const sendArrowUp = useCallback(() => sendKey("\x1b[A"), [sendKey])
  const sendArrowDown = useCallback(() => sendKey("\x1b[B"), [sendKey])
  const sendArrowLeft = useCallback(() => sendKey("\x1b[D"), [sendKey])
  const sendArrowRight = useCallback(() => sendKey("\x1b[C"), [sendKey])
  const sendEnter = useCallback(() => sendKey("\r"), [sendKey])
  const sendTab = useCallback(() => sendKey("\t"), [sendKey])

  const showMobileControls = isMobile || isTablet

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className="max-w-4xl w-[95vw] p-0 gap-0 bg-black border-border overflow-hidden flex flex-col"
        style={{ height: `${modalHeight}px` }}
      >
        {/* Resize bar */}
        <div
          ref={resizeBarRef}
          className="h-3 w-full cursor-ns-resize flex items-center justify-center bg-zinc-900 hover:bg-zinc-800 transition-colors touch-none"
          onMouseDown={handleResizeStart}
          onTouchStart={handleResizeStart}
        >
          <GripHorizontal className="h-4 w-4 text-zinc-500" />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2 bg-zinc-900 border-b border-zinc-800">
          <div className="flex items-center gap-3">
            <DialogTitle className="text-sm font-medium text-white">
              Terminal: {vmName} (ID: {vmid})
            </DialogTitle>
            <div className="flex items-center gap-1.5">
              <Activity
                className={`h-3.5 w-3.5 ${
                  connectionStatus === "online"
                    ? "text-green-500"
                    : connectionStatus === "connecting"
                      ? "text-yellow-500 animate-pulse"
                      : "text-red-500"
                }`}
              />
              <span className="text-xs text-zinc-400 capitalize">{connectionStatus}</span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="h-7 w-7 p-0 text-zinc-400 hover:text-white hover:bg-zinc-800"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Terminal container */}
        <div className="flex-1 overflow-hidden bg-black p-1">
          <div
            ref={terminalContainerRef}
            className="w-full h-full"
            style={{ minHeight: "200px" }}
          />
        </div>

        {/* Mobile/Tablet control buttons */}
        {showMobileControls && (
          <div className="px-3 py-2 bg-zinc-900 border-t border-zinc-800">
            <div className="flex items-center justify-center gap-2 flex-wrap">
              <Button
                variant="outline"
                size="sm"
                onClick={sendCtrlC}
                className="h-9 px-3 bg-red-600/20 border-red-600/50 text-red-400 hover:bg-red-600/30"
              >
                Ctrl+C
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendArrowUp}
                className="h-9 w-9 p-0 bg-zinc-800 border-zinc-700"
              >
                <ArrowUp className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendArrowDown}
                className="h-9 w-9 p-0 bg-zinc-800 border-zinc-700"
              >
                <ArrowDown className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendArrowLeft}
                className="h-9 w-9 p-0 bg-zinc-800 border-zinc-700"
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendArrowRight}
                className="h-9 w-9 p-0 bg-zinc-800 border-zinc-700"
              >
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendTab}
                className="h-9 px-3 bg-zinc-800 border-zinc-700"
              >
                Tab
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendEnter}
                className="h-9 px-3 bg-blue-600/20 border-blue-600/50 text-blue-400 hover:bg-blue-600/30"
              >
                <CornerDownLeft className="h-4 w-4 mr-1" />
                Enter
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
