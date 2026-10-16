import { fetchApi } from './api-config'

// A successful control POST accepts an asynchronous Proxmox task. In
// particular, an unchanged "running" status cannot confirm a reboot.
export async function waitForVmControlTask(vmid: number, action: string, task: string) {
  if (!task) throw new Error('controlNotConfirmed')
  const expected = action === 'shutdown' || action === 'stop' ? 'stopped' : 'running'
  const deadline = Date.now() + 180_000
  let readFailures = 0
  while (Date.now() < deadline) {
    let result: { status?: string; exitstatus?: string; guest_status?: string }
    try {
      result = await fetchApi(`/api/vms/${vmid}/control-task/${encodeURIComponent(task)}`, {
        signal: AbortSignal.timeout(10_000),
      })
      readFailures = 0
    } catch (error) {
      if (++readFailures >= 3) throw new Error('controlNotConfirmed')
      await new Promise(resolve => setTimeout(resolve, 1000))
      continue
    }
    if (result?.status === 'stopped') {
      if (!result.exitstatus) throw new Error('controlNotConfirmed')
      if (result.exitstatus !== 'OK') throw new Error(result.exitstatus)
      if (result.guest_status === expected) return result
    } else if (result?.status !== 'running') {
      throw new Error('controlNotConfirmed')
    }
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
  throw new Error('controlNotConfirmed')
}
