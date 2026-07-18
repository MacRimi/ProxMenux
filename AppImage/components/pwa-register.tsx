"use client"

import { useEffect } from "react"

// Unregisters any Service Worker registered against this origin on
// mount. Having a SW active on the Monitor origin caused a mobile
// dashboard-freeze bug over HTTPS + reverse proxy (setInterval polls
// stopped firing real fetches under battery throttling). Confirmed
// as the sole cause by the affected reporter on Brave and Firefox
// Android. `sw.js` is kept in the tree so PWA offline support can
// be revisited later without archaeology.
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
      .catch(() => {
        // Best-effort — private browsing or a locked-down browser
        // may reject the API; nothing to do.
      })
  }, [])
  return null
}
