/**
 * The Audit & Report document.
 *
 * Built on the shell the SMART, Lynis and latency reports share, so a
 * reader who has seen one of those recognises this one: the same header
 * and report identifier, the same numbered sections, the same action bar
 * that disappears when the page is printed.
 *
 * What the document adds is structure. On screen findings are ordered by
 * severity because the reader is triaging; on paper the node is
 * described first — how it is built, what it connects to, what it holds
 * — and only then judged, because a finding about a bridge means little
 * to someone who has not been shown the bridge. The diagrams carry the
 * relations the inventory resolves: a list of interfaces and a list of
 * guests do not say which path a guest's traffic takes to the wire.
 *
 * The closing section states the scope: what the report covers and what
 * it does not. That statement is what makes the document usable as
 * evidence rather than a screenshot.
 */

import {
  REPORT_CSS_AUDIT, callout, card, esc, grid, heading, openReportWindow,
  renderReport, reportId, section, table, writeReport, icon,
} from "./report-shell"
import {
  clusterDiagram, findingsChart, latencyChart, networkDiagram,
  nodeArchitectureDiagram, storageDiagram,
} from "./report-diagrams"
import { parseEvidence } from "./evidence-format"
import { presentFinding, auditInstant, auditLabel, resultBreakdown, unreadSources, subscriptionLabel } from "./audit-presentation"

type Translate = (key: string, params?: Record<string, string>) => string

export interface DocumentInput {
  profile: string
  run: {
    run_id: string; started_at: number; finished_at: number | null
    // What the engine recorded about the declaration it judged against.
    metadata?: { policy?: {
      declared?: boolean; guests_declared?: number
      storages_declared?: number; thresholds_declared?: string[]
    } } | null
  } | null
  findings: Array<{
    check_id: string; area: string; severity: string
    classification: string; decision?: string
    summary_key: string | null; summary_params: Record<string, unknown>
    affected: Array<Record<string, unknown>>; evidence: string | null
    incomplete?: boolean
    sources?: Array<{ source: string; collected_at?: number; error?: string }>
    exception?: { reason: string; accepted_by: string; accepted_at: number } | null
  }>
  inventory: any | null
  t: Translate
  locale: string
}

// One scale, worst first. An observation is drawn in a neutral blue
// rather than an alarm colour: it describes the host, it is not a fault.
const ORDER = ["critical", "warning", "observation", "unverified",
               "accepted", "conformant", "not_applicable"]

const CLASS_COLOR: Record<string, string> = {
  critical: "#dc2626", warning: "#ca8a04", observation: "#3b82f6",
  unverified: "#94a3b8", accepted: "#4f46e5", conformant: "#16a34a",
  not_applicable: "#cbd5e1",
}

/** What a finding reads as once the reader's decision is applied. */
function shownAs(f: { classification: string; decision?: string }): string {
  return f.decision === "accepted" ? "accepted" : f.classification
}

