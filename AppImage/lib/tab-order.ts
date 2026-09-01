import { useEffect, useState, useCallback } from "react"

// Persistent top-level tab order for the Monitor dashboard.
//
// Only the seven top-level slots are user-orderable; the internal
// items of the Node and Admin dropdowns keep their canonical order —
// grouped items move as a single unit.

export type TabId = "overview" | "apps" | "vms" | "node" | "backup" | "terminal" | "admin"

export const DEFAULT_TAB_ORDER: TabId[] = [
  "overview",
  "apps",
  "vms",
  "node",
  "backup",
  "terminal",
  "admin",
]

const STORAGE_KEY = "proxmenux-nav-order"
const CHANGE_EVENT = "proxmenux-nav-order-changed"

function isTabId(v: unknown): v is TabId {
  return typeof v === "string" && (DEFAULT_TAB_ORDER as string[]).includes(v)
}

// Read + normalise: unknown ids are dropped, missing ones are
// appended in their default position so a future release adding a
// new tab still surfaces it for users with a stored order.
export function readTabOrder(): TabId[] {
  if (typeof window === "undefined") return DEFAULT_TAB_ORDER
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_TAB_ORDER
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return DEFAULT_TAB_ORDER
    const seen = new Set<TabId>()
    const clean: TabId[] = []
    for (const item of parsed) {
      if (isTabId(item) && !seen.has(item)) {
        clean.push(item)
        seen.add(item)
      }
    }
    for (const id of DEFAULT_TAB_ORDER) {
      if (!seen.has(id)) clean.push(id)
    }
    return clean
  } catch {
    return DEFAULT_TAB_ORDER
  }
}

export function writeTabOrder(order: TabId[]): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(order))
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT))
  } catch {
    // Storage full / disabled — the in-memory state still updates.
  }
}

// Map a top-level slot id to the concrete `activeTab` value the
// Tabs component uses. Direct tabs pass through; grouped slots
// (Node/Admin) resolve to the first child in the dropdown so the
// dashboard lands on a real tab, not a group header.
const GROUP_FIRST_CHILD: Record<TabId, string> = {
  overview: "overview",
  apps:     "apps",
  vms:      "vms",
  node:     "storage",
  backup:   "backup",
  terminal: "terminal",
  admin:    "logs",
}

export function firstActualTab(order: TabId[] = readTabOrder()): string {
  const head = order[0]
  return (head && GROUP_FIRST_CHILD[head]) || "overview"
}

export function resetTabOrder(): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.removeItem(STORAGE_KEY)
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT))
  } catch {
    // ignore
  }
}

// Hook that keeps every consumer in sync. Firing a custom event on
// write means the Settings card and the top navigation update in the
// same tick without prop-drilling.
export function useTabOrder(): {
  order: TabId[]
  setOrder: (next: TabId[]) => void
  reset: () => void
  isCustom: boolean
} {
  const [order, setOrderState] = useState<TabId[]>(DEFAULT_TAB_ORDER)

  useEffect(() => {
    setOrderState(readTabOrder())
    const onChange = () => setOrderState(readTabOrder())
    window.addEventListener(CHANGE_EVENT, onChange)
    window.addEventListener("storage", (e) => {
      if (e.key === STORAGE_KEY) onChange()
    })
    return () => {
      window.removeEventListener(CHANGE_EVENT, onChange)
    }
  }, [])

  const setOrder = useCallback((next: TabId[]) => {
    writeTabOrder(next)
    setOrderState(next)
  }, [])

  const reset = useCallback(() => {
    resetTabOrder()
    setOrderState(DEFAULT_TAB_ORDER)
  }, [])

  const isCustom =
    order.length !== DEFAULT_TAB_ORDER.length ||
    order.some((id, idx) => id !== DEFAULT_TAB_ORDER[idx])

  return { order, setOrder, reset, isCustom }
}
