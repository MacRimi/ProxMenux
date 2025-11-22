"use client"

import type React from "react"
import { useEffect, useRef, useState, useCallback } from "react"
import { API_PORT } from "@/lib/api-config"
import {
  Activity,
  Trash2,
  X,
  Search,
  Send,
  Wifi,
  WifiOff,
  Lightbulb,
  Terminal,
  Plus,
  Split,
  Grid2X2,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
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
  // containerRef: React.RefObject<HTMLDivElement> // This is no longer needed as we use callback refs
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

export const TerminalPanel: React.FC<TerminalPanelProps> = ({ websocketUrl, onClose }) => {
  const [terminals, setTerminals] = useState<TerminalInstance[]>([])
  const [activeTerminalId, setActiveTerminalId] = useState<string>("")
  const [layout, setLayout] = useState<"single" | "vertical" | "horizontal" | "grid">("single")
  const [isMobile, setIsMobile] = useState(false)

  const [searchModalOpen, setSearchModalOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [filteredCommands, setFilteredCommands] = useState<Array<{ cmd: string; desc: string }>>(proxmoxCommands)
  const [lastKeyPressed, setLastKeyPressed] = useState<string | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<CheatSheetResult[]>([])
  const [useOnline, setUseOnline] = useState(true)

  const containerRefs = useRef<{ [key: string]: HTMLDivElement | null }>({})

  const setContainerRef = useCallback(
    (id: string) => (el: HTMLDivElement | null) => {
      containerRefs.current[id] = el
    },
    [],
  )

  useEffect(() => {
    setIsMobile(window.innerWidth < 768)
    const handleResize = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener("resize", handleResize)
    return () => window.removeEventListener("resize", handleResize)
  }, [])

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

        const formattedQuery = query.trim().replace(/\s+/g, "+")
        const url = `https://cht.sh/${formattedQuery}?QT`

        console.log("[v0] Fetching from cheat.sh:", url)

        const response = await fetch(url, {
          signal: AbortSignal.timeout(10000),
          headers: {
            "User-Agent": "curl/7.68.0",
          },
        })

        if (!response.ok) {
          console.log("[v0] API response not OK:", response.status)
          throw new Error(`API request failed: ${response.status}`)
        }

        const text = await response.text()
        console.log("[v0] Received response, length:", text.length)

        if (!text || text.includes("Unknown topic") || text.includes("nothing found")) {
          throw new Error("No results found")
        }

        const blocks = text.split(/\n\s*\n/).filter((block) => block.trim())
        const examples: string[] = []

        for (const block of blocks) {
          const lines = block.split("\n").filter((line) => {
            const trimmed = line.trim()
            return trimmed && !trimmed.startsWith("http") && !trimmed.includes("cheat.sh") && !trimmed.includes("[")
          })

          if (lines.length > 0) {
            const example = lines.join("\n").trim()
            if (example.length > 10 && example.length < 500) {
              examples.push(example)
            }
          }
        }

        console.log("[v0] Parsed examples:", examples.length)

        if (examples.length > 0) {
          setUseOnline(true)
          setSearchResults([
            {
              command: query,
              description: `Results from cheat.sh for "${query}"`,
              examples: examples.slice(0, 8),
            },
          ])
        } else {
          throw new Error("No valid examples found")
        }
      } catch (error) {
        console.log("[v0] Falling back to offline mode:", error)
        setUseOnline(false)
        const filtered = proxmoxCommands.filter(
          (item) =>
            item.cmd.toLowerCase().includes(query.toLowerCase()) ||
            item.desc.toLowerCase().includes(query.toLowerCase()),
        )
        setFilteredCommands(filtered)
        setSearchResults([])
      } finally {
        setIsSearching(false)
      }
    }

    const debounce = setTimeout(() => {
      if (searchQuery && searchQuery.length >= 2) {
        // Only search if query is at least 2 characters
        searchCheatSh(searchQuery)
      } else {
        setSearchResults([])
        setFilteredCommands(proxmoxCommands)
        setUseOnline(true) // Reset to online when query is cleared
      }
    }, 800) // Increased debounce to 800ms to avoid premature requests

    return () => clearTimeout(debounce)
  }, [searchQuery])

  const addNewTerminal = () => {
    if (terminals.length >= 4) return

    const newId = `terminal-${Date.now()}`
    // containerRefs.current[newId] = useRef<HTMLDivElement>(null) // No longer needed

    setTerminals((prev) => [
      ...prev,
      {
        id: newId,
        title: `Terminal ${prev.length + 1}`,
        term: null,
        ws: null,
        isConnected: false,
        // containerRef: containerRefs.current[newId], // No longer needed
      },
    ])
    setActiveTerminalId(newId)
  }

  const closeTerminal = (id: string) => {
    const terminal = terminals.find((t) => t.id === id)
    if (terminal) {
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

    delete containerRefs.current[id] // Clean up the ref
  }

  useEffect(() => {
    terminals.forEach((terminal) => {
      const container = containerRefs.current[terminal.id]
      if (!terminal.term && container) {
        initializeTerminal(terminal, container)
      }
    })
  }, [terminals, isMobile])

  const initializeTerminal = async (terminal: TerminalInstance, container: HTMLDivElement) => {
    const [Terminal, FitAddon] = await Promise.all([
      import("xterm").then((mod) => mod.Terminal),
      import("xterm-addon-fit").then((mod) => mod.FitAddon),
      import("xterm/css/xterm.css"),
    ]).then(([Terminal, FitAddon]) => [Terminal, FitAddon])

    const term = new Terminal({
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
      fontSize: isMobile ? 11 : 13,
      cursorBlink: true,
      scrollback: 2000,
      disableStdin: false,
      cols: isMobile ? 40 : layout === "grid" ? 60 : 120,
      rows: isMobile ? 20 : layout === "grid" ? 15 : 30,
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

    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)

    term.open(container)
    fitAddon.fit()

    const wsUrl = websocketUrl || getWebSocketUrl()
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      setTerminals((prev) => prev.map((t) => (t.id === terminal.id ? { ...t, isConnected: true, term, ws } : t)))
      term.writeln("\x1b[32mConnected to ProxMenux terminal.\x1b[0m")
    }

    ws.onmessage = (event) => {
      term.write(event.data)
    }

    ws.onerror = (error) => {
      console.error("[v0] TerminalPanel: WebSocket error:", error)
      setTerminals((prev) => prev.map((t) => (t.id === terminal.id ? { ...t, isConnected: false } : t)))
      term.writeln("\r\n\x1b[31m[ERROR] WebSocket connection error\x1b[0m")
    }

    ws.onclose = () => {
      setTerminals((prev) => prev.map((t) => (t.id === terminal.id ? { ...t, isConnected: false } : t)))
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
      window.removeEventListener("resize", handleResize)
      ws.close()
      term.dispose()
    }
  }

  const handleKeyButton = (key: string) => {
    const activeTerminal = terminals.find((t) => t.id === activeTerminalId)
    if (!activeTerminal || !activeTerminal.ws || activeTerminal.ws.readyState !== WebSocket.OPEN) return
    let seq = ""
    switch (key) {
      case "UP":
        seq = "\x1b[A"
        break
      case "DOWN":
        seq = "\x1b[B"
        break
      case "RIGHT":
        seq = "\x1b[C"
        break
      case "LEFT":
        seq = "\x1b[D"
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
      default:
        break
    }
    activeTerminal.ws.send(seq)
    if (key) {
      setLastKeyPressed(key)
      setTimeout(() => setLastKeyPressed(null), 2000)
    }
  }

  const handleClear = () => {
    const activeTerminal = terminals.find((t) => t.id === activeTerminalId)
    if (activeTerminal?.term) {
      activeTerminal.term.clear()
    }
  }

  const handleClose = () => {
    terminals.forEach((terminal) => {
      if (terminal.ws) terminal.ws.close()
      if (terminal.term) terminal.term.dispose()
    })
    onClose?.()
  }

  const sendToActiveTerminal = (command: string) => {
    const activeTerminal = terminals.find((t) => t.id === activeTerminalId)
    if (activeTerminal?.ws && activeTerminal.ws.readyState === WebSocket.OPEN) {
      activeTerminal.ws.send(command + "\n")
      setSearchModalOpen(false) // Close the search modal after sending a command
    }
  }

  const sendSequence = (seq: string, keyName?: string) => {
    const activeTerminal = terminals.find((t) => t.id === activeTerminalId)
    if (activeTerminal?.ws && activeTerminal.ws.readyState === WebSocket.OPEN) {
      activeTerminal.ws.send(seq)
      if (keyName) {
        setLastKeyPressed(keyName)
        setTimeout(() => setLastKeyPressed(null), 2000)
      }
    }
  }

  const getLayoutClass = () => {
    const count = terminals.length
    if (isMobile || count === 1) return "grid grid-cols-1"
    if (layout === "vertical" || count === 2) return "grid grid-cols-2"
    if (layout === "horizontal") return "grid grid-rows-2"
    if (layout === "grid" || count >= 3) return "grid grid-cols-2 grid-rows-2"
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
                onClick={() => setLayout("vertical")}
                variant="outline"
                size="sm"
                className={`h-8 px-2 ${layout === "vertical" ? "bg-blue-500/20 border-blue-500" : ""}`}
              >
                <Split className="h-4 w-4 rotate-90" />
              </Button>
              <Button
                onClick={() => setLayout("horizontal")}
                variant="outline"
                size="sm"
                className={`h-8 px-2 ${layout === "horizontal" ? "bg-blue-500/20 border-blue-500" : ""}`}
              >
                <Split className="h-4 w-4" />
              </Button>
              <Button
                onClick={() => setLayout("grid")}
                variant="outline"
                size="sm"
                className={`h-8 px-2 ${layout === "grid" ? "bg-blue-500/20 border-blue-500" : ""}`}
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
            className="h-8 gap-2 bg-green-600 hover:bg-green-700 border-green-500 text-white disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            <span className="hidden sm:inline">New</span>
          </Button>
          <Button
            onClick={() => setSearchModalOpen(true)}
            variant="outline"
            size="sm"
            disabled={!activeTerminal?.isConnected}
            className="h-8 gap-2 bg-blue-600 hover:bg-blue-700 border-blue-500 text-white disabled:opacity-50"
          >
            <Search className="h-4 w-4" />
            <span className="hidden sm:inline">Search</span>
          </Button>
          <Button
            onClick={handleClear}
            variant="outline"
            size="sm"
            disabled={!activeTerminal?.isConnected}
            className="h-8 gap-2 bg-yellow-600 hover:bg-yellow-700 border-yellow-500 text-white disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" />
            <span className="hidden sm:inline">Clear</span>
          </Button>
          <Button
            onClick={handleClose}
            variant="outline"
            size="sm"
            className="h-8 gap-2 bg-red-600 hover:bg-red-700 border-red-500 text-white"
          >
            <X className="h-4 w-4" />
            <span className="hidden sm:inline">Close</span>
          </Button>
        </div>
      </div>

      <div className="flex-1 min-h-0">
        {isMobile ? (
          <Tabs value={activeTerminalId} onValueChange={setActiveTerminalId} className="h-full flex flex-col">
            <TabsList className="w-full justify-start bg-zinc-900 rounded-none border-b border-zinc-800">
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
              <TabsContent key={terminal.id} value={terminal.id} className="flex-1 m-0 p-0">
                <div
                  ref={setContainerRef(terminal.id)}
                  className="w-full h-full bg-black"
                  style={{ height: "calc(100vh - 24rem)" }}
                />
              </TabsContent>
            ))}
          </Tabs>
        ) : (
          <div className={`${getLayoutClass()} h-full gap-0.5 bg-zinc-800 p-0.5`}>
            {terminals.map((terminal) => (
              <div key={terminal.id} className="relative bg-zinc-900 overflow-hidden">
                <div className="absolute top-0 left-0 right-0 z-10 flex items-center justify-between px-2 py-1 bg-zinc-900/95 border-b border-zinc-800">
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
                <div ref={setContainerRef(terminal.id)} className="w-full h-full bg-black pt-7" />
              </div>
            ))}
          </div>
        )}
      </div>

      {isMobile && (
        <div className="flex flex-wrap gap-2 justify-center items-center px-2 bg-zinc-900 text-sm rounded-b-md border-t border-zinc-700 py-1.5">
          {lastKeyPressed && (
            <span className="text-xs text-green-500 bg-green-500/10 px-2 py-0.5 rounded mr-2">
              Sent: {lastKeyPressed}
            </span>
          )}
          <Button onClick={() => sendSequence("\x1b")} variant="outline" size="sm" className="h-8 px-3 text-xs">
            ESC
          </Button>
          <Button onClick={() => sendSequence("\t")} variant="outline" size="sm" className="h-8 px-3 text-xs">
            TAB
          </Button>
          <Button onClick={() => handleKeyButton("UP")} variant="outline" size="sm" className="h-8 px-3 text-xs">
            ↑
          </Button>
          <Button onClick={() => handleKeyButton("DOWN")} variant="outline" size="sm" className="h-8 px-3 text-xs">
            ↓
          </Button>
          <Button onClick={() => handleKeyButton("LEFT")} variant="outline" size="sm" className="h-8 px-3 text-xs">
            ←
          </Button>
          <Button onClick={() => handleKeyButton("RIGHT")} variant="outline" size="sm" className="h-8 px-3 text-xs">
            →
          </Button>
          <Button onClick={() => sendSequence("\x03")} variant="outline" size="sm" className="h-8 px-3 text-xs">
            CTRL+C
          </Button>
        </div>
      )}

      <Dialog open={searchModalOpen} onOpenChange={setSearchModalOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader className="flex flex-row items-center justify-between space-y-0 pb-4 border-b border-zinc-800">
            <DialogTitle className="text-xl font-semibold">Search Commands</DialogTitle>
            <Badge variant={useOnline ? "default" : "secondary"} className="flex items-center gap-2">
              {useOnline ? (
                <>
                  <Wifi className="w-3 h-3" />
                  <span>Online Mode</span>
                </>
              ) : (
                <>
                  <WifiOff className="w-3 h-3" />
                  <span>Offline Mode</span>
                </>
              )}
            </Badge>
          </DialogHeader>

          <DialogDescription className="sr-only">Search for Linux and Proxmox commands</DialogDescription>

          <div className="space-y-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
              <Input
                placeholder="Search commands... (e.g., 'tar', 'docker ps', 'qm list', 'systemctl')"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10 bg-zinc-900 border-zinc-700 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
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
                searchResults.map((result, index) => (
                  <div
                    key={index}
                    className="p-4 rounded-lg border border-zinc-700 bg-zinc-800/50 hover:bg-zinc-800 hover:border-blue-500 transition-colors"
                  >
                    <div className="space-y-2">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1">
                          <code className="text-sm text-blue-400 font-mono font-bold">{result.command}</code>
                          {result.description && <p className="text-xs text-zinc-400 mt-1">{result.description}</p>}
                        </div>
                      </div>
                      {result.examples.length > 0 && (
                        <div className="space-y-1 mt-2 pt-2 border-t border-zinc-700">
                          <p className="text-xs text-zinc-500 mb-1">Examples:</p>
                          {result.examples.slice(0, 3).map((example, idx) => (
                            <div
                              key={idx}
                              onClick={(e) => {
                                e.stopPropagation()
                                sendToActiveTerminal(example)
                              }}
                              className="flex items-center justify-between p-2 rounded bg-zinc-900/50 hover:bg-zinc-900 group cursor-pointer transition-colors"
                            >
                              <code className="text-xs text-green-400 font-mono flex-1 break-all">{example}</code>
                              <Button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  sendToActiveTerminal(example)
                                }}
                                size="sm"
                                variant="ghost"
                                className="shrink-0 h-6 px-2 text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                              >
                                <Send className="h-3 w-3" />
                              </Button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))
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
                            {["tar", "grep", "docker ps", "qm list", "systemctl"].map((cmd) => (
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
                <span>
                  Tip: Search for any Linux command (tar, grep, docker, etc.) or Proxmox commands (qm, pct, pvesh)
                </span>
              </div>
              {useOnline && searchResults.length > 0 && <span className="text-zinc-600">Powered by cheat.sh</span>}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
