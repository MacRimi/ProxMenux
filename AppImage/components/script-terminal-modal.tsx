"use client"

import { useState, useEffect, useRef } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { X, CheckCircle2, XCircle, Loader2 } from "lucide-react"
import { TerminalPanel } from "./terminal-panel"
import { API_PORT } from "@/lib/api-config"

interface WebInteraction {
  type: "yesno" | "menu" | "msgbox" | "input" | "inputbox"
  id: string
  title: string
  message: string
  options?: Array<{ label: string; value: string }>
  default?: string
}

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
  const [currentInteraction, setCurrentInteraction] = useState<WebInteraction | null>(null)
  const [interactionInput, setInteractionInput] = useState("")
  const terminalRef = useRef<any>(null)

  useEffect(() => {
    if (open) {
      console.log("[v0] ScriptTerminalModal opened with:", {
        scriptPath,
        scriptName,
        params,
        sessionId,
      })
      setCurrentInteraction(null)
      setInteractionInput("")
    }
  }, [open, scriptPath, scriptName, params, sessionId])

  const getScriptWebSocketUrl = (): string => {
    if (typeof window === "undefined") {
      return `ws://localhost:${API_PORT}/ws/script/${sessionId}`
    }

    const { hostname, protocol } = window.location
    const wsProtocol = protocol === "https:" ? "wss:" : "ws:"
    return `${wsProtocol}//${hostname}:${API_PORT}/ws/script/${sessionId}`
  }

  const wsUrl = getScriptWebSocketUrl()

  const handleWebInteraction = (interaction: WebInteraction) => {
    console.log("[v0] Received web interaction:", interaction)
    setCurrentInteraction(interaction)
  }

  const handleInteractionResponse = (value: string) => {
    if (!terminalRef.current || !currentInteraction) return

    const response = JSON.stringify({
      type: "interaction_response",
      id: currentInteraction.id,
      value: value,
    })

    console.log("[v0] Sending interaction response:", response)

    // Access the terminal instance to send the response
    const terminal = terminalRef.current
    if (terminal?.terminals?.[0]?.ws) {
      terminal.terminals[0].ws.send(response)
    }

    setCurrentInteraction(null)
    setInteractionInput("")
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
            <TerminalPanel
              ref={terminalRef}
              websocketUrl={wsUrl}
              initMessage={{
                script_path: scriptPath,
                params: params,
              }}
              onWebInteraction={handleWebInteraction}
            />
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between p-4 border-t">
            <div className="text-sm text-muted-foreground">Session ID: {sessionId}</div>
            {isComplete && <Button onClick={onClose}>Close</Button>}
          </div>
        </DialogContent>
      </Dialog>

      {currentInteraction && (
        <Dialog open={true} onOpenChange={() => setCurrentInteraction(null)}>
          <DialogContent>
            <DialogTitle>{currentInteraction.title}</DialogTitle>
            <div className="space-y-4">
              <p className="whitespace-pre-wrap">{currentInteraction.message}</p>

              {currentInteraction.type === "yesno" && (
                <div className="flex gap-2">
                  <Button onClick={() => handleInteractionResponse("yes")} className="flex-1">
                    Yes
                  </Button>
                  <Button onClick={() => handleInteractionResponse("no")} variant="outline" className="flex-1">
                    No
                  </Button>
                </div>
              )}

              {currentInteraction.type === "menu" && currentInteraction.options && (
                <div className="space-y-2">
                  {currentInteraction.options.map((option) => (
                    <Button
                      key={option.value}
                      onClick={() => handleInteractionResponse(option.value)}
                      variant="outline"
                      className="w-full justify-start"
                    >
                      {option.label}
                    </Button>
                  ))}
                </div>
              )}

              {currentInteraction.type === "input" ||
                (currentInteraction.type === "inputbox" && (
                  <div className="space-y-2">
                    <Label>Your input:</Label>
                    <Input
                      value={interactionInput}
                      onChange={(e) => setInteractionInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          handleInteractionResponse(interactionInput)
                        }
                      }}
                      placeholder={currentInteraction.default || ""}
                    />
                    <Button onClick={() => handleInteractionResponse(interactionInput)} className="w-full">
                      Submit
                    </Button>
                  </div>
                ))}

              {currentInteraction.type === "msgbox" && (
                <Button onClick={() => handleInteractionResponse("ok")} className="w-full">
                  OK
                </Button>
              )}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
