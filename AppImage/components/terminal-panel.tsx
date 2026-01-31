"use client"

import type React from "react"
import { useEffect, useRef, useState } from "react"
import { API_PORT, fetchApi } from "@/lib/api-config" // Unificando importaciones de api-config en una sola línea con alias @/
import {
  Activity,
  Trash2,
  X,
  Search,
  Send,
  Lightbulb,
  Terminal,
  Plus,
  AlignJustify,
  Grid2X2,
  GripHorizontal,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import type { CheatSheetResult } from "@/lib/cheat-sheet-result" // Declare CheatSheetResult here

type TerminalPanelProps = {
  websocketUrl?: string
  onClose?: () => void
}

interface TerminalInstance {
  id: string
  title: string
  term: any
  ws: WebSocket | null
  isConnected: boolean
  fitAddon: any // Added fitAddon to TerminalInstance
  pingInterval?: ReturnType<typeof setInterval> | null // Heartbeat interval to keep connection alive
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

function getApiUrl(endpoint?: string): string {
  if (typeof window === "undefined") {
    return "http://localhost:8008"
  }

  const { protocol, hostname } = window.location
  const apiProtocol = protocol === "https:" ? "https:" : "http:"
  return `${apiProtocol}//${hostname}:${API_PORT}${endpoint || ""}`
}

const proxmoxCommands = [
  { cmd: "pvesh get /nodes", desc: "List all Proxmox nodes" },
  { cmd: "pvesh get /nodes/{node}/qemu", desc: "List VMs on a node" },
  { cmd: "pvesh get /nodes/{node}/lxc", desc: "List LXC containers on a node" },
  { cmd: "pvesh get /nodes/{node}/storage", desc: "List storage on a node" },
  { cmd: "pvesh get /nodes/{node}/network", desc: "List network interfaces" },
  { cmd: "qm list", desc: "List all QEMU/KVM virtual machines" },
  { cmd: "qm start <vmid>", desc: "Start a virtual machine" },
  { cmd: "qm stop <vmid>", desc: "Stop a virtual machine" },
  { cmd: "qm shutdown <vmid>", desc: "Shutdown a virtual machine gracefully" },
  { cmd: "qm status <vmid>", desc: "Show VM status" },
  { cmd: "qm config <vmid>", desc: "Show VM configuration" },
  { cmd: "qm snapshot <vmid> <snapname>", desc: "Create VM snapshot" },
  { cmd: "pct list", desc: "List all LXC containers" },
  { cmd: "pct start <vmid>", desc: "Start LXC container" },
  { cmd: "pct stop <vmid>", desc: "Stop LXC container" },
  { cmd: "pct enter <vmid>", desc: "Enter LXC container console" },
  { cmd: "pct config <vmid>", desc: "Show container configuration" },
  { cmd: "pvesm status", desc: "Show storage status" },
  { cmd: "pvesm list <storage>", desc: "List storage content" },
  { cmd: "pveperf", desc: "Test Proxmox system performance" },
  { cmd: "pveversion", desc: "Show Proxmox VE version" },
  { cmd: "systemctl status pve-cluster", desc: "Check cluster status" },
  { cmd: "pvecm status", desc: "Show cluster status" },
  { cmd: "pvecm nodes", desc: "List cluster nodes" },
  { cmd: "zpool status", desc: "Show ZFS pool status" },
  { cmd: "zpool list", desc: "List all ZFS pools" },
  { cmd: "zfs list", desc: "List all ZFS datasets" },
  { cmd: "ls -la", desc: "List all files with details" },
  { cmd: "cd /path/to/dir", desc: "Change directory" },
  { cmd: "mkdir dirname", desc: "Create new directory" },
  { cmd: "rm -rf dirname", desc: "Remove directory recursively" },
  { cmd: "cp source dest", desc: "Copy files or directories" },
  { cmd: "mv source dest", desc: "Move or rename files" },
  { cmd: "cat filename", desc: "Display file contents" },
  { cmd: "grep 'pattern' file", desc: "Search for pattern in file" },
  { cmd: "find . -name 'file'", desc: "Find files by name" },
  { cmd: "chmod 755 file", desc: "Change file permissions" },
  { cmd: "chown user:group file", desc: "Change file owner" },
  { cmd: "tar -xzf file.tar.gz", desc: "Extract tar.gz archive" },
  { cmd: "tar -czf archive.tar.gz dir/", desc: "Create tar.gz archive" },
  { cmd: "df -h", desc: "Show disk usage" },
  { cmd: "du -sh *", desc: "Show directory sizes" },
  { cmd: "free -h", desc: "Show memory usage" },
  { cmd: "top", desc: "Show running processes" },
  { cmd: "ps aux | grep process", desc: "Find running process" },
  { cmd: "kill -9 PID", desc: "Force kill process" },
  { cmd: "systemctl status service", desc: "Check service status" },
  { cmd: "systemctl start service", desc: "Start a service" },
  { cmd: "systemctl stop service", desc: "Stop a service" },
  { cmd: "systemctl restart service", desc: "Restart a service" },
  { cmd: "apt update && apt upgrade", desc: "Update Debian/Ubuntu packages" },
  { cmd: "apt install package", desc: "Install package on Debian/Ubuntu" },
  { cmd: "apt remove package", desc: "Remove package" },
  { cmd: "docker ps", desc: "List running containers" },
  { cmd: "docker images", desc: "List Docker images" },
  { cmd: "docker exec -it container bash", desc: "Enter container shell" },
  { cmd: "ip addr show", desc: "Show IP addresses" },
  { cmd: "ping host", desc: "Test network connectivity" },
  { cmd: "curl -I url", desc: "Get HTTP headers" },
  { cmd: "wget url", desc: "Download file from URL" },
  { cmd: "ssh user@host", desc: "Connect via SSH" },
  { cmd: "scp file user@host:/path", desc: "Copy file via SSH" },
  { cmd: "tail -f /var/log/syslog", desc: "Follow log file in real-time" },
  { cmd: "history", desc: "Show command history" },
  { cmd: "clear", desc: "Clear terminal screen" },
]

function reconnectTerminal(id: string) {
  // Implementation of reconnectTerminal function
}

export const TerminalPanel: React.FC<TerminalPanelProps> = ({ websocketUrl, onClose }) => {
  const [terminals, setTerminals] = useState<TerminalInstance[]>([])
  const [activeTerminalId, setActiveTerminalId] = useState<string>("")
  const [layout, setLayout] = useState<"single" | "grid">("grid")
  const [isMobile, setIsMobile] = useState(false)
  const [isTablet, setIsTablet] = useState(false)
  const [terminalHeight, setTerminalHeight] = useState<number>(500) // altura por defecto en px
  const [searchModalOpen, setSearchModalOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [filteredCommands, setFilteredCommands] = useState<Array<{ cmd: string; desc: string }>>(proxmoxCommands)
  const [isSearching, setIsSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<CheatSheetResult[]>([])
  const [useOnline, setUseOnline] = useState(true)

  const containerRefs = useRef<{ [key: string]: HTMLDivElement | null }>({})

  useEffect(() => {
    const updateDeviceType = () => {
      const width = window.innerWidth
      const isTouchDevice = "ontouchstart" in window || navigator.maxTouchPoints > 0
      const isTabletSize = width >= 768 && width <= 1366 // iPads Pro pueden llegar a 1366px

      setIsMobile(width < 768)
      setIsTablet(isTouchDevice && isTabletSize)
    }

    updateDeviceType()
    const handleResize = () => updateDeviceType()
    window.addEventListener("resize", handleResize)

    const savedHeight = localStorage.getItem("terminalHeight")
    if (savedHeight) {
      setTerminalHeight(Number.parseInt(savedHeight, 10))
    }

    return () => {
      window.removeEventListener("resize", handleResize)
    }
  }, [])

  // Handle page visibility change for automatic reconnection when user returns
  // This is especially important for mobile/tablet devices (iPad) where switching apps
  // puts the browser tab in background and may close WebSocket connections
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        // When page becomes visible again, check all terminal connections
        terminals.forEach((terminal) => {
          if (terminal.ws && terminal.ws.readyState !== WebSocket.OPEN && terminal.term) {
            // Terminal is disconnected, attempt to reconnect
            reconnectTerminal(terminal.id)
          }
        })
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [terminals])

  const handleResizeStart = (e: React.MouseEvent | React.TouchEvent) => {
    // Bloquear solo en pantallas muy pequeñas (móviles)
    if (window.innerWidth < 640 && !isTablet) {
      return
    }

    e.preventDefault()
    e.stopPropagation()

    // Detectar si es touch o mouse
    const clientY = "touches" in e ? e.touches[0].clientY : e.clientY
    const startY = clientY
    const startHeight = terminalHeight

    const handleMove = (moveEvent: MouseEvent | TouchEvent) => {
      const currentY = "touches" in moveEvent ? moveEvent.touches[0].clientY : moveEvent.clientY
      const deltaY = currentY - startY
      const newHeight = Math.max(200, Math.min(2400, startHeight + deltaY))

      setTerminalHeight(newHeight)
    }

    const handleEnd = () => {
      document.removeEventListener("mousemove", handleMove as any)
      document.removeEventListener("mouseup", handleEnd)
      document.removeEventListener("touchmove", handleMove as any)
      document.removeEventListener("touchend", handleEnd)

      localStorage.setItem("terminalHeight", terminalHeight.toString())
    }

    document.addEventListener("mousemove", handleMove as any)
    document.addEventListener("mouseup", handleEnd)
    document.addEventListener("touchmove", handleMove as any, { passive: false })
    document.addEventListener("touchend", handleEnd)
  }

  useEffect(() => {
    if (terminals.length === 0) {
      addNewTerminal()
    }
  }, [])

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

        console.log("[v0] Received parsed examples from server:", data.examples.length)

        const formattedResults: CheatSheetResult[] = data.examples.map((example: any) => ({
          command: example.command,
          description: example.description || "",
          examples: [example.command],
        }))

        setUseOnline(true)
        setSearchResults(formattedResults)
      } catch (error) {
        console.log("[v0] Error fetching from cheat.sh proxy, using offline commands:", error)
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

  // Function to reconnect a terminal when connection is lost
  // This is called when page visibility changes (user returns from another app)
  const reconnectTerminal = async (terminalId: string) => {
    const terminal = terminals.find(t => t.id === terminalId)
    if (!terminal || !terminal.term) return
    
    // Show reconnecting message
    terminal.term.writeln('\r\n\x1b[33m[INFO] Reconnecting...\x1b[0m')
    
    const wsUrl = websocketUrl || getWebSocketUrl()
    const ws = new WebSocket(wsUrl)
    
    ws.onopen = () => {
      // Clear any existing ping interval
      if (terminal.pingInterval) {
        clearInterval(terminal.pingInterval)
      }
      
      // Start heartbeat ping every 25 seconds to keep connection alive
      const pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        } else {
          clearInterval(pingInterval)
        }
      }, 25000)
      
      setTerminals((prev) =>
        prev.map((t) => (t.id === terminalId ? { ...t, isConnected: true, ws, pingInterval } : t))
      )
      terminal.term.writeln('\r\n\x1b[32m[INFO] Reconnected successfully\x1b[0m')
      
      // Sync terminal size
      if (terminal.fitAddon) {
        try {
          terminal.fitAddon.fit()
          ws.send(JSON.stringify({
            type: 'resize',
            cols: terminal.term.cols,
            rows: terminal.term.rows,
          }))
        } catch (err) {
          console.warn('[Terminal] resize on reconnect failed:', err)
        }
      }
    }
    
    ws.onmessage = (event) => {
      // Filter out pong responses from heartbeat - don't display in terminal
      if (event.data === '{"type": "pong"}' || event.data === '{"type":"pong"}') {
        return
      }
      terminal.term.write(event.data)
    }
    
    ws.onerror = () => {
      terminal.term.writeln('\r\n\x1b[31m[ERROR] Reconnection failed\x1b[0m')
    }
    
    ws.onclose = () => {
      setTerminals((prev) => prev.map((t) => {
        if (t.id === terminalId) {
          if (t.pingInterval) {
            clearInterval(t.pingInterval)
          }
          return { ...t, isConnected: false, pingInterval: null }
        }
        return t
      }))
      terminal.term.writeln('\r\n\x1b[33m[INFO] Connection closed\x1b[0m')
    }
    
    terminal.term.onData((data: string) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data)
      }
    })
  }

  const addNewTerminal = () => {
    if (terminals.length >= 4) return

    const newId = `terminal-${Date.now()}`
    setTerminals((prev) => [
      ...prev,
      {
        id: newId,
        title: `Terminal ${prev.length + 1}`,
        term: null,
        ws: null,
        isConnected: false,
        fitAddon: null, // Added fitAddon initialization
        pingInterval: null, // Added pingInterval initialization
      },
    ])
    setActiveTerminalId(newId)
  }

  const closeTerminal = (id: string) => {
    const terminal = terminals.find((t) => t.id === id)
    if (terminal) {
      // Clear heartbeat interval
      if (terminal.pingInterval) {
        clearInterval(terminal.pingInterval)
      }
      if (terminal.ws) {
        terminal.ws.close()
      }
      if (terminal.term) {
        terminal.term.dispose()
      }
    }

    setTerminals((prev) => {
      const filtered = prev.filter((t) => t.id !== id)
      if (filtered.length > 0 && activeTerminalId === id) {
        setActiveTerminalId(filtered[0].id)
      }
      return filtered
    })

    delete containerRefs.current[id]
  }

  useEffect(() => {
    terminals.forEach((terminal) => {
      const container = containerRefs.current[terminal.id]
      if (!terminal.term && container) {
        initializeTerminal(terminal, container)
      }
    })
  }, [terminals, isMobile])

  useEffect(() => {
    if (window.innerWidth < 640) return

    terminals.forEach((terminal) => {
      if (terminal.term && terminal.fitAddon && terminal.isConnected) {
        try {
          setTimeout(() => {
            terminal.fitAddon?.fit()
            if (terminal.ws?.readyState === WebSocket.OPEN) {
              const cols = terminal.term?.cols || 80
              const rows = terminal.term?.rows || 24
              terminal.ws.send(
                JSON.stringify({
                  type: "resize",
                  cols,
                  rows,
                }),
              )
            }
          }, 100)
        } catch (err) {
          console.warn("[Terminal] resize on height change failed:", err)
        }
      }
    })
  }, [terminalHeight, layout, terminals, isMobile])

  const initializeTerminal = async (terminal: TerminalInstance, container: HTMLDivElement) => {
    const [TerminalClass, FitAddonClass] = await Promise.all([
      import("xterm").then((mod) => mod.Terminal),
      import("xterm-addon-fit").then((mod) => mod.FitAddon),
      import("xterm/css/xterm.css"),
    ]).then(([Terminal, FitAddon]) => [Terminal, FitAddon])

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

    term.open(container)

    fitAddon.fit()

    const wsUrl = websocketUrl || getWebSocketUrl()
    const ws = new WebSocket(wsUrl)

    const syncSizeWithBackend = () => {
      try {
        fitAddon.fit()
        if (ws.readyState === WebSocket.OPEN) {
          const cols = term.cols
          const rows = term.rows
          ws.send(
            JSON.stringify({
              type: "resize",
              cols,
              rows,
            }),
          )
        }
      } catch (err) {
        console.warn("[Terminal] resize failed:", err)
      }
    }

    ws.onopen = () => {
      // Start heartbeat ping every 25 seconds to keep connection alive
      // This prevents disconnection when switching apps on mobile/tablet (iPad)
      const pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        } else {
          clearInterval(pingInterval)
        }
      }, 25000)
      
      setTerminals((prev) =>
        prev.map((t) => (t.id === terminal.id ? { ...t, isConnected: true, term, ws, fitAddon, pingInterval } : t)),
      )
      syncSizeWithBackend()
    }

    ws.onmessage = (event) => {
      // Filter out pong responses from heartbeat - don't display in terminal
      if (event.data === '{"type": "pong"}' || event.data === '{"type":"pong"}') {
        return
      }
      term.write(event.data)
    }

    ws.onerror = (error) => {
      console.error("[v0] TerminalPanel: WebSocket error:", error)
      setTerminals((prev) => prev.map((t) => {
        if (t.id === terminal.id) {
          if (t.pingInterval) {
            clearInterval(t.pingInterval)
          }
          return { ...t, isConnected: false, pingInterval: null }
        }
        return t
      }))
      term.writeln("\r\n\x1b[31m[ERROR] WebSocket connection error\x1b[0m")
    }

    ws.onclose = () => {
      setTerminals((prev) => prev.map((t) => {
        if (t.id === terminal.id) {
          if (t.pingInterval) {
            clearInterval(t.pingInterval)
          }
          return { ...t, isConnected: false, pingInterval: null }
        }
        return t
      }))
      term.writeln("\r\n\x1b[33m[INFO] Connection closed\x1b[0m")
    }

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data)
      }
    })

    let resizeTimeout: any = null

    const handleResize = () => {
      clearTimeout(resizeTimeout)
      resizeTimeout = setTimeout(() => {
        syncSizeWithBackend()
      }, 150)
    }

    window.addEventListener("resize", handleResize)

    return () => {
      window.removeEventListener("resize", handleResize)
      ws.close()
      term.dispose()
    }
  }

  const handleKeyButton = (key: string, e?: React.MouseEvent | React.TouchEvent) => {
    // Prevenir comportamientos por defecto del navegador
    if (e) {
      e.preventDefault()
      e.stopPropagation()
    }

    const activeTerminal = terminals.find((t) => t.id === activeTerminalId)
    if (!activeTerminal || !activeTerminal.ws || activeTerminal.ws.readyState !== WebSocket.OPEN) return

    let seq = ""
    switch (key) {
      case "UP":
        seq = "\x1bOA"
        break
      case "DOWN":
        seq = "\x1bOB"
        break
      case "RIGHT":
        seq = "\x1bOC"
        break
      case "LEFT":
        seq = "\x1bOD"
        break
      case "ESC":
        seq = "\x1b"
        break
      case "TAB":
        seq = "\t"
        break
      case "CTRL_C":
        seq = "\x03"
        break
      case "ENTER":
        seq = "\r"
        break
      default:
        break
    }

    activeTerminal.ws.send(seq)
  }

  const handleClear = () => {
    const activeTerminal = terminals.find((t) => t.id === activeTerminalId)
    if (activeTerminal?.term) {
      activeTerminal.term.clear()
    }
  }

