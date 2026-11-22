"use client"

import { useEffect, useRef, useState } from "react"
import { Button } from "./ui/button"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

export type HostUpdateJob = {
  id: string
  state: "starting" | "running" | "attention" | "finalizing" | "complete"
  exit_code: number | null
}

export function HostUpdateJobs({ open, activeId, onResume, onJobs, onSettled }: {
  open: boolean
  activeId?: string
  onResume: (job: HostUpdateJob) => void
  onJobs: (jobs: HostUpdateJob[]) => void
  onSettled: () => void
}) {
  const t = useT()
  const [jobs, setJobs] = useState<HostUpdateJob[]>([])
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const callbacks = useRef({ onJobs, onSettled })
  callbacks.current = { onJobs, onSettled }
  const observed = useRef(new Set<string>())
  useEffect(() => {
    if (!open) return
    let closed = false
    const read = async () => {
      try {
        const data = await fetchApi<{ jobs: HostUpdateJob[] }>("/api/host-update-jobs")
        if (closed) return
        const next = Array.isArray(data.jobs) ? data.jobs : []
        setJobs(next)
        callbacks.current.onJobs(next)
        for (const job of next) {
          if (job.state === "complete" && !observed.current.has(job.id)) {
            observed.current.add(job.id)
            callbacks.current.onSettled()
          }
        }
      } catch {
        // Authentication recovery belongs to fetchApi. Never retry a start.
      }
    }
    void read()
    const timer = setInterval(() => { void read() }, 5000)
    return () => { closed = true; clearInterval(timer) }
  }, [open])
  const visible = jobs.filter(job => job.id !== activeId && !(job.state === "complete" && hidden.has(job.id)))
  if (!visible.length) return null
  return <div className="space-y-2" role="status">
    {visible.map(job => <div key={job.id}
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3">
      <p className="text-sm">{t(`healthStatus.hostUpdate.${job.state === "complete" ? "finished" : job.state === "attention" ? "attention" : "running"}`)}</p>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={() => onResume(job)}>
          {t(job.state === "complete" ? "healthStatus.hostUpdate.viewResult" : "healthStatus.hostUpdate.view")}
        </Button>
        {job.state === "complete" && <Button size="sm" variant="ghost" onClick={() => setHidden(previous => new Set([...previous, job.id]))}>
          {t("healthStatus.hostUpdate.hideResult")}
        </Button>}
      </div>
    </div>)}
  </div>
}