function bytes(value: number | null | undefined): string {
  if (!value || value <= 0) return "—"
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
  let n = value, i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n >= 100 || i < 2 ? Math.round(n) : n.toFixed(1)} ${units[i]}`
}

/** Instants reach the document as epoch seconds or as an ISO string,
 *  depending on which store recorded them. */
function when(value: number | string | null | undefined, locale: string): string {
  return auditInstant(value, locale)
}

function chip(state: string, label: string): string {
  const mark = state === "critical" ? "×" : state === "warning" ? "!" : state === "conformant" ? "✓" : state === "observation" ? "ⓘ" : state === "unverified" ? "?" : "−"
  return `<span class="chip ${esc(state)}"><span aria-hidden="true">${mark}</span> ${esc(label)}</span>`
}

function summaryOf(f: DocumentInput["findings"][number], t: Translate,
                   breakdown = false): string {
  // The per-result breakdown belongs beside the table it describes. In
  // the one-line findings summary it replaced the sentence with a bare
  // count, which read as a broken cell next to every other row.
  if (breakdown && f.check_id === "backup.last_backup_age" && f.affected.length) {
    return resultBreakdown(f, t)
  }
  // A check that found nothing to apply to used to carry an English
  // sentence written by the engine; it now says so in the reader's own.
  if (!f.summary_key) {
    return f.classification === "not_applicable" ? t("audit.notApplicableScope") : ""
  }
  const params: Record<string, string> = {}
  for (const [k, v] of Object.entries(f.summary_params || {})) params[k] = String(v)
  const key = `audit.checks.${f.check_id}.summary.${f.summary_key}`
  const text = t(key, params)
  return text === key ? t("audit.summaryFallback") : text
}

/**
 * Evidence, rendered as the reader would want to read it rather than as
 * the check happened to serialise it.
 */
function evidenceHtml(evidence: string | null, locale: string,
                      compact?: { t: Translate; rows?: number; lines?: number; blocks?: number }): string {
  let blocks = parseEvidence(evidence, locale)
  if (blocks.length === 0) return ""
  let omitted = false
  if (compact?.blocks && blocks.length > compact.blocks) {
    blocks = blocks.slice(0, compact.blocks)
    omitted = true
  }
  const parts = blocks.map((block) => {
    const heading = block.title
      ? `<p class="evidence-title">${esc(block.title)}</p>` : ""
    if (block.kind === "table") {
      const rows = compact?.rows && block.rows.length > compact.rows
        ? (omitted = true, block.rows.slice(0, compact.rows)) : block.rows
      if (block.columns.length > 6) {
        return heading + rows.map(row => `<div class="evidence-record">` + table([], block.columns.map((column, i) => [esc(column), esc(row[i])])) + `</div>`).join("")
      }
      return heading + table(block.columns, rows.map((r) => r.map(esc)))
    }
    if (block.kind === "pairs") {
      const entries = compact?.rows && block.entries.length > compact.rows
        ? (omitted = true, block.entries.slice(0, compact.rows)) : block.entries
      return heading + table([], entries.map(([k, v]) =>
        [`<span class="muted">${esc(k)}</span>`, esc(v)]))
    }
    const lines = compact?.lines && block.lines.length > compact.lines
      ? (omitted = true, block.lines.slice(0, compact.lines)) : block.lines
    return heading + (lines.length
      ? `<ul class="evidence-list">${lines.map((l) =>
          `<li>${esc(l)}</li>`).join("")}</ul>` : "")
  })
  const notice = omitted && compact
    ? `<p class="evidence-excerpt-note">${esc(auditLabel(compact.t, "evidenceExcerpt"))}</p>` : ""
  return `<div class="evidence-block">${parts.join("")}${notice}</div>`
}

// ---------------------------------------------------------------------------
// Assessment summary
// ---------------------------------------------------------------------------

function executiveSummary(input: DocumentInput, n: number): string {
  const { findings, t, locale } = input
  const counts: Record<string, number> = {}
  for (const f of findings) {
    const shown = shownAs(f)
    counts[shown] = (counts[shown] || 0) + 1
  }

  const fails = counts.critical || 0
  const warns = counts.warning || 0
  // Coverage measures verified checks, not whether their result is favourable.
  // Decisions/acceptances never turn missing evidence into verified evidence.
  const applicable = findings.filter(f => f.classification !== "not_applicable")
  const verifiedChecks = applicable.filter(f => !f.incomplete &&
    ["critical", "warning", "observation", "conformant", "accepted"].includes(f.classification))
  const verified = verifiedChecks.length
  const incomplete = verified < applicable.length || !!(input.run && !input.run.finished_at)
  const coverage = applicable.length ? verified / applicable.length * 100 : 0
  const coverageValue = applicable.length ? `${verified}/${applicable.length}` : "—"

  const byArea: Record<string, Record<string, number>> = {}
  for (const f of findings) {
    const shown = shownAs(f)
    byArea[f.area] = byArea[f.area] || {}
    byArea[f.area][shown] = (byArea[f.area][shown] || 0) + 1
  }

  const chart = findingsChart(byArea, (a) => t(`audit.areas.${a}`), CLASS_COLOR, ORDER)
  const legend = ORDER.filter((c) => counts[c]).map((s) =>
    `<span style="display:inline-flex;align-items:center;gap:5px;margin-right:14px">
       <span style="width:10px;height:10px;border-radius:2px;display:inline-block;
             background:${CLASS_COLOR[s]}"></span>${esc(t(`audit.classifications.${s}`))}</span>`).join("")

  const body = `
  <div class="exec-box">
    <div class="audit-verification-ring">
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle cx="60" cy="60" r="54" fill="none" stroke="#e2e8f0" stroke-width="5" />
        <circle cx="60" cy="60" r="54" fill="none" stroke="currentColor" stroke-width="5"
          pathLength="100" stroke-dasharray="${coverage} 100" transform="rotate(-90 60 60)" />
      </svg>
      <div class="audit-verification-value"><strong>${coverageValue}</strong>
        <span>${esc(auditLabel(t, "verified"))}</span></div>
    </div>
    <div class="exec-text">
      <h3 class="audit-result-heading">${icon("summary", 22, "#64748b")}${esc(t("audit.document.verdictHeading"))}</h3>
      ${!findings.length ? `<p>${esc(t("audit.document.verdictText.none"))}</p>` : !applicable.length ? `<p>${esc(auditLabel(t, "noApplicable"))}</p>` : ""}
      ${incomplete ? `<p class="assessment-incomplete">${esc(auditLabel(t, "incomplete"))}</p>` : ""}
      <p class="muted">${esc(auditLabel(t, "verificationScope"))}</p>
      <p style="font-size:11px;color:#64748b;margin-top:6px">
        ${esc(t("audit.document.runAt", { date: when(input.run?.started_at, locale) }))}
      </p>
    </div>
  </div>
  <div class="audit-counters">${[
    card(t("audit.classifications.critical"), String(fails),
      { center: true, color: CLASS_COLOR.critical }),
    card(t("audit.classifications.warning"), String(warns),
      { center: true, color: CLASS_COLOR.warning }),
    card(t("audit.classifications.observation"), String(counts.observation || 0),
      { center: true, color: CLASS_COLOR.observation }),
    card(t("audit.classifications.conformant"), String(counts.conformant || 0),
      { center: true, color: CLASS_COLOR.conformant }),
    ...["unverified", "accepted", "not_applicable"].filter(c => counts[c]).map(c => card(t(`audit.classifications.${c}`), String(counts[c]), {center: true, color: CLASS_COLOR[c]})),
  ].join("")}</div>
  ${chart ? `<div class="diagram" style="margin-top:14px">
      <p class="diagram-note">${esc(t("audit.document.chartNote"))}</p>${chart}
      <div style="margin-top:10px;font-size:10px;color:#475569">${legend}</div>
    </div>` : ""}`
  const overview = findings.filter(f => !["conformant", "not_applicable"].includes(shownAs(f))).sort((a,b) => ORDER.indexOf(shownAs(a)) - ORDER.indexOf(shownAs(b)))
  const listing = overview.length ? heading(auditLabel(t, "overview"), "findings") + table(
    [auditLabel(t, "result"), t("audit.document.name"), auditLabel(t, "fact")],
    overview.map(f => [chip(shownAs(f), t(`audit.classifications.${shownAs(f)}`)),
      `<a href="#finding-${esc(f.check_id)}">${esc(t(`audit.checks.${f.check_id}.title`))}</a>`, esc(summaryOf(f,t))])) : ""
  // The list and ring share the same records, so the numerator is auditable.
  const checkList = (id: string, title: string, checks: DocumentInput["findings"]) => {
    if (!checks.length) return ""
    const sorted = [...checks].sort((a, b) =>
      t(`audit.areas.${a.area}`).localeCompare(t(`audit.areas.${b.area}`), locale) ||
      t(`audit.checks.${a.check_id}.title`).localeCompare(t(`audit.checks.${b.check_id}.title`), locale))
    return `<div class="audit-checks-inventory" id="${id}">` +
      heading(`${title} · ${checks.length}`, "summary") + table(
        [auditLabel(t, "checkName"), t("audit.document.area"), auditLabel(t, "result")],
        sorted.map(f => [
          `<a href="#finding-${esc(f.check_id)}">${esc(t(`audit.checks.${f.check_id}.title`))}</a>`,
          esc(t(`audit.areas.${f.area}`)), chip(shownAs(f), t(`audit.classifications.${shownAs(f)}`)),
        ])) + `</div>`
  }
  const checked = checkList("verified-checks", auditLabel(t, "verifiedChecks"), verifiedChecks)
  const unverified = checkList("unverified-checks", auditLabel(t, "unverifiedChecks"),
    applicable.filter(f => !verifiedChecks.includes(f)))
  const notApplicable = checkList("not-applicable-checks", t("audit.classifications.not_applicable"),
    findings.filter(f => f.classification === "not_applicable"))
  return section(n, t("audit.document.executiveSummary"), body + checked + unverified + notApplicable + listing, "summary")
}

// ---------------------------------------------------------------------------
// Identity and cluster
// ---------------------------------------------------------------------------

