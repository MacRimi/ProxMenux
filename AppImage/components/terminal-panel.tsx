"use client"

import type React from "react"
import { useEffect, useRef, useState } from "react"
import { API_PORT } from "@/lib/api-config"

type TerminalPanelProps = {
  websocketUrl?: string
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

export const TerminalPanel: React.FC<TerminalPanelProps> = ({ websocketUrl }) => {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const termRef = useRef<any>(null)
  const fitAddonRef = useRef<any>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const touchStartRef = useRef<{ x: number; y: number; time: number } | null>(null)

  const [xtermLoaded, setXtermLoaded] = useState(false)

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
          fontFamily: "monospace",
          fontSize: 13,
          cursorBlink: true,
          scrollback: 2000,
          disableStdin: false,
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
          term.writeln("\x1b[32mConnected to ProxMenux terminal.\x1b[0m")
        }

        ws.onmessage = (event) => {
          term.write(event.data)
        }

        ws.onerror = (error) => {
          console.error("[v0] TerminalPanel: WebSocket error:", error)
          term.writeln("\r\n\x1b[31m[ERROR] WebSocket connection error\x1b[0m")
        }

        ws.onclose = () => {
          console.log("[v0] TerminalPanel: WebSocket closed")
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
  }, [websocketUrl])

  const sendSequence = (seq: string) => {
    const term = termRef.current
    const ws = wsRef.current
    if (!term || !ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(seq)
  }

  const handleKeyButton = (key: string) => {
    switch (key) {
      case "UP":
        sendSequence("\x1b[A")
        break
      case "DOWN":
        sendSequence("\x1b[B")
        break
      case "RIGHT":
        sendSequence("\x1b[C")
        break
      case "LEFT":
        sendSequence("\x1b[D")
        break
      case "ESC":
        sendSequence("\x1b")
        break
      case "TAB":
        sendSequence("\t")
        break
      case "ENTER":
        sendSequence("\r")
        break
      case "CTRL_C":
        sendSequence("\x03")
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

  return (
    <div className="flex flex-col h-full w-full">
      <div
        ref={containerRef}
        className="flex-1 bg-black rounded-t-md overflow-hidden"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        {!xtermLoaded && (
          <div className="flex items-center justify-center h-full text-zinc-400">Initializing terminal...</div>
        )}
      </div>

      <div className="flex flex-wrap gap-2 justify-center items-center px-2 py-2 bg-zinc-900 text-sm rounded-b-md">
        <TouchKey label="ESC" onClick={() => handleKeyButton("ESC")} />
        <TouchKey label="TAB" onClick={() => handleKeyButton("TAB")} />
        <TouchKey label="↑" onClick={() => handleKeyButton("UP")} />
        <TouchKey label="↓" onClick={() => handleKeyButton("DOWN")} />
        <TouchKey label="←" onClick={() => handleKeyButton("LEFT")} />
        <TouchKey label="→" onClick={() => handleKeyButton("RIGHT")} />
        <TouchKey label="ENTER" onClick={() => handleKeyButton("ENTER")} />
        <TouchKey label="CTRL+C" onClick={() => handleKeyButton("CTRL_C")} />
      </div>
    </div>
  )
}

type TouchKeyProps = {
  label: string
  onClick: () => void
}

const TouchKey: React.FC<TouchKeyProps> = ({ label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className="px-3 py-1 rounded bg-zinc-800 hover:bg-zinc-700 active:bg-zinc-600 text-zinc-100 text-xs md:text-sm border border-zinc-700"
  >
    {label}
  </button>
)
