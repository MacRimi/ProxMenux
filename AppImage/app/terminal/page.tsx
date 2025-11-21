import dynamic from "next/dynamic"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { TerminalIcon } from "lucide-react"

const TerminalPanel = dynamic(() => import("@/components/terminal-panel").then((mod) => mod.TerminalPanel), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full">
      <div className="text-muted-foreground">Loading terminal...</div>
    </div>
  ),
})

export default function TerminalPage() {
  return (
    <div className="min-h-screen bg-background p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex items-center gap-3">
          <TerminalIcon className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-3xl font-bold">System Terminal</h1>
            <p className="text-muted-foreground">Execute commands and manage your Proxmox system</p>
          </div>
        </div>

        <Card className="h-[calc(100vh-200px)]">
          <CardHeader>
            <CardTitle>Interactive Shell</CardTitle>
            <CardDescription>
              Full bash terminal with support for all system commands. Use touch gestures or keyboard shortcuts.
            </CardDescription>
          </CardHeader>
          <CardContent className="h-[calc(100%-80px)]">
            <TerminalPanel />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
