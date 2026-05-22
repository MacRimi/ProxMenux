"use client"

import { useState, useEffect } from "react"
import { Button } from "./ui/button"
import { Dialog, DialogContent, DialogTitle } from "./ui/dialog"
import { X, Sparkles, Thermometer, Activity, HardDrive, Shield, Globe, Cpu, Zap, Sliders, Wrench, RefreshCw, Server } from "lucide-react"
import { Checkbox } from "./ui/checkbox"

const APP_VERSION = "1.2.1.3-beta" // Sync with AppImage/package.json

interface ReleaseNote {
  date: string
  changes: {
    added?: string[]
    changed?: string[]
    fixed?: string[]
  }
}

export const CHANGELOG: Record<string, ReleaseNote> = {
  "1.2.1.3-beta": {
    date: "May 22, 2026",
    changes: {
      added: [
        "LXC Update Detection - A new dedicated section in Settings (between Health Monitor Thresholds and Notifications) with a single toggle that gates the per-CT apt list --upgradable / apk list -u scan end-to-end. Default ON. When OFF the scan stops entirely (no pct exec calls), every type=lxc entry is purged from the managed-installs registry immediately, and the matching notification toggle in Notifications -> Services disappears from the UI while preserving its stored preference",
        "LXC update checker auto-refresh - The checker now reads the mtime of the CT's package-manager metadata cache and runs apt-get update / apk update from outside via pct exec if it is older than 24h, with a 60s timeout and silent failure. Long-running appliance CTs whose caches were months stale now surface their real upstream backlog (a Debian 12 CT with a 524-day-old cache went from \"0 updates\" to \"117 (12 security)\" on lab hardware)",
      ],
      changed: [
        "AI Enhancement section in Notifications - Rewritten from a muted uppercase row that testers consistently scrolled past, to a normal-case foreground label with a leading Sparkles icon and a persistent badge (green Active when AI is enabled, neutral Optional when it isn't) so the feature is visible regardless of state",
      ],
      fixed: [
        "Terminal modals on HTTPS hosts - Every terminal modal (dashboard terminal, LXC terminal, script terminal) used to fail with WebSocket connection error on hosts with HTTPS enabled. Root cause: the gevent+SSL path stacked geventwebsocket's WebSocketHandler on top of flask-sock's protocol implementation, so the server emitted two consecutive HTTP/1.1 101 Switching Protocols headers and the browser closed the connection as a corrupt frame. Dropping handler_class=WebSocketHandler restores a single 101 response and lets the handshake complete normally",
        "Health Monitor kernel updates on PVE 9.x (#208) - The System Updates -> Kernel/PVE row reported \"Kernel/PVE up to date\" on PVE 9.x hosts even when an update for the running kernel was waiting upstream. Three combined fixes: (a) the kernel-package prefix list now includes proxmox-kernel-* and proxmox-firmware-* (PVE 9.x ships kernels under proxmox-kernel-, not pve-kernel- as in 7.x/8.x), (b) the dry-run switched from apt-get upgrade --dry-run to apt-get dist-upgrade --dry-run so kernel updates packaged as new installs are visible at all, (c) the categoriser now reads uname -r and flags an update as a running-kernel update when the package matches the running release exactly or its branch meta-package (e.g. proxmox-kernel-6.14 for a host on 6.14.11-4-pve). The row text now distinguishes \"Running kernel update available (reboot required)\" from \"N kernel update(s) available (none for running kernel)\"",
      ],
    },
  },
  "1.2.1.2-beta": {
    date: "May 20, 2026",
    changes: {
      added: [
        "Coral TPU installer - Uninstall path mirroring the NVIDIA flow, and registry-driven update notifications for both the PCIe gasket-dkms driver (tracked against feranick/gasket-driver) and the USB libedgetpu1 runtime (tracked via apt)",
        "Disk I/O severity tiers - Sliding 24h window classifies dmesg ATA/SCSI errors into silent (0-10), WARNING (11-100) and CRITICAL (100+ or any hard error like UNC / Buffer I/O / Sense Key Hardware Error), so quiet days stay quiet and a single Buffer I/O event still pages immediately",
        "Quiet Hours buffering - Events suppressed during a channel's quiet window are now persisted to SQLite and released as a grouped summary when the window closes, instead of being silently dropped",
      ],
      changed: [
        "Burst aggregation wording - Burst summaries now report only the additional events that arrived after the initial individual alert, so the operator no longer sees the first event counted twice (\"+N more X in window\" instead of the old \"N X in window\" overlap)",
        "Known-error classifier - Word-boundary regex on ATA/UNC patterns so kernel messages like nvidia_uvm:FatalError are no longer misclassified as ATA cable issues",
        "Health journal context - Excludes proxmenux-monitor.service systemd lines so internal watchdog SIGKILLs no longer leak into the body of unrelated kernel events",
        "Resolved notifications severity - The \"previous severity\" now matches the severity the user actually saw in the notification, not whatever escalated value silently landed in the DB during the 24h same-key cooldown",
        "log2ram apply path - The auto/update flow now restarts log2ram after writing the new size, so a configured 512M actually takes effect on the running tmpfs (previously left at 128M until a manual restart)",
        "VM/CT control errors - Failed start/stop/restart now surfaces the real pvesh stderr (e.g. \"no space left on device\") in the UI toast and fires a vm_fail / ct_fail notification, instead of a bare 500 INTERNAL SERVER ERROR",
        "Mobile design of Quiet Hours / Daily Digest - Time inputs are now full-height with inline labels instead of the cramped grid layout that overflowed on narrow screens",
      ],
      fixed: [
        "ATA disk error not recorded - disk_observations is now written before the SMART gate, so transient errors that don't yet trip SMART still build the per-disk history",
        "Quiet Hours toggle not persisting - get_settings now returns the per-channel quiet_*/digest_* fields so the toggle's state reloads correctly after a refresh",
        "Frontend 401 cascade - Login screen no longer swallows the 401 forever after a brief stale-token state; the dedup flag is cleared on mount and on successful login",
      ],
    },
  },
  "1.2.1.1-beta": {
    date: "May 9, 2026",
    changes: {
      added: [
        "Post-install function update detection - The Monitor now tracks installed ProxMenux optimizations (Log2Ram, Memory Settings, System Limits, Logrotate...) and notifies when a newer version of any of them is available, with one-click apply",
        "Health Monitor Thresholds - Per-category warning and critical levels for CPU, memory, temperature, storage and more, configurable from Settings",
        "NVIDIA driver update notifications - Kernel-aware detection of new compatible driver versions, surfaced in the Hardware tab and as notifications when a newer build is published upstream",
        "Secure Gateway update flow - One-click Tailscale update from Settings with Last-checked / Installed / Latest indicators and notification when a new version is available",
        "Helper-Scripts menu - Richer context and useful information for each entry, making it easier to know what every script does before running it",
      ],
      changed: [
        "Disk temperature monitoring - Improved readings, smarter caching across SMART probes and a redesigned history modal that opens at 24h by default with min/avg/max statistics",
        "VM and LXC modal - Expanded with additional information so a single panel covers the data you previously had to look up across multiple tabs",
        "Page load - Faster first paint and lighter network usage on the Overview, Storage and Hardware tabs",
        "Security improvements - Tighter authentication checks across notification, scripts and terminal endpoints, plus a more conservative default policy for new installs",
      ],
      fixed: [
        "NVIDIA installer - The version menu now respects the running kernel compatibility window, only offering driver branches that won't fail to compile",
        "NVIDIA installer on Alpine LXC - Container-side userspace install reworked so it succeeds on Alpine hosts, and free-space detection works reliably across all storage layouts",
        "NVIDIA installer with NVENC patch - When the host has the NVENC patch applied, the version menu narrows to drivers supported by the patch so reinstalling never silently loses it",
        "Webhook URL - PVE notification webhook now follows the active SSL state automatically, switching between http and https when you toggle HTTPS in the panel",
      ],
    },
  },
  "1.1.2-beta": {
    date: "March 18, 2026",
    changes: {
      added: [
        "Temperature & Latency Charts - Real-time visual monitoring with interactive graphs",
        "WebSocket Terminal - Direct access to Proxmox host and LXC containers terminal",
        "AI-Enhanced Notifications - Intelligent message formatting with multi-provider support (OpenAI, Groq, Anthropic, Ollama)",
        "Security Section - Comprehensive security settings for ProxMenux and Proxmox",
        "VPN Integration - Easy Tailscale VPN installation and configuration",
        "GPU Scripts - Installation utilities for Intel, AMD and NVIDIA drivers",
        "Disk Observations System - Track and document disk health observations over time",
        "Enhanced Health Monitor - Configurable monitoring with advanced settings panel",
      ],
      changed: [
        "Improved overall performance with optimized data fetching",
        "Notifications now support rich formatting with contextual emojis",
        "Health monitor now configurable from Settings section",
        "Better Proxmox service name translation for non-expert users",
      ],
      fixed: [
        "Fixed notification message truncation for large backup reports",
        "Improved disk error deduplication to prevent repeated alerts",
        "Corrected AI provider base URL handling for OpenAI-compatible APIs",
      ],
    },
  },
  "1.0.1": {
    date: "November 11, 2025",
    changes: {
      added: [
        "Proxy Support - Access ProxMenux through reverse proxies with full functionality",
        "Authentication System - Secure your dashboard with password protection",
        "PCIe Link Speed Detection - View NVMe drive connection speeds and detect performance issues",
        "Two-Factor Authentication (2FA) - Enhanced security with TOTP support",
        "Health Monitoring System - Comprehensive system health checks with dismissible warnings",
      ],
      changed: [
        "Optimized VM & LXC page - Reduced CPU usage by 85% through intelligent caching",
        "Storage metrics now separate local and remote storage for clarity",
      ],
      fixed: [
        "Fixed dark mode text contrast issues in various components",
        "Corrected storage calculation discrepancies between Overview and Storage pages",
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
    icon: <RefreshCw className="h-5 w-5" />,
    text: "Post-install function update detection - The Monitor tracks installed ProxMenux optimizations and notifies when a newer version of any of them is available, with one-click apply",
  },
  {
    icon: <Sliders className="h-5 w-5" />,
    text: "Health Monitor Thresholds - Per-category warning and critical levels for CPU, memory, temperature, storage and more, fully configurable from Settings",
  },
  {
    icon: <Cpu className="h-5 w-5" />,
    text: "NVIDIA driver update notifications - Kernel-aware detection of new compatible driver versions, surfaced in the Hardware tab and as notifications when a newer build is published",
  },
  {
    icon: <Globe className="h-5 w-5" />,
    text: "Secure Gateway update flow - One-click Tailscale update from Settings, with version indicators and notification when a new release is available",
  },
  {
    icon: <Wrench className="h-5 w-5" />,
    text: "Helper-Scripts menu - Richer context and useful information for each entry, so you know what every script does before running it",
  },
  {
    icon: <Thermometer className="h-5 w-5" />,
    text: "Improved disk temperature monitoring - Better readings, smarter caching across SMART probes and a redesigned history modal that opens at 24h by default",
  },
  {
    icon: <Server className="h-5 w-5" />,
    text: "VM and LXC modal expanded - Additional information consolidated into a single panel so you don't have to look it up across multiple tabs",
  },
  {
    icon: <Zap className="h-5 w-5" />,
    text: "Faster page load and tighter security - Lighter network usage on the main tabs, plus stricter authentication checks across notification, scripts and terminal endpoints",
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
      <DialogContent className="max-w-2xl max-h-[85vh] p-0 gap-0 border-0 bg-transparent">
        <DialogTitle className="sr-only">Release Notes - Version {APP_VERSION}</DialogTitle>
        <div className="relative bg-card rounded-lg shadow-2xl h-full flex flex-col max-h-[85vh]">
          <Button
            variant="ghost"
            size="icon"
            className="absolute top-4 right-4 z-50 h-8 w-8 rounded-full bg-background/80 backdrop-blur-sm hover:bg-background"
            onClick={handleClose}
          >
            <X className="h-4 w-4" />
          </Button>

          <div className="relative h-32 md:h-40 bg-gradient-to-br from-amber-500 via-orange-500 to-red-500 flex items-center justify-center overflow-hidden flex-shrink-0">
            <div className="absolute inset-0 bg-black/10" />
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_120%,rgba(255,255,255,0.1),transparent)]" />

            <div className="relative z-10 text-white animate-pulse">
              <Sparkles className="h-12 w-12 md:h-14 md:w-14" />
            </div>

            <div className="absolute top-10 left-10 w-20 h-20 bg-white/10 rounded-full blur-2xl" />
            <div className="absolute bottom-10 right-10 w-32 h-32 bg-white/10 rounded-full blur-3xl" />
          </div>

          <div className="flex-1 overflow-y-auto p-6 md:p-8 space-y-4 md:space-y-6 min-h-0">
            <div className="space-y-2">
              <h2 className="text-xl md:text-2xl font-bold text-foreground text-balance">
                What's New in Version {APP_VERSION}
              </h2>
              <p className="text-sm text-muted-foreground leading-relaxed">
                We've added exciting new features and improvements to make ProxMenux Monitor even better!
              </p>
            </div>

            <div className="space-y-2">
              {CURRENT_VERSION_FEATURES.map((feature, index) => (
                <div
                  key={index}
                  className="flex items-start gap-2 md:gap-3 p-3 rounded-lg bg-muted/50 border border-border/50 hover:bg-muted/70 transition-colors"
                >
                  <div className="text-orange-500 mt-0.5 flex-shrink-0">{feature.icon}</div>
                  <p className="text-xs md:text-sm text-foreground leading-relaxed">{feature.text}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="flex-shrink-0 p-6 md:p-8 pt-4 border-t border-border/50 bg-card">
            <div className="flex flex-col gap-3">
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
