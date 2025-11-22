"use client"

import type React from "react"
import { useEffect, useRef, useState } from "react"
import { API_PORT } from "@/lib/api-config"
import { Trash2, X, Send, ChevronUp, ChevronDown, ChevronLeft, ChevronRight, Activity } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

type TerminalPanelProps = {
  websocketUrl?: string
  onClose?: () => void
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

export const TerminalPanel: React.FC<TerminalPanelProps> = ({ websocketUrl, onClose }) => {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const termRef = useRef<any>(null)
  const fitAddonRef = useRef<any>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const touchStartRef = useRef<{ x: number; y: number; time: number } | null>(null)

  const [xtermLoaded, setXtermLoaded] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [mobileInput, setMobileInput] = useState("")
  const [lastKeyPressed, setLastKeyPressed] = useState<string | null>(null)
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    setIsMobile(window.innerWidth < 768)
    const handleResize = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener("resize", handleResize)
    return () => window.removeEventListener("resize", handleResize)
  }, [])

  useEffect(() => {
    if (typeof window === "undefined") return

    Promise.all([
      import("xterm").then((mod) => mod.Terminal),
      import("xterm-addon-fit").then((mod) => mod.FitAddon),
      import("xterm/css/xterm.css"),
    ])
      .then(([Terminal, FitAddon]) => {
        if (!containerRef.current) return

        console.log("[v0] TerminalPanel: Initializing terminal")

        const term = new Terminal({
          fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
          fontSize: isMobile ? 11 : 13,
          cursorBlink: true,
          scrollback: 2000,
          disableStdin: false,
          cols: 150,
          rows: 30,
          theme: {
            background: "#0d1117",
            foreground: "#e6edf3",
            cursor: "#58a6ff",
            cursorAccent: "#0d1117",
            black: "#484f58",
            red: "#f85149",
            green: "#3fb950",
            yellow: "#d29922",
            blue: "#58a6ff",
            magenta: "#bc8cff",
            cyan: "#39d353",
            white: "#b1bac4",
            brightBlack: "#6e7681",
            brightRed: "#ff7b72",
            brightGreen: "#56d364",
            brightYellow: "#e3b341",
            brightBlue: "#79c0ff",
            brightMagenta: "#d2a8ff",
            brightCyan: "#56d364",
            brightWhite: "#f0f6fc",
          },
        })

        const fitAddon = new FitAddon()
        term.loadAddon(fitAddon)

        term.open(containerRef.current)
        fitAddon.fit()

        termRef.current = term
        fitAddonRef.current = fitAddon
        setXtermLoaded(true)

        const wsUrl = websocketUrl || getWebSocketUrl()
        console.log("[v0] TerminalPanel: Connecting to WebSocket:", wsUrl)

        const ws = new WebSocket(wsUrl)
        wsRef.current = ws

        ws.onopen = () => {
          console.log("[v0] TerminalPanel: WebSocket connected")
          setIsConnected(true)
          term.writeln("\x1b[32mConnected to ProxMenux terminal.\x1b[0m")
        }

        ws.onmessage = (event) => {
          term.write(event.data)
        }

        ws.onerror = (error) => {
          console.error("[v0] TerminalPanel: WebSocket error:", error)
          setIsConnected(false)
          term.writeln("\r\n\x1b[31m[ERROR] WebSocket connection error\x1b[0m")
        }

        ws.onclose = () => {
          console.log("[v0] TerminalPanel: WebSocket closed")
          setIsConnected(false)
          term.writeln("\r\n\x1b[33m[INFO] Connection closed\x1b[0m")
        }

        term.onData((data) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(data)
          }
        })

        const handleResize = () => {
          try {
            fitAddon.fit()
          } catch {
            // Ignore resize errors
          }
        }
        window.addEventListener("resize", handleResize)

        return () => {
          console.log("[v0] TerminalPanel: Cleaning up")
          window.removeEventListener("resize", handleResize)
          ws.close()
          term.dispose()
        }
      })
      .catch((error) => {
        console.error("[v0] TerminalPanel: Failed to load xterm:", error)
      })
  }, [websocketUrl, isMobile])

  const sendSequence = (seq: string, keyName?: string) => {
    const term = termRef.current
    const ws = wsRef.current
    if (!term || !ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(seq)
    if (keyName) {
      setLastKeyPressed(keyName)
      setTimeout(() => setLastKeyPressed(null), 2000)
    }
  }

  const handleKeyButton = (key: string) => {
    switch (key) {
      case "UP":
        sendSequence("\x1b[A", "↑")
        break
      case "DOWN":
        sendSequence("\x1b[B", "↓")
        break
      case "RIGHT":
        sendSequence("\x1b[C", "→")
        break
      case "LEFT":
        sendSequence("\x1b[D", "←")
        break
      case "ESC":
        sendSequence("\x1b", "ESC")
        break
      case "TAB":
        sendSequence("\t", "TAB")
        break
      case "CTRL_C":
        sendSequence("\x03", "CTRL+C")
        break
      default:
        break
    }
  }

  const handleTouchStart = (e: React.TouchEvent<HTMLDivElement>) => {
    const touch = e.touches[0]
    touchStartRef.current = {
      x: touch.clientX,
      y: touch.clientY,
      time: Date.now(),
    }
  }

  const handleTouchEnd = (e: React.TouchEvent<HTMLDivElement>) => {
    const start = touchStartRef.current
    if (!start) return

    const touch = e.changedTouches[0]
    const dx = touch.clientX - start.x
    const dy = touch.clientY - start.y
    const dt = Date.now() - start.time

    const minDistance = 30
    const maxTime = 1000

    touchStartRef.current = null

    if (dt > maxTime) return

    if (Math.abs(dx) < minDistance && Math.abs(dy) < minDistance) {
      return
    }

    if (Math.abs(dx) > Math.abs(dy)) {
      if (dx > 0) {
        handleKeyButton("RIGHT")
      } else {
        handleKeyButton("LEFT")
      }
    } else {
      if (dy > 0) {
        handleKeyButton("DOWN")
      } else {
        handleKeyButton("UP")
      }
    }
  }

  const handleClear = () => {
    const term = termRef.current
    if (!term) return
    term.clear()
  }

  const handleClose = () => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.close()
    }
    if (onClose) {
      onClose()
    }
  }

  const handleMobileInputSend = () => {
    if (!mobileInput.trim()) return
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(mobileInput)
      setLastKeyPressed(mobileInput)
      setTimeout(() => setLastKeyPressed(null), 2000)
    }
    setMobileInput("")
  }

  return (
    <div className="flex flex-col h-[calc(100vh-16rem)] min-h-[500px] w-full">
      <div className="flex items-center justify-between gap-2 px-3 py-2 bg-zinc-900 border-b border-zinc-700 rounded-t-md">
        <div className="flex items-center gap-3">
          <Activity className="h-5 w-5 text-blue-500" />
          <span className="text-zinc-300 text-sm font-semibold">ProxMenux Terminal</span>
          <Badge
            variant="outline"
            className={`text-xs ${
              isConnected
                ? "border-green-500 text-green-500 bg-green-500/10"
                : "border-red-500 text-red-500 bg-red-500/10"
            }`}
          >
            <div className={`w-1.5 h-1.5 rounded-full mr-1.5 ${isConnected ? "bg-green-500" : "bg-red-500"}`}></div>
            {isConnected ? "Connected" : "Disconnected"}
          </Badge>
        </div>

        <div className="flex gap-2">
          <Button
            onClick={handleClear}
            variant="outline"
            size="sm"
            disabled={!isConnected}
            className="h-8 gap-2 bg-zinc-800 hover:bg-zinc-700 border-zinc-600 text-zinc-100 disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" />
            <span className="hidden sm:inline">Clear</span>
          </Button>
          <Button
            onClick={handleClose}
            variant="outline"
            size="sm"
            className="h-8 gap-2 bg-zinc-800 hover:bg-zinc-700 border-zinc-600 text-zinc-100"
          >
            <X className="h-4 w-4" />
            <span className="hidden sm:inline">Close</span>
          </Button>
        </div>
      </div>

      <div
        ref={containerRef}
        className="flex-1 bg-[#0d1117] overflow-auto min-h-0"
        onTouchStart={touchStartRef.current ? undefined : handleTouchStart}
        onTouchEnd={touchStartRef.current ? handleTouchEnd : undefined}
      >
        {!xtermLoaded && (
          <div className="flex items-center justify-center h-full text-zinc-400">Initializing terminal...</div>
        )}
      </div>

      {isMobile && (
        <div className="px-3 py-2 bg-zinc-900/50 border-t border-zinc-700">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-zinc-400">Mobile Input</span>
            {lastKeyPressed && (
              <span className="text-xs text-green-500 bg-green-500/10 px-2 py-0.5 rounded">Sent: {lastKeyPressed}</span>
            )}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={mobileInput}
              onChange={(e) => setMobileInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleMobileInputSend()}
              placeholder="Type command..."
              className="flex-1 px-3 py-2 text-sm border border-zinc-600 rounded-md bg-zinc-800 text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              disabled={!isConnected}
            />
            <Button
              onClick={handleMobileInputSend}
              variant="default"
              size="sm"
              disabled={!isConnected || !mobileInput.trim()}
              className="px-3 bg-blue-600 hover:bg-blue-700"
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2 justify-center items-center px-2 py-2 bg-zinc-900 text-sm rounded-b-md border-t border-zinc-700">
        <Button
          onClick={() => handleKeyButton("ESC")}
          variant="outline"
          size="sm"
          disabled={!isConnected}
          className="h-8 px-3 bg-zinc-800 hover:bg-zinc-700 border-zinc-600 text-zinc-100"
        >
          ESC
        </Button>
        <Button
          onClick={() => handleKeyButton("TAB")}
          variant="outline"
          size="sm"
          disabled={!isConnected}
          className="h-8 px-3 bg-zinc-800 hover:bg-zinc-700 border-zinc-600 text-zinc-100"
        >
          TAB
        </Button>
        <Button
          onClick={() => handleKeyButton("UP")}
          variant="outline"
          size="sm"
          disabled={!isConnected}
          className="h-8 px-2 bg-zinc-800 hover:bg-zinc-700 border-zinc-600 text-zinc-100"
        >
          <ChevronUp className="h-4 w-4" />
        </Button>
        <Button
          onClick={() => handleKeyButton("DOWN")}
          variant="outline"
          size="sm"
          disabled={!isConnected}
          className="h-8 px-2 bg-zinc-800 hover:bg-zinc-700 border-zinc-600 text-zinc-100"
        >
          <ChevronDown className="h-4 w-4" />
        </Button>
        <Button
          onClick={() => handleKeyButton("LEFT")}
          variant="outline"
          size="sm"
          disabled={!isConnected}
          className="h-8 px-2 bg-zinc-800 hover:bg-zinc-700 border-zinc-600 text-zinc-100"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Button
          onClick={() => handleKeyButton("RIGHT")}
          variant="outline"
          size="sm"
          disabled={!isConnected}
          className="h-8 px-2 bg-zinc-800 hover:bg-zinc-700 border-zinc-600 text-zinc-100"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button
          onClick={() => handleKeyButton("CTRL_C")}
          variant="outline"
          size="sm"
          disabled={!isConnected}
          className="h-8 px-3 bg-zinc-800 hover:bg-zinc-700 border-zinc-600 text-zinc-100"
        >
          CTRL+C
        </Button>
      </div>
    </div>
  )
}
