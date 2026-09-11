/**
 * Inline SVG diagrams for the audit report.
 *
 * The inventory already resolves how the pieces of a node connect; a
 * diagram is what makes those relations legible at a glance. Drawn as
 * SVG with no dependency so the document stays self-contained and prints
 * as vector rather than as a screenshot.
 *
 * Colours come from the report stylesheet's palette so a diagram reads
 * as part of the document and not as an embedded picture.
 */

import { esc } from "./report-shell"

const INK = "#0f172a"
const MUTED = "#64748b"
const LINE = "#94a3b8"
const FILL = "#f8fafc"
const EDGE = "#e2e8f0"
const ACCENT = "#06b6d4"
const WARN = "#ca8a04"

/**
 * Approximate width of a string at a given size.
 *
 * SVG has no layout: text drawn wider than its box simply spills over
 * it. Measuring properly needs the font metrics, which are not available
 * while composing the document, so widths are estimated per character
 * class — narrow, wide and everything else — which is close enough to
 * decide where to cut.
 */
function textWidth(text: string, size: number, bold = false): number {
  let units = 0
  for (const c of text) {
    if ("iljI.,:;'|! ".includes(c)) units += 0.30
    else if ("mwMW@".includes(c)) units += 0.92
    else if (c >= "A" && c <= "Z") units += 0.68
    else if (c >= "0" && c <= "9") units += 0.56
    else units += 0.54
  }
  return units * size * (bold ? 1.06 : 1)
}

/** Cuts a label to what fits, marking the cut. */
function fit(text: string, width: number, size: number, bold = false): string {
  if (textWidth(text, size, bold) <= width) return text
  let out = text
  while (out.length > 1 && textWidth(out + "…", size, bold) > width) {
    out = out.slice(0, -1)
  }
  return out.trimEnd() + "…"
}

/**
 * Processor models carry trademark noise and a clock the diagram states
 * elsewhere. The part a reader identifies the chip by is the family and
 * the model number.
 */
export function shortenCpu(model: string): string {
  return (model || "")
    .replace(/\((?:R|TM|r|tm)\)/g, "")
    .replace(/\b(CPU|Processor)\b/gi, "")
    .replace(/\s*@.*$/, "")
    .replace(/\s{2,}/g, " ")
    .trim()
}

interface Node { id: string; label: string; sub?: string; tone?: "plain" | "accent" | "warn" }

function box(x: number, y: number, w: number, h: number, n: Node): string {
  const stroke = n.tone === "accent" ? ACCENT : n.tone === "warn" ? WARN : EDGE
  const inner = w - 12
  return `<g>
    <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="5"
          fill="${FILL}" stroke="${stroke}" stroke-width="1.5"/>
    <text x="${x + w / 2}" y="${y + (n.sub ? h / 2 - 3 : h / 2 + 4)}" text-anchor="middle"
          font-size="11" font-weight="600" fill="${INK}">${esc(fit(n.label, inner, 11, true))}</text>
    ${n.sub ? `<text x="${x + w / 2}" y="${y + h / 2 + 11}" text-anchor="middle"
          font-size="9" fill="${MUTED}">${esc(fit(n.sub, inner, 9))}</text>` : ""}
  </g>`
}

function arrow(x1: number, y1: number, x2: number, y2: number): string {
  return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${LINE}"
          stroke-width="1.4" marker-end="url(#pmx-arrow)"/>`
}

const DEFS = `<defs>
  <marker id="pmx-arrow" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="5" markerHeight="5" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="${LINE}"/>
  </marker>
</defs>`

function svg(width: number, height: number, body: string): string {
  // A viewBox with no fixed width lets the diagram scale down to a narrow
  // column, but `max-width` caps it at its own coordinate space so a
  // diagram with few elements is not scaled up until its boxes and text
  // fill the page. Centred, so a capped diagram sits under its heading.
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" role="img"
       preserveAspectRatio="xMidYMin meet"
       style="display:block;height:auto;max-width:${width}px;margin-inline:auto">${DEFS}${body}</svg>`
}

