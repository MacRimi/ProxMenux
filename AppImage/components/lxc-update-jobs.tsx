"use client"

import { useEffect, useState } from "react"
import { Button } from "./ui/button"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"
import { viewedUpdateJobs, type LxcUpdateJob } from "../lib/lxc-update-jobs"

export function LxcUpdateJobs({ activeRunId, onResume }: {
  activeRunId?: string
  onResume: (job: LxcUpdateJob) => void
}) {
  const t = useT()
  const [jobs, setJobs] = useState<LxcUpdateJob[]>([])
  const [seen, setSeen] = useState<string[]>([])
  useEffect(() => {
    let closed = false
    const read = () => {
      void fetchApi<{ jobs: LxcUpdateJob[] }>("/api/lxc-update-jobs")
        .then((data) => { if (!closed) setJobs(Array.isArray(data.jobs) ? data.jobs : []) })
        .catch(() => {}) // Auth recovery belongs to fetchApi, never to a job retry.
    }
    const viewed = () => setSeen(viewedUpdateJobs())
    viewed()
    read()
    const timer = setInterval(read, 5000)
    window.addEventListener("proxmenux-update-jobs-viewed", viewed)
    return () => {
      closed = true
      clearInterval(timer)
      window.removeEventListener("proxmenux-update-jobs-viewed", viewed)
    }
  }, [])
  const visible = jobs.filter((job) => job.id !== activeRunId
    && (job.state !== "complete" || !seen.includes(job.id)))
  if (!visible.length) return null
  return <div className="space-y-2" role="status">
    {visible.map((job) => <div key={job.id}
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3">
      <p className="text-sm">{t(job.state === "complete"
        ? "vmLxc.updates.backgroundFinished" : "vmLxc.updates.backgroundRunning",
      { vmid: job.vmid, name: job.ct_name || `CT-${job.vmid}` })}</p>
      <Button variant="outline" size="sm" onClick={() => onResume(job)}>
        {t("vmLxc.updates.viewBackgroundJob")}
      </Button>
    </div>)}
  </div>
}
