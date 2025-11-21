"use client"

import type React from "react"
import { useEffect, useRef } from "react"
import { Terminal } from "xterm"
import { FitAddon } from "xterm-addon-fit"
import "xterm/css/xterm.css"

type TerminalPanelProps = {
  websocketUrl?: string // Custom WebSocket URL if needed
}

export const TerminalPanel: React.FC<TerminalPanelProps> = ({ websocketUrl = "ws://localhost:8008/ws/terminal" }) => {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  // For touch gestures
  const touchStartRef = useRef<{ x: number; y: number; time: number } | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

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

    // WebSocket connection to backend (Flask)
    const ws = new WebSocket(websocketUrl)
    wsRef.current = ws

    ws.onopen = () => {
      term.writeln("\x1b[32mConnected to ProxMenux terminal.\x1b[0m")
      // Optional: notify backend to start shell
      // ws.send(JSON.stringify({ type: 'start', shell: 'bash' }));
    }

    ws.onmessage = (event) => {
      // Backend sends plain text (bash output)
      term.write(event.data)
    }

    ws.onerror = () => {
      term.writeln("\r\n\x1b[31m[ERROR] WebSocket connection error\x1b[0m")
    }

    ws.onclose = () => {
      term.writeln("\r\n\x1b[33m[INFO] Connection closed\x1b[0m")
    }

    // Send user input to backend
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        // Send raw data or JSON depending on backend implementation
        ws.send(data)
      }
    })

    // Re-adjust terminal size on window resize
    const handleResize = () => {
      try {
        fitAddon.fit()
      } catch {
        // Ignore resize errors
      }
    }
    window.addEventListener("resize", handleResize)

    return () => {
      window.removeEventListener("resize", handleResize)
      ws.close()
      term.dispose()
    }
  }, [websocketUrl])

  // --- Helpers for special key sequences ---
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
        sendSequence("\x03") // Ctrl+C
        break
      default:
        break
    }
  }

  // --- Touch gestures for arrow keys ---
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

    const minDistance = 30 // Minimum pixels for swipe detection
    const maxTime = 1000 // Maximum time in milliseconds

    touchStartRef.current = null

    if (dt > maxTime) return // Gesture too slow, ignore

    if (Math.abs(dx) < minDistance && Math.abs(dy) < minDistance) {
      return // Movement too small, ignore
    }

    if (Math.abs(dx) > Math.abs(dy)) {
      // Horizontal swipe
      if (dx > 0) {
        handleKeyButton("RIGHT")
      } else {
        handleKeyButton("LEFT")
      }
    } else {
      // Vertical swipe
      if (dy > 0) {
        handleKeyButton("DOWN")
      } else {
        handleKeyButton("UP")
      }
    }
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Terminal display */}
      <div
        ref={containerRef}
        className="flex-1 bg-black rounded-t-md overflow-hidden"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      />

      {/* Touch keyboard bar for mobile/tablet */}
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

// Reusable button component for touch keyboard
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