/**
 * Network path: physical interfaces, the bond that groups them when one
 * exists, each bridge and the guests attached to it. This is the chain a
 * reader would otherwise reconstruct by hand from three separate lists.
 */
export function networkDiagram(
  bridges: Record<string, any>,
  guests: Array<{ vmid: number; name: string; interfaces: Array<{ bridge: string }> }>,
  labels: { nic: string; bond: string; bridge: string; guests: string },
): string {
  const entries = Object.entries(bridges || {})
  if (entries.length === 0) return ""

  // COL_W is the column pitch and BOX_W the box itself: the difference
  // between them is the horizontal air between a box and the next, drawn
  // as the arrow. A wider pitch spreads the columns apart.
  const COL_W = 180, BOX_W = 116, BOX_H = 34, GAP_Y = 12, PAD = 12
  const rows: Array<{ nics: Node[]; bond: Node | null; bridge: Node; count: number }> = []

  for (const [id, b] of entries) {
    const hops = (b.uplink || []) as Array<{ kind: string; id: string; mode?: string }>
    const bond = hops.find((h) => h.kind === "bond")
    const nics = hops.filter((h) => h.kind === "nic")
    const attached = guests.filter((g) =>
      (g.interfaces || []).some((n) => n.bridge === id)).length
    rows.push({
      nics: nics.length ? nics.map((n) => ({ id: n.id, label: n.id }))
                        : [{ id: `${id}-none`, label: "—", tone: "warn" as const }],
      bond: bond ? { id: bond.id, label: bond.id, sub: bond.mode, tone: "accent" as const } : null,
      bridge: { id, label: id, tone: "accent" as const },
      count: attached,
    })
  }

  // A host with no bond has no bond column: keeping the caption over an
  // empty lane invites the reader to look for something that is not
  // there, and leaves the diagram a quarter wider than it needs to be.
  const hasBond = rows.some((r) => r.bond)
  const bridgeCol = hasBond ? 2 : 1
  const guestsCol = bridgeCol + 1

  const height = PAD * 2 + rows.reduce((h, r) =>
    h + Math.max(r.nics.length, 1) * (BOX_H + GAP_Y), 0)
  const width = PAD * 2 + COL_W * guestsCol + BOX_W

  let y = PAD
  const parts: string[] = []
  // Column captions
  const captions = hasBond
    ? [labels.nic, labels.bond, labels.bridge, labels.guests]
    : [labels.nic, labels.bridge, labels.guests]
  parts.push(captions.map((c, i) =>
    `<text x="${PAD + COL_W * i + BOX_W / 2}" y="${PAD - 2}" text-anchor="middle"
      font-size="9" font-weight="700" letter-spacing="0.06em"
      fill="${MUTED}">${esc(c.toUpperCase())}</text>`).join(""))
  y += 8

  for (const row of rows) {
    const block = Math.max(row.nics.length, 1) * (BOX_H + GAP_Y)
    const midY = y + block / 2 - BOX_H / 2

    row.nics.forEach((n, i) => {
      const ny = y + i * (BOX_H + GAP_Y)
      parts.push(box(PAD, ny, BOX_W, BOX_H, n))
      const target = row.bond ? PAD + COL_W : PAD + COL_W * bridgeCol
      parts.push(arrow(PAD + BOX_W, ny + BOX_H / 2, target, midY + BOX_H / 2))
    })

    if (row.bond) {
      parts.push(box(PAD + COL_W, midY, BOX_W, BOX_H, row.bond))
      parts.push(arrow(PAD + COL_W + BOX_W, midY + BOX_H / 2,
                       PAD + COL_W * bridgeCol, midY + BOX_H / 2))
    }
    parts.push(box(PAD + COL_W * bridgeCol, midY, BOX_W, BOX_H, row.bridge))
    parts.push(arrow(PAD + COL_W * bridgeCol + BOX_W, midY + BOX_H / 2,
                     PAD + COL_W * guestsCol, midY + BOX_H / 2))
    parts.push(box(PAD + COL_W * guestsCol, midY, BOX_W, BOX_H,
      { id: `${row.bridge.id}-g`, label: String(row.count), sub: labels.guests }))
    y += block
  }
  return svg(width, height + 8, parts.join(""))
}

