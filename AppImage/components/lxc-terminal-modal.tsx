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
  ChevronDown,
  Search,
  Send,
  Lightbulb,
  Terminal,
  Trash2,
  X,
} from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu"
import { DialogHeader, DialogDescription } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Dialog as SearchDialog, DialogContent as SearchDialogContent, DialogTitle as SearchDialogTitle } from "@/components/ui/dialog"
import "xterm/css/xterm.css"
import { API_PORT, fetchApi } from "@/lib/api-config"

interface LxcTerminalModalProps {
  open: boolean
  onClose: () => void
  vmid: number
  vmName: string
}

interface CheatSheetResult {
  command: string
  description: string
  examples: string[]
}

const proxmoxCommands = [
  { cmd: "ls -la", desc: "List all files with details" },
  { cmd: "cd /path/to/dir", desc: "Change directory" },
  { cmd: "cat filename", desc: "Display file contents" },
  { cmd: "grep 'pattern' file", desc: "Search for pattern in file" },
  { cmd: "find . -name 'file'", desc: "Find files by name" },
  { cmd: "df -h", desc: "Show disk usage" },
  { cmd: "du -sh *", desc: "Show directory sizes" },
  { cmd: "free -h", desc: "Show memory usage" },
  { cmd: "top", desc: "Show running processes" },
  { cmd: "ps aux | grep process", desc: "Find running process" },
  { cmd: "systemctl status service", desc: "Check service status" },
  { cmd: "systemctl restart service", desc: "Restart a service" },
  { cmd: "apt update && apt upgrade", desc: "Update packages" },
  { cmd: "apt install package", desc: "Install package" },
  { cmd: "tail -f /var/log/syslog", desc: "Follow log file" },
  { cmd: "chmod 755 file", desc: "Change file permissions" },
  { cmd: "chown user:group file", desc: "Change file owner" },
  { cmd: "tar -xzf file.tar.gz", desc: "Extract tar.gz archive" },
  { cmd: "docker ps", desc: "List running containers" },
  { cmd: "docker images", desc: "List Docker images" },
  { cmd: "ip addr show", desc: "Show IP addresses" },
  { cmd: "ping host", desc: "Test network connectivity" },
  { cmd: "curl -I url", desc: "Get HTTP headers" },
  { cmd: "history", desc: "Show command history" },
  { cmd: "clear", desc: "Clear terminal screen" },
]

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
  const isInsideLxcRef = useRef(false)
  const outputBufferRef = useRef<string>("")

  const [modalHeight, setModalHeight] = useState(500)
  const [isResizing, setIsResizing] = useState(false)
  const resizeBarRef = useRef<HTMLDivElement>(null)
  const modalHeightRef = useRef(500)

  // Search state
  const [searchModalOpen, setSearchModalOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [filteredCommands, setFilteredCommands] = useState<Array<{ cmd: string; desc: string }>>(proxmoxCommands)
  const [isSearching, setIsSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<CheatSheetResult[]>([])
  const [useOnline, setUseOnline] = useState(true)

  

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
      isInsideLxcRef.current = false
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
        
        // Buffer output until we detect we're inside the LXC
        // pct enter always enters directly without login prompt when run as root
        if (!isInsideLxcRef.current) {
          outputBufferRef.current += event.data
          
          // Detect when we're inside the LXC container
          // The LXC prompt will NOT contain "constructor" (the host name)
          // It will be something like "root@plex:/#" or "user@containername:~$"
          const buffer = outputBufferRef.current
          
          // Look for a prompt that:
          // 1. Comes after pct enter command
          // 2. Has @ followed by container name (not host name)
          // 3. Ends with # or $
          const pctEnterMatch = buffer.match(/pct enter \d+\r?\n/)
          if (pctEnterMatch) {
            const afterPctEnter = buffer.substring(buffer.indexOf(pctEnterMatch[0]) + pctEnterMatch[0].length)
            
            // Find the LXC prompt - it should be a line ending with :~# :~$ :/# or similar
            // and NOT containing the host name "constructor"
            const lxcPromptMatch = afterPctEnter.match(/\r?\n?([^\r\n]*@(?!constructor)[^\r\n]*[#$]\s*)$/)
            
            if (lxcPromptMatch) {
              // Successfully inside LXC - only show from the LXC prompt onwards
              isInsideLxcRef.current = true
              
              // Find where the LXC prompt line starts
              const promptStart = afterPctEnter.lastIndexOf(lxcPromptMatch[1])
              if (promptStart !== -1) {
                // Only show the LXC prompt itself
                term.write(lxcPromptMatch[1])
              }
              return
            }
          }
        } else {
          // Already inside LXC, write directly
          term.write(event.data)
        }
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

  // Search effect - debounced search with cheat.sh
  useEffect(() => {
    const searchCheatSh = async (query: string) => {
      if (!query.trim()) {
        setSearchResults([])
        setFilteredCommands(proxmoxCommands)
        return
      }

      try {
        setIsSearching(true)
        const searchEndpoint = `/api/terminal/search-command?q=${encodeURIComponent(query)}`
        const data = await fetchApi<{ success: boolean; examples: any[] }>(searchEndpoint, {
          method: "GET",
          signal: AbortSignal.timeout(10000),
        })

        if (!data.success || !data.examples || data.examples.length === 0) {
          throw new Error("No examples found")
        }

        const formattedResults: CheatSheetResult[] = data.examples.map((example: any) => ({
          command: example.command,
          description: example.description || "",
          examples: [example.command],
        }))

        setUseOnline(true)
        setSearchResults(formattedResults)
      } catch (error) {
        const filtered = proxmoxCommands.filter(
          (item) =>
            item.cmd.toLowerCase().includes(query.toLowerCase()) ||
            item.desc.toLowerCase().includes(query.toLowerCase()),
        )
        setFilteredCommands(filtered)
        setSearchResults([])
        setUseOnline(false)
      } finally {
        setIsSearching(false)
      }
    }

    const debounce = setTimeout(() => {
      if (searchQuery && searchQuery.length >= 2) {
        searchCheatSh(searchQuery)
      } else {
        setSearchResults([])
        setFilteredCommands(proxmoxCommands)
      }
    }, 800)

    return () => clearTimeout(debounce)
  }, [searchQuery])

  const handleClear = useCallback(() => {
    if (termRef.current) {
      termRef.current.clear()
    }
  }, [])

  const sendToTerminal = useCallback((command: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(command)
      setTimeout(() => {
        setSearchModalOpen(false)
      }, 100)
    }
  }, [])

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
          <div className="flex gap-2">
            <Button
              onClick={() => setSearchModalOpen(true)}
              variant="outline"
              size="sm"
              disabled={connectionStatus !== "online"}
              className="h-8 gap-2 bg-blue-600/20 hover:bg-blue-600/30 border-blue-600/50 text-blue-400 disabled:opacity-50"
            >
              <Search className="h-4 w-4" />
              <span className="hidden sm:inline">Search</span>
            </Button>
            <Button
              onClick={handleClear}
              variant="outline"
              size="sm"
              disabled={connectionStatus !== "online"}
              className="h-8 gap-2 bg-yellow-600/20 hover:bg-yellow-600/30 border-yellow-600/50 text-yellow-400 disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" />
              <span className="hidden sm:inline">Clear</span>
            </Button>
          </div>
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
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 px-2 text-xs bg-zinc-800 border-zinc-700 text-zinc-300 gap-1"
                  >
                    Ctrl
                    <ChevronDown className="h-3 w-3" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuLabel className="text-xs text-muted-foreground">Control Sequences</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onSelect={() => sendKey("\x03")}>
                    <span className="font-mono text-xs mr-2">Ctrl+C</span>
                    <span className="text-muted-foreground text-xs">Cancel/Interrupt</span>
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => sendKey("\x18")}>
                    <span className="font-mono text-xs mr-2">Ctrl+X</span>
                    <span className="text-muted-foreground text-xs">Exit (nano)</span>
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => sendKey("\x12")}>
                    <span className="font-mono text-xs mr-2">Ctrl+R</span>
                    <span className="text-muted-foreground text-xs">Search history</span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
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
            size="sm"
            className="h-8 gap-2 bg-red-600/20 hover:bg-red-600/30 border-red-600/50 text-red-400"
          >
            <X className="h-4 w-4" />
            <span className="hidden sm:inline">Close</span>
          </Button>
        </div>
      </DialogContent>

      {/* Search Commands Modal */}
      <SearchDialog open={searchModalOpen} onOpenChange={setSearchModalOpen}>
        <SearchDialogContent className="max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader className="flex flex-row items-center justify-between space-y-0 pb-4 border-b border-zinc-800">
            <SearchDialogTitle className="text-xl font-semibold">Search Commands</SearchDialogTitle>
            <div className="flex items-center gap-2">
              <div
                className={`w-2 h-2 rounded-full ${useOnline ? "bg-green-500" : "bg-red-500"}`}
                title={useOnline ? "Online - Using cheat.sh API" : "Offline - Using local commands"}
              />
            </div>
          </DialogHeader>

          <DialogDescription className="sr-only">Search for Linux commands</DialogDescription>

          <div className="space-y-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
              <Input
                placeholder="Search commands... (e.g., tar, docker, systemctl)"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10 bg-zinc-900 border-zinc-700 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 text-base"
                autoCapitalize="none"
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
              />
            </div>

            {isSearching && (
              <div className="text-center py-4 text-zinc-400">
                <div className="animate-spin inline-block w-6 h-6 border-2 border-current border-t-transparent rounded-full mb-2" />
                <p className="text-sm">Searching cheat.sh...</p>
              </div>
            )}

            <div className="flex-1 overflow-y-auto space-y-2 pr-2 max-h-[50vh]">
              {searchResults.length > 0 ? (
                <>
                  {searchResults.map((result, index) => (
                    <div
                      key={index}
                      className="p-4 rounded-lg border border-zinc-700 bg-zinc-800/50 hover:border-zinc-600 transition-colors"
                    >
                      {result.description && (
                        <p className="text-xs text-zinc-400 mb-2 leading-relaxed"># {result.description}</p>
                      )}
                      <div
                        onClick={() => sendToTerminal(result.command)}
                        className="flex items-start justify-between gap-2 cursor-pointer group hover:bg-zinc-800/50 rounded p-2 -m-2"
                      >
                        <code className="text-sm text-blue-400 font-mono break-all flex-1">{result.command}</code>
                        <Send className="h-4 w-4 text-zinc-600 group-hover:text-blue-400 flex-shrink-0 mt-0.5 transition-colors" />
                      </div>
                    </div>
                  ))}
                  <div className="text-center py-2">
                    <p className="text-xs text-zinc-500">
                      <Lightbulb className="inline-block w-3 h-3 mr-1" />
                      Powered by cheat.sh
                    </p>
                  </div>
                </>
              ) : filteredCommands.length > 0 && !useOnline ? (
                filteredCommands.map((item, index) => (
                  <div
                    key={index}
                    onClick={() => sendToTerminal(item.cmd)}
                    className="p-3 rounded-lg border border-zinc-700 bg-zinc-800/50 hover:bg-zinc-800 hover:border-blue-500 cursor-pointer transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <code className="text-sm text-blue-400 font-mono break-all">{item.cmd}</code>
                        <p className="text-xs text-zinc-400 mt-1">{item.desc}</p>
                      </div>
                      <Button
                        onClick={(e) => {
                          e.stopPropagation()
                          sendToTerminal(item.cmd)
                        }}
                        size="sm"
                        variant="ghost"
                        className="shrink-0 h-7 px-2 text-xs"
                      >
                        <Send className="h-3 w-3 mr-1" />
                        Send
                      </Button>
                    </div>
                  </div>
                ))
              ) : !isSearching && !searchQuery && !useOnline ? (
                proxmoxCommands.map((item, index) => (
                  <div
                    key={index}
                    onClick={() => sendToTerminal(item.cmd)}
                    className="p-3 rounded-lg border border-zinc-700 bg-zinc-800/50 hover:bg-zinc-800 hover:border-blue-500 cursor-pointer transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <code className="text-sm text-blue-400 font-mono break-all">{item.cmd}</code>
                        <p className="text-xs text-zinc-400 mt-1">{item.desc}</p>
                      </div>
                      <Button
                        onClick={(e) => {
                          e.stopPropagation()
                          sendToTerminal(item.cmd)
                        }}
                        size="sm"
                        variant="ghost"
                        className="shrink-0 h-7 px-2 text-xs"
                      >
                        <Send className="h-3 w-3 mr-1" />
                        Send
                      </Button>
                    </div>
                  </div>
                ))
              ) : !isSearching ? (
                <div className="text-center py-12 space-y-4">
                  {searchQuery ? (
                    <>
                      <Search className="w-12 h-12 text-zinc-600 mx-auto" />
                      <div>
                        <p className="text-zinc-400 font-medium">{"No results found for \""}{searchQuery}{"\""}</p>
                        <p className="text-xs text-zinc-500 mt-1">Try a different command or check your spelling</p>
                      </div>
                    </>
                  ) : (
                    <>
                      <Terminal className="w-12 h-12 text-zinc-600 mx-auto" />
                      <div>
                        <p className="text-zinc-400 font-medium mb-2">Search for any command</p>
                        <div className="text-sm text-zinc-500 space-y-1">
                          <p>Try searching for:</p>
                          <div className="flex flex-wrap justify-center gap-2 mt-2">
                            {["tar", "grep", "docker", "systemctl", "curl"].map((cmd) => (
                              <code
                                key={cmd}
                                onClick={() => setSearchQuery(cmd)}
                                className="px-2 py-1 bg-zinc-800 rounded text-blue-400 cursor-pointer hover:bg-zinc-700"
                              >
                                {cmd}
                              </code>
                            ))}
                          </div>
                        </div>
                      </div>
                      {useOnline && (
                        <div className="flex items-center justify-center gap-2 text-xs text-zinc-600 mt-4">
                          <Lightbulb className="w-3 h-3" />
                          <span>Powered by cheat.sh</span>
                        </div>
                      )}
                    </>
                  )}
                </div>
              ) : null}
            </div>

            <div className="pt-2 border-t border-zinc-800 flex items-center justify-between text-xs text-zinc-500">
              <div className="flex items-center gap-2">
                <Lightbulb className="w-3 h-3" />
                <span>Tip: Search for any Linux command</span>
              </div>
              {useOnline && searchResults.length > 0 && <span className="text-zinc-600">Powered by cheat.sh</span>}
            </div>
          </div>
        </SearchDialogContent>
      </SearchDialog>
    </Dialog>
  )
}
