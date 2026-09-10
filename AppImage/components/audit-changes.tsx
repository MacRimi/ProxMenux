"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Badge } from "./ui/badge"
import {
  ChevronDown, ChevronRight, FileCode, HelpCircle, Loader2, Package,
  Play, Settings2,
} from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT, useI18n } from "../lib/i18n/provider"

/**
 * What ProxMenux changed on this host.
 *
 * The complaint this answers is not that the tool changes things: it is
 * that afterwards nobody can say what it changed. Showing the script
 * does not answer it either — a function of four hundred lines may alter
 * two values, and the reader cannot tell which two. So what is shown
 * here is the difference and nothing else.
 *
 * Two distinctions are kept in front of the reader, because both bear on
 * what they can do about what they are looking at: whether ProxMenux
 * authored the change or merely ran something the user asked for, and
 * how much of the previous state is actually known.
 */

interface Change {
  id: number
  recorded_at: number
  class: string
  operation: string
  source: string
  function: string
  function_version: string
  target: string
  before_ref: string
  after_ref: string
  capture: string
  revert: string
  exactness: string
  result: string
  recoverable: boolean
  detail: Record<string, unknown>
  diff?: {
    available: boolean; reason?: string
    added?: number; removed?: number; truncated?: boolean; hunks?: string[]
  } | null
}

interface Summary {
  total: number
  by_class: Record<string, number>
  functions: Array<{
    function: string; source: string; version: string
    changes: number; last_change: number; first_change: number
  }>
  journal_started: number | null
}

// A file that did not exist before was created, not replaced — a sysadmin
// reading this must see "new file", not "file replaced". `capture` carries
// that distinction: "created" for a file born here, "present" for one that
// already had contents we captured before overwriting them.
function operationLabelKey(change: { operation: string; capture: string }): string {
  // Two truthful labels for a file: created if it did not exist, modified if
  // it did. The diff below shows exactly what changed either way, so there is
  // no need to distinguish write/edit/append in the label.
  if (["write_file", "edit_file", "append_file"].includes(change.operation)) {
    return change.capture === "created" ? "operation.file_created" : "operation.file_modified"
  }
  return `operation.${change.operation}`
}

// Undoing follows `revert`, not `exactness`: a created file is undone by
// deleting it (there was nothing before), an overwritten one by restoring
// what we captured.
function undoKey(change: { revert: string; exactness: string }): string {
  if (change.revert === "remove") return "undo.remove"
  if (change.revert === "restore" && change.exactness === "exact") return "undo.restore"
  return `exactness.${change.exactness}`
}

const FN_LABEL: Record<string, string> = {
  apply_amd_fixes: "Apply AMD CPU fixes",
  apply_network_optimizations: "Apply network optimizations",
  apt_upgrade: "Update and upgrade system",
  cleanup_duplicate_repos_pve9: "Configure Proxmox APT repositories",
  configure_fastfetch: "Install and configure Fastfetch",
  configure_figurine: "Install Figurine",
  configure_kernel_panic: "Enable restart on kernel panic",
  configure_log2ram: "Install and configure Log2RAM",
  configure_pigz: "Use pigz for faster gzip compression",
  configure_time_sync: "Synchronize time automatically",
  customize_bashrc: "Customize bashrc",
  disable_rpc: "Disable portmapper/rpcbind",
  enable_ha: "Enable High Availability services",
  enable_kexec: "Enable fast reboots",
  enable_tcp_fast_open: "Enable TCP BBR/Fast Open control",
  enable_vfio_iommu: "Enable VFIO IOMMU support",
  enable_zfs_autotrim: "Enable ZFS autotrim (SSD/NVMe pools)",
  force_apt_ipv4: "Force APT to use IPv4",
  increase_system_limits: "Increase various system limits",
  install_ceph: "Add latest Ceph support",
  install_guest_agent: "Install relevant guest agent",
  install_log2ram: "Install and configure Log2RAM",
  install_log2ram_auto: "Install and configure Log2RAM",
  install_openvswitch: "Install Open vSwitch",
  install_ovh_rtm: "Install OVH Real Time Monitoring",
  install_system_utils: "Install common system utilities",
  install_zfs_auto_snapshot: "Install ZFS auto-snapshot",
  optimize_journald: "Optimize journald",
  optimize_logrotate: "Optimize logrotate",
  optimize_memory_settings: "Optimize Memory",
  optimize_vzdump: "Increase vzdump backup speed",
  optimize_zfs_arc: "Optimize ZFS ARC size",
  remove_subscription_banner: "Remove subscription banner",
  setup_motd: "Set up custom MOTD banner",
  setup_persistent_network: "Interface Names (persistent)",
  setup_proxmox_repositories: "Configure Proxmox APT repositories",
  skip_apt_languages: "Skip downloading additional languages",
  update_pve8: "Update and upgrade system",
  update_pve9: "Update and upgrade system",
  update_pve_appliance_manager: "Update Proxmox VE Appliance Manager",
}