function identitySection(input: DocumentInput, n: number): string {
  const s = input.inventory?.sections || {}
  const id = s.identity
  const { t } = input
  if (!id) return ""
  const hw = s.hardware || {}
  const body = grid(3, [
    card(t("audit.inventory.node"), esc(id.node)),
    card(t("audit.inventory.pveVersion"), esc(String(id.pve_version || "—").match(/pve-manager\/([^/]+)/)?.[1] || id.pve_version)),
    card(t("audit.inventory.kernel"), esc(id.kernel)),
    card(t("audit.inventory.subscription"), esc(subscriptionLabel(t, id.subscription))),
    card(t("audit.inventory.cluster"), esc(id.cluster || t("audit.inventory.standalone"))),
    card(t("audit.document.system"),
      esc([hw.system?.manufacturer, hw.system?.product].filter(Boolean).join(" ") || "—")),
  ])
  return section(n, t("audit.document.nodeIdentity"), body, "node")
}

function clusterSection(input: DocumentInput, n: number): string {
  const s = input.inventory?.sections || {}
  const { t } = input
  if (!("cluster" in s)) return ""
  const cluster = s.cluster

  if (!cluster) {
    return section(n, t("audit.document.cluster"),
      callout("info", t("audit.inventory.standalone"),
              esc(t("audit.document.standaloneNote"))), "cluster")
  }

  const diagram = clusterDiagram(cluster, {
    thisNode: t("audit.document.thisNode"),
    unreachable: t("audit.document.unreachable"),
    links: t("audit.document.corosyncLinks"),
  })
  const rows = (cluster.nodes || []).map((node: any) => [
    esc(node.name) + (node.local
      ? ` <span class="muted">(${esc(t("audit.document.thisNode"))})</span>` : ""),
    esc(node.nodeid || "—"),
    esc(node.ring0_addr || "—"),
    esc(node.ring1_addr || "—"),
    node.online === false
      ? chip("warn", t("audit.document.unreachable"))
      : node.online === true ? chip("pass", t("audit.document.member")) : "—",
  ])
  const body = `
  ${grid(3, [
    card(t("audit.inventory.cluster"), esc(cluster.name)),
    card(t("audit.document.quorum"), cluster.quorate == null
      ? "—" : chip(cluster.quorate ? "pass" : "fail",
          t(cluster.quorate ? "audit.document.quorate" : "audit.document.inquorate"))),
    card(t("audit.document.votes"),
      esc(`${cluster.total_votes ?? "—"} / ${cluster.expected_votes ?? "—"}`)),
  ])}
  ${diagram ? `<div class="diagram">
      <p class="diagram-note">${esc(t("audit.document.clusterDiagramNote"))}</p>${diagram}
    </div>` : ""}
  ${table([t("audit.document.nodeName"), "nodeid", "ring0", "ring1",
           t("audit.document.state")], rows)}`
  return section(n, t("audit.document.cluster"), body, "cluster")
}

// ---------------------------------------------------------------------------
// How the node is built
// ---------------------------------------------------------------------------

function architectureSection(input: DocumentInput, n: number): string {
  const s = input.inventory?.sections || {}
  const hw = s.hardware
  const { t } = input
  if (!hw) return ""

  const cpu = hw.cpu || {}
  const mem = hw.memory || {}
  const diagram = nodeArchitectureDiagram(hw, s.identity || {}, {
    chassis: t("audit.document.board"),
    processor: t("audit.document.processor"),
    memory: t("audit.document.memory"),
    controllers: t("audit.document.controllers"),
    disks: t("audit.document.disks"),
    adapters: t("audit.document.adapters"),
    slotsUsed: t("audit.document.slotsUsed"),
    cores: t("audit.document.cores"),
    threads: t("audit.document.threads"),
    empty: t("audit.document.emptySlot"),
  })

  const identityRows = [
    [t("audit.document.manufacturer"), esc(hw.system?.manufacturer || "—")],
    [t("audit.document.product"), esc(hw.system?.product || "—")],
    [t("audit.document.serial"), esc(hw.system?.serial || "—")],
    [t("audit.document.board"),
     esc([hw.board?.manufacturer, hw.board?.product].filter(Boolean).join(" ") || "—")],
    ["BIOS", esc([hw.bios?.vendor, hw.bios?.version, hw.bios?.date]
      .filter(Boolean).join(" · ") || "—")],
  ]

  const memoryRows = (mem.modules || []).map((m: any) => [
    esc(m.locator || "—"), esc(m.size || "—"), esc(m.type || "—"),
    esc(m.form_factor || "—"), esc(m.speed || "—"),
    esc([m.manufacturer, m.part_number].filter(Boolean).join(" · ") || "—"),
  ])

  const controllerRows = (hw.controllers || []).map((c: any) => [
    `<span class="muted" style="font-family:ui-monospace,Menlo,monospace;font-size:10.5px">${esc(c.slot)}</span>`,
    esc(c.class), esc(c.name),
  ])

  const body = `
  ${grid(4, [
    card(t("audit.document.processor"), esc(cpu.model || "—")),
    card(t("audit.document.topology"),
      esc(`${cpu.sockets || 1} × ${cpu.cores_per_socket || "?"} / ${cpu.threads || "?"}`)),
    card(t("audit.document.memory"), esc(bytes(hw.memory_bytes))),
    card(t("audit.document.iommuGroups"), esc(String(hw.iommu_groups ?? "—"))),
  ])}
  ${diagram ? `<div class="diagram">
      <p class="diagram-note">${esc(t("audit.document.architectureNote"))}</p>${diagram}
    </div>` : ""}
  ${heading(t("audit.document.systemIdentity"), "node")}
  ${table([t("audit.document.field"), t("audit.document.value")], identityRows)}
  ${memoryRows.length ? `
    ${heading(t("audit.document.memoryModules"), "memory",
      t("audit.document.slotsFilled", { used: String(mem.populated ?? 0),
        total: String(mem.slots ?? mem.populated ?? 0) }))}
    ${table([t("audit.document.slot"), t("audit.document.size"), t("audit.document.type"),
             t("audit.document.formFactor"), t("audit.document.speed"),
             t("audit.document.manufacturer")], memoryRows)}` : ""}
  ${controllerRows.length ? `
    ${heading(t("audit.document.controllers"), "controller")}
    ${table(["PCI", t("audit.document.class"), t("audit.document.device")], controllerRows)}` : ""}`
  return section(n, t("audit.document.architecture"), body, "architecture")
}

// ---------------------------------------------------------------------------
// Disks, with what has been observed of them
// ---------------------------------------------------------------------------

