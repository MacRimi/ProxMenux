"use client"

import { useState, useEffect } from "react"
import { Button } from "./ui/button"
import { Dialog, DialogContent } from "./ui/dialog"
import { X, Sparkles, Link2, Shield, Zap, HardDrive, Gauge, Wrench, Settings } from "lucide-react"
import { Checkbox } from "./ui/checkbox"

const APP_VERSION = "1.0.1" // Sync with AppImage/package.json

interface ReleaseNote {
  date: string
  changes: {
    added?: string[]
    changed?: string[]
    fixed?: string[]
  }
}

export const CHANGELOG: Record<string, ReleaseNote> = {
  "1.0.1": {
    date: "November 11, 2025",
    changes: {
      added: [
        "Proxy Support - Access ProxMenux through reverse proxies with full functionality",
        "Authentication System - Secure your dashboard with password protection",
        "PCIe Link Speed Detection - View NVMe drive connection speeds and detect performance issues",
        "Enhanced Storage Display - Better formatting for disk sizes (auto-converts GB to TB when needed)",
        "SATA/SAS Information - View detailed interface information for all storage devices",
        "Two-Factor Authentication (2FA) - Enhanced security with TOTP support",
        "Health Monitoring System - Comprehensive system health checks with dismissible warnings",
        "Release Notes Modal - Automatic notification of new features and improvements",
      ],
      changed: [
        "Optimized VM & LXC page - Reduced CPU usage by 85% through intelligent caching",
        "Storage metrics now separate local and remote storage for clarity",
        "Update warnings now appear only after 365 days instead of 30 days",
        "API intervals staggered to distribute server load (23s and 37s)",
      ],
      fixed: [
        "Fixed dark mode text contrast issues in various components",
        "Corrected storage calculation discrepancies between Overview and Storage pages",
        "Resolved JSON stringify error in VM control actions",
        "Improved IP address fetching for LXC containers",
      ],
    },
  },
  "1.0.0": {
    date: "October 15, 2025",
    changes: {
      added: [
        "Initial release of ProxMenux Monitor",
        "Real-time system monitoring dashboard",
        "Storage management with SMART health monitoring",
        "Network metrics and bandwidth tracking",
        "VM & LXC container management",
        "Hardware information display",
        "System logs viewer with filtering",
      ],
    },
  },
}

const CURRENT_VERSION_FEATURES = [
  {
    icon: <Link2 className="h-5 w-5" />,
    text: "Proxy Support - Access ProxMenux through reverse proxies with full functionality",
  },
  {
    icon: <Shield className="h-5 w-5" />,
    text: "Two-Factor Authentication (2FA) - Enhanced security with TOTP support for login protection",
  },
  {
    icon: <Zap className="h-5 w-5" />,
    text: "Performance Improvements - Optimized loading times and reduced CPU usage by 85%",
  },
  {
    icon: <HardDrive className="h-5 w-5" />,
    text: "Storage Enhancements - Improved disk space consumption display with local and remote storage separation",
  },
  {
    icon: <Gauge className="h-5 w-5" />,
    text: "PCIe Link Speed Detection - View NVMe drive connection speeds and identify performance bottlenecks",
  },
  {
    icon: <Wrench className="h-5 w-5" />,
    text: "Hardware Page Improvements - Enhanced hardware information display with detailed PCIe and interface data",
  },
  {
    icon: <Settings className="h-5 w-5" />,
    text: "New Settings Page - Centralized configuration for authentication, optimizations, and system preferences",
  },
]

interface ReleaseNotesModalProps {
  open: boolean
  onClose: () => void
}

export function ReleaseNotesModal({ open, onClose }: ReleaseNotesModalProps) {
  const [dontShowAgain, setDontShowAgain] = useState(false)

  const handleClose = () => {
    if (dontShowAgain) {
      localStorage.setItem("proxmenux-last-seen-version", APP_VERSION)
    }
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-3xl p-0 gap-0 overflow-hidden border-0 bg-transparent">
        <div className="relative bg-card rounded-lg overflow-hidden shadow-2xl">
          <Button
            variant="ghost"
            size="icon"
            className="absolute top-4 right-4 z-50 h-8 w-8 rounded-full bg-background/80 backdrop-blur-sm hover:bg-background"
            onClick={handleClose}
          >
            <X className="h-4 w-4" />
          </Button>

          <div className="relative h-48 md:h-56 bg-gradient-to-br from-amber-500 via-orange-500 to-red-500 flex items-center justify-center overflow-hidden">
            <div className="absolute inset-0 bg-black/10" />
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_120%,rgba(255,255,255,0.1),transparent)]" />

            <div className="relative z-10 text-white animate-pulse">
              <Sparkles className="h-16 w-16" />
            </div>

            <div className="absolute top-10 left-10 w-20 h-20 bg-white/10 rounded-full blur-2xl" />
            <div className="absolute bottom-10 right-10 w-32 h-32 bg-white/10 rounded-full blur-3xl" />
          </div>

          <div className="p-6 md:p-8 space-y-4 md:space-y-6 max-h-[60vh] md:max-h-none overflow-y-auto">
            <div className="space-y-2">
              <h2 className="text-2xl md:text-3xl font-bold text-foreground text-balance">
                What's New in Version {APP_VERSION}
              </h2>
              <p className="text-sm md:text-base text-muted-foreground leading-relaxed">
                We've added exciting new features and improvements to make ProxMenux Monitor even better!
              </p>
            </div>

            <div className="space-y-2 md:space-y-3">
              {CURRENT_VERSION_FEATURES.map((feature, index) => (
                <div
                  key={index}
                  className="flex items-start gap-2 md:gap-3 p-3 md:p-4 rounded-lg bg-muted/50 border border-border/50 hover:bg-muted/70 transition-colors"
                >
                  <div className="text-orange-500 mt-0.5 flex-shrink-0">{feature.icon}</div>
                  <p className="text-xs md:text-sm text-foreground leading-relaxed">{feature.text}</p>
                </div>
              ))}
            </div>

            <div className="flex flex-col gap-3 pt-4">
              <Button
                onClick={handleClose}
                className="w-full bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600"
              >
                <Sparkles className="h-4 w-4 mr-2" />
                Got it!
              </Button>

              <div className="flex items-center justify-center gap-2">
                <Checkbox
                  id="dont-show-version-again"
                  checked={dontShowAgain}
                  onCheckedChange={(checked) => setDontShowAgain(checked as boolean)}
                />
                <label
                  htmlFor="dont-show-version-again"
                  className="text-xs md:text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer select-none"
                >
                  Don't show again for this version
                </label>
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function useVersionCheck() {
  const [showReleaseNotes, setShowReleaseNotes] = useState(false)

  useEffect(() => {
    const lastSeenVersion = localStorage.getItem("proxmenux-last-seen-version")

    if (lastSeenVersion !== APP_VERSION) {
      setShowReleaseNotes(true)
    }
  }, [])

  return { showReleaseNotes, setShowReleaseNotes }
}

export { APP_VERSION }