/**
 * Where each guest's disks live, and what protects them. Storages and
 * backup destinations are drawn once with the guests that depend on
 * them, which is what turns two lists into a dependency picture.
 */
export function storageDiagram(
  guests: Array<{
    vmid: number; name: string
    disks: Array<{ storage: string | null }>
    backups: Array<{ storage: string }>
  }>,
  labels: { guests: string; storage: string; backup: string; unprotected: string },
): string {
  const storages = new Map<string, number>()
  const destinations = new Map<string, number>()
  let unprotected = 0

  for (const g of guests || []) {
    for (const storage of new Set((g.disks || []).map(d => d.storage).filter(Boolean))) {
      if (storage) storages.set(storage, (storages.get(storage) || 0) + 1)
    }
    if ((g.backups || []).length === 0) unprotected += 1
    for (const storage of new Set((g.backups || []).map(b => b.storage))) {
      destinations.set(storage, (destinations.get(storage) || 0) + 1)
    }
  }
  if (storages.size === 0) return ""

  const COL_W = 168, BOX_H = 34, GAP_Y = 12, PAD = 12
  const left = [...storages.entries()].sort()
  const right = [...destinations.entries()].sort()
  const lanes = Math.max(left.length, right.length + (unprotected ? 1 : 0), 1)
  const height = PAD * 2 + 10 + lanes * (BOX_H + GAP_Y)
  const width = COL_W * 3 + PAD * 2

  const parts: string[] = []
  parts.push([labels.storage, labels.guests, labels.backup].map((c, i) =>
    `<text x="${PAD + COL_W * i + COL_W / 2}" y="${PAD - 2}" text-anchor="middle"
      font-size="9" font-weight="700" letter-spacing="0.06em"
      fill="${MUTED}">${esc(c.toUpperCase())}</text>`).join(""))

  const centreY = PAD + 8 + (lanes * (BOX_H + GAP_Y)) / 2 - BOX_H / 2
  parts.push(box(PAD + COL_W, centreY, COL_W - 24, BOX_H, {
    id: "guests", label: String((guests || []).length), sub: labels.guests, tone: "accent",
  }))

  left.forEach(([name, count], i) => {
    const y = PAD + 8 + i * (BOX_H + GAP_Y)
    parts.push(box(PAD, y, COL_W - 24, BOX_H, { id: name, label: name, sub: `${count}` }))
    parts.push(arrow(PAD + COL_W - 24, y + BOX_H / 2, PAD + COL_W, centreY + BOX_H / 2))
  })

  right.forEach(([name, count], i) => {
    const y = PAD + 8 + i * (BOX_H + GAP_Y)
    parts.push(box(PAD + COL_W * 2, y, COL_W - 24, BOX_H,
      { id: name, label: name, sub: `${count}` }))
    parts.push(arrow(PAD + COL_W * 2 - 24, centreY + BOX_H / 2, PAD + COL_W * 2, y + BOX_H / 2))
  })

  if (unprotected > 0) {
    const y = PAD + 8 + right.length * (BOX_H + GAP_Y)
    parts.push(box(PAD + COL_W * 2, y, COL_W - 24, BOX_H, {
      id: "unprotected", label: String(unprotected), sub: labels.unprotected,
    }))
    parts.push(arrow(PAD + COL_W * 2 - 24, centreY + BOX_H / 2, PAD + COL_W * 2, y + BOX_H / 2))
  }
  return svg(width, height, parts.join(""))
}

/**
 * Findings per area and state, as a stacked bar. A table of counts is
 * exact but does not show where the weight of the assessment sits.
 */
