"use client"

import { useEffect } from "react"

// ===========================================================
// PwaRegister
// ===========================================================
// Registers /sw.js once on mount. Chrome (Android) only
// surfaces the "Install app" prompt when a service worker
// is active, so even though the SW itself does nothing
// (network-only, no caching), its mere presence flips the
// PWA-installability check from no-to-yes.
//
// Mounted from app/layout.tsx so it runs on every route.
//
// On every `visibilitychange` back to visible we call
// `registration.update()`. Mobile browsers (Brave / Firefox
// Android/iOS) are aggressive about deferring the SW's
// scheduled 24h `sw.js` re-check to save battery, which
// stranded users on the pre-v2 SW after the Cache Storage
// fix shipped — they saw the dashboard freeze until they
// force-stopped the browser. Forcing an `update()` on every
// return-to-foreground brings the SW check inline with
// user attention so future SW_VERSION bumps propagate at
// the first regreso a la pestaña instead of hours later.
// ===========================================================
export function PwaRegister() {
  useEffect(() => {
    if (typeof window === "undefined") return
    if (!("serviceWorker" in navigator)) return

    let registration: ServiceWorkerRegistration | null = null

    const register = () => {
      navigator.serviceWorker
        .register("/sw.js", { scope: "/" })
        .then((reg) => {
          registration = reg
        })
        .catch((err) => {
          // Surface the failure only in DevTools — silent in prod.
          console.warn("[pwa] service worker registration failed:", err)
        })
    }

    const onVisible = () => {
      if (document.visibilityState !== "visible") return
      // Prefer the captured registration from the initial register()
      // call; fall back to `getRegistration()` in case that promise
      // hadn't resolved yet on the first visibility change.
      if (registration) {
        registration.update().catch(() => {})
      } else {
        navigator.serviceWorker
          .getRegistration()
          .then((reg) => reg?.update().catch(() => {}))
          .catch(() => {})
      }
    }

    if (document.readyState === "complete") {
      register()
    } else {
      window.addEventListener("load", register, { once: true })
    }

    document.addEventListener("visibilitychange", onVisible)

    return () => {
      window.removeEventListener("load", register)
      document.removeEventListener("visibilitychange", onVisible)
    }
  }, [])
  return null
}
