"use client"

import { useState } from "react"
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

interface WebInteraction {
  type: "yesno" | "menu" | "msgbox" | "input"
  id: string
  title: string
  message: string
  options?: Array<{ label: string; value: string }>
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
            <TerminalPanel websocketUrl={getScriptWebSocketUrl()} />
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
