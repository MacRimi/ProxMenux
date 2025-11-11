"use client"

import { useEffect, useState } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog"
import { Button } from "./ui/button"
import { ScrollArea } from "./ui/scroll-area"
import { Badge } from "./ui/badge"
import { Sparkles } from "lucide-react"

const APP_VERSION = "1.0.1" // Sync with package.json

const CHANGELOG = {
  "1.0.1": {
    date: "2025-02-11",
    changes: {
      added: [
        "Automatic support for reverse proxies",
        "New api-config.ts utility for automatic proxy configuration detection",
        "Complete proxy configuration documentation",
        "Configuration examples for Nginx, Caddy, Apache, Traefik, and Nginx Proxy Manager",
      ],
      changed: [
        "Refactored API call system to use relative URLs when a proxy is detected",
        "All components now use the new getApiUrl() utility for URL construction",
        "Improved Flask server connection detection",
      ],
      fixed: [
        "Issue where charts and metrics wouldn't load when accessed through a reverse proxy",
        "Hardcoded URLs to port 8008 causing connection errors behind proxies",
      ],
    },
  },
  "1.0.0": {
    date: "2025-02-01",
    changes: {
      added: [
        "Complete monitoring dashboard for Proxmox",
        "Real-time metrics for CPU, memory, network, and storage",
        "VM and LXC container management",
        "Detailed hardware information",
        "System logs viewer",
        "Light/dark theme support",
        "Responsive design",
      ],
    },
  },
}

interface ReleaseNotesModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ReleaseNotesModal({ open, onOpenChange }: ReleaseNotesModalProps) {
  const currentVersion = CHANGELOG[APP_VERSION as keyof typeof CHANGELOG]

  const handleDontShowAgain = () => {
    localStorage.setItem("proxmenux-last-seen-version", APP_VERSION)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh]">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-blue-500" />
            <DialogTitle>What's New in v{APP_VERSION}</DialogTitle>
          </div>
        </DialogHeader>

        <ScrollArea className="max-h-[60vh] pr-4">
          {currentVersion && (
            <div className="space-y-4">
              <div className="text-sm text-muted-foreground">Released on {currentVersion.date}</div>

              {currentVersion.changes.added && (
                <div>
                  <Badge variant="default" className="mb-2">
                    Added
                  </Badge>
                  <ul className="list-disc list-inside space-y-1 text-sm">
                    {currentVersion.changes.added.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              {currentVersion.changes.changed && (
                <div>
                  <Badge variant="secondary" className="mb-2">
                    Changed
                  </Badge>
                  <ul className="list-disc list-inside space-y-1 text-sm">
                    {currentVersion.changes.changed.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              {currentVersion.changes.fixed && (
                <div>
                  <Badge variant="outline" className="mb-2">
                    Fixed
                  </Badge>
                  <ul className="list-disc list-inside space-y-1 text-sm">
                    {currentVersion.changes.fixed.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        <div className="flex justify-between items-center pt-4 border-t">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button onClick={handleDontShowAgain}>Don't show again for this version</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

// Hook to detect version changes
export function useVersionCheck() {
  const [showReleaseNotes, setShowReleaseNotes] = useState(false)

  useEffect(() => {
    const lastSeenVersion = localStorage.getItem("proxmenux-last-seen-version")

    // Show release notes if:
    // 1. User has never seen any version
    // 2. Current version is different from last seen
    if (!lastSeenVersion || lastSeenVersion !== APP_VERSION) {
      setShowReleaseNotes(true)
    }
  }, [])

  return { showReleaseNotes, setShowReleaseNotes }
}

// Export version and changelog for Settings page
export { APP_VERSION, CHANGELOG }
