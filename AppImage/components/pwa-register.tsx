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
// ===========================================================
export function PwaRegister() {
  useEffect(() => {
    if (typeof window === "undefined") return
    if (!("serviceWorker" in navigator)) return
    // Wait for the load event to avoid competing with the
    // initial render — the SW registration is not on the
    // critical render path.
    const register = () => {
      navigator.serviceWorker
        .register("/sw.js", { scope: "/" })
        .catch((err) => {
          // Surface the failure only in DevTools — silent in prod.
          console.warn("[pwa] service worker registration failed:", err)
        })
    }
    if (document.readyState === "complete") {
      register()
    } else {
      window.addEventListener("load", register, { once: true })
      return () => window.removeEventListener("load", register)
    }
  }, [])
  return null
}
