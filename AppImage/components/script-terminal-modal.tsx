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
    console.log("[v0] currentInteraction changed:", currentInteraction)
    if (currentInteraction) {
      console.log("[v0] Interaction opened, type:", currentInteraction.type, "id:", currentInteraction.id)
    } else {
      console.log("[v0] Interaction closed/cleared")
      console.trace("[v0] Stack trace for currentInteraction = null")
    }
  }, [currentInteraction])

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
    console.log("[v0] handleWebInteraction called with:", interaction)
    setCurrentInteraction(interaction)
    console.log("[v0] setCurrentInteraction called with interaction")
  }

  const handleInteractionResponse = (value: string) => {
    console.log("[v0] handleInteractionResponse called with value:", value)
    if (!terminalRef.current || !currentInteraction) {
      console.log("[v0] Cannot send response - no terminal ref or interaction")
      return
    }

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
      console.log("[v0] Response sent successfully")
    } else {
      console.log("[v0] Could not send response - no WebSocket available")
    }

    console.log("[v0] Clearing currentInteraction after response")
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
        <Dialog open={true} modal={true}>
          <DialogContent
            className="max-w-4xl max-h-[80vh] overflow-y-auto"
            onInteractOutside={(e) => {
              console.log("[v0] onInteractOutside triggered - preventing close")
              e.preventDefault()
            }}
            onEscapeKeyDown={(e) => {
              console.log("[v0] onEscapeKeyDown triggered - preventing close")
              e.preventDefault()
            }}
          >
            <DialogTitle>{currentInteraction.title}</DialogTitle>
            <div className="space-y-4">
              <p className="whitespace-pre-wrap">{currentInteraction.message}</p>

              {currentInteraction.type === "yesno" && (
                <div className="flex gap-2">
                  <Button
                    onClick={() => handleInteractionResponse("yes")}
                    className="flex-1 bg-blue-600 hover:bg-blue-700 text-white"
                  >
                    Yes
                  </Button>
                  <Button
                    onClick={() => handleInteractionResponse("no")}
                    variant="outline"
                    className="flex-1 hover:bg-red-600 hover:text-white hover:border-red-600"
                  >
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
