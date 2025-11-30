"use client"

import { useEffect, useState, useRef } from "react"
import { fetchApi } from "@/lib/api-config"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Loader2, CheckCircle2, XCircle, AlertCircle } from "lucide-react"

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

interface LogEntry {
  timestamp: string
  message: string
  type: "info" | "error" | "warning" | "success"
}

export function HybridScriptMonitor({
  sessionId,
  title = "Script Execution",
  description = "Monitoring script execution...",
  onClose,
  onComplete,
}: HybridScriptMonitorProps) {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [interaction, setInteraction] = useState<ScriptInteraction | null>(null)
  const [status, setStatus] = useState<"running" | "completed" | "failed">("running")
  const [inputValue, setInputValue] = useState("")
  const [selectedMenuItem, setSelectedMenuItem] = useState<string>("")
  const [isResponding, setIsResponding] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const lastLogPositionRef = useRef<number>(0)

  const decodeBase64 = (str: string): string => {
    try {
      return atob(str)
    } catch (e) {
      console.error("[v0] Failed to decode base64:", str, e)
      return str
    }
  }

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  useEffect(() => {
    if (!sessionId) return

    const pollLogsAndStatus = async () => {
      try {
        console.log("[v0] Polling logs and status for session:", sessionId)

        const statusData = await fetchApi(`/api/scripts/status/${sessionId}`)
        console.log("[v0] Status data:", statusData)

        if (statusData.status === "completed" || statusData.exit_code === 0) {
          console.log("[v0] Script execution completed:", statusData.status)
          setStatus("completed")
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current)
          }
          onComplete?.(true)
        } else if (statusData.status === "failed" || (statusData.exit_code !== null && statusData.exit_code !== 0)) {
          console.log("[v0] Script execution failed:", statusData)
          setStatus("failed")
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current)
          }
          onComplete?.(false)
        }

        if (statusData.pending_interaction) {
          const parts = statusData.pending_interaction.split(":")
          if (parts.length >= 4) {
            const [type, id, titleB64, textB64, ...dataParts] = parts
            const dataB64 = dataParts.join(":")

            console.log("[v0] Detected pending interaction from status:", { type, id, titleB64, textB64, dataB64 })

            setInteraction({
              type: type as ScriptInteraction["type"],
              id,
              title: decodeBase64(titleB64),
              text: decodeBase64(textB64),
              data: dataB64 ? decodeBase64(dataB64) : undefined,
            })
          }
        }

        try {
          const logsData = await fetchApi(`/api/scripts/session/${sessionId}/logs?from=${lastLogPositionRef.current}`)

          if (logsData.logs && Array.isArray(logsData.logs)) {
            const newLogs = logsData.logs
              .map((line: string) => {
                if (line.includes("WEB_INTERACTION:")) {
                  const interactionPart = line.split("WEB_INTERACTION:")[1]
                  const parts = interactionPart.split(":")

                  if (parts.length >= 4) {
                    const [type, id, titleB64, textB64, ...dataParts] = parts
                    const dataB64 = dataParts.join(":")

                    console.log("[v0] Detected interaction in log:", { type, id, titleB64, textB64, dataB64 })

                    const decodedTitle = decodeBase64(titleB64)
                    const decodedText = decodeBase64(textB64)
                    const decodedData = dataB64 ? decodeBase64(dataB64) : undefined

                    console.log("[v0] Decoded interaction:", {
                      type,
                      id,
                      title: decodedTitle,
                      text: decodedText,
                      data: decodedData,
                    })

                    setInteraction({
                      type: type as ScriptInteraction["type"],
                      id,
                      title: decodedTitle,
                      text: decodedText,
                      data: decodedData,
                    })
                  }
                  return null
                }

                return {
                  timestamp: new Date().toLocaleTimeString(),
                  message: line,
                  type: line.toLowerCase().includes("error")
                    ? "error"
                    : line.toLowerCase().includes("warning")
                      ? "warning"
                      : line.toLowerCase().includes("success") || line.toLowerCase().includes("complete")
                        ? "success"
                        : "info",
                } as LogEntry
              })
              .filter(Boolean)

            if (newLogs.length > 0) {
              setLogs((prev) => [...prev, ...newLogs])
              lastLogPositionRef.current = logsData.position || lastLogPositionRef.current + newLogs.length
            }
          }
        } catch (logError) {
          console.error("[v0] Error fetching logs:", logError)
        }
      } catch (error) {
        console.error("[v0] Error polling:", error)
        setLogs((prev) => [
          ...prev,
          {
            timestamp: new Date().toLocaleTimeString(),
            message: `Error: ${error}`,
            type: "error",
          },
        ])
      }
    }

    pollLogsAndStatus()

    pollingIntervalRef.current = setInterval(pollLogsAndStatus, 1000)

    return () => {
      console.log("[v0] Cleaning up polling")
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current)
      }
    }
  }, [sessionId, onComplete])

  const handleInteractionResponse = async (response: string) => {
    if (!interaction || !sessionId) return

    setIsResponding(true)

    try {
      console.log("[v0] Sending interaction response:", {
        session_id: sessionId,
        interaction_id: interaction.id,
        value: response,
      })

      await fetchApi("/api/scripts/respond", {
        method: "POST",
        body: JSON.stringify({
          session_id: sessionId,
          interaction_id: interaction.id,
          value: response,
        }),
      })

      console.log("[v0] Response sent successfully")
      setInteraction(null)
      setInputValue("")
      setSelectedMenuItem("")
    } catch (error) {
      console.error("[v0] Error responding to interaction:", error)
      setLogs((prev) => [
        ...prev,
        {
          timestamp: new Date().toLocaleTimeString(),
          message: `Error responding: ${error}`,
          type: "error",
        },
      ])
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
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{interaction.title}</DialogTitle>
              </DialogHeader>
              <DialogDescription className="py-4">{interaction.text}</DialogDescription>
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
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{interaction.title}</DialogTitle>
              </DialogHeader>
              <DialogDescription className="py-4">{interaction.text}</DialogDescription>
              <div className="flex justify-end gap-2">
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
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{interaction.title}</DialogTitle>
              </DialogHeader>
              <DialogDescription className="py-4">{interaction.text}</DialogDescription>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="input-value">Input</Label>
                  <Input
                    id="input-value"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    placeholder={interaction.data || "Enter value..."}
                  />
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => handleInteractionResponse("")} disabled={isResponding}>
                    Cancel
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
            <DialogContent className="max-w-2xl">
              <DialogHeader>
                <DialogTitle>{interaction.title}</DialogTitle>
              </DialogHeader>
              <DialogDescription className="py-4">{interaction.text}</DialogDescription>
              <ScrollArea className="max-h-96">
                <div className="space-y-2">
                  {menuItems.map((item, index) => (
                    <Button
                      key={index}
                      variant={selectedMenuItem === item ? "default" : "outline"}
                      className="w-full justify-start"
                      onClick={() => setSelectedMenuItem(item)}
                    >
                      {item}
                    </Button>
                  ))}
                </div>
              </ScrollArea>
              <div className="flex justify-end gap-2 mt-4">
                <Button variant="outline" onClick={() => handleInteractionResponse("")} disabled={isResponding}>
                  Cancel
                </Button>
                <Button
                  onClick={() => handleInteractionResponse(selectedMenuItem)}
                  disabled={isResponding || !selectedMenuItem}
                >
                  {isResponding ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Select
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
        <DialogContent className="max-w-4xl max-h-[80vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {status === "running" && <Loader2 className="h-5 w-5 animate-spin" />}
              {status === "completed" && <CheckCircle2 className="h-5 w-5 text-green-500" />}
              {status === "failed" && <XCircle className="h-5 w-5 text-red-500" />}
              {title}
            </DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="border rounded-lg p-4 bg-muted/50">
              <div className="flex items-center gap-2 mb-2">
                <AlertCircle className="h-4 w-4" />
                <span className="text-sm font-medium">Execution Logs</span>
              </div>
              <ScrollArea className="h-64" ref={scrollRef}>
                <div className="space-y-1 font-mono text-xs">
                  {logs.length === 0 ? (
                    <div className="text-muted-foreground">Waiting for logs...</div>
                  ) : (
                    logs.map((log, index) => (
                      <div
                        key={index}
                        className={`${
                          log.type === "error"
                            ? "text-red-500"
                            : log.type === "warning"
                              ? "text-yellow-500"
                              : log.type === "success"
                                ? "text-green-500"
                                : "text-foreground"
                        }`}
                      >
                        <span className="text-muted-foreground">[{log.timestamp}]</span> {log.message}
                      </div>
                    ))
                  )}
                </div>
              </ScrollArea>
            </div>

            <div className="flex items-center justify-between pt-4 border-t">
              <div className="text-sm text-muted-foreground">Session ID: {sessionId}</div>
              {status !== "running" && <Button onClick={onClose}>Close</Button>}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {renderInteractionModal()}
    </>
  )
}
