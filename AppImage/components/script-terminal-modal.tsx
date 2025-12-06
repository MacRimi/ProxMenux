"use client"

import type React from "react"
import { useState, useRef } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { CheckCircle2, XCircle, GripHorizontal } from "lucide-react"
import { TerminalPanel } from "./terminal-panel"
import { useIsMobile } from "@/hooks/use-mobile"

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
  const [isComplete, setIsComplete] = useState(false)
  const [exitCode, setExitCode] = useState<number | null>(null)
  const [currentInteraction, setCurrentInteraction] = useState<WebInteraction | null>(null)
  const [interactionInput, setInteractionInput] = useState("")
  const isMobile = useIsMobile()

  const [modalHeight, setModalHeight] = useState(80)
  const [isResizing, setIsResizing] = useState(false)
  const startYRef = useRef(0)
  const startHeightRef = useRef(80)

  const initMessage = {
    script_path: scriptPath,
    params: {
      EXECUTION_MODE: "web",
      ...params,
    },
  }

  const handleInteractionResponse = (value: string) => {
    if (value === "cancel" || value === "") {
      setCurrentInteraction(null)
      setInteractionInput("")
      onClose()
      return
    }

    // TerminalPanel manejará el envío de la respuesta
    setCurrentInteraction(null)
    setInteractionInput("")
  }

  const handleResizeStart = (e: React.MouseEvent | React.TouchEvent) => {
    setIsResizing(true)
    startYRef.current = "clientY" in e ? e.clientY : e.touches[0].clientY
    startHeightRef.current = modalHeight
    document.addEventListener("mousemove", handleResize as any)
    document.addEventListener("touchmove", handleResize as any)
    document.addEventListener("mouseup", handleResizeEnd)
    document.addEventListener("touchend", handleResizeEnd)
  }

  const handleResize = (e: MouseEvent | TouchEvent) => {
    if (!isResizing) return
    const currentY = e instanceof MouseEvent ? e.clientY : e.touches[0].clientY
    const deltaY = currentY - startYRef.current
    const newHeight = startHeightRef.current + (deltaY / window.innerHeight) * 100
    setModalHeight(Math.max(50, Math.min(95, newHeight)))
  }

  const handleResizeEnd = () => {
    setIsResizing(false)
    document.removeEventListener("mousemove", handleResize as any)
    document.removeEventListener("touchmove", handleResize as any)
    document.removeEventListener("mouseup", handleResizeEnd)
    document.removeEventListener("touchend", handleResizeEnd)
  }

  return (
    <>
      <Dialog open={open}>
        <DialogContent
          className="max-w-4xl p-0 flex flex-col"
          style={{ height: isMobile ? "80vh" : `${modalHeight}vh` }}
          onInteractOutside={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => e.preventDefault()}
        >
          <DialogTitle className="sr-only">{title}</DialogTitle>

          <div className="flex items-center gap-2 p-4 border-b">
            {isComplete &&
              (exitCode === 0 ? (
                <CheckCircle2 className="h-5 w-5 text-green-500" />
              ) : (
                <XCircle className="h-5 w-5 text-red-500" />
              ))}
            <div>
              <h2 className="text-lg font-semibold">{title}</h2>
              {description && <p className="text-sm text-muted-foreground">{description}</p>}
            </div>
          </div>

          <div className="flex-1 overflow-hidden">
            <TerminalPanel
              isScriptModal={true}
              initMessage={initMessage}
              onWebInteraction={(interaction) => {
                setCurrentInteraction({
                  type: interaction.type as any,
                  id: interaction.id,
                  title: interaction.title || "",
                  message: interaction.message || "",
                  options: interaction.options,
                  default: interaction.default,
                })
              }}
              onClose={onClose}
            />
          </div>

          {!isMobile && (
            <div
              className={`h-2 cursor-ns-resize flex items-center justify-center transition-colors ${
                isResizing ? "bg-blue-500" : "bg-zinc-800 hover:bg-blue-500/50"
              }`}
              onMouseDown={handleResizeStart}
              onTouchStart={handleResizeStart}
            >
              <GripHorizontal className={`h-4 w-4 ${isResizing ? "text-white" : "text-zinc-500"}`} />
            </div>
          )}
        </DialogContent>
      </Dialog>

      {currentInteraction && (
        <Dialog open={true}>
          <DialogContent
            className="max-w-4xl max-h-[80vh] overflow-y-auto"
            onInteractOutside={(e) => e.preventDefault()}
            onEscapeKeyDown={(e) => e.preventDefault()}
            hideClose
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
                    onClick={() => handleInteractionResponse("cancel")}
                    variant="outline"
                    className="flex-1 hover:bg-red-600 hover:text-white hover:border-red-600"
                  >
                    Cancel
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
                      className="w-full justify-start hover:bg-blue-600 hover:text-white"
                    >
                      {option.label}
                    </Button>
                  ))}
                  <Button
                    onClick={() => handleInteractionResponse("cancel")}
                    variant="outline"
                    className="w-full hover:bg-red-600 hover:text-white hover:border-red-600"
                  >
                    Cancel
                  </Button>
                </div>
              )}

              {(currentInteraction.type === "input" || currentInteraction.type === "inputbox") && (
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
                  <div className="flex gap-2">
                    <Button
                      onClick={() => handleInteractionResponse(interactionInput)}
                      className="flex-1 bg-blue-600 hover:bg-blue-700"
                    >
                      Submit
                    </Button>
                    <Button
                      onClick={() => handleInteractionResponse("cancel")}
                      variant="outline"
                      className="flex-1 hover:bg-red-600 hover:text-white hover:border-red-600"
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}

              {currentInteraction.type === "msgbox" && (
                <div className="flex gap-2">
                  <Button
                    onClick={() => handleInteractionResponse("ok")}
                    className="flex-1 bg-blue-600 hover:bg-blue-700"
                  >
                    OK
                  </Button>
                  <Button
                    onClick={() => handleInteractionResponse("cancel")}
                    variant="outline"
                    className="flex-1 hover:bg-red-600 hover:text-white hover:border-red-600"
                  >
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
