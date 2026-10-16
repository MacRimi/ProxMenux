"use client"

import { useState } from "react"
import useSWR from "swr"
import { PBSPanel } from "./pbs-panel"
import { Security } from "./security"
import { SystemLogs } from "./system-logs"
import { TerminalPanel } from "./terminal-panel"
import { ThemeToggle } from "./theme-toggle"
import { Button } from "./ui/button"
import { Card, CardContent } from "./ui/card"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

interface Vitals { hostname: string; cpu_usage: number; memory_usage: number; memory_used: number; memory_total: number; uptime: string }

export function PBSDashboard() {
  const t = useT()
  const [tab, setTab] = useState("overview")
  const { data } = useSWR<Vitals>("/api/system", url => fetchApi<Vitals>(url), { refreshInterval: 10000 })
  return <div className="container mx-auto max-w-7xl space-y-6 px-4 py-6">
    <header className="flex flex-wrap items-center gap-3 border-b pb-4">
      <div className="mr-auto"><h1 className="text-2xl font-bold">ProxMenux · PBS</h1><p className="text-sm text-muted-foreground">{data?.hostname || t("pbs.loading")}</p></div>
      <ThemeToggle />
      <Button variant="outline" onClick={() => { localStorage.removeItem("proxmenux-auth-token"); window.location.reload() }}>{t("pbs.logout")}</Button>
    </header>
    <nav aria-label={t("pbs.navigation")} className="flex flex-wrap gap-2">
      {(["overview", "logs", "terminal", "security"] as const).map(key =>
        <Button key={key} variant={tab === key ? "default" : "outline"} onClick={() => setTab(key)}>{t(`pbs.${key}`)}</Button>)}
    </nav>
    {tab === "overview" && <>
      <div className="grid gap-4 sm:grid-cols-3">
        {[[t("pbs.cpu"), data ? `${data.cpu_usage.toFixed(1)}%` : "—"],
          [t("pbs.memory"), data ? `${data.memory_used.toFixed(1)} / ${data.memory_total.toFixed(1)} GiB (${data.memory_usage.toFixed(1)}%)` : "—"],
          [t("pbs.uptime"), data?.uptime || "—"]].map(([label, value]) =>
          <Card key={label}><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-lg font-semibold">{value}</p></CardContent></Card>)}
      </div>
      <PBSPanel />
    </>}
    {tab === "logs" && <SystemLogs />}
    {tab === "terminal" && <TerminalPanel />}
    {tab === "security" && <Security hostType="pbs" />}
  </div>
}
