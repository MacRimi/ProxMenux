"use client"

import { useEffect, useState, useRef } from "react"
import { fetchApi, getApiUrl } from "@/lib/api-config"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Loader2, CheckCircle2, XCircle, TerminalIcon } from "lucide-react"

import { Terminal } from "xterm"
import { FitAddon } from "xterm-addon-fit"
import "xterm/css/xterm.css"

interface HybridScriptMonitorProps {
  sessionId: string | null
  title?: string
  description?: string
  onClose: () => void
  onComplete?: (success: boolean) => void
}

interface ScriptInteraction {
  type: "msgbox" | "yesno" | "inputbox" | "menu"
  id: string
  title: string
  text: string
  data?: string
}

export function HybridScriptMonitor({
  sessionId,
  title = "Script Execution",
  description = "Monitoring script execution...",
  onClose,
  onComplete,
}: HybridScriptMonitorProps) {
  const [interaction, setInteraction] = useState<ScriptInteraction | null>(null)
  const [status, setStatus] = useState<"running" | "completed" | "failed">("running")
  const [inputValue, setInputValue] = useState("")
  const [selectedMenuItem, setSelectedMenuItem] = useState<string>("")
  const [isResponding, setIsResponding] = useState(false)

  const terminalRef = useRef<HTMLDivElement>(null)
  const xtermRef = useRef<Terminal | null>(null)
  const fitAddonRef = useRef<FitAddon | null>(null)
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null)

  const decodeBase64 = (str: string): string => {
    try {
      return atob(str)
    } catch (e) {
      console.error("[v0] Failed to decode base64:", str, e)
      return str
    }
  }

  useEffect(() => {
    if (!terminalRef.current || xtermRef.current) return

    const term = new Terminal({
      cursorBlink: false,
      fontSize: 13,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      theme: {
        background: "#1e1e1e",
        foreground: "#d4d4d4",
        cursor: "#d4d4d4",
        black: "#000000",
        red: "#cd3131",
        green: "#0dbc79",
        yellow: "#e5e510",
        blue: "#2472c8",
        magenta: "#bc3fbc",
        cyan: "#11a8cd",
        white: "#e5e5e5",
        brightBlack: "#666666",
        brightRed: "#f14c4c",
        brightGreen: "#23d18b",
        brightYellow: "#f5f543",
        brightBlue: "#3b8eea",
        brightMagenta: "#d670d6",
        brightCyan: "#29b8db",
        brightWhite: "#ffffff",
      },
      convertEol: true,
      disableStdin: true, // Terminal es solo lectura
    })

    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(terminalRef.current)
    fitAddon.fit()

    xtermRef.current = term
    fitAddonRef.current = fitAddon

    // Ajustar terminal cuando cambia el tamaño
    const resizeObserver = new ResizeObserver(() => {
      fitAddon.fit()
    })
    resizeObserver.observe(terminalRef.current)

    return () => {
      resizeObserver.disconnect()
      term.dispose()
      xtermRef.current = null
      fitAddonRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!sessionId || !xtermRef.current) return

    const term = xtermRef.current
    term.writeln("\x1b[32m[INFO] Conectando al stream de logs...\x1b[0m")

    const eventSourceUrl = getApiUrl(`/api/scripts/logs/${sessionId}`)
    const eventSource = new EventSource(eventSourceUrl)

    eventSource.onopen = () => {
      term.writeln("\x1b[32m[INFO] Conexión establecida con el servidor\x1b[0m")
    }

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.type === "init") {
          term.writeln(`\x1b[36m[INICIO] Ejecutando: ${data.script}\x1b[0m`)
          term.writeln(`\x1b[36m[INICIO] Session ID: ${data.session_id}\x1b[0m`)
          term.writeln("")
        } else if (data.type === "raw") {
          const message = data.message

          // Detectar WEB_INTERACTION y mostrar modal, pero NO escribir en terminal
          if (message.includes("WEB_INTERACTION:")) {
            const interactionPart = message.split("WEB_INTERACTION:")[1]

            if (interactionPart) {
              const parts = interactionPart.split(":")

              if (parts.length >= 4) {
                const [type, id, titleB64, textB64, ...dataParts] = parts
                const dataB64 = dataParts.join(":")

                setInteraction({
                  type: type as ScriptInteraction["type"],
                  id,
                  title: decodeBase64(titleB64),
                  text: decodeBase64(textB64),
                  data: dataB64 ? decodeBase64(dataB64) : undefined,
                })
              }
            }
          } else {
            term.writeln(message)
          }
        } else if (data.type === "error") {
          term.writeln(`\x1b[31m[ERROR] ${data.message}\x1b[0m`)
        }
      } catch (e) {
        term.writeln(`\x1b[31m[PARSE ERROR] ${event.data.substring(0, 100)}\x1b[0m`)
      }
    }

    eventSource.onerror = () => {
      term.writeln("\x1b[31m[ERROR] Conexión perdida, reintentando...\x1b[0m")
    }

    const pollStatus = async () => {
      try {
        const statusData = await fetchApi(`/api/scripts/status/${sessionId}`)

        if (statusData.status === "completed" || statusData.exit_code === 0) {
          term.writeln("")
          term.writeln("\x1b[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\x1b[0m")
          term.writeln("\x1b[32m✓ Script completado exitosamente\x1b[0m")
          term.writeln("\x1b[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\x1b[0m")
          setStatus("completed")
          eventSource.close()
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current)
          }
          onComplete?.(true)
        } else if (statusData.status === "failed" || (statusData.exit_code !== null && statusData.exit_code !== 0)) {
          term.writeln("")
          term.writeln("\x1b[31m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\x1b[0m")
          term.writeln(`\x1b[31m✗ Script falló con código de salida: ${statusData.exit_code}\x1b[0m`)
          term.writeln("\x1b[31m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\x1b[0m")
          setStatus("failed")
          eventSource.close()
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current)
          }
          onComplete?.(false)
        }

        // Detectar interacciones pendientes desde el status
        if (statusData.pending_interaction) {
          const parts = statusData.pending_interaction.split(":")
          if (parts.length >= 4) {
            const [type, id, titleB64, textB64, ...dataParts] = parts
            const dataB64 = dataParts.join(":")

            setInteraction({
              type: type as ScriptInteraction["type"],
              id,
              title: decodeBase64(titleB64),
              text: decodeBase64(textB64),
              data: dataB64 ? decodeBase64(dataB64) : undefined,
            })
          }
        }
      } catch (error) {
        console.error("[v0] Error polling status:", error)
      }
    }

    pollStatus()
    pollingIntervalRef.current = setInterval(pollStatus, 2000)

    return () => {
      eventSource.close()
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current)
      }
    }
  }, [sessionId, onComplete])

  const handleInteractionResponse = async (response: string) => {
    if (!interaction || !sessionId || !xtermRef.current) return

    const term = xtermRef.current
    setIsResponding(true)

    try {
      term.writeln(`\x1b[33m[USUARIO] Respuesta: ${response}\x1b[0m`)

      await fetchApi("/api/scripts/respond", {
        method: "POST",
        body: JSON.stringify({
          session_id: sessionId,
          interaction_id: interaction.id,
          value: response,
        }),
      })

      setInteraction(null)
      setInputValue("")
      setSelectedMenuItem("")
    } catch (error) {
      term.writeln(`\x1b[31m[ERROR] Error enviando respuesta: ${error}\x1b[0m`)
    } finally {
      setIsResponding(false)
    }
  }

  const renderInteractionModal = () => {
    if (!interaction) return null

    switch (interaction.type) {
      case "msgbox":
        return (
          <Dialog open={true} onOpenChange={() => {}}>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>{interaction.title}</DialogTitle>
              </DialogHeader>
              <DialogDescription className="py-6 text-base whitespace-pre-wrap">{interaction.text}</DialogDescription>
              <div className="flex justify-end">
                <Button onClick={() => handleInteractionResponse("ok")} disabled={isResponding}>
                  {isResponding ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  OK
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        )

      case "yesno":
        return (
          <Dialog open={true} onOpenChange={() => {}}>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>{interaction.title}</DialogTitle>
              </DialogHeader>
              <DialogDescription className="py-6 text-base whitespace-pre-wrap">{interaction.text}</DialogDescription>
              <div className="flex justify-end gap-3">
                <Button variant="outline" onClick={() => handleInteractionResponse("no")} disabled={isResponding}>
                  No
                </Button>
                <Button onClick={() => handleInteractionResponse("yes")} disabled={isResponding}>
                  {isResponding ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Yes
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        )

      case "inputbox":
        return (
          <Dialog open={true} onOpenChange={() => {}}>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>{interaction.title}</DialogTitle>
              </DialogHeader>
              <DialogDescription className="py-4 text-base whitespace-pre-wrap">{interaction.text}</DialogDescription>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="input-value">Valor</Label>
                  <Input
                    id="input-value"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    placeholder={interaction.data || "Introduce el valor..."}
                    autoFocus
                  />
                </div>
                <div className="flex justify-end gap-3">
                  <Button variant="outline" onClick={() => handleInteractionResponse("")} disabled={isResponding}>
                    Cancelar
                  </Button>
                  <Button onClick={() => handleInteractionResponse(inputValue)} disabled={isResponding || !inputValue}>
                    {isResponding ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    OK
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        )

      case "menu":
        const menuItems = interaction.data?.split("|").filter(Boolean) || []
        return (
          <Dialog open={true} onOpenChange={() => {}}>
            <DialogContent className="sm:max-w-2xl max-h-[80vh]">
              <DialogHeader>
                <DialogTitle>{interaction.title}</DialogTitle>
              </DialogHeader>
              <DialogDescription className="py-4 text-base whitespace-pre-wrap">{interaction.text}</DialogDescription>
              <ScrollArea className="max-h-96 pr-4">
                <div className="space-y-2">
                  {menuItems.map((item, index) => {
                    const [value, label] = item.includes(":") ? item.split(":") : [item, item]
                    return (
                      <Button
                        key={index}
                        variant={selectedMenuItem === value ? "default" : "outline"}
                        className="w-full justify-start text-left h-auto py-3 px-4"
                        onClick={() => setSelectedMenuItem(value)}
                      >
                        {label}
                      </Button>
                    )
                  })}
                </div>
              </ScrollArea>
              <div className="flex justify-end gap-3 mt-4 pt-4 border-t">
                <Button variant="outline" onClick={() => handleInteractionResponse("")} disabled={isResponding}>
                  Cancelar
                </Button>
                <Button
                  onClick={() => handleInteractionResponse(selectedMenuItem)}
                  disabled={isResponding || !selectedMenuItem}
                >
                  {isResponding ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Seleccionar
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        )

      default:
        return null
    }
  }

  if (!sessionId) return null

  return (
    <>
      <Dialog open={true} onOpenChange={status !== "running" ? onClose : undefined}>
        <DialogContent className="max-w-5xl max-h-[85vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {status === "running" && <Loader2 className="h-5 w-5 animate-spin" />}
              {status === "completed" && <CheckCircle2 className="h-5 w-5 text-green-500" />}
              {status === "failed" && <XCircle className="h-5 w-5 text-red-500" />}
              <TerminalIcon className="h-5 w-5" />
              {title}
            </DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="border rounded-lg overflow-hidden bg-[#1e1e1e]">
              <div ref={terminalRef} className="h-[500px] p-2" style={{ width: "100%", height: "500px" }} />
            </div>

            <div className="flex items-center justify-between pt-4 border-t">
              <div className="text-sm text-muted-foreground">
                Session ID: <span className="font-mono">{sessionId}</span>
              </div>
              {status !== "running" && (
                <Button onClick={onClose} size="lg">
                  Cerrar
                </Button>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {renderInteractionModal()}
    </>
  )
}
