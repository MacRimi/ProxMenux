import useSWR from "swr"
import { fetchApi } from "./api-config"

// Shares the dashboard's /api/platform request through the SWR cache.
export function useIsPbs(): boolean {
  const { data } = useSWR<{ product: string }>("/api/platform", (url: string) => fetchApi<{ product: string }>(url), { revalidateOnFocus: false })
  return data?.product === "pbs"
}