export function findingsChart(
  byArea: Record<string, Record<string, number>>,
  areaLabel: (a: string) => string,
  stateColor: Record<string, string>,
  order: string[],
): string {
  const areas = Object.keys(byArea).sort()
  if (areas.length === 0) return ""
  const ROW_H = 26, PAD = 12, LABEL_W = 128, BAR_W = 320
  const max = Math.max(...areas.map((a) =>
    order.reduce((s, st) => s + (byArea[a][st] || 0), 0)), 1)
  const height = PAD * 2 + areas.length * ROW_H
  const width = LABEL_W + BAR_W + PAD * 2 + 30

  const parts = areas.map((a, i) => {
    const y = PAD + i * ROW_H
    let x = LABEL_W
    const total = order.reduce((s, st) => s + (byArea[a][st] || 0), 0)
    const segs = order.filter((st) => byArea[a][st]).map((st) => {
      const w = (byArea[a][st] / max) * BAR_W
      const seg = `<rect x="${x}" y="${y + 5}" width="${w}" height="14" rx="2"
        fill="${stateColor[st] || LINE}"><title>${esc(st)}: ${byArea[a][st]}</title></rect>`
      x += w
      return seg
    }).join("")
    return `<text x="${LABEL_W - 8}" y="${y + 16}" text-anchor="end" font-size="10"
        fill="${INK}">${esc(areaLabel(a))}</text>${segs}
      <text x="${x + 6}" y="${y + 16}" font-size="10" fill="${MUTED}">${total}</text>`
  })
  return svg(width, height, parts.join(""))
}

/**
 * How the node is built: the chassis and what is seated in it.
 *
 * Read left to right as the machine is assembled — processor and memory
 * on the board, the controllers the board exposes, and what hangs off
 * each controller. Drawn as nested frames rather than as a graph,
 * because containment is what the reader is being told: this disk is
 * behind that controller, these modules sit in those slots.
 */
