"use client"

// The Backup tab: the backups of the host and the backup jobs of the VMs
// and LXCs, each in its own view.

import { useState } from "react"
import { DatabaseBackup } from "lucide-react"
import { HostBackup } from "./host-backup"
import { VmBackupJobs } from "./vm-backup-jobs"
import { useT } from "../lib/i18n/provider"

type BackupView = "host" | "guests"

export function BackupTab() {
  const t = useT()
  const [view, setView] = useState<BackupView>("host")

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
        <div className="flex items-center gap-2">
          <DatabaseBackup className="h-6 w-6 shrink-0 text-foreground" />
          <h2 className="text-xl lg:text-2xl font-bold text-foreground">{t("navigation.backup")}</h2>
        </div>
        <div className="flex flex-col gap-2 sm:ml-auto sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
          <div
            role="group"
            aria-label={t("backup.viewSwitch.ariaLabel")}
            className="flex w-full rounded-lg border border-border bg-muted/40 p-1 gap-1
                       sm:inline-flex sm:w-auto"
          >
            {(["host", "guests"] as const).map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={view === key}
                onClick={() => setView(key)}
                className={`flex-1 inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors sm:flex-none ${
                  view === key
                    ? "bg-blue-500 text-white shadow-sm"
                    : "text-muted-foreground hover:text-foreground hover:bg-background/60"
                }`}
              >
                {t(`backup.viewSwitch.${key}`)}
              </button>
            ))}
          </div>
        </div>
      </div>
      {/* The host view stays mounted: it follows a running backup or restore. */}
      <div className={view === "host" ? "" : "hidden"}>
        <HostBackup />
      </div>
      {view === "guests" && <VmBackupJobs />}
    </div>
  )
}
