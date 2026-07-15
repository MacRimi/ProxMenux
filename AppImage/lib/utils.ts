import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatStorage(sizeInGB: number): string {
  if (sizeInGB < 1) {
    // Less than 1 GB, show in MB
    const mb = sizeInGB * 1024
    return `${mb % 1 === 0 ? mb.toFixed(0) : mb.toFixed(1)} MB`
  } else if (sizeInGB < 1024) {
    // Less than 1024 GB, show in GB
    return `${sizeInGB % 1 === 0 ? sizeInGB.toFixed(0) : sizeInGB.toFixed(1)} GB`
  } else {
    // 1024 GB or more, show in TB
    const tb = sizeInGB / 1024
    return `${tb % 1 === 0 ? tb.toFixed(0) : tb.toFixed(1)} TB`
  }
}

// Byte-aware formatter. Scales B → KB → MB → GB → TB. Use when the
// raw value comes in bytes (log file sizes from os.path.getsize(),
// PBS / Borg datastore capacity reported by the backend in bytes).
// The Backups page used to ship its own copy that capped at GB, so a
// 7 TB datastore showed up as "7311.55 GB" — extracted here so it
// can't drift again.
export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—"
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`
  if (n < 1024 * 1024 * 1024 * 1024) {
    return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`
  }
  return `${(n / (1024 * 1024 * 1024 * 1024)).toFixed(2)} TB`
}
