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