// Post-install functions run from the auto/customizable scripts; everything
// else is a general host script (nvidia/tpu installers, PVE update, vfio…).
const POST_INSTALL_SOURCES = new Set(["auto", "customizable"])

// Which of the three sections a change belongs to: installations are their
// own block, post-install optimizations another, general scripts the rest.
function blockOf(c: { class: string; source: string }): "installs" | "postInstall" | "scripts" {
  if (c.class === "installation") return "installs"
  if (POST_INSTALL_SOURCES.has(c.source)) return "postInstall"
  return "scripts"
}

// A post-install function shows its menu name; anything else shows the script
// that made the change.
function groupLabel(fn: string, source: string): string {
  return FN_LABEL[fn] || source || fn || "—"
}

const CLASS_STYLE: Record<string, { chip: string; Icon: typeof Settings2 }> = {
  configuration: { chip: "bg-blue-500/10 text-blue-400 border-blue-400/20", Icon: Settings2 },
  installation: { chip: "bg-green-500/10 text-green-500 border-green-500/20", Icon: Package },
  execution: { chip: "bg-muted text-muted-foreground border-border", Icon: Play },
  registration: { chip: "bg-muted text-muted-foreground border-border", Icon: HelpCircle },
}

function ChangeCard({ change, expanded, onToggle, t, when }: {
  change: Change; expanded: boolean; onToggle: () => void
  t: (k: string, params?: Record<string, string>) => string
  when: (n: number) => string
}) {
  const style = CLASS_STYLE[change.class] || CLASS_STYLE.registration
  const Icon = style.Icon
  const installed = String(change.detail?.installed || "")
  return (
    <Card className="bg-card border-border">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="w-full text-left p-3 flex flex-wrap items-center gap-2
                   rounded-lg hover:bg-white/5 transition-colors cursor-pointer"
      >
        {expanded
          ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
          : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
        <Badge variant="outline" className={`${style.chip} gap-1.5 shrink-0`}>
          <Icon className="h-3.5 w-3.5" />
          {t(`audit.changes.${operationLabelKey(change)}`)}
        </Badge>
        <span className="min-w-0 font-mono text-sm text-foreground break-all">
          {change.target}
        </span>
        {change.diff?.available && (
          <Badge variant="outline" className="text-xs tabular-nums shrink-0">
            +{change.diff.added} −{change.diff.removed}
          </Badge>
        )}
        {change.capture === "unknown" && (
          <Badge variant="outline" className="text-xs shrink-0">
            {t("audit.changes.capture.unknown")}
          </Badge>
        )}
        <span className="ml-auto shrink-0 text-xs text-muted-foreground">
          {when(change.recorded_at)}
        </span>
      </button>

      {expanded && (
        <CardContent className="pt-0 pl-10 space-y-3">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
            <span>{t("audit.changes.source")}:{" "}
              <span className="font-mono">{change.source || "—"}</span></span>
            {change.revert && change.revert !== "none" && (
              <span>{t("audit.changes.reversibility")}:{" "}
                {t(`audit.changes.${undoKey(change)}`)}</span>
            )}
          </div>

          {(change.operation === "enable_service" || change.operation === "disable_service")
            && Boolean(change.detail?.before_state || change.detail?.after_state) && (
            <div className="flex items-center gap-2 text-xs">
              <span className="font-mono text-muted-foreground">
                {String(change.detail?.before_state || "—").replace(/\s+/g, " ")}
              </span>
              <span className="text-muted-foreground">→</span>
              <span className="font-mono text-foreground">
                {String(change.detail?.after_state || "—").replace(/\s+/g, " ")}
              </span>
            </div>
          )}

          {installed && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1">
                {t("audit.changes.packagesAdded")}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {installed.split(/\s+/).filter(Boolean).map((pkg) => (
                  <Badge key={pkg} variant="outline" className="font-mono text-xs">
                    {pkg}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {change.class === "execution" && Boolean(change.detail?.command) && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1">
                {t("audit.changes.commandRun")}
              </p>
              <pre className="text-xs font-mono bg-background border border-border
                              rounded-md p-2.5 overflow-x-auto">
                {String(change.detail.command)}
              </pre>
              <p className="text-xs text-muted-foreground mt-1">
                {t("audit.changes.executionNote")}
              </p>
            </div>
          )}

          {change.diff && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1">
                {t("audit.changes.difference")}
              </p>
              {change.diff.available ? (
                <>
                  <pre className="text-xs font-mono bg-background border border-border
                                  rounded-md p-2.5 overflow-x-auto">
                    {(change.diff.hunks || []).map((line: string, i: number) => (
                      <div key={i} className={
                        line.startsWith("+") ? "text-green-500"
                        : line.startsWith("-") ? "text-red-400"
                        : line.startsWith("@@") ? "text-blue-400" : ""
                      }>{line}</div>
                    ))}
                  </pre>
                  {change.diff.truncated && (
                    <p className="text-xs text-muted-foreground mt-1">
                      {t("audit.changes.diffTruncated")}
                    </p>
                  )}
                </>
              ) : (
                <p className="text-xs text-muted-foreground">
                  {t("audit.changes.diffUnavailable")}
                </p>
              )}
            </div>
          )}

          {change.capture === "unknown" && (
            <p className="text-xs text-muted-foreground">
              {t("audit.changes.unknownNote")}
            </p>
          )}
        </CardContent>
      )}
    </Card>
  )
}

function GroupSection({ title, groups, openFn, toggleFn, open, toggle, t, when }: {
  title: string
  groups: { key: string; label: string; version: string; last: number; items: Change[] }[]
  openFn: Set<string>; toggleFn: (k: string) => void
  open: Set<number>; toggle: (id: number) => void
  t: (k: string, params?: Record<string, string>) => string
  when: (n: number) => string
}) {
  if (groups.length === 0) return null
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-foreground px-1">{title}</h3>
      {groups.map((g) => {
        const fnOpen = openFn.has(g.key)
        return (
          <Card key={g.key} className="bg-card border-border">
            <button
              type="button"
              onClick={() => toggleFn(g.key)}
              aria-expanded={fnOpen}
              className="w-full text-left p-3 flex flex-wrap items-center gap-2
                         rounded-lg hover:bg-white/5 transition-colors cursor-pointer"
            >
              {fnOpen
                ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
              <FileCode className="h-4 w-4 shrink-0 text-blue-400" />
              <span className="min-w-0 text-sm font-medium text-foreground break-words">
                {g.label}
              </span>
              {g.version && (
                <Badge variant="outline" className="text-xs shrink-0">v{g.version}</Badge>
              )}
              <Badge variant="outline" className="text-xs tabular-nums shrink-0">
                {t("audit.changes.count", { count: String(g.items.length) })}
              </Badge>
              <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                {when(g.last)}
              </span>
            </button>
            {fnOpen && (
              <CardContent className="pt-0 pl-10 pr-3 space-y-2">
                {g.items.map((change) => (
                  <ChangeCard key={change.id} change={change}
                    expanded={open.has(change.id)} onToggle={() => toggle(change.id)}
                    t={t} when={when} />
                ))}
              </CardContent>
            )}
          </Card>
        )
      })}
    </div>
  )
}

export function AuditChanges() {
  const t = useT()
  const { language } = useI18n()
  const [changes, setChanges] = useState<Change[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<Set<number>>(new Set())

  const load = useCallback(async () => {
    try {
      const res: any = await fetchApi("/api/audit/changes?limit=500")
      if (res?.success) {
        setChanges(res.changes || [])
        setSummary(res.summary || null)
        setError(null)
      } else {
        setError(res?.message || t("audit.changes.failed"))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => { load() }, [load])

  const toggle = (id: number) => setOpen((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  const [openFn, setOpenFn] = useState<Set<string>>(new Set())
  const toggleFn = (fn: string) => setOpenFn((prev) => {
    const next = new Set(prev)
    next.has(fn) ? next.delete(fn) : next.add(fn)
    return next
  })

  // A sysadmin reads this in three sections: what ProxMenux optimized
  // (post-install), what its other scripts changed, and what it installed.
  // Within each, changes are grouped under a card that opens to reveal them.
  type Group = { key: string; label: string; version: string; last: number; items: Change[] }
  const blocks = useMemo(() => {
    const mk = () => new Map<string, Group>()
    const post = mk(), scripts = mk(), installs = mk()
    const pick = (b: string) => b === "installs" ? installs : b === "postInstall" ? post : scripts
    for (const c of changes) {
      const target = pick(blockOf(c))
      const key = c.function || c.source || "—"
      const label = groupLabel(c.function, c.source)
      const g = target.get(key) || { key, label, version: c.function_version || "", last: 0, items: [] }
      g.items.push(c)
      if (c.recorded_at > g.last) g.last = c.recorded_at
      if (c.function_version) g.version = c.function_version
      target.set(key, g)
    }
    const sort = (m: Map<string, Group>) => Array.from(m.values()).sort((a, b) => b.last - a.last)
    return { post: sort(post), scripts: sort(scripts), installs: sort(installs) }
  }, [changes])

  const when = (epoch: number) => new Date(epoch * 1000).toLocaleString(language)

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />{t("audit.changes.loading")}
      </div>
    )
  }
  if (error) return <p className="text-sm text-red-400 px-1">{error}</p>

  return (
    <div className="space-y-4">
      <Card className="bg-card border-border">
        <CardContent className="py-4 space-y-3">
          <p className="text-sm text-muted-foreground">{t("audit.changes.intro")}</p>
          {/* A host with nothing recorded should say why, rather than
              looking like a host nothing has touched. */}
          {summary && summary.total === 0 && (
            <p className="text-sm text-muted-foreground">{t("audit.changes.empty")}</p>
          )}
          {summary && summary.journal_started && (
            <p className="text-xs text-muted-foreground">
              {t("audit.changes.since", { date: when(summary.journal_started) })}
            </p>
          )}
        </CardContent>
      </Card>

      <GroupSection title={t("audit.changes.section.postInstall")}
        groups={blocks.post} openFn={openFn} toggleFn={toggleFn}
        open={open} toggle={toggle} t={t} when={when} />
      <GroupSection title={t("audit.changes.section.scripts")}
        groups={blocks.scripts} openFn={openFn} toggleFn={toggleFn}
        open={open} toggle={toggle} t={t} when={when} />
      <GroupSection title={t("audit.changes.section.installs")}
        groups={blocks.installs} openFn={openFn} toggleFn={toggleFn}
        open={open} toggle={toggle} t={t} when={when} />
      {summary && summary.total > 0
        && blocks.post.length + blocks.scripts.length + blocks.installs.length === 0 && (
        <p className="text-sm text-muted-foreground px-1">{t("audit.changes.empty")}</p>
      )}
    </div>
  )
}
