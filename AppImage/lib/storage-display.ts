import { useEffect, useState, useCallback } from "react"

// Per-browser display preference for the Storage view: whether the
// "Physical Disks & SMART Status" card groups disks under the storage
// controller they hang off. Off by default so the layout is unchanged
// until the user opts in from Settings.

const STORAGE_KEY = "proxmenux-group-disks-by-controller"
const CHANGE_EVENT = "proxmenux-group-disks-by-controller-changed"

export function readGroupDisksByController(): boolean {
  if (typeof window === "undefined") return false
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "true"
  } catch {
    return false
  }
}

export function writeGroupDisksByController(enabled: boolean): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(STORAGE_KEY, String(enabled))
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT))
  } catch {
    // Storage full / disabled; the in-memory state still updates.
  }
}

// Hook that keeps the Settings card and the Storage view in sync in the
// same tab (custom event) and across tabs (storage event).
export function useGroupDisksByController(): [boolean, (enabled: boolean) => void] {
  const [enabled, setEnabledState] = useState(false)

  useEffect(() => {
    setEnabledState(readGroupDisksByController())
    const onChange = () => setEnabledState(readGroupDisksByController())
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) onChange()
    }
    window.addEventListener(CHANGE_EVENT, onChange)
    window.addEventListener("storage", onStorage)
    return () => {
      window.removeEventListener(CHANGE_EVENT, onChange)
      window.removeEventListener("storage", onStorage)
    }
  }, [])

  const setEnabled = useCallback((next: boolean) => {
    writeGroupDisksByController(next)
    setEnabledState(next)
  }, [])

  return [enabled, setEnabled]
}
