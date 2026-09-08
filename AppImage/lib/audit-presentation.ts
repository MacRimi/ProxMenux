/** Descriptive view model shared by the Monitor and the printable report.
 * Raw evidence remains separate. This layer never proposes an action.
 */
import { splitLeadingJson, durationOf, formatValue } from "./evidence-format"

export type AuditTranslate = (key: string, params?: Record<string, string>) => string
export interface PresentedFinding {
  check_id: string
  classification: string
  affected: Array<Record<string, unknown>>
  evidence: string | null
}
export interface AuditGroup {
  title: string
  note?: string
  columns: string[]
  rows: Array<{ cells: string[]; classification: string }>
}
export const auditLabel = (t: AuditTranslate, key: string) => t(`audit.presentation.${key}`)

/** El estado que devuelve `pvesubscription get`, en palabras del lector. */
export function subscriptionLabel(t: AuditTranslate, status?: string | null): string {
  const key = (status || "").trim().toLowerCase()
  if (!key) return ""
  const known = ["notfound", "active", "invalid", "expired", "suspended", "new", "unknown"]
  return known.includes(key) ? t(`audit.inventory.subscriptionStatus.${key}`) : (status as string)
}

/**
 * What a check could not read, in the reader's own words.
 *
 * A check that reports "could not be evaluated" and stops there
 * describes the assessment rather than the host: the reason is recorded
 * against each source, but it sat two collapsed sections below a line
 * that explained nothing. This is what the finding says out loud
 * instead.
 */
export function unreadSources(
  sources: Array<{ source: string; error?: string }> | undefined,
  t: AuditTranslate,
): string {
  const failed = (sources || []).filter((s) => s.error)
  if (!failed.length) return ""
  const named = failed.map((s) => {
    // Sources are recorded as they were invoked — `cmd:["pvesm", …]`.
    // The reader wants the command, not its serialisation.
    let name = s.source
    if (name.startsWith("cmd:")) {
      try {
        name = (JSON.parse(name.slice(4)) as string[]).join(" ")
      } catch {
        name = name.slice(4)
      }
    }
    return `${name} — ${String(s.error).replace(/\s+/g, " ").trim()}`
  })
  return `${auditLabel(t, "couldNotRead")}: ${named.join(" · ")}`
}

export function auditDuration(hours: number, locale: string): string {
  return durationOf(hours, locale)
}

export function evidenceRecords(evidence: string | null): Array<Record<string, any>> {
  const parsed = splitLeadingJson((evidence || "").trim())
  return parsed && Array.isArray(parsed[0]) ? parsed[0].filter(x => x && typeof x === "object") : []
}

const clean = (v: unknown): string => v === undefined || v === null || v === "-" ? "" : String(v)

/**
 * Instants in the audit have two deliberate forms: epoch seconds from
 * Proxmox, and local ISO timestamps from the Monitor's SQLite stores.
 * A timezone-less SQLite value is already local wall time; treating it
 * as UTC shifts it a second time in the printable report.
 */
function auditDate(value: unknown): Date | null {
  if (value === undefined || value === null || value === "") return null
  if (typeof value === "number" || /^\d+(?:\.\d+)?$/.test(String(value))) {
    const date = new Date(Number(value) * 1000)
    return Number.isNaN(date.getTime()) ? null : date
  }
  const text = String(value).trim()
  const local = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?$/.exec(text)
  const date = local
    ? new Date(Number(local[1]), Number(local[2]) - 1, Number(local[3]),
        Number(local[4]), Number(local[5]), Number(local[6]),
        Number((local[7] || "0").slice(0, 3).padEnd(3, "0")))
    : new Date(text)
  return Number.isNaN(date.getTime()) ? null : date
}

export function auditInstant(value: unknown, locale: string): string {
  const date = auditDate(value)
  return date ? date.toLocaleString(locale) : clean(value) || "—"
}

