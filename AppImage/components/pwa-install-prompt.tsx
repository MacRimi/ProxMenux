"use client"

import { useCallback, useEffect, useState } from "react"
import { Download, Plus, Share, X } from "lucide-react"

// ==========================================================
// PwaInstallPrompt
// ==========================================================
// Bottom-sheet shown on mobile when the Monitor is opened in
// a browser (not launched as an installed PWA). Two variants:
//   iOS Safari  → manual 3-step instructions (no browser API)
//   Android     → native install prompt when the browser
//                 fires `beforeinstallprompt` (Chromium 89+
//                 delivers it based on manifest validity alone,
//                 no Service Worker required), with the manual
//                 "browser menu → Add to Home Screen" steps
//                 always shown below as a fallback.
//
// Dismissal options:
//   "Not now"          → temporary, hidden for 30 days
//   "Don't show again" → permanent (no expiry)
//   Backdrop / X       → session-only dismiss (reappears on
//                        the next page load)
// ==========================================================

const DISMISSED_FOREVER_KEY = "proxmenux-install-dismissed"
const DISMISSED_UNTIL_KEY = "proxmenux-install-dismissed-until"
const NOT_NOW_DAYS = 30

// `BeforeInstallPromptEvent` isn't in the TS DOM lib yet.
interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[]
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>
  prompt(): Promise<void>
}

function isMobileDevice(): boolean {
  if (typeof window === "undefined") return false
  // Prefer feature detection (coarse pointer + touch) over UA sniffing,
  // and fall back to UA for the corner case where a mobile browser
  // reports fine pointer under a desktop-mode toggle.
  const coarse = window.matchMedia("(pointer: coarse)").matches
  const ua = navigator.userAgent
  const uaMobile = /Android|iPhone|iPad|iPod|Mobile|Opera Mini|BlackBerry|IEMobile/i.test(ua)
  return coarse || uaMobile
}

function isStandalone(): boolean {
  if (typeof window === "undefined") return false
  const displayModeStandalone = window.matchMedia("(display-mode: standalone)").matches
  const iosStandalone = (window.navigator as Navigator & { standalone?: boolean }).standalone === true
  return displayModeStandalone || iosStandalone
}

function isIOS(): boolean {
  if (typeof window === "undefined") return false
  const ua = navigator.userAgent
  // iPadOS 13+ reports as MacIntel — detect that too when maxTouchPoints > 1.
  const iPadMasqueradingAsMac =
    ua.includes("Macintosh") && (navigator as Navigator & { maxTouchPoints?: number }).maxTouchPoints! > 1
  return /iPhone|iPad|iPod/i.test(ua) || iPadMasqueradingAsMac
}

