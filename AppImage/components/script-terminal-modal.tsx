"use client"

import { useState, useEffect, useRef } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { X, CheckCircle2, XCircle, Loader2 } from "lucide-react"
import { TerminalPanel } from "./terminal-panel"
import { API_PORT } from "@/lib/api-config"

interface ScriptTerminalModalProps {
  open: boolean
  onClose: () => void
  scriptPath: string
  scriptName: string
  params?: Record<string, string>
  title: string
  description: string
}

export function ScriptTerminalModal({
  open,
  onClose,
  scriptPath,
  scriptName,
  params = {},
  title,
  description,
}: ScriptTerminalModalProps) {
  const [sessionId] = useState(() => Math.random().toString(36).substring(7))
  const [isComplete, setIsComplete] = useState(false)
  const [exitCode, setExitCode] = useState<number | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const terminalRef = useRef<any>(null)

  useEffect(() => {
    if (!open) return

    const originalWebSocket = window.WebSocket
    let interceptedWs: WebSocket | null = null

    window.WebSocket = ((url: string | URL, protocols?: string | string[]) => {
      const ws = new originalWebSocket(url, protocols)

      // Solo interceptar nuestro WebSocket específico
      if (url.toString().includes(`/ws/script/${sessionId}`)) {
        interceptedWs = ws
        wsRef.current = ws

        // Cuando se abre la conexión, enviar los parámetros del script
        ws.addEventListener("open", () => {
          const initMessage = JSON.stringify({
            script_path: scriptPath,
            params: params,
          })
          console.log("[v0] Sending script init message:", initMessage)
          ws.send(initMessage)
        })

        // Interceptar mensajes entrantes para filtrar y detectar eventos especiales
        const originalOnMessage = Object.getOwnPropertyDescriptor(WebSocket.prototype, "onmessage")

        Object.defineProperty(ws, "onmessage", {
          set(handler) {
            const wrappedHandler = (event: MessageEvent) => {
              const data = event.data

              if (typeof data === "string" && data.includes("Connected to ProxMenux terminal")) {
                console.log("[v0] Filtered welcome message")
                return // No pasar este mensaje a la terminal
              }

              // Detectar mensajes JSON especiales
              try {
                const parsed = JSON.parse(data)

                // Detectar finalización del script
                if (parsed.type === "exit") {
                  console.log("[v0] Script completed with exit code:", parsed.code)
                  setIsComplete(true)
                  setExitCode(parsed.code || 0)
                }

                // Detectar errores
                if (parsed.type === "error") {
                  console.error("[v0] Script error:", parsed.message)
                }
              } catch (e) {
                // No es JSON, es output normal de terminal
              }

              // Pasar el mensaje al handler original
              if (handler) {
                handler.call(ws, event)
              }
            }

            // Almacenar el handler wrapped
            Object.defineProperty(this, "_wrappedOnMessage", {
              value: wrappedHandler,
              writable: true,
            })

            if (originalOnMessage?.set) {
              originalOnMessage.set.call(this, wrappedHandler)
            }
          },
          get() {
            return this._wrappedOnMessage
          },
        })
      }

      return ws
    }) as any

    // Cleanup: restaurar WebSocket original
    return () => {
      window.WebSocket = originalWebSocket
      if (interceptedWs) {
        wsRef.current = null
      }
    }
  }, [open, sessionId, scriptPath, params])

  const getScriptWebSocketUrl = (): string => {
    if (typeof window === "undefined") {
      return `ws://localhost:${API_PORT}/ws/script/${sessionId}`
    }

    const { hostname, protocol } = window.location
    const wsProtocol = protocol === "https:" ? "wss:" : "ws:"

    // Siempre usar el puerto de Flask directamente
    return `${wsProtocol}//${hostname}:${API_PORT}/ws/script/${sessionId}`
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onClose}>
        <DialogContent className="max-w-4xl h-[80vh] p-0 flex flex-col">
          <DialogTitle className="sr-only">{title}</DialogTitle>

          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b">
            <div className="flex items-center gap-2">
              {isComplete ? (
                exitCode === 0 ? (
                  <CheckCircle2 className="h-5 w-5 text-green-500" />
                ) : (
                  <XCircle className="h-5 w-5 text-red-500" />
                )
              ) : (
                <Loader2 className="h-5 w-5 animate-spin" />
              )}
              <div>
                <h2 className="text-lg font-semibold">{title}</h2>
                {description && <p className="text-sm text-muted-foreground">{description}</p>}
              </div>
            </div>
            <Button variant="ghost" size="icon" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>

          <div className="flex-1 overflow-hidden">
            <TerminalPanel ref={terminalRef} websocketUrl={getScriptWebSocketUrl()} />
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between p-4 border-t">
            <div className="text-sm text-muted-foreground">Session ID: {sessionId}</div>
            {isComplete && <Button onClick={onClose}>Close</Button>}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
