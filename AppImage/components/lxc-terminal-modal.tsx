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
  
  // Track host prompt to detect when user exits LXC
  const hostPromptRef = useRef<string>("")
  const insideLxcRef = useRef(false)
  const outputBufferRef = useRef<string>("")

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
      hostPromptRef.current = ""
      insideLxcRef.current = false
      outputBufferRef.current = ""
    }
  }, [isOpen])

  // Initialize terminal
  useEffect(() => {
    if (!isOpen) return

    // Small delay to ensure Dialog content is rendered
    const initTimeout = setTimeout(() => {
      if (!terminalContainerRef.current) return
      initTerminal()
    }, 100)

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

      // Connect WebSocket to host terminal
      const wsUrl = getWebSocketUrl()
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws
      
      // Reset state for new connection
      isInsideLxcRef.current = false
      outputBufferRef.current = ""

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
        
        // Auto-execute pct enter after connection is ready
        setTimeout(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(`pct enter ${vmid}\r`)
          }
        }, 300)
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
      
      ws.onmessage = (event) => {
        // Filter out pong responses
        if (event.data === '{"type": "pong"}' || event.data === '{"type":"pong"}') {
          return
        }
        
        const data = event.data
        
        // Buffer output until we're inside the LXC
        if (!insideLxcRef.current) {
          outputBufferRef.current += data
          
          // Capture host prompt (pattern like "root@hostname" or "[user@hostname")
          if (!hostPromptRef.current) {
            const hostMatch = outputBufferRef.current.match(/\[?(\w+@[\w-]+)/)
            if (hostMatch) {
              hostPromptRef.current = hostMatch[1]
            }
          }
          
          // Detect when we're inside the LXC
          // Look for a prompt that is different from the host prompt after pct enter
          if (hostPromptRef.current && outputBufferRef.current.includes(`pct enter ${vmid}`)) {
            const hostName = hostPromptRef.current.split('@')[1]
            // Look for a new prompt line that doesn't contain the host name
            const lines = outputBufferRef.current.split('\n')
            for (let i = lines.length - 1; i >= 0; i--) {
              const line = lines[i]
              // Check if this line has a prompt (@) but NOT the host name
              if (line.includes('@') && !line.includes(hostName) && (line.includes('#') || line.includes('$'))) {
                // Found LXC prompt - we're inside
                insideLxcRef.current = true
                // Only show from this prompt onwards
                term.write(line)
                break
              }
            }
          }
          return
        }
        
        // Already inside LXC - write directly
        // But check if user exited (host prompt appears again)
        if (hostPromptRef.current && data.includes(hostPromptRef.current)) {
          // User exited LXC, close modal after short delay
          term.write(data)
          setTimeout(() => {
            onClose()
          }, 500)
          return
        }
        
        term.write(data)
      }
    }

    return () => {
      clearTimeout(initTimeout)
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

  const sendEsc = useCallback(() => sendKey("\x1b"), [sendKey])
  const sendTab = useCallback(() => sendKey("\t"), [sendKey])
  const sendArrowUp = useCallback(() => sendKey("\x1b[A"), [sendKey])
  const sendArrowDown = useCallback(() => sendKey("\x1b[B"), [sendKey])
  const sendArrowLeft = useCallback(() => sendKey("\x1b[D"), [sendKey])
  const sendArrowRight = useCallback(() => sendKey("\x1b[C"), [sendKey])
  const sendEnter = useCallback(() => sendKey("\r"), [sendKey])
  const sendCtrlC = useCallback(() => sendKey("\x03"), [sendKey]) // Ctrl+C
  
  // Ctrl key state - user presses Ctrl button, then types a letter
  const [ctrlPressed, setCtrlPressed] = useState(false)
  
  const handleCtrlPress = useCallback(() => {
    setCtrlPressed(true)
    setTimeout(() => setCtrlPressed(false), 3000)
  }, [])
  
  // Handle keyboard input when Ctrl is pressed
  useEffect(() => {
    if (!ctrlPressed || !isOpen) return
    
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key.length === 1) {
        e.preventDefault()
        const code = e.key.toLowerCase().charCodeAt(0) - 96
        if (code >= 1 && code <= 26) {
          sendKey(String.fromCharCode(code))
        }
        setCtrlPressed(false)
      }
    }
    
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [ctrlPressed, isOpen, sendKey])

  const showMobileControls = isMobile || isTablet

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className="max-w-4xl w-[95vw] p-0 gap-0 bg-black border-border overflow-hidden flex flex-col"
        style={{ height: `${modalHeight}px` }}
        hideClose
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
          <DialogTitle className="text-sm font-medium text-white">
            Terminal: {vmName} (ID: {vmid})
          </DialogTitle>
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
          <div className="px-2 py-2 bg-zinc-900 border-t border-zinc-800">
            <div className="flex items-center justify-center gap-1.5">
              <Button
                variant="outline"
                size="sm"
                onClick={sendEsc}
                className="h-8 px-2 text-xs bg-zinc-800 border-zinc-700 text-zinc-300"
              >
                ESC
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendTab}
                className="h-8 px-2 text-xs bg-zinc-800 border-zinc-700 text-zinc-300"
              >
                TAB
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendArrowUp}
                className="h-8 w-8 p-0 bg-zinc-800 border-zinc-700"
              >
                <ArrowUp className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendArrowDown}
                className="h-8 w-8 p-0 bg-zinc-800 border-zinc-700"
              >
                <ArrowDown className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendArrowLeft}
                className="h-8 w-8 p-0 bg-zinc-800 border-zinc-700"
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendArrowRight}
                className="h-8 w-8 p-0 bg-zinc-800 border-zinc-700"
              >
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={sendEnter}
                className="h-8 px-2 text-xs bg-blue-600/20 border-blue-600/50 text-blue-400 hover:bg-blue-600/30"
              >
                <CornerDownLeft className="h-4 w-4 mr-1" />
                Enter
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleCtrlPress}
                className={`h-8 px-2 text-xs ${ctrlPressed 
                  ? "bg-yellow-600/30 border-yellow-600/50 text-yellow-400" 
                  : "bg-zinc-800 border-zinc-700 text-zinc-300"}`}
              >
                {ctrlPressed ? "Ctrl+?" : "Ctrl"}
              </Button>
            </div>
          </div>
        )}

        {/* Status bar at bottom */}
        <div className="flex items-center justify-between px-4 py-2 bg-zinc-900 border-t border-zinc-800">
          <div className="flex items-center gap-3">
            <Activity className="h-5 w-5 text-blue-500" />
            <div
              className={`w-2 h-2 rounded-full ${
                connectionStatus === "online"
                  ? "bg-green-500"
                  : connectionStatus === "connecting"
                    ? "bg-yellow-500 animate-pulse"
                    : "bg-red-500"
              }`}
            />
            <span className="text-xs text-zinc-400 capitalize">{connectionStatus}</span>
          </div>
          <Button
            onClick={onClose}
            variant="outline"
            className="bg-red-600/20 hover:bg-red-600/30 border-red-600/50 text-red-400"
          >
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