function disksSection(input: DocumentInput, n: number): string {
  const s = input.inventory?.sections || {}
  const disks = s.hardware?.disks || []
  const { t, locale } = input
  if (!disks.length) return ""

  const rows = disks.map((d: any) => {
    const life = typeof d.power_on_hours === "number" && d.power_on_hours > 0
      ? t("audit.document.years", { years: (d.power_on_hours / 8760).toFixed(1) })
      : "—"
    // smartctl reports the overall assessment as "PASSED"; the Monitor
    // normalises some devices to "healthy".
    const ok = ["passed", "healthy", "ok"].includes(String(d.health).toLowerCase())
    const health = ok ? chip("pass", t("audit.document.healthy"))
      : d.health && d.health !== "unknown" ? chip("warn", esc(d.health)) : "—"
    return [
      `<strong>${esc(d.name)}</strong>`,
      esc(d.model || "—"),
      `<span class="muted" style="font-size:10.5px">${esc(d.serial || "—")}</span>`,
      esc(bytes(d.size_bytes)),
      esc(d.bus ? d.bus.toUpperCase() : "—") + (d.rotational ? " · HDD" : " · SSD"),
      health,
      esc(life),
      d.observations?.length
        ? chip("warn", String(d.observations.length))
        : `<span class="muted">—</span>`,
    ]
  })

  // Observations are the disk's history. SMART reports what is true now;
  // the log reports what happened. A disk that recovered still recorded
  // the event, and that pattern is what precedes a failure.
  const withEvents = disks.filter((d: any) => (d.observations || []).length)
  const observations = withEvents.map((d: any) => {
    const entries = d.observations.map((o: any) => [
      esc(o.type || "—"),
      // The stored severity is an English database value, and this page
      // exists in eight languages.
      o.severity === "critical"
        ? chip("fail", esc(t("audit.classifications.critical")))
        : o.severity ? chip("warn", esc(t("audit.classifications.warning"))) : "—",
      esc(String(o.count ?? "—")),
      esc(when(o.first_seen, locale)),
      esc(when(o.last_seen, locale)),
      `<span class="muted" style="font-size:10.5px">${esc(o.message || "")}</span>`,
    ])
    return `${heading(d.name, "disks", d.model || undefined)}
      ${table([t("audit.document.event"), t("audit.document.severity"),
               t("audit.document.occurrences"), t("audit.document.firstSeen"),
               t("audit.document.lastSeen"), t("audit.document.detail")], entries)}`
  }).join("")

  const body = `
  ${table([t("audit.document.device"), t("audit.document.model"),
           t("audit.document.serial"), t("audit.document.size"),
           t("audit.document.bus"), "SMART", t("audit.document.serviceLife"),
           t("audit.document.events")], rows)}
  ${heading(t("audit.document.observations"), "observation")}
  ${withEvents.length
    ? `<p class="diagram-note">${esc(t("audit.document.observationsNote"))}</p>${observations}`
    : callout("ok", t("audit.document.noObservations"),
              esc(t("audit.document.noObservationsNote")))}`
  return section(n, t("audit.document.storageDevices"), body, "disks")
}

// ---------------------------------------------------------------------------
// Network
// ---------------------------------------------------------------------------

function chain(hops: Array<{ id: string; mode?: string }> | null, t: Translate): string {
  if (hops === null) return `<span class="muted">${esc(t("audit.inventory.unresolved"))}</span>`
  if (hops.length === 0) return `<span class="muted">${esc(t("audit.inventory.noUplink"))}</span>`
  return hops.map((h) => esc(h.id + (h.mode ? ` · ${h.mode}` : "")))
    .join('<span class="sep">&rarr;</span>')
}

function networkSection(input: DocumentInput, n: number): string {
  const s = input.inventory?.sections || {}
  const { t } = input
  const net = s.network
  const guests = s.guests || []
  const adapters = s.hardware?.adapters || []
  if (!net && !adapters.length) return ""

  const diagram = net?.bridges
    ? networkDiagram(net.bridges, guests, {
        nic: t("audit.document.adapters"), bond: t("audit.document.bond"),
        bridge: t("audit.document.bridge"), guests: t("audit.inventory.guests"),
      })
    : ""

  const adapterRows = adapters.map((a: any) => [
    `<strong>${esc(a.name)}</strong>`,
    a.state === "up" ? chip("pass", esc(a.state)) : chip("unknown", esc(a.state || "—")),
    a.speed_mbps
      ? esc(a.speed_mbps >= 1000 ? `${a.speed_mbps / 1000} Gb/s` : `${a.speed_mbps} Mb/s`)
      : "—",
    `<span class="muted" style="font-family:ui-monospace,Menlo,monospace;font-size:10.5px">${esc(a.mac || "—")}</span>`,
    esc(a.driver || "—"),
    `<span class="muted" style="font-size:10.5px">${esc(a.pci || "—")}</span>`,
  ])

  const bridgeRows = Object.entries(net?.bridges || {}).map(([id, b]: [string, any]) => [
    `<strong>${esc(id)}</strong>`,
    chain(b.uplink ?? null, t),
    esc(String(guests.filter((g: any) =>
      (g.interfaces || []).some((i: any) => i.bridge === id)).length)),
  ])

  const body = `
  ${diagram ? `<div class="diagram">
      <p class="diagram-note">${esc(t("audit.document.networkDiagramNote"))}</p>${diagram}
    </div>` : ""}
  ${adapterRows.length ? `
    ${heading(t("audit.document.physicalAdapters"), "adapter")}
    ${table([t("audit.document.interface"), t("audit.document.state"),
             t("audit.document.speed"), "MAC", t("audit.document.driver"), "PCI"],
            adapterRows)}` : ""}
  ${bridgeRows.length ? `
    ${heading(t("audit.document.bridges"), "bridge")}
    ${table([t("audit.document.bridge"), t("audit.document.uplink"),
             t("audit.inventory.guests")], bridgeRows)}` : ""}`
  return section(n, t("audit.document.network"), body, "network")
}

function latencySection(input: DocumentInput, n: number): string {
  const s = input.inventory?.sections || {}
  const { t } = input
  const latency = s.latency
  if (!latency?.targets?.length) return ""

  // The legend reads in the reader's language, like the table under it.
  const named = latency.targets.map((target: any) => ({
    ...target, label: t(`audit.document.target.${target.target}`),
  }))
  const chart = latencyChart(named, {
    ms: t("audit.document.milliseconds"), hours: t("audit.document.hours"),
  })
  const ms = (v: number | null | undefined) =>
    typeof v === "number" ? `${v} ms` : "—"
  const rows = latency.targets.map((target: any) => [
    `<strong>${esc(t(`audit.document.target.${target.target}`))}</strong>`,
    esc(ms(target.min_ms)), esc(ms(target.avg_ms)), esc(ms(target.max_ms)),
    esc(typeof target.packet_loss === "number" ? `${target.packet_loss} %` : "—"),
    esc(String(target.samples)),
  ])

  const body = `
  ${chart ? `<div class="diagram">
      <p class="diagram-note">${esc(t("audit.document.latencyNote"))}</p>${chart}
    </div>` : ""}
  ${table([t("audit.document.target.label"), t("audit.document.minimum"),
           t("audit.document.average"), t("audit.document.maximum"),
           t("audit.document.packetLoss"), t("audit.document.samples")], rows)}`
  return section(n, t("audit.document.latency"), body, "latency")
}