export function nodeArchitectureDiagram(
  hw: any,
  identity: { node?: string; pve_version?: string },
  labels: {
    chassis: string; processor: string; memory: string
    controllers: string; disks: string; adapters: string
    slotsUsed: string; cores: string; threads: string; empty: string
  },
): string {
  if (!hw) return ""

  const PAD = 14, W = 860
  const parts: string[] = []
  let y = PAD + 18

  const frame = (title: string, x: number, w: number, top: number, h: number) => {
    parts.push(`<rect x="${x}" y="${top}" width="${w}" height="${h}" rx="7"
      fill="none" stroke="${EDGE}" stroke-width="1.5"/>
      <rect x="${x + 12}" y="${top - 6}" width="${title.length * 6.2 + 12}" height="12"
        fill="#ffffff"/>
      <text x="${x + 18}" y="${top + 3}" font-size="9" font-weight="700"
        letter-spacing="0.08em" fill="${MUTED}">${esc(title.toUpperCase())}</text>`)
  }

  const chip = (x: number, top: number, w: number, h: number,
                title: string, lines: string[], tone: "plain" | "accent" | "warn" = "plain") => {
    const stroke = tone === "accent" ? ACCENT : tone === "warn" ? WARN : EDGE
    const inner = w - 12
    parts.push(`<rect x="${x}" y="${top}" width="${w}" height="${h}" rx="5"
      fill="${FILL}" stroke="${stroke}" stroke-width="1.5"/>
      <text x="${x + w / 2}" y="${top + 15}" text-anchor="middle" font-size="10.5"
        font-weight="600" fill="${INK}">${esc(fit(title, inner, 10.5, true))}</text>` +
      lines.map((l, i) => `<text x="${x + w / 2}" y="${top + 29 + i * 11}"
        text-anchor="middle" font-size="9" fill="${MUTED}">${esc(fit(l, inner, 9))}</text>`).join(""))
  }

  // Board: processor and memory slots.
  const cpu = hw.cpu || {}
  const mem = hw.memory || {}
  const modules: any[] = mem.modules || []
  const slots = mem.slots || modules.length
  const boardH = 76
  frame(labels.chassis, PAD, W - PAD * 2, y, boardH)

  const model = shortenCpu(cpu.model) || labels.processor
  const cpuW = Math.min(250, Math.max(150, textWidth(model, 10.5, true) + 20))
  chip(PAD + 14, y + 14, cpuW, 48, model, [
    `${cpu.sockets || 1} × ${cpu.cores_per_socket || "?"} ${labels.cores}`,
    `${cpu.threads || "?"} ${labels.threads}`,
  ], "accent")

  // One tile per slot, so an empty slot is as visible as a filled one.
  // The tiles share what the processor leaves, gaps included, so a board
  // with many slots narrows them rather than dropping the last one.
  const count = Math.max(slots, modules.length, 1)
  const slotArea = W - PAD * 2 - cpuW - 42
  const tileW = Math.min(96, Math.max(34, (slotArea - (count - 1) * 6) / count))
  for (let i = 0; i < count; i++) {
    const m = modules[i]
    const x = PAD + 28 + cpuW + i * (tileW + 6)
    if (x + tileW > W - PAD - 8) break
    chip(x, y + 14, tileW, 48, m ? String(m.size || "") : labels.empty,
      m ? [String(m.type || ""), String(m.speed || "")] : [],
      m ? "plain" : "warn")
  }
  parts.push(`<text x="${W - PAD - 6}" y="${y + boardH + 12}" text-anchor="end"
    font-size="9" fill="${MUTED}">${esc(labels.memory)}: ${mem.populated || 0}/${slots || "?"} ${esc(labels.slotsUsed)}</text>`)
  y += boardH + 26

  // Controllers, with what each one carries underneath.
  const controllers: any[] = hw.controllers || []
  const disks: any[] = hw.disks || []
  const adapters: any[] = hw.adapters || []
  const byBus = new Map<string, any[]>()
  for (const d of disks) {
    const bus = d.bus || labels.disks
    byBus.set(bus, [...(byBus.get(bus) || []), d])
  }

  const groups: Array<{ title: string; sub: string; items: string[] }> = []
  for (const [bus, list] of [...byBus.entries()].sort()) {
    const kind = bus === "nvme" ? "Non-Volatile memory controller"
               : bus === "sata" ? "SATA controller" : ""
    const count = controllers.filter((c) => c.class === kind).length
    groups.push({
      title: bus.toUpperCase(),
      sub: count ? `${count} ${labels.controllers.toLowerCase()}` : labels.controllers.toLowerCase(),
      items: list.map((d) => `${d.name} · ${d.rotational ? "HDD" : "SSD"}`),
    })
  }
  if (adapters.length) {
    groups.push({
      title: labels.adapters.toUpperCase(),
      sub: `${adapters.length}`,
      items: adapters.map((a) =>
        `${a.name}${a.speed_mbps ? ` · ${a.speed_mbps >= 1000
          ? `${a.speed_mbps / 1000}G` : `${a.speed_mbps}M`}` : ""}`),
    })
  }
  if (groups.length === 0) return svg(W, y + PAD, parts.join(""))

  const colW = (W - PAD * 2 - (groups.length - 1) * 10) / groups.length
  const rows = Math.max(...groups.map((g) => g.items.length))
  const groupH = 34 + Math.min(rows, 8) * 15 + 10
  groups.forEach((g, i) => {
    const x = PAD + i * (colW + 10)
    parts.push(`<rect x="${x}" y="${y}" width="${colW}" height="${groupH}" rx="6"
      fill="none" stroke="${EDGE}" stroke-width="1.5"/>
      <rect x="${x}" y="${y}" width="${colW}" height="24" rx="6" fill="${FILL}"/>
      <text x="${x + colW / 2}" y="${y + 16}" text-anchor="middle" font-size="10"
        font-weight="700" fill="${INK}">${esc(fit(g.title, colW - 12, 10, true))}</text>` +
      g.items.slice(0, 8).map((item, j) =>
        `<text x="${x + 10}" y="${y + 39 + j * 15}" font-size="9.5"
          fill="${MUTED}">${esc(fit(item, colW - 20, 9.5))}</text>`).join("") +
      (g.items.length > 8
        ? `<text x="${x + 10}" y="${y + 39 + 8 * 15}" font-size="9" fill="${MUTED}">+${g.items.length - 8}</text>`
        : ""))
    // Tie each group back to the board it hangs from.
    parts.push(`<line x1="${x + colW / 2}" y1="${y - 12}" x2="${x + colW / 2}" y2="${y}"
      stroke="${LINE}" stroke-width="1.2"/>`)
  })
  return svg(W, y + groupH + PAD, parts.join(""))
}