export function PwaInstallPrompt() {
  const [open, setOpen] = useState(false)
  const [platform, setPlatform] = useState<"ios" | "android" | null>(null)
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null)

  useEffect(() => {
    if (typeof window === "undefined") return
    if (!isMobileDevice() || isStandalone()) return

    try {
      if (localStorage.getItem(DISMISSED_FOREVER_KEY) === "1") return
      const untilRaw = localStorage.getItem(DISMISSED_UNTIL_KEY)
      if (untilRaw) {
        const until = Number.parseInt(untilRaw, 10)
        // Corrupt / non-numeric values fall through and the prompt shows,
        // which is the safe default.
        if (Number.isFinite(until) && until > Date.now()) return
      }
    } catch {
      // localStorage unavailable (private mode etc.) — treat as not dismissed.
    }

    setPlatform(isIOS() ? "ios" : "android")
    setOpen(true)
  }, [])

  useEffect(() => {
    if (typeof window === "undefined") return
    const onBeforeInstall = (e: Event) => {
      // Suppress the browser's own mini-infobar so the Install button
      // in the bottom sheet is the primary path.
      e.preventDefault()
      setDeferredPrompt(e as BeforeInstallPromptEvent)
    }
    const onInstalled = () => {
      // The browser confirms the install landed on the home screen —
      // close the sheet and drop the deferred event.
      setDeferredPrompt(null)
      setOpen(false)
    }
    window.addEventListener("beforeinstallprompt", onBeforeInstall)
    window.addEventListener("appinstalled", onInstalled)
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall)
      window.removeEventListener("appinstalled", onInstalled)
    }
  }, [])

  const handleNotNow = useCallback(() => {
    try {
      const until = Date.now() + NOT_NOW_DAYS * 24 * 60 * 60 * 1000
      localStorage.setItem(DISMISSED_UNTIL_KEY, String(until))
    } catch {
      // Best-effort; if localStorage fails the user will see the prompt
      // again next visit, which is the safe default.
    }
    setOpen(false)
  }, [])

  const handleNeverAgain = useCallback(() => {
    try {
      localStorage.setItem(DISMISSED_FOREVER_KEY, "1")
    } catch {
      // Best-effort; if localStorage fails the user will see the prompt
      // again next visit, which is the safe default.
    }
    setOpen(false)
  }, [])

  const handleClose = useCallback(() => {
    // Session-only dismiss: closing via X or backdrop does NOT persist,
    // so the prompt reappears on the next page load. Users who want to
    // silence it for longer must use "Not now" (30 d) or "Don't show again".
    setOpen(false)
  }, [])

  const handleInstall = useCallback(async () => {
    if (!deferredPrompt) return
    try {
      await deferredPrompt.prompt()
      const { outcome } = await deferredPrompt.userChoice
      // A `beforeinstallprompt` event can only be used once; drop the
      // reference either way so the button hides.
      setDeferredPrompt(null)
      if (outcome === "accepted") {
        setOpen(false)
      }
    } catch {
      // Browser refused to run the prompt (already handled, race with
      // appinstalled, etc.) — leave the sheet open so the operator can
      // fall back to the manual steps rendered below.
      setDeferredPrompt(null)
    }
  }, [deferredPrompt])

  if (!open || !platform) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="pwa-install-title"
      className="fixed inset-0 z-[100] flex items-end justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose()
      }}
    >
      <div
        className="w-full max-w-md rounded-t-2xl bg-background text-foreground shadow-2xl border-t border-border animate-in slide-in-from-bottom duration-300"
        style={{ paddingBottom: "max(1.25rem, env(safe-area-inset-bottom))" }}
      >
        <div className="relative px-5 pt-5">
          <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-border" aria-hidden="true" />
          <button
            type="button"
            onClick={handleClose}
            aria-label="Close"
            className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground hover:bg-muted transition-colors"
          >
            <X className="h-4 w-4" />
          </button>

          <div className="mb-4 flex items-start gap-3.5">
            <div className="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-xl bg-muted p-1 shadow-md">
              <img src="/icon.svg" alt="ProxMenux Monitor" className="h-full w-full object-contain" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 id="pwa-install-title" className="text-[17px] font-bold leading-tight tracking-tight text-foreground">
                Install ProxMenux Monitor
              </h3>
              <p className="mt-1 text-[13px] leading-snug text-muted-foreground">
                {platform === "ios"
                  ? "Add the Monitor to your home screen for quick access."
                  : "Add the Monitor as an app to launch it like a native application."}
              </p>
            </div>
          </div>

          {platform === "ios" ? (
            <ol className="mb-4 flex flex-col gap-2" role="list">
              <li className="flex items-center gap-3 rounded-xl bg-primary/10 px-3.5 py-3 text-[13.5px] leading-tight">
                <span className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-bold text-primary-foreground">
                  1
                </span>
                <span>
                  Tap the{" "}
                  <span className="inline-flex items-center gap-1 font-semibold text-primary">
                    <Share className="h-4 w-4" aria-hidden="true" />
                    Share
                  </span>{" "}
                  button in the bottom bar
                </span>
              </li>
              <li className="flex items-center gap-3 rounded-xl bg-primary/10 px-3.5 py-3 text-[13.5px] leading-tight">
                <span className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-bold text-primary-foreground">
                  2
                </span>
                <span>
                  Choose{" "}
                  <span className="inline-flex items-center gap-1 font-semibold text-primary">
                    <Plus className="h-4 w-4" aria-hidden="true" />
                    Add to Home Screen
                  </span>
                </span>
              </li>
              <li className="flex items-center gap-3 rounded-xl bg-primary/10 px-3.5 py-3 text-[13.5px] leading-tight">
                <span className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-bold text-primary-foreground">
                  3
                </span>
                <span>
                  Confirm by tapping <b>Add</b> in the top-right
                </span>
              </li>
            </ol>
          ) : (
            <>
              {deferredPrompt && (
                <button
                  type="button"
                  onClick={handleInstall}
                  className="mb-3 flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 text-[14px] font-semibold text-primary-foreground shadow-sm hover:opacity-90 active:opacity-80 transition-opacity"
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  Install
                </button>
              )}
              <div className="mb-4 rounded-lg border border-border bg-muted/50 px-3.5 py-3 text-[13px] leading-relaxed text-muted-foreground">
                {deferredPrompt ? (
                  <>
                    Or install manually: browser menu <b className="text-foreground">⋮</b> →{" "}
                    <b className="text-foreground">Add to Home Screen</b> → confirm by tapping{" "}
                    <b className="text-foreground">Install</b>.
                  </>
                ) : (
                  <>
                    Open the browser menu <b className="text-foreground">⋮</b> →{" "}
                    <b className="text-foreground">Add to Home Screen</b> → confirm by tapping{" "}
                    <b className="text-foreground">Install</b>.
                  </>
                )}
              </div>
            </>
          )}

          <div className="mt-1 flex flex-col gap-1 border-t border-border pt-3">
            <button
              type="button"
              onClick={handleNotNow}
              className="rounded-lg py-2.5 text-center text-[13.5px] font-semibold text-muted-foreground hover:bg-muted transition-colors"
            >
              Not now
            </button>
            <button
              type="button"
              onClick={handleNeverAgain}
              className="rounded-lg py-2.5 text-center text-[13.5px] font-semibold text-amber-700 dark:text-amber-500 hover:bg-muted transition-colors"
            >
              Don&apos;t show again
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