export function presentFinding(f: PresentedFinding, t: AuditTranslate, locale: string,
                               guests: Array<{ vmid: number; name?: string; type?: string }> = []): AuditGroup[] {
  const label = (key: string) => auditLabel(t, key)
  const records = evidenceRecords(f.evidence)
  const parsedEvidence = splitLeadingJson((f.evidence || "").trim())
  const evidenceObject = parsedEvidence && parsedEvidence[0] &&
    typeof parsedEvidence[0] === "object" && !Array.isArray(parsedEvidence[0])
    ? parsedEvidence[0] as Record<string, any> : null
  const guest = (o: Record<string, unknown>) => {
    const id = o.vmid ?? o.guest
    const known = guests.find(g => String(g.vmid) === String(id))
    const type = o.type || known?.type
    const prefix = type === "qemu" || type === "vm" ? "VM" : type === "lxc" || type === "ct" ? "LXC" : label("guest")
    const name = clean(o.name || known?.name)
    return `${name ? name + " · " : ""}${prefix} ${id}`
  }
  const resource = (o: Record<string, unknown>) => o.vmid !== undefined || o.guest !== undefined
    ? guest(o) : clean(o.name || o.device || o.storage || o.pool || o.bond || o.interface || o.job || o.package || o.test) || label("host")
  // A decision the reader took stands in front of the technical result:
  // an object excluded by policy is not a finding at a low gravity, it
  // is one that was taken out of the question.
  const status = (o: Record<string, unknown>) =>
    clean(o.decision) || clean(o.classification) || f.classification
  const state = (o: Record<string, unknown>) => t(`audit.classifications.${status(o)}`)
  const reason = (o: Record<string, unknown>) => {
    const key = `audit.presentation.reasons.${clean(o.reason_key)}`
    const translated = t(key)
    return translated !== key ? translated : t(`audit.checks.${f.check_id}.title`)
  }
  const group = (title: string, columns: string[], objects: Array<Record<string, unknown>>,
                 cells: (o: Record<string, unknown>) => string[]): AuditGroup => ({
    title, columns, rows: objects.map(o => ({ cells: cells(o), classification: status(o) })),
  })
  if (f.check_id === "storage.connected_storage") {
    const storages = Array.isArray(evidenceObject?.storages)
      ? evidenceObject!.storages.filter((o: unknown) => o && typeof o === "object") : []
    if (storages.length) {
      const objects = storages.map((row: Record<string, unknown>) => {
        const finding = f.affected.find(o => o.storage === row.storage)
        return { ...row, classification: finding?.classification ||
          (["active", "available", "namespace_restricted"].includes(clean(row.status))
            ? "conformant" : "unverified") }
      })
      return [group("PVE", [t("audit.document.storage"), t("audit.document.type"),
        t("audit.document.state"), label("capacity"), label("fact")], objects, o => {
        const dependencyCount = Array.isArray(o.dependencies) ? o.dependencies.length : 0
        const jobCount = Array.isArray(o.jobs) ? o.jobs.length : 0
        const observed = [dependencyCount ? `${dependencyCount} ${t("audit.inventory.guests")}` : "",
          jobCount ? `${jobCount} ${t("audit.document.backup")}` : ""].filter(Boolean).join(" · ") || "—"
        const capacity = o.capacity_known && o.used_percent !== undefined
          ? `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(Number(o.used_percent))} %`
          : "—"
        return [clean(o.storage), clean(o.type), clean(o.status) || t("audit.classifications.unverified"),
          capacity, observed]
      })]
    }
  }
  if (f.check_id === "storage.thin_pool_overprovisioning" && records.length) {
    const objects = records.map(row => {
      const related = f.affected.filter(o => o.pool === row.pool)
      const classification = related.some(o => o.classification === "warning") ? "warning"
        : related.some(o => o.classification === "observation") ? "observation" : "conformant"
      return { ...row, classification,
        fact: related.map(reason).filter((v, i, all) => all.indexOf(v) === i).join(" · ") }
    })
    const pct = (value: unknown) => Number.isFinite(Number(value))
      ? `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(Number(value))} %` : "—"
    return [group(label("records"), [label("resource"), label("capacity"), label("data"), label("metadata"), label("fact")],
      objects, o => {
        const allocation = Number.isFinite(Number(o.allocation_percent))
          ? `${pct(o.allocation_percent)} (${formatValue("allocated_bytes", Number(o.allocated_bytes), locale)} / ${formatValue("pool_bytes", Number(o.pool_bytes), locale)})` : "—"
        return [clean(o.pool), allocation, pct(o.data_percent), pct(o.metadata_percent),
          clean(o.fact) || state(o)]
      })]
  }
  if (f.check_id === "backup.guest_coverage") {
    const excluded = f.affected.filter(o => o.reason_key === "dataExcludedFromBackup")
    const notSelected = f.affected.filter(o => o.reason_key !== "dataExcludedFromBackup")
    const groups = []
    if (notSelected.length) groups.push(group(label("unscheduled"), [label("guest"), label("result")],
      notSelected, o => [guest(o), state(o)]))
    if (excluded.length) {
      const ids = [...new Set(excluded.map(o => o.vmid))]
      groups.push(group(`${label("excludedDisks")} · ${excluded.length} / ${ids.length} ${label("guests")}`,
        [label("guest"), label("disks"), label("result")], ids.map(vmid => ({...excluded.find(o => o.vmid === vmid)!, vmid})),
        o => [guest(o), excluded.filter(d => d.vmid === o.vmid).map(d => clean(d.volume)).join(", "), state(o)]))
    }
    return groups
  }
  if (f.check_id === "backup.last_backup_age") {
    return ["critical", "warning", "observation", "unverified"].flatMap(classification => {
      const objects = f.affected.filter(o => status(o) === classification)
      if (!objects.length) return []
      const result = group(t(`audit.classifications.${classification}`),
        [label("guest"), label("destination"), label("lastCopy"), label("backupAge"), label("backupLimit"), label("fact")], objects, o => {
          const row = records.find(r => String(r.vmid) === String(o.vmid) && (
            o.storage === "any" || r.expected_storage === o.storage ||
            r.expected_storage === "any visible destination (no explicit target)" ||
            r.storage === o.storage))
          const basis = row?.age_policy === "declared recovery objective" ? label("limitDeclared")
            : row?.age_policy === "schedule and grace" ? label("limitSchedule")
            : typeof row?.age_policy === "string" && row.age_policy.startsWith("fallback;") ? label("limitReference") : ""
          const limit = row?.max_age_hours != null && Number.isFinite(Number(row.max_age_hours))
            ? [auditDuration(Number(row.max_age_hours), locale), basis].filter(Boolean).join(" · ") : "—"
          return [guest(o), o.storage === "any" ? label("noDestination") : clean(o.storage),
            row?.last_backup ? new Date(Number(row.last_backup) * 1000).toLocaleString(locale) : classification === "unverified" ? t("audit.classifications.unverified") : label("notFound"),
            row?.age_hours != null && Number.isFinite(Number(row.age_hours)) ? auditDuration(Number(row.age_hours), locale) : "—",
            limit,
            reason(o)]
        })
      // Shared limits retain their origin without repeating it for every guest.
      const shared = [1,4,5].filter(index => result.rows.length > 1 && result.rows.every(row => row.cells[index] === result.rows[0].cells[index]))
      result.note = shared.map(index => `${result.columns[index]}: ${result.rows[0].cells[index]}`).join(" · ")
      result.columns = result.columns.filter((_,index) => !shared.includes(index))
      result.rows.forEach(row => { row.cells = row.cells.filter((_,index) => !shared.includes(index)) })
      return [result]
    })
  }
  if (f.check_id === "backup.job_results") {
    // The PVE task list may contain dozens of repetitions of the same
    // failed job. One row per task obscures the useful facts, so retain
    // the count, time range, final status and latest UPID per guest.
    const merged = new Map<string, Record<string, unknown>>()
    for (const item of f.affected) {
      // If PVE supplied neither an id field nor a guest-bearing UPID,
      // keep the task separate rather than combining unrelated failures.
      const identity = clean(item.vmid) || clean(item.upid || item.job)
      const key = `${identity}\u0000${clean(item.status)}`
      const known = merged.get(key)
      const currentMs = auditDate(item.when)?.getTime() ?? 0
      if (!known) {
        merged.set(key, { ...item, count: 1, first_seen: item.when,
          last_seen: item.when, latest_job: item.upid || item.job,
          _first_ms: currentMs, _last_ms: currentMs })
        continue
      }
      known.count = Number(known.count || 0) + 1
      if (currentMs && (!Number(known._first_ms) || currentMs < Number(known._first_ms))) {
        known._first_ms = currentMs
        known.first_seen = item.when
      }
      if (currentMs >= Number(known._last_ms || 0)) {
        known._last_ms = currentMs
        known.last_seen = item.when
        known.latest_job = item.upid || item.job
      }
    }
    const objects = [...merged.values()].sort((a, b) =>
      Number(b._last_ms || 0) - Number(a._last_ms || 0))
    return objects.length ? [group(t("audit.classifications.warning"),
      [label("guest"), label("occurrences"), t("audit.document.firstSeen"),
       t("audit.document.lastSeen"), label("detail"), label("technical")],
      objects, o => [o.vmid === undefined || o.vmid === null ? "—" : guest(o),
        clean(o.count) || "1", auditInstant(o.first_seen, locale),
        auditInstant(o.last_seen, locale), clean(o.status) || reason(o),
        clean(o.latest_job) || "—"])] : []
  }
  // The inventory already presents these events properly: what happened,
  // how severe, how often, when it started, when it last happened and
  // what the kernel actually said. Six rows reading "sdh · still
  // reporting errors" described none of that, so the finding shows the
  // same table the inventory does, grouped by device.
  if (f.check_id === "hardware.disk_errors") {
    const devices = Array.from(new Set(f.affected.map(o => clean(o.name))))
    return devices.map(device => group(device,
      [t("audit.document.event"), t("audit.document.severity"),
       t("audit.document.occurrences"), t("audit.document.firstSeen"),
       t("audit.document.lastSeen"), t("audit.document.detail")],
      f.affected.filter(o => clean(o.name) === device),
      o => [clean(o.type) || "—",
            clean(o.severity) ? t(`audit.classifications.${
              o.severity === "critical" ? "critical" : "warning"}`) : "—",
            clean(o.count) || "—", auditInstant(o.first_seen, locale), auditInstant(o.last_seen, locale),
            clean(o.message) || "—"]))
  }
  // Lynis repeats a warning once per thing it applies to: ten
  // promiscuous interfaces are ten identical records. Printed one per
  // row under a heading that already said the same sentence, thirteen
  // warnings filled seventeen rows and a column whose only content was
  // the identifier repeated from the heading beside it. Collapsed to one
  // row per distinct warning, with how many times it was raised and what
  // it named where Lynis said so.
  if (f.check_id === "security.lynis_warnings") {
    const seen = new Map<string, Record<string, unknown>[]>()
    for (const o of f.affected) {
      const key = `${clean(o.test)}\u0000${clean(o.message)}`
      seen.set(key, [...(seen.get(key) || []), o])
    }
    const entries = [...seen.values()]
    const detailed = entries.some(items => items.some(o => clean(o.details)))
    // `occurrences` is worded for the middle of a sentence; the column
    // header the disk table already uses reads correctly on its own.
    const columns = [label("lynisTest"), label("lynisWarning"),
                     t("audit.document.occurrences")]
    return [group(label("records"), detailed ? [...columns, label("detail")] : columns,
      entries.map(items => items[0]), (o) => {
        const items = seen.get(`${clean(o.test)}\u0000${clean(o.message)}`) || [o]
        const cells = [clean(o.test) || "—", clean(o.message) || label("noDescription"),
                       String(items.length)]
        if (!detailed) return cells
        const named = [...new Set(items.map(i => clean(i.details)).filter(Boolean))]
        return [...cells, named.join(", ") || "—"]
      })]
  }
  return f.affected.length ? [group(label("records"), [label("resource"), label("fact"), label("result")], f.affected, o => {
    const details = [clean(o.volume), clean(o.version), o.hours !== undefined ? auditDuration(Number(o.hours), locale) : ""].filter(Boolean).join(" · ")
    return [resource(o), [reason(o), details].filter(Boolean).join(" · "), state(o)]
  })] : []
}

export function affectedDescription(f: PresentedFinding, t: AuditTranslate): string {
  const label = (key: string) => auditLabel(t, key)
  if (f.check_id === "backup.guest_coverage") {
    const disks = f.affected.filter(o => o.reason_key === "dataExcludedFromBackup").length
    const guests = f.affected.length - disks
    return [guests ? `${guests} ${label("unscheduled")}` : "", disks ? `${disks} ${label("excludedDisks")}` : ""].filter(Boolean).join(" · ")
  }
  return f.affected.length ? `${f.affected.length} ${label(f.check_id === "security.lynis_warnings" ? "occurrences" : "records")}` : ""
}

export function resultBreakdown(f: PresentedFinding, t: AuditTranslate): string {
  const counts = new Map<string, number>()
  for (const item of f.affected) {
    const key = clean(item.classification) || f.classification
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts].map(([key, count]) => `${count} · ${t(`audit.classifications.${key}`)}`).join(" / ")
}