/**
 * Cluster membership: every configured node, which one this report
 * describes, and whether the node currently sees it.
 */
export function clusterDiagram(
  cluster: any,
  labels: { thisNode: string; unreachable: string; links: string },
): string {
  if (!cluster || !(cluster.nodes || []).length) return ""
  const nodes: any[] = cluster.nodes
  const PAD = 16, BOX_W = 132, BOX_H = 46, GAP = 16
  const perRow = Math.min(nodes.length, 5)
  const rowCount = Math.ceil(nodes.length / perRow)
  const width = PAD * 2 + perRow * BOX_W + (perRow - 1) * GAP
  const busY = PAD + 22
  const height = busY + 26 + rowCount * (BOX_H + 26) + PAD

  const parts: string[] = []
  // The corosync ring, drawn as the bus every node attaches to.
  parts.push(`<line x1="${PAD}" y1="${busY}" x2="${width - PAD}" y2="${busY}"
    stroke="${ACCENT}" stroke-width="2"/>
    <text x="${PAD}" y="${busY - 7}" font-size="9" font-weight="700"
      letter-spacing="0.08em" fill="${MUTED}">${esc(
        `${cluster.name} · ${cluster.links || 1} ${labels.links}`.toUpperCase())}</text>`)

  nodes.forEach((n, i) => {
    const row = Math.floor(i / perRow), col = i % perRow
    const x = PAD + col * (BOX_W + GAP)
    const y = busY + 26 + row * (BOX_H + 26)
    parts.push(`<line x1="${x + BOX_W / 2}" y1="${busY}" x2="${x + BOX_W / 2}" y2="${y}"
      stroke="${LINE}" stroke-width="1.2"/>`)
    const offline = n.online === false
    const stroke = offline ? WARN : n.local ? ACCENT : EDGE
    parts.push(`<rect x="${x}" y="${y}" width="${BOX_W}" height="${BOX_H}" rx="6"
      fill="${FILL}" stroke="${stroke}" stroke-width="${n.local ? 2 : 1.5}"/>
      <text x="${x + BOX_W / 2}" y="${y + 19}" text-anchor="middle" font-size="11"
        font-weight="600" fill="${INK}">${esc(n.name)}</text>
      <text x="${x + BOX_W / 2}" y="${y + 32}" text-anchor="middle" font-size="9"
        fill="${MUTED}">${esc(n.ring0_addr || "")}</text>
      <text x="${x + BOX_W / 2}" y="${y + 42}" text-anchor="middle" font-size="8.5"
        fill="${offline ? WARN : MUTED}">${esc(
          offline ? labels.unreachable : n.local ? labels.thisNode : `id ${n.nodeid}`)}</text>`)
  })
  return svg(width, height, parts.join(""))
}

/**
 * Latency over the reported window, one line per target.
 *
 * Averages say what is normal; the shape says whether it stayed that
 * way. A table of min/avg/max cannot show a link that was fine except
 * for twenty minutes, which is the reading the chart exists for.
 */
