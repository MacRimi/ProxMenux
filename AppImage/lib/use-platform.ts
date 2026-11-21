import useSWR from "swr"
import { fetchApi } from "./api-config"

// Shares the dashboard's /api/platform request through the SWR cache.
export function useIsPbs(): boolean {
  const { data } = useSWR<{ product: string }>("/api/platform", (url: string) => fetchApi<{ product: string }>(url), { revalidateOnFocus: false })
  return data?.product === "pbs"
}

// The Proxmox product whose accounts can sign in to this Monitor, and the port
// of its own web interface. The sign-in page reads `pbs` from /api/auth/status,
// the rest of the dashboard from useIsPbs(): both come from the same detection.
export const proxmoxProduct = (pbs: boolean) => pbs ? "Proxmox Backup Server" : "Proxmox VE"
export const proxmoxWebPort = (pbs: boolean) => pbs ? 8007 : 8006
