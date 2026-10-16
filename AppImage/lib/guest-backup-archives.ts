import { fetchApi } from './api-config'

export interface GuestBackup {
  volid: string
  storage: string
  type: string
  size: number
  size_human: string
  timestamp: number
  date: string
  notes?: string
  protected?: boolean
}

export interface BackupDeletionResult {
  volid: string
  status: 'deleted' | 'pending' | 'unconfirmed'
  task?: string
  error?: string
}

// Exposed separately so callers can invalidate their inventory even after a
// lost POST response. Never retry the destructive request automatically.
export async function deleteGuestBackups(vmid: number, backups: GuestBackup[]): Promise<BackupDeletionResult[]> {
  const response = await fetchApi<{ results: BackupDeletionResult[] }>(`/api/vms/${vmid}/backups/delete`, {
    method: 'POST',
    body: JSON.stringify({ confirm: true, backups: backups.map(({ volid, storage }) => ({ volid, storage })) }),
    signal: AbortSignal.timeout(120_000),
  })
  if (!Array.isArray(response.results) || response.results.length !== backups.length ||
      response.results.some((result, index) => result.volid !== backups[index].volid ||
        !['deleted', 'pending', 'unconfirmed'].includes(result.status))) throw new Error('deletionUnconfirmed')

  return Promise.all(response.results.map(async result => {
    if (result.status !== 'pending' || !result.task) return result
    const deadline = Date.now() + 120_000
    let failures = 0
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 1500))
      try {
        const status = await fetchApi<BackupDeletionResult>(
          `/api/vms/${vmid}/backups/delete-status?task=${encodeURIComponent(result.task!)}`,
          { signal: AbortSignal.timeout(10_000) },
        )
        if (status.volid !== result.volid || !['deleted', 'pending', 'unconfirmed'].includes(status.status)) break
        if (status.status !== 'pending') return status
        failures = 0
      } catch {
        if (++failures >= 3) break
      }
    }
    return { ...result, status: 'unconfirmed', error: 'deletionUnconfirmed' }
  }))
}