// ---------------------------------------------------------------------------
// Storage and protection
// ---------------------------------------------------------------------------

function storageSection(input: DocumentInput, n: number): string {
  const s = input.inventory?.sections || {}
  const { t } = input
  const storages = s.storages || []
  const guests = s.guests || []
  if (!storages.length) return ""

  const diagram = storageDiagram(guests, {
    guests: t("audit.inventory.guests"), storage: t("audit.document.storage"),
    backup: t("audit.document.backupDestination"),
    unprotected: auditLabel(t,"noJob"),
  })

  const rows = storages.map((st: any) => [
    `<strong>${esc(st.id)}</strong>`,
    esc(st.type),
    esc(st.content || "—"),
    st.shared ? chip("pass", t("audit.document.shared")) : `<span class="muted">—</span>`,
    esc(st.server || st.path || "—"),
    esc(String(guests.filter((g: any) =>
      (g.disks || []).some((d: any) => d.storage === st.id)).length)),
  ])

  const unprotected = guests.filter((g: any) => !(g.backups || []).length)
  const selected = guests.length - unprotected.length
  const fraction = guests.length ? selected / guests.length * 100 : 0
  const capacityFinding = input.findings.find(f => f.check_id === "storage.connected_storage")
  let capacityRows: any[] = []
  try { capacityRows = JSON.parse(capacityFinding?.evidence || "{}").storages || [] } catch { /* Raw evidence stays in the appendix. */ }
  const capacity = capacityRows.filter(r => Number(r.total) > 0 && r.used != null).map(r => {
    const ratio = Math.max(0, Math.min(100, Number(r.used) / Number(r.total) * 100))
    return `<div class="capacity-item"><strong>${esc(r.storage)}</strong><span>${esc(bytes(Number(r.used)))} / ${esc(bytes(Number(r.total)))}</span><div class="audit-meter"><span style="width:${ratio}%"></span></div></div>`
  }).join("")
  const body = `
  ${guests.length ? `<div class="coverage-panel"><h3>${icon("storage")}${esc(auditLabel(t,"coverage"))}</h3>
    <div class="audit-meter"><span style="width:${fraction}%"></span></div>
    <div class="coverage-labels"><span>${selected} / ${guests.length} · ${esc(auditLabel(t,"scheduled"))}</span><span>${unprotected.length} · ${esc(auditLabel(t,"noJob"))}</span></div>
    <p class="muted">${esc(auditLabel(t,"copyScope"))}</p></div>` : ""}
  ${diagram ? `<div class="diagram">
      <p class="diagram-note">${esc(t("audit.document.storageDiagramNote"))}</p>${diagram}
    </div>` : ""}
  ${table([t("audit.document.storage"), t("audit.document.type"),
           t("audit.document.content"), t("audit.document.shared"),
           t("audit.document.location"), t("audit.inventory.guests")], rows)}
  ${capacity ? heading(auditLabel(t,"capacity"), "storage") + capacity : ""}
  ${unprotected.length
    ? callout("info", t("audit.document.unprotectedGuests",
        { count: String(unprotected.length) }),
        esc(unprotected.map((g: any) => `${g.vmid} ${g.name}`).join(" · ")))
    : callout("info", auditLabel(t,"scheduled"),
        esc(auditLabel(t,"copyScope")))}`
  return section(n, t("audit.document.storageAndProtection"), body, "storage")
}

// ---------------------------------------------------------------------------
// Guests, passthrough, managed software
// ---------------------------------------------------------------------------

function guestsSection(input: DocumentInput, n: number): string {
  const s = input.inventory?.sections || {}
  const guests = s.guests || []
  const { t } = input
  if (!guests.length) return ""

  const rows = guests.map((g: any) => [
    `<strong>${esc(String(g.vmid))}</strong>`,
    esc(g.name || "—"),
    g.type === "lxc" ? "LXC" : "VM",
    esc(String(g.cores || "—")),
    esc(g.memory ? bytes(Number(g.memory) * 1024 * 1024) : "—"),
    esc([...new Set((g.disks || []).map((d: any) => d.storage).filter(Boolean))].join(", ") || "—"),
    esc([...new Set((g.interfaces || []).map((i: any) => i.bridge).filter(Boolean))].join(", ") || "—"),
    (g.backups || []).length
      ? esc((g.backups || []).map((b: any) => b.storage).join(", "))
      : esc(auditLabel(t,"noJob")),
  ])
  return section(n, t("audit.inventory.guests"),
    table([t("audit.document.vmid"), t("audit.document.name"), t("audit.document.kind"),
           t("audit.document.cores"), t("audit.document.memory"),
           t("audit.document.storage"), t("audit.document.bridge"),
           t("audit.document.backup")], rows), "guests")
}

function passthroughSection(input: DocumentInput, n: number): string {
  const s = input.inventory?.sections || {}
  const devices = s.passthrough || []
  const { t } = input
  if (!devices.length) return ""
  const rows = devices.map((d: any) => [
    esc(String(d.vmid)),
    esc(d.guest || "—"),
    esc(d.slot || "—"),
    `<span style="font-family:ui-monospace,Menlo,monospace;font-size:10.5px">${esc(d.address || "—")}</span>`,
    esc((d.iommu_groups || []).join(", ") || "—"),
    (d.shared_group_devices || []).length
      ? chip("warn", String(d.shared_group_devices.length))
      : `<span class="muted">—</span>`,
  ])
  return section(n, t("audit.inventory.passthrough"),
    table([t("audit.document.vmid"), t("audit.document.name"), t("audit.document.slot"),
           t("audit.document.device"), t("audit.document.iommuGroup"),
           auditLabel(t,"otherDevices")], rows), "passthrough")
}

