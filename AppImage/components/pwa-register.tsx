"use client"

import { useEffect } from "react"

// Unregister any Service Worker on this origin at mount. A SW here
// interacts badly with mobile battery throttling behind reverse
// proxies. `sw.js` is kept for a future PWA-offline revisit.
export function PwaRegister() {
  useEffect(() => {
    if (typeof window === "undefined") return
    if (!("serviceWorker" in navigator)) return
    navigator.serviceWorker
      .getRegistrations()
      .then((regs) => {
        if (regs.length === 0) return
        return Promise.all(regs.map((r) => r.unregister()))
      })
      .catch(() => {})
  }, [])
  return null
}
