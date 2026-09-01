// Deterministic OKLCH colouring for category badges. Shared between
// the Apps dashboard and the LXC App tab so both surfaces show the
// exact same colour for a given category name.
//
// Hue exclusions
// --------------
// Two bands are skipped because their meaning is already reserved by
// the rest of the Monitor and a chip in those hues on the same view
// would be visually confusing:
//   * 260–319°  purple/violet — "update available" (ArrowUpCircle)
//   * 340–19°   red           — error / danger signal
// Green and yellow ARE used elsewhere for health status, but only as
// tiny dots in other views — a chip in those hues on an app card
// carries no false meaning, so they stay in the allowed range.
//
// Allowed ranges after the exclusions:
//   [20, 260) ∪ [320, 340)  = 240° + 20° = 260° of usable hues.

import { useEffect, useState } from "react"

export function hueForCategory(text: string): number {
  let hash = 5381
  for (let i = 0; i < text.length; i++) {
    hash = ((hash << 5) + hash + text.charCodeAt(i)) | 0
  }
  const raw = Math.abs(hash) % 260
  if (raw < 240) return 20 + raw          // 0-239 → 20-259 (orange..blue)
  return 320 + (raw - 240)                // 240-259 → 320-339 (pink/magenta)
}

// OKLCH is perceptually uniform — L=0.80 looks equally bright for a
// blue and a yellow. HSL fails this because eyes weight green/yellow
// more, so the same L% renders visually darker for blues.
export function categoryChipStyle(text: string, isLight: boolean): {
  backgroundColor: string
  color: string
  borderColor: string
} {
  const h = hueForCategory(text)
  if (isLight) {
    return {
      backgroundColor: `oklch(0.55 0.20 ${h} / 0.14)`,
      color: `oklch(0.42 0.19 ${h})`,
      borderColor: `oklch(0.55 0.20 ${h} / 0.5)`,
    }
  }
  return {
    backgroundColor: `oklch(0.60 0.16 ${h} / 0.18)`,
    color: `oklch(0.80 0.16 ${h})`,
    borderColor: `oklch(0.60 0.16 ${h} / 0.55)`,
  }
}

// Read the effective theme from next-themes' hooks on <html>:
// `class="dark|light"` (Tailwind class strategy) or `data-theme`.
// Falls back to the OS setting when the user hasn't chosen one.
export function readIsLightTheme(): boolean {
  if (typeof window === "undefined" || typeof document === "undefined") return false
  const el = document.documentElement
  if (el.classList.contains("dark")) return false
  if (el.classList.contains("light")) return true
  const attr = el.getAttribute("data-theme")
  if (attr === "light") return true
  if (attr === "dark") return false
  return window.matchMedia("(prefers-color-scheme: light)").matches
}

// React hook — recomputes when the user toggles theme or the OS pref
// flips. Watches <html>'s attributes (data-theme + class) and the
// system media query. Used by any component that renders category
// chips so they stay legible after a theme change.
export function useIsLightTheme(): boolean {
  const [isLight, setIsLight] = useState<boolean>(false)
  useEffect(() => {
    const update = () => setIsLight(readIsLightTheme())
    update()
    const mq = window.matchMedia("(prefers-color-scheme: light)")
    const observer = new MutationObserver(update)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "class"],
    })
    mq.addEventListener("change", update)
    return () => { observer.disconnect(); mq.removeEventListener("change", update) }
  }, [])
  return isLight
}