function proxmenuxSection(input: DocumentInput, n: number): string {
  const s = input.inventory?.sections || {}
  const { t } = input
  const pmx = s.proxmenux
  const apps = s.applications || []
  if (!pmx && !apps.length) return ""

  const toolRows = (pmx?.optimizations || []).map((tool: any) => {
    const pending = (pmx?.pending_updates || []).find((u: any) => u.key === tool.key)
    return [
      esc(tool.key.replace(/_/g, " ")), esc(tool.version === "True" || tool.version === "False" ? auditLabel(t,"unversioned") : tool.version || auditLabel(t,"unversioned")),
      pending ? chip("warn", t("audit.document.updateAvailable",
                              { version: String(pending.available) }))
              : esc(auditLabel(t,"noPendingRecorded")),
    ]
  })
  const appRows = apps.map((a: any) => [
    esc(a.name || "—"), esc(String(a.vmid ?? "—")),
    esc(a.version || t("audit.inventory.versionUnknown")),
  ])

  const body = `
  ${toolRows.length ? `
    ${heading(t("audit.inventory.proxmenux"), "software")}
    ${table([t("audit.document.name"), t("audit.document.version"),
             t("audit.document.state")], toolRows)}` : ""}
  ${appRows.length ? `
    ${heading(t("audit.inventory.applications"), "software")}
    ${table([t("audit.document.name"), t("audit.document.vmid"),
             t("audit.document.version")], appRows)}` : ""}`
  return section(n, t("audit.document.managedSoftware"), body, "software")
}

// ---------------------------------------------------------------------------
// Findings in full
// ---------------------------------------------------------------------------

function findingsSection(input: DocumentInput, n: number): string {
  const { findings, t, locale } = input
  if (findings.length === 0) return ""
  const areas = Array.from(new Set(findings.map((f) => f.area))).sort()
  const parts: string[] = []

  for (const area of areas) {
    // Within an area the reader still wants the worst first.
    const rows = findings.filter((f) => f.area === area)
      .sort((a, b) => ORDER.indexOf(shownAs(a)) - ORDER.indexOf(shownAs(b)))
    parts.push(`${heading(t(`audit.areas.${area}`))}`)
    for (const f of rows) {
      const groups = presentFinding(f, t, locale, input.inventory?.sections?.guests || [])
      const bits = [
        `<div class="finding-head" id="finding-${esc(f.check_id)}">`,
        chip(shownAs(f), t(`audit.classifications.${shownAs(f)}`)),
        `<span class="title">${esc(t(`audit.checks.${f.check_id}.title`))}</span>`,
        f.incomplete ? chip("unknown", t("audit.document.incomplete")) : "",
        `</div>`,
      ]
      const summary = summaryOf(f, t, true)
      if (summary) bits.push(`<p>${esc(summary)}</p>`)
      // "Could not be evaluated" describes the assessment, not the host.
      const unread = unreadSources(f.sources, t)
      if (unread) bits.push(`<p class="muted">${esc(unread)}</p>`)
      bits.push(`<p class="rationale">${esc(t(`audit.checks.${f.check_id}.rationale`))}</p>`)
      if (f.exception) {
        bits.push(`<p><strong>${esc(t("audit.detail.acceptedRisk"))}:</strong> ` +
          `${esc(f.exception.reason)} — ${esc(f.exception.accepted_by)}, ` +
          `${esc(when(f.exception.accepted_at, locale))}</p>`)
      }
      for (const group of groups) {
        bits.push(heading(group.title), group.note ? `<p class="muted">${esc(group.note)}</p>` : "", table(group.columns, group.rows.map(row => row.cells.map(esc))))
      }
      if (f.evidence && shownAs(f) === "conformant" && groups.length === 0) {
        bits.push(heading(auditLabel(t, "evidenceObserved"), "scope"),
          evidenceHtml(f.evidence, locale, { t, rows: 4, lines: 5, blocks: 3 }))
      } else if (f.evidence && f.classification !== "not_applicable") {
        bits.push(`<p class="technical-ref"><a href="#evidence-${esc(f.check_id)}">${esc(auditLabel(t,"detailsLink"))}: ${esc(f.check_id)}</a></p>`)
      }
      const rowCount = groups.reduce((total, group) => total + group.rows.length, 0)
      parts.push(`<div class="finding ${esc(shownAs(f))} ${rowCount <= 4 ? "finding-short" : "finding-long"}">${bits.join("\n")}</div>`)
    }
  }
  return section(n, t("audit.document.findings"), parts.join("\n"), "findings")
}


// ---------------------------------------------------------------------------
// Quick diagnosis
// ---------------------------------------------------------------------------

/** How many affected rows a diagnostic prints before it stops counting. */
const DIAGNOSTIC_ROW_CAP = 8

/**
 * What the host is asking its administrator to decide, and nothing else.
 *
 * The full report answers "what is this machine"; this one answers "what
 * do I do now". Everything conformant is left out on purpose: a document
 * that prints thirty passing checks to reach five failing ones makes the
 * five harder to find, which is the opposite of a diagnosis.
 */
function diagnosticSummary(input: DocumentInput, n: number): string {
  const { findings, t, locale } = input
  const acting = findings.filter((f) => ["critical", "warning"].includes(shownAs(f)))
  const counts = ["critical", "warning"].map((c) => ({
    key: c, total: findings.filter((f) => shownAs(f) === c).length,
  }))
  const node = input.inventory?.sections?.identity?.node || t("audit.document.unknownNode")
  const ran = input.run?.finished_at ?? input.run?.started_at

  const body = grid(4, [
    card(t("audit.document.node"), esc(String(node))),
    card(t("audit.document.generated"), esc(when(ran, locale))),
    ...counts.map((c) => card(t(`audit.classifications.${c.key}`), String(c.total))),
  ])
  const verdict = acting.length
    ? `<p>${esc(t("audit.document.diagnosticActing", { count: String(acting.length) }))}</p>`
    : `<p>${esc(t("audit.document.diagnosticClear"))}</p>`
  return section(n, t("audit.document.diagnosticTitle"), body + verdict, "summary")
}

/**
 * Each finding that asks for a decision, with the evidence needed to
 * take it and no more. Long tables are cut: thirty identical rows say
 * the same thing the first eight already said, and the reader who wants
 * every one of them wants the full report.
 */