export function latencyChart(
  targets: Array<{
    target: string; label?: string
    series: Array<{ t: number; v: number; max?: number | null }>
  }>,
  labels: { ms: string; hours: string },
): string {
  const drawn = targets.filter((t) => (t.series || []).length > 1)
  if (drawn.length === 0) return ""

  const PAD = 12, LEFT = 46, BOTTOM = 24, W = 760, H = 210
  const plotW = W - LEFT - PAD, plotH = H - PAD - BOTTOM
  const all = drawn.flatMap((t) => t.series)
  const times = all.map((s) => s.t)
  const t0 = Math.min(...times), t1 = Math.max(...times)
  // The ceiling covers the peaks, so the chart cannot disagree with the
  // maximum the table reports.
  const peak = Math.max(...all.map((s) => Math.max(s.v, s.max ?? 0)), 1)
  const top = niceCeiling(peak)

  const colors = [ACCENT, "#7c3aed", "#ca8a04"]
  const x = (t: number) => LEFT + (t1 === t0 ? plotW : ((t - t0) / (t1 - t0)) * plotW)
  const y = (v: number) => PAD + plotH - (Math.min(v, top) / top) * plotH

  const parts: string[] = []
  for (let i = 0; i <= 4; i++) {
    const value = (top / 4) * i
    const gy = y(value)
    parts.push(`<line x1="${LEFT}" y1="${gy}" x2="${W - PAD}" y2="${gy}"
        stroke="${EDGE}" stroke-width="1"/>
      <text x="${LEFT - 6}" y="${gy + 3}" text-anchor="end" font-size="9"
        fill="${MUTED}">${axisLabel(value)}</text>`)
  }
  parts.push(`<text x="${PAD - 4}" y="${PAD + 4}" font-size="9" fill="${MUTED}">${esc(labels.ms)}</text>`)

  drawn.forEach((t, i) => {
    const color = colors[i % colors.length]
    const points = t.series
    // The band spans each sample's peak, the line its average: one shows
    // what the link usually does, the other what it did at worst.
    if (points.some((s) => typeof s.max === "number")) {
      const area = points.map((s, j) =>
        `${j === 0 ? "M" : "L"}${x(s.t).toFixed(1)} ${y(s.max ?? s.v).toFixed(1)}`).join(" ")
      const back = points.slice().reverse().map((s) =>
        `L${x(s.t).toFixed(1)} ${y(s.v).toFixed(1)}`).join(" ")
      parts.push(`<path d="${area} ${back} Z" fill="${color}" fill-opacity="0.13"
          stroke="none"/>`)
    }
    const line = points
      .map((s, j) => `${j === 0 ? "M" : "L"}${x(s.t).toFixed(1)} ${y(s.v).toFixed(1)}`)
      .join(" ")
    parts.push(`<path d="${line}" fill="none" stroke="${color}"
        stroke-width="1.4" stroke-linejoin="round"/>`)

    const legendX = LEFT + i * 150
    parts.push(`<rect x="${legendX}" y="${H - 13}" width="9" height="3" rx="1.5"
        fill="${color}"/>
      <text x="${legendX + 14}" y="${H - 9}" font-size="9"
        fill="${MUTED}">${esc(fit(t.label || t.target, 130, 9))}</text>`)
  })

  const span = Math.max(1, Math.round((t1 - t0) / 3600))
  parts.push(`<text x="${W - PAD}" y="${H - 9}" text-anchor="end" font-size="9"
      fill="${MUTED}">${esc(`${span} ${labels.hours}`)}</text>`)
  return svg(W, H, parts.join(""))
}

/** A ceiling that divides into four readable gridlines. */
function niceCeiling(peak: number): number {
  const magnitude = Math.pow(10, Math.floor(Math.log10(peak)))
  for (const step of [1, 2, 2.5, 5, 10]) {
    const candidate = step * magnitude
    if (candidate >= peak) return candidate
  }
  return 10 * magnitude
}

function axisLabel(value: number): string {
  if (value === 0) return "0"
  // Gridlines land on quarters of the ceiling, so halves are common;
  // rounding them away would put a label where the line is not.
  return String(Number(value.toFixed(Number.isInteger(value) ? 0 : 1)))
}
