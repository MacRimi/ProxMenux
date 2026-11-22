import { fetchApi } from "./api-config"

export type LxcRemovalTaskState = "running" | "succeeded" | "failed" | "warning" | "unknown"

export interface LxcRemovalTaskResult {
  state: LxcRemovalTaskState
  task: string | null
  reason?: string
  exitstatus?: string
}

export interface LxcRemovalReceipt {
  vmid: number
  check: string
}

export const lxcRemovalReceiptKey = (vmid: number) => `proxmenux.lxc-removal.${vmid}`

export function saveLxcRemovalReceipt(receipt: LxcRemovalReceipt) {
  if (typeof window === "undefined") return false
  try {
    sessionStorage.setItem(lxcRemovalReceiptKey(receipt.vmid), JSON.stringify({ ...receipt, savedAt: Date.now() }))
    return true
  } catch {
    return false
  }
}

export function clearLxcRemovalReceipt(vmid: number) {
  if (typeof window === "undefined") return
  try {
    sessionStorage.removeItem(lxcRemovalReceiptKey(vmid))
  } catch {
    // The native task result is still visible through Proxmox itself.
  }
}

export function loadLxcRemovalReceipt(vmid?: number): LxcRemovalReceipt | null {
  if (typeof window === "undefined") return null
  try {
    for (let index = 0; index < sessionStorage.length; index += 1) {
      const key = sessionStorage.key(index)
      if (!key?.startsWith("proxmenux.lxc-removal.") || (vmid !== undefined && key !== lxcRemovalReceiptKey(vmid))) continue
      try {
        const value = JSON.parse(sessionStorage.getItem(key) || "")
        if (Number.isSafeInteger(value?.vmid) && value.vmid > 0 && key === lxcRemovalReceiptKey(value.vmid)
            && typeof value.check === "string" && value.check.length > 0
            && typeof value.savedAt === "number" && Date.now() - value.savedAt < 86_400_000) {
          return { vmid: value.vmid, check: value.check }
        }
      } catch {
        // A malformed entry must not hide another guest's receipt.
      }
    }
  } catch {
    // A malformed receipt is ignored: it cannot authorize an action.
  }
  return null
}

export async function readLxcRemovalTask({ vmid, check }: LxcRemovalReceipt): Promise<LxcRemovalTaskResult> {
  return fetchApi<LxcRemovalTaskResult>(`/api/vms/${vmid}/remove-operation`, {
    headers: { "X-LXC-Removal-Check": check },
    signal: AbortSignal.timeout(10_000),
  })
}