function actionsSection(input: DocumentInput, n: number): string {
  const { findings, t, locale } = input
  const acting = findings
    .filter((f) => ["critical", "warning"].includes(shownAs(f)))
    .sort((a, b) => ORDER.indexOf(shownAs(a)) - ORDER.indexOf(shownAs(b)))
  if (!acting.length) return ""

  const parts = acting.map((f) => {
    const bits = [
      `<div class="finding-head" id="finding-${esc(f.check_id)}">`,
      chip(shownAs(f), t(`audit.classifications.${shownAs(f)}`)),
      `<span class="title">${esc(t(`audit.checks.${f.check_id}.title`))}</span>`,
      `<span class="muted">${esc(t(`audit.areas.${f.area}`))}</span>`,
      `</div>`,
    ]
    const summary = summaryOf(f, t)
    if (summary) bits.push(`<p>${esc(summary)}</p>`)
    const unread = unreadSources(f.sources, t)
    if (unread) bits.push(`<p class="muted">${esc(unread)}</p>`)
    bits.push(`<p class="rationale">${esc(t(`audit.checks.${f.check_id}.rationale`))}</p>`)
    for (const group of presentFinding(f, t, locale, input.inventory?.sections?.guests || [])) {
      const shown = group.rows.slice(0, DIAGNOSTIC_ROW_CAP)
      bits.push(heading(group.title),
        table(group.columns, shown.map((row) => row.cells.map(esc))))
      if (group.rows.length > shown.length) {
        bits.push(`<p class="muted">${esc(t("audit.document.diagnosticMoreRows",
          { count: String(group.rows.length - shown.length) }))}</p>`)
      }
    }
    return `<div class="finding ${esc(shownAs(f))}">${bits.join("\n")}</div>`
  })
  // The same heading the full report uses: naming the section after what
  // the reader is expected to do with it was a judgement the document
  // has no business making.
  return section(n, t("audit.document.findings"), parts.join("\n"), "findings")
}

/**
 * Readings that could not be taken. Kept because a diagnosis that hides
 * its own blind spots is worse than one that names them.
 */
function unreadSection(input: DocumentInput, n: number): string {
  const { findings, t } = input
  const unread = findings.filter((f) => f.classification === "unverified")
  if (!unread.length) return ""
  const rows = unread.map((f) => [
    esc(t(`audit.checks.${f.check_id}.title`)),
    esc(t(`audit.areas.${f.area}`)),
    esc(summaryOf(f, t)),
  ])
  return section(n, t("audit.document.diagnosticUnread"),
    table([t("audit.presentation.checkName"), t("audit.document.area"),
           auditLabel(t, "fact")], rows), "scope")
}

// ---------------------------------------------------------------------------
// Scope
// ---------------------------------------------------------------------------

function evidenceSection(input: DocumentInput, n: number): string {
  // Passing checks carry a compact evidence excerpt beside their result.
  // The appendix is reserved for findings whose evidence an operator may
  // need to investigate, which keeps a useful report from becoming dozens
  // of pages of successful raw probes.
  const rows = input.findings.filter(f => f.evidence &&
    !["conformant", "not_applicable"].includes(shownAs(f)))
  if (!rows.length) return ""
  return section(n, auditLabel(input.t,"annex"), `<p class="muted">${esc(auditLabel(input.t,"annexScope"))}</p>` + rows.map(f =>
    `<div class="technical-entry" id="evidence-${esc(f.check_id)}">` + heading(input.t(`audit.checks.${f.check_id}.title`), "scope", f.check_id) +
    evidenceHtml(f.evidence, input.locale) + `</div>`).join(""), "scope")
}

function scopeSection(input: DocumentInput, n: number): string {
  const { t, inventory } = input
  const missing = Object.entries(inventory?.unavailable || {})
  // The engine records which declaration it judged against. A report
  // that omits it reads identically whether the host was measured
  // against stated expectations or against none, and those are two
  // different reports about the same machine.
  const policy = input.run?.metadata?.policy
  const declared = policy?.declared
    ? t("audit.document.policyDeclared", {
        guests: String(policy.guests_declared ?? 0),
        storages: String(policy.storages_declared ?? 0),
        thresholds: String((policy.thresholds_declared || []).length),
      })
    : t("audit.document.policyNone")
  const body = `
  <div class="scope">
    <p style="margin:0">${esc(t("audit.document.scopeText",
      { profile: t(`audit.profile.${input.profile}`) }))}</p>
    <ul>
      <li>${esc(t("audit.document.scopeLocal"))}</li>
      <li>${esc(auditLabel(t,"readOnlyScope"))}</li>
      <li>${esc(t("audit.document.scopeMoment"))}</li>
      <li>${esc(declared)}</li>
    </ul>
    ${missing.length ? `
      <p style="margin:12px 0 4px"><strong>${esc(t("audit.document.notRead"))}</strong></p>
      <ul>${missing.map(([k, v]) =>
        `<li>${esc(k)}: ${esc(String(v))}</li>`).join("")}</ul>` : ""}
  </div>`
  return section(n, t("audit.document.scope"), body, "scope")
}

// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Focused reports: a posture header and the one panel that answers the
// report's question. A focused report opens on its verdict, not on what
// the machine is — the inventory is its own report.
// ---------------------------------------------------------------------------

/** The verdict a focused report opens on: the counts that bear on its
 *  question, phrased in its own terms. The counts are already scoped,
 *  because a focused run only ran that profile's checks. */
function postureHeader(input: DocumentInput, n: number): string {
  const { findings, t, locale } = input
  const counts: Record<string, number> = {}
  for (const f of findings) { const c = shownAs(f); counts[c] = (counts[c] || 0) + 1 }
  const fails = counts.critical || 0
  const warns = counts.warning || 0
  const applicable = findings.filter(f => f.classification !== "not_applicable")
  const verified = applicable.filter(f => !f.incomplete &&
    ["critical", "warning", "observation", "conformant", "accepted"].includes(f.classification)).length
  const incomplete = verified < applicable.length || !!(input.run && !input.run.finished_at)
  const state = fails ? "critical" : warns ? "warning"
    : counts.observation ? "observation" : "conformant"
  const headline = t(`audit.document.posture.${input.profile}`, {
    critical: String(fails), warning: String(warns),
    observation: String(counts.observation || 0),
  })
  const body = `
  <div class="exec-box posture-${esc(state)}">
    <div class="exec-text">
      <h3 class="audit-result-heading">${icon("summary", 22, CLASS_COLOR[state])}${esc(t(`audit.profile.${input.profile}`))}</h3>
      <p>${esc(headline)}</p>
      ${incomplete ? `<p class="assessment-incomplete">${esc(auditLabel(t, "incomplete"))}</p>` : ""}
      <p style="font-size:11px;color:#64748b;margin-top:6px">
        ${esc(t("audit.document.runAt", { date: when(input.run?.started_at, locale) }))}
      </p>
    </div>
  </div>
  <div class="audit-counters">${[
    card(t("audit.classifications.critical"), String(fails), { center: true, color: CLASS_COLOR.critical }),
    card(t("audit.classifications.warning"), String(warns), { center: true, color: CLASS_COLOR.warning }),
    card(t("audit.classifications.observation"), String(counts.observation || 0), { center: true, color: CLASS_COLOR.observation }),
    card(t("audit.classifications.conformant"), String(counts.conformant || 0), { center: true, color: CLASS_COLOR.conformant }),
  ].join("")}</div>`
  return section(n, t("audit.document.postureTitle"), body, "summary")
}

