"use client"

import type React from "react"
import { useEffect, useRef, useState } from "react"
import { API_PORT } from "@/lib/api-config"
import { Trash2, X, Send, ChevronUp, ChevronDown, ChevronLeft, ChevronRight, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"

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

interface CheatSheetResult {
  command: string
  description: string
  examples: string[]
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
  const containerRef = useRef<HTMLDivElement | null>(null)
  const termRef = useRef<any>(null)
  const fitAddonRef = useRef<any>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const touchStartRef = useRef<{ x: number; y: number; time: number } | null>(null)

  const [xtermLoaded, setXtermLoaded] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [searchModalOpen, setSearchModalOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [filteredCommands, setFilteredCommands] = useState<Array<{ cmd: string; desc: string }>>(proxmoxCommands)
  const [lastKeyPressed, setLastKeyPressed] = useState<string | null>(null)
  const [isMobile, setIsMobile] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<CheatSheetResult[]>([])
  const [useOnline, setUseOnline] = useState(true)

  useEffect(() => {
    setIsMobile(window.innerWidth < 768)
    const handleResize = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener("resize", handleResize)
    return () => window.removeEventListener("resize", handleResize)
  }, [])

  useEffect(() => {
    if (!searchQuery.trim()) {
      setFilteredCommands(proxmoxCommands)
      setSearchResults([])
      return
    }

    const query = searchQuery.toLowerCase().trim()

    if (useOnline && query.length > 2) {
      setIsSearching(true)

      const searchCheatSh = async () => {
        try {
          const response = await fetch(`https://cheat.sh/${encodeURIComponent(query)}?T`, {
            signal: AbortSignal.timeout(5000),
          })

          if (response.ok) {
            const text = await response.text()

            const lines = text.split("\n").filter((line) => line.trim())
            const results: CheatSheetResult[] = []

            let currentCommand = ""
            let currentDesc = ""
            let currentExamples: string[] = []

            for (const line of lines) {
              if (line.startsWith("#")) {
                if (currentCommand) {
                  results.push({
                    command: currentCommand,
                    description: currentDesc,
                    examples: currentExamples,
                  })
                }
                currentCommand = line.replace(/^#\s*/, "").trim()
                currentDesc = ""
                currentExamples = []
              } else if (line.trim().startsWith("-")) {
                currentDesc += line.trim().replace(/^-\s*/, "") + " "
              } else if (line.trim() && !line.includes("cheat.sh")) {
                currentExamples.push(line.trim())
              }
            }

            if (currentCommand) {
              results.push({
                command: currentCommand,
                description: currentDesc,
                examples: currentExamples,
              })
            }

            setSearchResults(results)
            setFilteredCommands([]) // Clear local results when using online
          } else {
            throw new Error("API request failed")
          }
        } catch (error) {
          console.log("[v0] Cheat.sh unavailable, using offline mode")
          setUseOnline(false)
          const filtered = proxmoxCommands.filter(
            (item) => item.cmd.toLowerCase().includes(query) || item.desc.toLowerCase().includes(query),
          )
          setFilteredCommands(filtered)
          setSearchResults([])
        } finally {
          setIsSearching(false)
        }
      }

      const timer = setTimeout(searchCheatSh, 500)
      return () => clearTimeout(timer)
    } else {
      const filtered = proxmoxCommands.filter(
        (item) => item.cmd.toLowerCase().includes(query) || item.desc.toLowerCase().includes(query),
      )
      setFilteredCommands(filtered)
      setSearchResults([])
      setIsSearching(false)
    }
  }, [searchQuery, useOnline])

  useEffect(() => {
    if (typeof window === "undefined") return

    Promise.all([
      import("xterm").then((mod) => mod.Terminal),
      import("xterm-addon-fit").then((mod) => mod.FitAddon),
      import("xterm/css/xterm.css"),
    ])
      .then(([Terminal, FitAddon]) => {
        if (!containerRef.current) return

        const term = new Terminal({
          fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
          fontSize: isMobile ? 11 : 13,
          cursorBlink: true,
          scrollback: 2000,
          disableStdin: false,
          cols: 150,
          rows: 30,
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

        term.open(containerRef.current)
        fitAddon.fit()

        termRef.current = term
        fitAddonRef.current = fitAddon
        setXtermLoaded(true)

        const wsUrl = websocketUrl || getWebSocketUrl()

        const ws = new WebSocket(wsUrl)
        wsRef.current = ws

        ws.onopen = () => {
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

  const handleSendCommand = (command: string) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(command + "\r")
      setLastKeyPressed(command)
      setTimeout(() => setLastKeyPressed(null), 3000)
    }
    setSearchModalOpen(false)
    setSearchQuery("")
    setSearchResults([])
  }

  return (
    <div className="flex flex-col h-full w-full">
      <div className="flex items-center justify-between gap-2 px-3 py-2 bg-zinc-900 border-b border-zinc-700 rounded-t-md">
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

        <div className="flex gap-2">
          <Button
            onClick={() => setSearchModalOpen(true)}
            variant="outline"
            size="sm"
            disabled={!isConnected}
            className="h-8 gap-2 bg-blue-600 hover:bg-blue-700 border-blue-500 text-white disabled:opacity-50"
          >
            <Search className="h-4 w-4" />
            <span className="hidden sm:inline">Search</span>
          </Button>
          <Button
            onClick={handleClear}
            variant="outline"
            size="sm"
            disabled={!isConnected}
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

      <div
        ref={containerRef}
        className="flex-1 bg-black overflow-auto min-h-0"
        onTouchStart={touchStartRef.current ? undefined : handleTouchStart}
        onTouchEnd={touchStartRef.current ? handleTouchEnd : undefined}
      >
        {!xtermLoaded && (
          <div className="flex items-center justify-center h-full text-zinc-400">Initializing terminal...</div>
        )}
      </div>

      <div className="flex flex-wrap gap-2 justify-center items-center px-2 py-2 bg-zinc-900 text-sm rounded-b-md border-t border-zinc-700">
        {lastKeyPressed && (
          <span className="text-xs text-green-500 bg-green-500/10 px-2 py-0.5 rounded mr-2">
            Sent: {lastKeyPressed}
          </span>
        )}
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

      <Dialog open={searchModalOpen} onOpenChange={setSearchModalOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center justify-between">
              <span>Search Commands</span>
              <Badge variant="outline" className="text-xs">
                {useOnline ? "🌐 Online (cheat.sh)" : "📦 Offline Mode"}
              </Badge>
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 flex-1 overflow-hidden flex flex-col">
            <Input
              type="text"
              placeholder="Search commands... (e.g., 'tar', 'docker ps', 'qm list', 'systemctl')"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-zinc-900 border-zinc-700 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              autoFocus
            />

            {isSearching && (
              <div className="text-center py-4 text-zinc-400">
                <div className="animate-spin inline-block w-6 h-6 border-2 border-current border-t-transparent rounded-full mb-2" />
                <p className="text-sm">Searching cheat.sh...</p>
              </div>
            )}

            <div className="flex-1 overflow-y-auto space-y-2 pr-2">
              {searchResults.length > 0 ? (
                searchResults.map((result, index) => (
                  <div
                    key={index}
                    className="p-4 rounded-lg border border-zinc-700 bg-zinc-800/50 hover:bg-zinc-800 hover:border-blue-500 cursor-pointer transition-colors"
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
                                handleSendCommand(example)
                              }}
                              className="flex items-center justify-between p-2 rounded bg-zinc-900/50 hover:bg-zinc-900 group"
                            >
                              <code className="text-xs text-green-400 font-mono flex-1 break-all">{example}</code>
                              <Button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleSendCommand(example)
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
              ) : filteredCommands.length > 0 ? (
                filteredCommands.map((item, index) => (
                  <div
                    key={index}
                    onClick={() => handleSendCommand(item.cmd)}
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
                          handleSendCommand(item.cmd)
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
                <div className="text-center py-8 text-zinc-400">
                  {searchQuery ? `No commands found for "${searchQuery}"` : "Type to search commands..."}
                </div>
              ) : null}
            </div>

            <div className="text-xs text-zinc-500 pt-2 border-t border-zinc-700">
              💡 Tip: Search for any Linux command (tar, grep, docker, etc.) or Proxmox commands (qm, pct, pvesh)
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