const handleClose = () => {
    terminals.forEach((terminal) => {
      // Clear heartbeat interval
      if (terminal.pingInterval) clearInterval(terminal.pingInterval)
      if (terminal.ws) terminal.ws.close()
      if (terminal.term) terminal.term.dispose()
    })
    onClose?.()
  }

  const sendToActiveTerminal = (command: string) => {
    const activeTerminal = terminals.find((t) => t.id === activeTerminalId)

    if (activeTerminal?.ws && activeTerminal.ws.readyState === WebSocket.OPEN) {
      activeTerminal.ws.send(command)

      setTimeout(() => {
        setSearchModalOpen(false)
      }, 100)
    }
  }

  const sendSequence = (seq: string, e?: React.MouseEvent | React.TouchEvent) => {
    if (e) {
      e.preventDefault()
      e.stopPropagation()
    }

    const activeTerminal = terminals.find((t) => t.id === activeTerminalId)
    if (activeTerminal?.ws && activeTerminal.ws.readyState === WebSocket.OPEN) {
      activeTerminal.ws.send(seq)
    }
  }

  const getLayoutClass = () => {
    const count = terminals.length
    if (isMobile || count === 1) return "grid grid-cols-1"

    // Vista de cuadrícula 2x2
    if (layout === "grid") {
      if (count === 2) return "grid grid-cols-2"
      if (count === 3) return "grid grid-cols-2 grid-rows-2"
      if (count === 4) return "grid grid-cols-2 grid-rows-2"
    }

    if (count === 2) return "grid grid-cols-1 grid-rows-2"
    if (count === 3) return "grid grid-cols-1 grid-rows-3"
    if (count === 4) return "grid grid-cols-1 grid-rows-4"

    // Vista de filas apiladas (single) - una terminal debajo de otra
    return "grid grid-cols-1"
  }

  const activeTerminal = terminals.find((t) => t.id === activeTerminalId)

  return (
    <div className="flex flex-col h-full bg-zinc-950 rounded-md overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-zinc-900 border-b border-zinc-800">
        <div className="flex items-center gap-3">
          <Activity className="h-5 w-5 text-blue-500" />
          <div
            className={`w-2 h-2 rounded-full ${activeTerminal?.isConnected ? "bg-green-500" : "bg-red-500"}`}
            title={activeTerminal?.isConnected ? "Connected" : "Disconnected"}
          ></div>
          <span className="text-xs text-zinc-500">{terminals.length} / 4 terminals</span>
        </div>

        <div className="flex gap-2">
          {!isMobile && terminals.length > 1 && (
            <>
              <Button
                onClick={() => setLayout("single")}
                variant="outline"
                size="sm"
                className={`h-8 px-2 ${layout === "single" ? "bg-blue-500/20 border-blue-500" : ""}`}
                title="Vista apilada (filas)"
              >
                <AlignJustify className="h-4 w-4" />
              </Button>
              <Button
                onClick={() => setLayout("grid")}
                variant="outline"
                size="sm"
                className={`h-8 px-2 ${layout === "grid" ? "bg-blue-500/20 border-blue-500" : ""}`}
                title="Vista cuadrícula 2x2"
              >
                <Grid2X2 className="h-4 w-4" />
              </Button>
            </>
          )}
          <Button
            onClick={addNewTerminal}
            variant="outline"
            size="sm"
            disabled={terminals.length >= 4}
            className="h-8 gap-2 bg-green-600/20 hover:bg-green-600/30 border-green-600/50 text-green-400 disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            <span className="hidden sm:inline">New</span>
          </Button>
          <Button
            onClick={() => setSearchModalOpen(true)}
            variant="outline"
            size="sm"
            disabled={!activeTerminal?.isConnected}
            className="h-8 gap-2 bg-blue-600/20 hover:bg-blue-600/30 border-blue-600/50 text-blue-400 disabled:opacity-50"
          >
            <Search className="h-4 w-4" />
            <span className="hidden sm:inline">Search</span>
          </Button>
          <Button
            onClick={handleClear}
            variant="outline"
            size="sm"
            disabled={!activeTerminal?.isConnected}
            className="h-8 gap-2 bg-yellow-600/20 hover:bg-yellow-600/30 border-yellow-600/50 text-yellow-400 disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" />
            <span className="hidden sm:inline">Clear</span>
          </Button>
          <Button
            onClick={handleClose}
            variant="outline"
            size="sm"
            className="h-8 gap-2 bg-red-600/20 hover:bg-red-600/30 border-red-600/50 text-red-400"
          >
            <X className="h-4 w-4" />
            <span className="hidden sm:inline">Close</span>
          </Button>
        </div>
      </div>

      <div
        data-terminal-container
        ref={(el) => {
          containerRefs.current["main"] = el
        }}
        className={`overflow-hidden flex flex-col ${isMobile ? "flex-1 h-[60vh]" : "overflow-hidden"} w-full max-w-full`}
        style={!isMobile || isTablet ? { height: `${terminalHeight}px`, flexShrink: 0 } : undefined}
      >
        {isMobile ? (
          <Tabs value={activeTerminalId} onValueChange={setActiveTerminalId} className="h-full flex flex-col">
            <TabsList className="w-full justify-start bg-zinc-900 rounded-none border-b border-zinc-800 overflow-x-auto">
              {terminals.map((terminal) => (
                <TabsTrigger key={terminal.id} value={terminal.id} className="relative">
                  {terminal.title}
                  {terminals.length > 1 && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        closeTerminal(terminal.id)
                      }}
                      className="ml-2 hover:bg-zinc-700 rounded p-0.5"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </TabsTrigger>
              ))}
            </TabsList>
            {terminals.map((terminal) => (
              <TabsContent
                key={terminal.id}
                value={terminal.id}
                forceMount
                className={`flex-1 h-full mt-0 ${activeTerminalId === terminal.id ? "block" : "hidden"}`}
              >
                <div
                  ref={(el) => (containerRefs.current[terminal.id] = el)}
                  className="w-full h-full flex-1 bg-black overflow-hidden"
                />
              </TabsContent>
            ))}
          </Tabs>
        ) : (
          <div className={`${getLayoutClass()} h-full gap-0.5 bg-zinc-800 p-0.5 w-full overflow-hidden`}>
            {terminals.map((terminal) => (
              <div
                key={terminal.id}
                className={`relative bg-zinc-900 overflow-hidden flex flex-col min-h-0 w-full ${
                  terminals.length > 1 && activeTerminalId === terminal.id ? "ring-2 ring-blue-500" : ""
                }`}
              >
                <div className="flex-shrink-0 flex items-center justify-between px-2 py-1 bg-zinc-900/95 border-b border-zinc-800">
                  <button
                    onClick={() => setActiveTerminalId(terminal.id)}
                    className={`text-xs font-medium ${
                      activeTerminalId === terminal.id ? "text-blue-400" : "text-zinc-500"
                    }`}
                  >
                    {terminal.title}
                  </button>
                  {terminals.length > 1 && (
                    <button onClick={() => closeTerminal(terminal.id)} className="hover:bg-zinc-700 rounded p-0.5">
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </div>
                <div
                  ref={(el) => (containerRefs.current[terminal.id] = el)}
                  onClick={() => setActiveTerminalId(terminal.id)}
                  className="flex-1 w-full max-w-full bg-black overflow-hidden cursor-pointer"
                  data-terminal-container
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {(isTablet || (!isMobile && !isTablet)) && terminals.length > 0 && (
        <div
          onMouseDown={handleResizeStart}
          onTouchStart={handleResizeStart}
          className="h-2 w-full cursor-row-resize bg-zinc-800 hover:bg-blue-600 transition-colors flex items-center justify-center group relative"
          style={{ touchAction: "none" }}
        >
          <GripHorizontal className="h-4 w-4 text-zinc-600 group-hover:text-white pointer-events-none" />
        </div>
      )}

      {(isMobile || isTablet) && (
        <div className="flex flex-wrap gap-1.5 justify-center items-center px-1 bg-zinc-900 text-sm rounded-b-md border-t border-zinc-700 py-1.5">
          <Button
            onPointerDown={(e) => {
              e.preventDefault()
              e.stopPropagation()
              sendSequence("\x1b", e)
            }}
            variant="outline"
            size="sm"
            className="h-8 px-2.5 text-xs"
          >
            ESC
          </Button>
          <Button
            onPointerDown={(e) => {
              e.preventDefault()
              e.stopPropagation()
              sendSequence("\t", e)
            }}
            variant="outline"
            size="sm"
            className="h-8 px-2.5 text-xs"
          >
            TAB
          </Button>
          <Button
            onPointerDown={(e) => {
              e.preventDefault()
              e.stopPropagation()
              handleKeyButton("UP", e)
            }}
            variant="outline"
            size="sm"
            className="h-8 px-3 text-xs"
          >
            ↑
          </Button>
          <Button
            onPointerDown={(e) => {
              e.preventDefault()
              e.stopPropagation()
              handleKeyButton("DOWN", e)
            }}
            variant="outline"
            size="sm"
            className="h-8 px-3 text-xs"
          >
            ↓
          </Button>
          <Button
            onPointerDown={(e) => {
              e.preventDefault()
              e.stopPropagation()
              handleKeyButton("LEFT", e)
            }}
            variant="outline"
            size="sm"
            className="h-8 px-3 text-xs"
          >
            ←
          </Button>
          <Button
            onPointerDown={(e) => {
              e.preventDefault()
              e.stopPropagation()
              handleKeyButton("RIGHT", e)
            }}
            variant="outline"
            size="sm"
            className="h-8 px-3 text-xs"
          >
            →
          </Button>
          <Button
            onPointerDown={(e) => {
              e.preventDefault()
              e.stopPropagation()
              handleKeyButton("ENTER", e)
            }}
            variant="outline"
            size="sm"
            className="h-8 px-3 text-xs bg-blue-600/20 hover:bg-blue-600/30 border-blue-600/50 text-blue-400"
          >
            ↵ Enter
          </Button>
          <Button
            onPointerDown={(e) => {
              e.preventDefault()
              e.stopPropagation()
              sendSequence("\x03", e)
            }}
            variant="outline"
            size="sm"
            className="h-8 px-2 text-xs"
          >
            Ctrl
          </Button>
        </div>
      )}

      <Dialog open={searchModalOpen} onOpenChange={setSearchModalOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader className="flex flex-row items-center justify-between space-y-0 pb-4 border-b border-zinc-800">
            <DialogTitle className="text-xl font-semibold">Search Commands</DialogTitle>
            <div className="flex items-center gap-2">
              <div
                className={`w-2 h-2 rounded-full ${useOnline ? "bg-green-500" : "bg-red-500"}`}
                title={useOnline ? "Online - Using cheat.sh API" : "Offline - Using local commands"}
              />
            </div>
          </DialogHeader>

          <DialogDescription className="sr-only">Search for Linux and Proxmox commands</DialogDescription>

          <div className="space-y-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
              <Input
                placeholder="Search commands... (e.g., tar, docker, qm, systemctl)"
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
                        onClick={() => sendToActiveTerminal(result.command)}
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
                    onClick={() => sendToActiveTerminal(item.cmd)}
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
                          sendToActiveTerminal(item.cmd)
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
                    onClick={() => sendToActiveTerminal(item.cmd)}
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
                          sendToActiveTerminal(item.cmd)
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
                        <p className="text-zinc-400 font-medium">No results found for "{searchQuery}"</p>
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
                            {["tar", "grep", "docker", "qm", "systemctl"].map((cmd) => (
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
                <span>Tip: Search for any Linux command or Proxmox commands (qm, pct, zpool)</span>
              </div>
              {useOnline && searchResults.length > 0 && <span className="text-zinc-600">Powered by cheat.sh</span>}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