/** Backup coverage: the signature panel of the backup report — how many
 *  guests carry a job, drawn as a meter with the guests that carry none. */
function backupCoveragePanel(input: DocumentInput, n: number): string {
  const s = input.inventory?.sections || {}
  const guests = s.guests || []
  const { t } = input
  if (!guests.length) return ""
  const unprotected = guests.filter((g: any) => !(g.backups || []).length)
  const selected = guests.length - unprotected.length
  const fraction = guests.length ? selected / guests.length * 100 : 0
  const diagram = storageDiagram(guests, {
    guests: t("audit.inventory.guests"), storage: t("audit.document.storage"),
    backup: t("audit.document.backupDestination"), unprotected: auditLabel(t, "noJob"),
  })
  const body = `
  <div class="coverage-panel"><h3>${icon("storage")}${esc(auditLabel(t, "coverage"))}</h3>
    <div class="audit-meter"><span style="width:${fraction}%"></span></div>
    <div class="coverage-labels"><span>${selected} / ${guests.length} · ${esc(auditLabel(t, "scheduled"))}</span><span>${unprotected.length} · ${esc(auditLabel(t, "noJob"))}</span></div>
    <p class="muted">${esc(auditLabel(t, "copyScope"))}</p></div>
  ${diagram ? `<div class="diagram"><p class="diagram-note">${esc(t("audit.document.storageDiagramNote"))}</p>${diagram}</div>` : ""}
  ${unprotected.length
    ? callout("info", t("audit.document.unprotectedGuests", { count: String(unprotected.length) }),
        esc(unprotected.map((g: any) => `${g.vmid} ${g.name}`).join(" · ")))
    : callout("info", auditLabel(t, "scheduled"), esc(auditLabel(t, "copyScope")))}`
  return section(n, auditLabel(t, "coverage"), body, "storage")
}

/** Capacity meters: the signature panel of the capacity report — used
 *  against total per connected storage, read from the check's evidence. */
function capacityMetersPanel(input: DocumentInput, n: number): string {
  const { t } = input
  const finding = input.findings.find(f => f.check_id === "storage.connected_storage")
  let capacityRows: any[] = []
  try { capacityRows = JSON.parse(finding?.evidence || "{}").storages || [] } catch { /* Raw evidence stays in the appendix. */ }
  const meters = capacityRows.filter(r => Number(r.total) > 0 && r.used != null).map(r => {
    const ratio = Math.max(0, Math.min(100, Number(r.used) / Number(r.total) * 100))
    return `<div class="capacity-item"><strong>${esc(r.storage)}</strong><span>${esc(bytes(Number(r.used)))} / ${esc(bytes(Number(r.total)))}</span><div class="audit-meter"><span style="width:${ratio}%"></span></div></div>`
  }).join("")
  if (!meters) return ""
  return section(n, auditLabel(t, "capacity"), meters, "storage")
}

export function buildAuditDocument(input: DocumentInput): string {
  const { t, locale } = input
  const node = input.inventory?.sections?.identity?.node || t("audit.document.unknownNode")
  const id = reportId("AUDIT")

  // The quick diagnosis is a different document, not the same one with
  // sections withheld: it opens on what needs a decision instead of on
  // what the machine is, and it prints no inventory, no diagrams and no
  // annex. Everything is still assessed — only the printing is short.
  // Structure and configuration, with nothing assessed. The profile runs
  // no checks, so an assessment summary above it counted nothing and a
  // findings section below it listed nothing: two empty frames around
  // the only thing the reader opened this for.
  // The inventory is its own report: an assessment — the whole audit or
  // a focused one — opens on its verdict and prints no structure tables.
  // A focused report adds the one panel that answers its question, and
  // the inventory profile is the only one that documents the machine.
  const builders = input.profile === "inventory"
    ? [
      identitySection, clusterSection, architectureSection, disksSection,
      networkSection, latencySection, storageSection, guestsSection,
      passthroughSection, proxmenuxSection, scopeSection,
    ]
    : input.profile === "diagnostic"
    ? [diagnosticSummary, actionsSection, unreadSection, scopeSection]
    : input.profile === "security"
    ? [postureHeader, findingsSection, scopeSection, evidenceSection]
    : input.profile === "backup"
    ? [postureHeader, backupCoveragePanel, findingsSection, scopeSection, evidenceSection]
    : input.profile === "capacity"
    ? [postureHeader, capacityMetersPanel, disksSection, findingsSection, scopeSection, evidenceSection]
    : [executiveSummary, findingsSection, scopeSection, evidenceSection]

  // A section a profile did not ask for produces nothing, and the
  // numbering closes over the gap rather than skipping a number. Each
  // builder is therefore called once the previous one is known to have
  // produced something, not in a pass of its own.
  const sections: string[] = []
  for (const build of builders) {
    const html = build(input, sections.length + 1)
    if (html) sections.push(html)
  }
  const body = sections.join("\n").replace(/<table\b/g, '<div class="audit-table-scroll"><table').replace(/<\/table>/g, '</table></div>')

  // A document that assesses nothing should not be titled as an audit.
  const documentKey = input.profile === "diagnostic" ? "diagnostic"
    : input.profile === "inventory" ? "structure" : ""
  return renderReport({
    title: documentKey ? t(`audit.document.${documentKey}Title`) : t("audit.document.title"),
    subtitle: documentKey ? t(`audit.document.${documentKey}Subtitle`, { node })
                          : t("audit.document.subtitle", { node }),
    topBarSubtitle: node,
    meta: [
      [t("audit.document.node"), node],
      [t("audit.document.profile"), t(`audit.profile.${input.profile}`)],
      [t("audit.document.generated"), new Date().toLocaleString(locale)],
    ],
    reportId: id,
    logoUrl: `${window.location.origin}/images/proxmenux-logo.png`,
    footerLeft: `ProxMenux · ${t("audit.document.title")} · ${node}`,
    footerRight: `${id} · ${new Date().toLocaleDateString(locale)}`,
    lang: locale,
    extraCss: REPORT_CSS_AUDIT + `@page { @bottom-left { content: "ProxMenux · ${esc(String(node)).replace(/["\\\n\r]/g, " ")}"; font-size: 8pt; color: #64748b; } @bottom-right { content: counter(page) " / " counter(pages); font-size: 8pt; color: #64748b; } }`,
    body,
  })
}

/**
 * The window is opened by the caller on the click itself so the popup
 * blocker sees the gesture; the document is written into it once the
 * inventory has been fetched.
 */
export function openAuditDocument(input: DocumentInput, target: Window | null): void {
  writeReport(target, buildAuditDocument(input))
}

export { openReportWindow }
