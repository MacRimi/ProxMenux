"use client"

// Network flow diagram — proof of concept.
// Shows NICs → host → bridges → guests with animated rx/tx pulses.
// SVG-based so it scales cleanly and animates with CSS keyframes.

import { useEffect, useMemo, useRef, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card"
import { Activity } from "lucide-react"

// One animated comet-trail pulse. Returned as DATA from the layout
// renderers instead of an SVG string so the parent component can
// render them as JSX <path>s and preserve DOM identity across
// re-renders — otherwise replacing the SVG via innerHTML restarts
// every CSS animation, producing the visible "rebound" effect.
type PulseData = {
  d: string
  type: "rx" | "tx"
  strokeWidth: number
  animDur?: number
  key: string
  // Combined rx+tx rate of the originating guest, in MB/s. Used to
  // escalate the head's glow when a guest is a heavy consumer
  // (1 MB/s → warm, 30 MB/s → hot).
  rate?: number
}

// ─── Public types — match the /api/network shape ────────────
type NIC = {
  id: string
  link: string
  rx: number   // MB/s
  tx: number
  status?: "up" | "down"   // present → drives the active state instead of the rate
  // Set when this NIC is enslaved to a bond. The diagram then routes it
  // through the bond node instead of straight to the host.
  bond?: string
  // Current role INSIDE the bond, re-read on every poll so a failover
  // flips the labels. "member" = every slave transmits (LACP, balance-*),
  // so no active/standby distinction exists.
  role?: "active" | "standby" | "member"
}
type Bond = {
  id: string
  mode?: string           // "active-backup", "balance-alb", "802.3ad", …
  rx: number
  tx: number
  status?: "up" | "down"
}
type Bridge = {
  id: string
  parent?: string
}
type Guest = {
  id: string
  label: string
  kind: "lxc" | "vm" | "host"
  bridge: string
  rx: number
  tx: number
  offline?: boolean
}
export type NetworkFlowData = {
  nics: NIC[]
  bonds?: Bond[]
  bridges: Bridge[]
  consumers: Guest[]   // includes the host pseudo-entry
}

// ─── Lucide icon paths inlined (we render them as raw <path>) ──
const ICONS: Record<string, string> = {
  nic: `<path d="m15 20 3-3h2a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h2l3 3z"/><path d="M6 8v1"/><path d="M10 8v1"/><path d="M14 8v1"/><path d="M18 8v1"/>`,
  bridge: `<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>`,
  host: `<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>`,
  // Router — same glyph the interface cards use for a bond, so the node
  // in the diagram and the row in the list read as the same thing.
  bond: `<rect width="20" height="8" x="2" y="14" rx="2"/><path d="M6.01 18H6"/><path d="M10.01 18H10"/><path d="M15 10v4"/><path d="M17.84 7.17a4 4 0 0 0-5.66 0"/><path d="M20.66 4.34a8 8 0 0 0-11.31 0"/>`,
  lxc: `<path d="M22 7.7c0-.6-.4-1.2-.8-1.5l-6.3-3.9a1.72 1.72 0 0 0-1.7 0l-10.3 6c-.5.2-.9.8-.9 1.4v6.6c0 .5.4 1.2.8 1.5l6.3 3.9a1.72 1.72 0 0 0 1.7 0l10.3-6c.5-.3.9-1 .9-1.5Z"/><path d="M10 21.9V14L2.1 9.1"/><path d="m10 14 11.9-6.9"/><path d="M14 19.8v-8.1"/><path d="M18 17.5V9.4"/>`,
  vm: `<rect width="20" height="8" x="2" y="2" rx="2"/><rect width="20" height="8" x="2" y="14" rx="2"/><path d="M6 6h.01"/><path d="M6 18h.01"/>`,
}

const COLORS = {
  host: "var(--amber-500, #f59e0b)",
  lxc: "var(--cyan-500, #06b6d4)",
  vm: "var(--purple-500, #a855f7)",
  nic: "var(--amber-500, #f59e0b)",
  // Warm like the NICs (both live on the physical side of the topology)
  // but clearly its own hue, so the aggregation node doesn't read as
  // just another NIC.
  bond: "var(--orange-500, #f97316)",
  bridge: "var(--cyan-500, #06b6d4)",
  gray: "#525252",
}

// Bond membership resolved once and shared by both layouts. Only bonds
// that actually have a rendered slave are kept — an orphan bond node
// with nothing feeding it would be noise.
function resolveBonds(data: NetworkFlowData): {
  bonds: Bond[]
  bondOfNic: Map<string, string>
  nics: NIC[]
} {
  const declared = data.bonds || []
  const byId = new Map(declared.map((b) => [b.id, b]))
  const bondOfNic = new Map<string, string>()
  data.nics.forEach((n) => {
    if (n.bond && byId.has(n.bond)) bondOfNic.set(n.id, n.bond)
  })
  const bonds = declared.filter((b) =>
    data.nics.some((n) => bondOfNic.get(n.id) === b.id)
  )
  // Group slaves of the same bond together so its node sits next to the
  // NICs feeding it and the links don't cross unrelated ones. Array sort
  // is stable, so NICs within a group keep their backend order.
  const nics = [...data.nics].sort((a, b) => {
    const ba = bondOfNic.get(a.id) || ""
    const bb = bondOfNic.get(b.id) || ""
    if (ba === bb) return 0
    if (!ba) return 1     // unbonded NICs last
    if (!bb) return -1
    return ba < bb ? -1 : 1
  })
  return { bonds, bondOfNic, nics }
}

// Sub-label under a NIC. In active-backup the role is the useful bit
// (which cable is actually carrying traffic right now); in every other
// mode all slaves transmit, so the link speed stays.
function nicSubLabel(n: NIC): string {
  if (n.status === "down") return "down"
  const role = n.role === "standby" || n.role === "active" ? n.role : ""
  if (!role) return n.link
  // A NIC that doesn't report a negotiated speed renders its link as
  // "—"; pairing that with the role would read as "— · active".
  if (!n.link || n.link === "—") return role
  return `${n.link} · ${role}`
}

function fmt(v: number): string {
  if (!v) return "0 B/s"
  // Below 1 KB/s show B/s — the previous "—" hid real-but-low traffic.
  if (v < 0.001) return `${Math.round(v * 1024 * 1024)} B/s`
  if (v < 1) return `${(v * 1024).toFixed(0)} KB/s`
  return `${v.toFixed(1)} MB/s`
}
// "Active" = running guest, regardless of current rate. Lab hosts can
// have idle guests we still want to see in the topology. The previous
// 50 KB/s threshold hid everything on a quiet host like .1.10.
function activeConsumers(consumers: Guest[]): Guest[] {
  return consumers
    .filter((c) => !c.offline && c.kind !== "host")
    .sort((a, b) => a.id.localeCompare(b.id))
}
// Bridges without ANY active guest are hidden — the diagram stays
// focused on the parts of the topology that actually carry traffic.
function visibleBridges(bridges: Bridge[], guests: Guest[]): Bridge[] {
  const used = new Set(guests.map((c) => c.bridge))
  return bridges.filter((b) => used.has(b.id))
}

function svgIcon(kind: string, cx: number, cy: number, size: number, color: string): string {
  const half = size / 2
  const path = ICONS[kind] || ""
  return `<g transform="translate(${cx - half}, ${cy - half}) scale(${size / 24})">
    <g class="nf-icon" stroke="${color}">${path}</g>
  </g>`
}

function orthLink(x1: number, y1: number, x2: number, y2: number, r = 12): string {
  if (Math.abs(y2 - y1) < 2) return `M ${x1} ${y1} L ${x2} ${y2}`
  const midX = (x1 + x2) / 2
  const dy = y2 > y1 ? 1 : -1
  return [
    `M ${x1} ${y1}`,
    `L ${midX - r} ${y1}`,
    `Q ${midX} ${y1} ${midX} ${y1 + dy * r}`,
    `L ${midX} ${y2 - dy * r}`,
    `Q ${midX} ${y2} ${midX + r} ${y2}`,
    `L ${x2} ${y2}`,
  ].join(" ")
}
function orthLinkV(x1: number, y1: number, x2: number, y2: number, r = 10): string {
  if (Math.abs(x2 - x1) < 2) return `M ${x1} ${y1} L ${x2} ${y2}`
  const midY = (y1 + y2) / 2
  const dx = x2 > x1 ? 1 : -1
  return [
    `M ${x1} ${y1}`,
    `L ${x1} ${midY - r}`,
    `Q ${x1} ${midY} ${x1 + dx * r} ${midY}`,
    `L ${x2 - dx * r} ${midY}`,
    `Q ${x2} ${midY} ${x2} ${midY + r}`,
    `L ${x2} ${y2}`,
  ].join(" ")
}

// Build the COMPLETE flow path for one guest: host → bridge → bus →
// tap → guest. One SVG path concatenating each segment so a single
// pulse can travel end-to-end with that guest's own speed.
function buildFullFlowPath(
  hostX: number, hostY: number, radHost: number,
  bridgesX: number, bridgeY: number, radBridge: number,
  busX0: number, busY: number,
  cx: number, targetY: number, tapR: number,
): string {
  const hbPath = orthLink(hostX + radHost, hostY, bridgesX - radBridge, bridgeY, 14)
  const bbPath = orthLink(bridgesX + radBridge, bridgeY, busX0, busY, 12)
  const dy = targetY > busY ? 1 : -1
  const tail = `L ${cx - tapR} ${busY} Q ${cx} ${busY} ${cx} ${busY + dy * tapR} L ${cx} ${targetY}`
  return `${hbPath} ${bbPath} ${tail}`
}
function curvedTap(cx: number, busY: number, targetY: number, r = 14): string {
  const dy = targetY > busY ? 1 : -1
  return `M ${cx - r} ${busY} Q ${cx} ${busY} ${cx} ${busY + dy * r} L ${cx} ${targetY}`
}

// ─── Renderer: returns full SVG markup string for a given width ──
function renderHorizontal(data: NetworkFlowData, W: number): { svg: string; pulses: PulseData[]; height: number } {
  const top = activeConsumers(data.consumers)
  const bridges = visibleBridges(data.bridges, top)
  const host = data.consumers.find((c) => c.kind === "host")
  const { bonds, bondOfNic, nics } = resolveBonds(data)

  const tight = W < 1100
  const nicX = tight ? 70 : 90
  const hostX = tight ? 280 : 340
  const bridgesX = tight ? 470 : 540
  const busX0 = tight ? 580 : 660
  const busXEnd = W - 40
  const busAvail = busXEnd - busX0

  const radNic = tight ? 26 : 30
  const radHost = tight ? 38 : 44
  const radBridge = tight ? 22 : 26
  const radGuest = 22
  const radBond = tight ? 22 : 26
  // Bond column sits halfway between the NICs and the host — the gap
  // between those two columns was already wide enough to host it, so
  // nothing downstream (bridges, bus, guests) has to move.
  const bondX = Math.round((nicX + hostX) / 2)

  // More vertical breathing room around each guest. The previous 110
  // crammed circle+label+sub close to the bus; bumping to 135 lets
  // the text halo fully clear the trunk pulses behind it.
  const topCellH = 135
  // Bot was 135; bumped to 160 because we moved the bot guest 30 px
  // further from the bus so the tap beam has room to flow.
  const botCellH = 160
  const minCellW = 140
  const maxGuestsPerRow = Math.max(2, Math.floor(busAvail / minCellW))

  // Sort bridges so the ones WITH guests come first. Idle bridges
  // sit compactly at the top (just below the host) and don't push
  // anything below them down the canvas.
  const bridgesSorted = [...bridges].sort((a, b) => {
    const aN = top.filter((c) => c.bridge === a.id).length
    const bN = top.filter((c) => c.bridge === b.id).length
    return bN - aN
  })

  let cursorY = 40
  const sections = bridgesSorted.map((b) => {
    const guests = top.filter((c) => c.bridge === b.id)
    const pairsPerBus = maxGuestsPerRow
    const totalPairs = Math.ceil(guests.length / 2)
    const busRowCount = totalPairs > 0 ? Math.ceil(totalPairs / pairsPerBus) : 0
    const buses: Array<{
      pairs: Array<{ top: Guest | null; bot: Guest | null }>
      busY: number
      cellW: number
    }> = []
    for (let r = 0; r < busRowCount; r++) {
      const sliceStart = r * pairsPerBus * 2
      const slice = guests.slice(sliceStart, sliceStart + pairsPerBus * 2)
      const pairs: Array<{ top: Guest | null; bot: Guest | null }> = []
      for (let p = 0; p < Math.ceil(slice.length / 2); p++) {
        pairs.push({ top: slice[p * 2] || null, bot: slice[p * 2 + 1] || null })
      }
      const cellCount = pairs.length
      const cellW = Math.max(minCellW, Math.min(220, busAvail / Math.max(1, cellCount)))
      const busY = cursorY + topCellH
      buses.push({ pairs, busY, cellW })
      cursorY += topCellH + botCellH
    }
    let sectionTop: number, sectionBot: number, bridgeY: number
    if (buses.length > 0) {
      sectionTop = buses[0].busY - topCellH
      sectionBot = cursorY
    } else {
      // Compact slot for an idle bridge — just enough for the circle
      // + label + sub. Previous 100 px was wasted space and pushed
      // sibling bridges far below.
      sectionTop = cursorY
      sectionBot = cursorY + 60
      cursorY = sectionBot
    }
    bridgeY = (sectionTop + sectionBot) / 2
    cursorY += 8
    return { b, guests, buses, sectionTop, sectionBot, bridgeY }
  })

  const nicCount = nics.length
  // Vertical pitch per NIC = circle + label + sub + breathing
  // room. Was 118; bumped to 132 because the new 9-px-wide trunk
  // line passing near sibling NICs ate into the label/sub area
  // visually (the line and the text were "stuck" together).
  const nicPitchMin = 132
  const nicMinH = 80 + nicCount * nicPitchMin
  const H = Math.max(220, nicMinH, cursorY + 20)
  const sectionsTop = sections.length ? sections[0].sectionTop : 40
  const sectionsBot = sections.length ? sections[sections.length - 1].sectionBot : H - 40
  const hostY = sections.length ? (sectionsTop + sectionsBot) / 2 : H / 2
  // Always at least nicPitchMin between NICs so labels/subs never collide.
  const nicSpacing = Math.max(nicPitchMin, Math.min(140, H / Math.max(1, nicCount + 1)))
  // Center the NIC stack VERTICALLY in the canvas — anchoring it to
  // hostY (which itself anchors to the centre of the bridge grid)
  // produced an asymmetric column on hosts where the bridge grid
  // sits high (e.g. .1.10): first NIC stuck to the top, big empty
  // space below the last NIC.
  const nicStackH = (nicCount - 1) * nicSpacing
  const nicY0 = Math.max(radNic + 8, (H - nicStackH) / 2)

  // Split into two layers so EVERY static line is drawn before EVERY
  // pulse. Otherwise a later-drawn static path (e.g. ens4f2's grey
  // trunk) covers the pulses of earlier paths sharing its column,
  // making them "fade to grey".
  const linksStatic: string[] = []
  const linksPulse: PulseData[] = []
  const nodes: string[] = []

  const nicYById = new Map<string, number>()
  nics.forEach((n, i) => {
    const y = nicY0 + i * nicSpacing
    nicYById.set(n.id, y)
    // NIC is "active" when the kernel reports the link up — independent
    // of current rate (a NIC with 100 B/s of background traffic should
    // not render as gray).
    const active = n.status ? n.status === "up" : n.rx + n.tx > 0
    const stroke = active ? COLORS.nic : COLORS.gray
    // A healthy standby is NOT a fault: it keeps its colour and is only
    // slightly dimmed, so it stays clearly distinct from a down link.
    const opacity = !active ? 0.45 : n.role === "standby" ? 0.72 : 1
    nodes.push(`<g data-node-id="${n.id}" data-node-kind="nic" style="cursor:pointer;opacity:${opacity}">
      <circle class="nf-circle" cx="${nicX}" cy="${y}" r="${radNic}" stroke="${stroke}" />
      ${svgIcon("nic", nicX, y, 18, stroke)}
      <text class="nf-label" x="${nicX}" y="${y + radNic + 14}">${n.id}</text>
      <text class="nf-sub"   x="${nicX}" y="${y + radNic + 26}">${nicSubLabel(n)}</text>
    </g>`)
  })

  // Bond node — vertically centred on the slaves feeding it, but lifted
  // when unbonded NICs are also present. Those run their own trunk up to
  // the host, and orthLink turns them at the midpoint of the NIC→host
  // gap — which is the bond's own column. Their vertical leg therefore
  // occupies everything BELOW hostY at that x, so the bond's three-line
  // label has to sit above hostY to stay out of it. With every NIC in a
  // bond there is no such trunk and the node keeps its natural centre.
  const BOND_TEXT_BLOCK = 38          // label + mode + rate under the circle
  const hasLooseNics = nics.some((n) => !bondOfNic.has(n.id))
  const bondCeiling = hostY - radBond - BOND_TEXT_BLOCK - 16
  const bondYById = new Map<string, number>()
  bonds.forEach((b) => {
    const ys = nics
      .filter((n) => bondOfNic.get(n.id) === b.id)
      .map((n) => nicYById.get(n.id) as number)
    if (!ys.length) return
    const centre = ys.reduce((a, v) => a + v, 0) / ys.length
    const y = Math.max(
      radBond + 8,
      hasLooseNics ? Math.min(centre, bondCeiling) : centre,
    )
    bondYById.set(b.id, y)
    const up = b.status ? b.status === "up" : true
    const stroke = up ? COLORS.bond : COLORS.gray
    nodes.push(`<g data-node-id="${b.id}" data-node-kind="bond" style="cursor:pointer;opacity:${up ? 1 : 0.45}">
      <circle class="nf-circle" cx="${bondX}" cy="${y}" r="${radBond}" stroke="${stroke}" />
      ${svgIcon("bond", bondX, y, 16, stroke)}
      <text class="nf-label" x="${bondX}" y="${y + radBond + 14}">${b.id}</text>
      <text class="nf-sub"   x="${bondX}" y="${y + radBond + 26}">${b.mode || "bond"}</text>
      <text class="nf-sub"   x="${bondX}" y="${y + radBond + 38}">${fmt(b.rx + b.tx)}</text>
    </g>`)
  })

  nodes.push(`<g>
    <circle class="nf-circle" cx="${hostX}" cy="${hostY}" r="${radHost}" stroke="${COLORS.host}" stroke-width="2.5" />
    ${svgIcon("host", hostX, hostY, 24, COLORS.host)}
    <text class="nf-label" x="${hostX}" y="${hostY + radHost + 14}" font-weight="600">PROXMOX</text>
    <text class="nf-sub"   x="${hostX}" y="${hostY + radHost + 26}">${fmt((host?.rx || 0) + (host?.tx || 0))}</text>
  </g>`)

  // Logarithmic mapping rate (MB/s) → pulse animation duration (s),
  // then SNAPPED to 7 discrete buckets. Reason: CSS restarts the
  // keyframe animation whenever animation-duration changes, so a
  // continuously varying duration produces a visible "rebound /
  // restart" on every poll. With snapping, duration only changes
  // when the rate crosses a threshold — smooth otherwise.
  //
  //   ≤ 250 KB/s   → 2.5 s
  //   ~300 KB/s    → 1.8 s
  //   ~1 MB/s      → 1.4 s
  //   ~5 MB/s      → 1.0 s
  //   ~20 MB/s     → 0.75 s
  //   ~80 MB/s     → 0.5 s
  //   ≥ 500 MB/s   → 0.3 s
  const SPEED_BUCKETS = [0.3, 0.5, 0.75, 1.0, 1.4, 1.8, 2.5]
  const durFor = (rate: number) => {
    const raw = 1.8 / Math.log10(1 + Math.max(0, rate) * 30)
    if (!isFinite(raw) || raw >= 2.5) return 2.5
    return SPEED_BUCKETS.find((b) => b >= raw) ?? 2.5
  }

  // All structural lines (trunk + taps) share the SAME thickness so
  // the diagram reads as one consistent network. The only thing that
  // varies per guest is pulse SPEED — faster animation = heavier
  // consumer at a glance.
  // Single-lane in beam mode (rx and tx share the centre line, passing
  // each other in opposite directions). dashes/gradient still apply a
  // small perpendicular offset, but 5 px is enough for those too —
  // 9 px was leftover from a previous two-lane experiment.
  const TRUNK_WIDTH = 5
  const TRUNK_PULSE_WIDTH = 3
  const TAP_WIDTH = TRUNK_WIDTH
  const TAP_PULSE_WIDTH = TRUNK_PULSE_WIDTH
  sections.forEach((sec) => {
    const bridgeRate = sec.guests.reduce((a, c) => a + c.rx + c.tx, 0)
    // Trunk activates per-bridge only when at least ONE guest of
    // that bridge has > 1.1 KB/s — not the sum, which adds up
    // background noise to a meaningless total.
    const sumRx = sec.guests.some((c) => c.rx > 0.00108) ? 1 : 0
    const sumTx = sec.guests.some((c) => c.tx > 0.00108) ? 1 : 0

    nodes.push(`<g data-node-id="${sec.b.id}" data-node-kind="bridge" style="cursor:pointer">
      <circle class="nf-circle" cx="${bridgesX}" cy="${sec.bridgeY}" r="${radBridge}" stroke="${COLORS.bridge}" />
      ${svgIcon("bridge", bridgesX, sec.bridgeY, 16, COLORS.bridge)}
      <text class="nf-label" x="${bridgesX}" y="${sec.bridgeY + radBridge + 14}">${sec.b.id}</text>
      <text class="nf-sub"   x="${bridgesX}" y="${sec.bridgeY + radBridge + 26}">${fmt(bridgeRate)}</text>
    </g>`)

    // Trunk lines are STATIC only — every per-guest path will travel
    // over them with its own pulse, so no need for a shared trunk
    // pulse that would mix all guests into one velocity.
    const hbPath = orthLink(hostX + radHost + 5, hostY, bridgesX - radBridge - 5, sec.bridgeY, 14)
    linksStatic.push(`<path class="nf-link" d="${hbPath}" stroke-width="${TRUNK_WIDTH}" />`)

    sec.buses.forEach((bus) => {
      const conn = orthLink(bridgesX + radBridge + 5, sec.bridgeY, busX0, bus.busY, 12)
      linksStatic.push(`<path class="nf-link" d="${conn}" stroke-width="${TRUNK_WIDTH}" />`)

      const cellCount = bus.pairs.length
      const lastCellCentre = busX0 + (cellCount - 1) * bus.cellW + bus.cellW / 2
      const tapR = 14
      const busEndX = lastCellCentre - tapR
      const busPath = `M ${busX0} ${bus.busY} L ${busEndX} ${bus.busY}`
      linksStatic.push(`<path class="nf-link" d="${busPath}" stroke-width="${TRUNK_WIDTH}" />`)

      const emitGuest = (g: Guest, cx: number, circleY: number, labelY: number, subY: number) => {
        const stroke = COLORS[g.kind] || COLORS.gray
        // Heavy-consumer halo: a concentric ring emanates from the
        // circle when total rate ≥ 5 MB/s. Pulses outward and fades,
        // making "hot" guests visible at a glance even without
        // reading the rate label.
        const rateMBs = (g.rx || 0) + (g.tx || 0)
        const haloSVG = rateMBs >= 5
          ? `<circle class="nf-guest-halo" cx="${cx}" cy="${circleY}" r="${radGuest}" stroke="${stroke}" style="--halo-r0:${radGuest}px;--halo-r1:${radGuest + 16}px" />`
          : ""
        nodes.push(`<g data-node-id="${g.id}" data-node-kind="${g.kind}" style="cursor:pointer">
          ${haloSVG}
          <circle class="nf-circle" cx="${cx}" cy="${circleY}" r="${radGuest}" stroke="${stroke}" />
          ${svgIcon(g.kind, cx, circleY, 14, stroke)}
          <text class="nf-label" x="${cx}" y="${labelY}">${g.label}</text>
          <text class="nf-sub"   x="${cx}" y="${subY}">${fmt(g.rx + g.tx)}</text>
        </g>`)
      }

      bus.pairs.forEach((pair, col) => {
        const cx = busX0 + col * bus.cellW + bus.cellW / 2
        if (pair.top) {
          const g = pair.top
          const circleY = bus.busY - topCellH + radGuest + 8
          // Text sits BELOW the circle (between circle and bus) —
          // this is the locked layout convention. The tap therefore
          // must STOP where the text begins, otherwise it would
          // visually overlap the label/rate.
          const labelY = circleY + radGuest + 14
          const subY = labelY + 14
          // Coming from the bus (below) the tap stops just under the
          // SUB text — the first text element it would meet. 8 px of
          // padding so the tap visibly approaches the text block
          // without crossing it.
          const tapTopEnd = subY + 8
          const tap = curvedTap(cx, bus.busY, tapTopEnd, tapR)
          linksStatic.push(`<path class="nf-link" d="${tap}" stroke-width="${TAP_WIDTH}" />`)
          if (g.rx > 0.005 || g.tx > 0.005) {
            // ONE continuous pulse from host all the way to the
            // guest. The beam recovers smoothly across trunk, bus
            // and tap without resync or speed/size jumps at the
            // curves.
            const fullD = buildFullFlowPath(
              hostX, hostY, radHost, bridgesX, sec.bridgeY, radBridge,
              busX0, bus.busY, cx, tapTopEnd, tapR,
            )
            const dur = durFor(g.rx + g.tx)
            const totalRate = g.rx + g.tx
            if (g.rx > 0.005) linksPulse.push({ d: fullD, type: "rx", strokeWidth: TAP_PULSE_WIDTH, animDur: dur, key: `top-rx-${g.id}`, rate: totalRate })
            if (g.tx > 0.005) linksPulse.push({ d: fullD, type: "tx", strokeWidth: TAP_PULSE_WIDTH, animDur: dur, key: `top-tx-${g.id}`, rate: totalRate })
          }
          emitGuest(g, cx, circleY, labelY, subY)
        }
        if (pair.bot) {
          const g = pair.bot
          // Was bus.busY + 30 + radGuest — moved the guest farther
          // from the bus so the tap is long enough for the beam to
          // visibly travel down between the curve and the circle.
          const circleY = bus.busY + 60 + radGuest
          const labelY = circleY + radGuest + 14
          const subY = labelY + 14
          // Coming from the bus (above) the tap stops 5 px above
          // the circle's top edge — never crosses the circle ring.
          // The label/rate sit BELOW the circle and remain free.
          const tapEnd = circleY - radGuest - 5
          const tap = curvedTap(cx, bus.busY, tapEnd, tapR)
          linksStatic.push(`<path class="nf-link" d="${tap}" stroke-width="${TAP_WIDTH}" />`)
          if (g.rx > 0.005 || g.tx > 0.005) {
            const fullD = buildFullFlowPath(
              hostX, hostY, radHost, bridgesX, sec.bridgeY, radBridge,
              busX0, bus.busY, cx, tapEnd, tapR,
            )
            const dur = durFor(g.rx + g.tx)
            const totalRate = g.rx + g.tx
            if (g.rx > 0.005) linksPulse.push({ d: fullD, type: "rx", strokeWidth: TAP_PULSE_WIDTH, animDur: dur, key: `bot-rx-${g.id}`, rate: totalRate })
            if (g.tx > 0.005) linksPulse.push({ d: fullD, type: "tx", strokeWidth: TAP_PULSE_WIDTH, animDur: dur, key: `bot-tx-${g.id}`, rate: totalRate })
          }
          emitGuest(g, cx, circleY, labelY, subY)
        }
      })
    })
  })

  // Each NIC's line animates only when that NIC's own rate is above
  // the threshold. Was 5 KB/s, which flickered on/off when a NIC
  // hovered around that mark; 2 KB/s sits clearly above the
  // background noise floor so the animation stays solid.
  const NIC_PULSE_MIN_MBPS = 0.002   // 2 KB/s

  nics.forEach((n) => {
    const y = nicYById.get(n.id) as number
    const active = n.status ? n.status === "up" : n.rx + n.tx > 0
    if (!active) return
    // A slave stops at its bond; only a NIC with no bond goes straight
    // to the host. Add a 5-px gap between each circle and the trunk
    // line so the static lane doesn't visually overlap the node ring.
    const bondId = bondOfNic.get(n.id)
    const bondY = bondId !== undefined ? bondYById.get(bondId) : undefined
    const path = bondY !== undefined
      ? orthLink(nicX + radNic + 5, y, bondX - radBond - 5, bondY, 14)
      : orthLink(nicX + radNic + 5, y, hostX - radHost - 5, hostY, 14)
    linksStatic.push(`<path class="nf-link" d="${path}" stroke-width="${TRUNK_WIDTH}" />`)
    // Per-NIC pulse speed mirrors the per-guest logic: more traffic
    // on this NIC → faster pulse on its line. Each NIC reads
    // independently from the others.
    const nicDur = durFor(n.rx + n.tx)
    if (n.rx > NIC_PULSE_MIN_MBPS) linksPulse.push({ d: path, type: "rx", strokeWidth: TRUNK_PULSE_WIDTH, animDur: nicDur, key: `nic-rx-${n.id}` })
    if (n.tx > NIC_PULSE_MIN_MBPS) linksPulse.push({ d: path, type: "tx", strokeWidth: TRUNK_PULSE_WIDTH, animDur: nicDur, key: `nic-tx-${n.id}` })
  })

  // Bond → host: one aggregated lane carrying the sum of its slaves.
  bonds.forEach((b) => {
    const y = bondYById.get(b.id)
    if (y === undefined) return
    const path = orthLink(bondX + radBond + 5, y, hostX - radHost - 5, hostY, 14)
    linksStatic.push(`<path class="nf-link" d="${path}" stroke-width="${TRUNK_WIDTH}" />`)
    const dur = durFor(b.rx + b.tx)
    if (b.rx > NIC_PULSE_MIN_MBPS) linksPulse.push({ d: path, type: "rx", strokeWidth: TRUNK_PULSE_WIDTH, animDur: dur, key: `bond-rx-${b.id}` })
    if (b.tx > NIC_PULSE_MIN_MBPS) linksPulse.push({ d: path, type: "tx", strokeWidth: TRUNK_PULSE_WIDTH, animDur: dur, key: `bond-tx-${b.id}` })
  })

  // Static svg = lines + nodes. Pulses are returned SEPARATELY as
  // data so NetworkFlow can render them as JSX <path>s. That keeps
  // each pulse's DOM node stable across re-renders → CSS animations
  // never restart unless that specific pulse changes.
  return {
    svg: linksStatic.join("") + nodes.join(""),
    pulses: linksPulse,
    height: H,
  }
}

// Mobile/tree layout. Approved design (mirrors _simulations/network-flow.html):
//   NIC → PROXMOX → vmbr → VM/LXC, each level in its OWN x column.
//   The trunk (host) is ONLY on HOST_X; bridges are in BRIDGE_X (a
//   separate column → trunk doesn't pass through them); the bridge's
//   own sub-trunk lives at SUB_TRUNK_X and fans out to its guests in
//   an arc (some above, some below the bridge.cy). All elbows use Q
//   curves; no sharp 90° corners anywhere.
function renderVertical(data: NetworkFlowData): { svg: string; pulses: PulseData[]; height: number; viewBox: string } {
  // Smaller W → SVG scales up on the mobile screen, nodes look bigger.
  // All four x-columns evenly spaced so curve→target distances are
  // homogeneous (host→bridge, bridge→spine, spine→guest all ~60 px).
  const W = 380
  const top = activeConsumers(data.consumers)
  const bridges = visibleBridges(data.bridges, top)
  const host = data.consumers.find((c) => c.kind === "host")
  const { bonds, bondOfNic, nics } = resolveBonds(data)

  const linksStatic: string[] = []
  const linksPulse: PulseData[] = []
  const nodes: string[] = []

  // Layout constants — kept inline so the function is self-contained.
  // Spacing model:
  //   - HOST_X → BRIDGE_X → SUB_TRUNK_X use a fixed inter-column
  //     step (homogeneous between trunk, bridge and its spine).
  //   - GUEST_X sits at the MIDDLE between the bridge's sub-trunk
  //     (the reference line the guests actually hang from) and the
  //     right edge of the canvas. So the spine-to-guest leg can be
  //     longer than the others, which is exactly what we want — the
  //     stub into each guest visibly stretches before the curve.
  const HOST_X       = 56
  const COL_STEP     = 60
  const BRIDGE_X     = HOST_X + COL_STEP
  const SUB_TRUNK_X  = HOST_X + COL_STEP * 2
  const GUEST_X      = Math.round((SUB_TRUNK_X + W) / 2)
  const RAD_HOST = 26
  const RAD_NIC = 22
  const RAD_BRIDGE = 24
  const RAD_GUEST = 20
  const RAD_BOND = 22
  // Extra rows the bond level needs when at least one bond exists:
  // the gap between where the NIC lines start and the bond circle, and
  // the space its three texts (name / mode / rate) occupy underneath.
  const BOND_ROW_GAP = 48
  const BOND_TEXT_H = 44
  // Same split the NICs use (see NIC_PATH_START_OFFSET / NIC_VERTICAL_LEG):
  // the link starts BELOW the rate text instead of on top of it, then runs
  // a visible stretch before curving toward the host.
  const BOND_PATH_START_OFFSET = BOND_TEXT_H + 14
  const BOND_VERTICAL_LEG = 40
  const NIC_TOP_Y = 6
  const NIC_PITCH_X_PREFERRED = 88
  const NIC_LEFT_MARGIN = 8
  // NIC line geometry, split into TWO independent quantities so we
  // can tune them separately:
  //   NIC_PATH_START_OFFSET — gap between the circle bottom and where
  //                           the line BEGINS (must clear the sub text
  //                           below the circle so the line doesn't
  //                           cross the rate label).
  //   NIC_VERTICAL_LEG      — actual length of the vertical drop
  //                           BEFORE the curve to the convergence row.
  const NIC_PATH_START_OFFSET = 46    // clears SUB_OFFSET_Y + text height
  const NIC_VERTICAL_LEG = 56
  const HOST_GAP_FROM_CONVERGE = 56
  const GUEST_ROW_H = 100          // más separación vertical entre
                                   // guests para que sub no toque
                                   // el círculo del siguiente
  const BRIDGE_PITCH_PAD = 36
  // Vertical positions of the label and the sub (rate) BELOW each
  // node's circle. Both grew when the font went up to 12.5 px; this
  // matched gap keeps them readable without overlap.
  const LABEL_OFFSET_Y = 16        // gap circle bottom → label baseline
  const SUB_OFFSET_Y   = 32        // gap circle bottom → sub baseline
                                   // (16 px between label and sub)
  const CORNER_R = 12
  const PULSE_THRESHOLD = 0.005

  // Orthogonal NIC→host path with an EXPLICIT convergence y. All NICs
  // (regardless of which row they sit in) drop vertically until they
  // hit `convergeY`, then run horizontally to HOST_X and drop to
  // host top. This guarantees that a row-0 NIC's line never crosses
  // the circle of a row-1 NIC below it.
  const vPath = (x1: number, y1: number, x2: number, y2: number,
                 convergeY: number, r = CORNER_R): string => {
    if (Math.abs(x2 - x1) < 2) return `M ${x1} ${y1} L ${x2} ${y2}`
    const midY = convergeY
    const dx = x2 > x1 ? 1 : -1
    return [
      `M ${x1} ${y1}`,
      `L ${x1} ${midY - r}`,
      `Q ${x1} ${midY} ${x1 + dx * r} ${midY}`,
      `L ${x2 - dx * r} ${midY}`,
      `Q ${x2} ${midY} ${x2} ${midY + r}`,
      `L ${x2} ${y2}`,
    ].join(" ")
  }
  // Single-elbow path (host trunk → bridge left edge, or any "drop
  // then turn right" connector). Q corner where the verticals meet.
  const elbow = (x1: number, y1: number, x2: number, y2: number, r = CORNER_R): string => {
    const dy = y2 > y1 ? 1 : -1
    const dx = x2 > x1 ? 1 : -1
    return [
      `M ${x1} ${y1}`,
      `L ${x1} ${y2 - dy * r}`,
      `Q ${x1} ${y2} ${x1 + dx * r} ${y2}`,
      `L ${x2} ${y2}`,
    ].join(" ")
  }

  // ─── 1. NICs ALWAYS in a single horizontal row ────────────
  // No wrap to a second row — multiple rows cause NIC paths to cross
  // the circles of NICs sitting underneath them. Instead, the pitch
  // shrinks dynamically when there are many NICs so they all fit.
  // Row is centred around HOST_X (not the canvas) so a single NIC
  // sits directly above the host — straight vertical path, no weird
  // S-curve. When the row is too wide to be centred there without
  // falling off the canvas, it slides right (or left, clamped).
  const nicCount = nics.length
  const fitWidth = W - 2 * (NIC_LEFT_MARGIN + RAD_NIC)
  const dynamicPitch = nicCount > 1
    ? Math.min(NIC_PITCH_X_PREFERRED, fitWidth / (nicCount - 1))
    : 0
  const rowWidth = (nicCount - 1) * dynamicPitch
  const minStart = NIC_LEFT_MARGIN + RAD_NIC
  const maxStart = W - NIC_LEFT_MARGIN - RAD_NIC - rowWidth
  const idealStart = HOST_X - rowWidth / 2
  const startX = Math.max(minStart, Math.min(maxStart, idealStart))
  const nicCy = NIC_TOP_Y + RAD_NIC
  const nicGeom = nics.map((n, i) => ({
    n, cx: startX + i * dynamicPitch, cy: nicCy, r: RAD_NIC,
  }))

  // Convergence row: single y-line BELOW every NIC at which all
  // drops bend horizontally toward HOST_X. The vertical "leg" of the
  // NIC path (NIC_VERTICAL_LEG) is what makes the line visibly run
  // a stretch BEFORE turning into the curve.
  const nicPathStartY = nicCy + RAD_NIC + NIC_PATH_START_OFFSET

  // ─── 1b. Bond row — between the NICs and the convergence row ──
  // Each bond sits horizontally at the centroid of its own slaves, so
  // its links stay short and don't cross a neighbouring bond's.
  const hasBonds = bonds.length > 0
  const bondCy = nicPathStartY + BOND_ROW_GAP + RAD_BOND
  const bondGeom = hasBonds
    ? bonds.map((b) => {
        const xs = nicGeom
          .filter(({ n }) => bondOfNic.get(n.id) === b.id)
          .map(({ cx }) => cx)
        return { b, cx: xs.reduce((a, v) => a + v, 0) / xs.length, cy: bondCy, r: RAD_BOND }
      })
    : []
  const bondCxById = new Map(bondGeom.map(({ b, cx }) => [b.id, cx]))
  // Slaves bend into their bond one row above the bond circle.
  const bondConvergeY = bondCy - RAD_BOND - 20
  // With a bond level present the shared convergence row moves below
  // the bond's texts; without bonds the geometry is exactly as before.
  const convergeY = hasBonds
    ? bondCy + RAD_BOND + BOND_PATH_START_OFFSET + BOND_VERTICAL_LEG
    : nicPathStartY + NIC_VERTICAL_LEG
  const hostY = convergeY + HOST_GAP_FROM_CONVERGE + RAD_HOST
  const hostTopY = hostY - RAD_HOST - 4

  // NIC → bond (if enslaved) or NIC → host, both orth+Q.
  nicGeom.forEach(({ n, cx, cy, r }) => {
    const startX = cx, startY = cy + r + NIC_PATH_START_OFFSET
    const bondId = bondOfNic.get(n.id)
    const bondCx = bondId !== undefined ? bondCxById.get(bondId) : undefined
    const pathD = bondCx !== undefined
      ? vPath(startX, startY, bondCx, bondCy - RAD_BOND - 4, bondConvergeY)
      : vPath(startX, startY, HOST_X, hostTopY, convergeY)
    linksStatic.push(`<path class="nf-link" d="${pathD}" stroke-width="2.5" />`)
    const active = n.status ? n.status === "up" : n.rx + n.tx > 0
    if (active) {
      const rate = n.rx + n.tx
      if (n.rx > 0.001) linksPulse.push({ d: pathD, type: "rx", strokeWidth: 3, key: `m-nic-rx-${n.id}`, rate })
      if (n.tx > 0.001) linksPulse.push({ d: pathD, type: "tx", strokeWidth: 3, key: `m-nic-tx-${n.id}`, rate })
    }
    const isDown = n.status === "down"
    const color = isDown ? COLORS.gray : COLORS.nic
    const opacity = isDown ? 0.45 : n.role === "standby" ? 0.72 : 1
    nodes.push(`<g data-node-id="${n.id}" data-node-kind="nic" style="cursor:pointer;opacity:${opacity}">
      <circle class="nf-circle" cx="${cx}" cy="${cy}" r="${r}" stroke="${color}" />
      ${svgIcon("nic", cx, cy, 13, color)}
      <text class="nf-label" x="${cx}" y="${cy + r + LABEL_OFFSET_Y}" text-anchor="middle" style="font-size:12.5px">${n.id}</text>
      <text class="nf-sub"   x="${cx}" y="${cy + r + SUB_OFFSET_Y}" text-anchor="middle" style="font-size:11px">${nicSubLabel(n)}</text>
    </g>`)
  })

  // Bond node + its aggregated link down to the host.
  bondGeom.forEach(({ b, cx, cy, r }) => {
    const pathD = vPath(cx, cy + r + BOND_PATH_START_OFFSET, HOST_X, hostTopY, convergeY)
    linksStatic.push(`<path class="nf-link" d="${pathD}" stroke-width="2.5" />`)
    const rate = b.rx + b.tx
    if (b.rx > 0.001) linksPulse.push({ d: pathD, type: "rx", strokeWidth: 3, key: `m-bond-rx-${b.id}`, rate })
    if (b.tx > 0.001) linksPulse.push({ d: pathD, type: "tx", strokeWidth: 3, key: `m-bond-tx-${b.id}`, rate })
    const isDown = b.status === "down"
    const color = isDown ? COLORS.gray : COLORS.bond
    nodes.push(`<g data-node-id="${b.id}" data-node-kind="bond" style="cursor:pointer;opacity:${isDown ? 0.45 : 1}">
      <circle class="nf-circle" cx="${cx}" cy="${cy}" r="${r}" stroke="${color}" />
      ${svgIcon("bond", cx, cy, 13, color)}
      <text class="nf-label" x="${cx}" y="${cy + r + LABEL_OFFSET_Y}" text-anchor="middle" style="font-size:12.5px">${b.id}</text>
      <text class="nf-sub"   x="${cx}" y="${cy + r + SUB_OFFSET_Y}" text-anchor="middle" style="font-size:11px">${b.mode || "bond"}</text>
      <text class="nf-sub"   x="${cx}" y="${cy + r + BOND_TEXT_H}" text-anchor="middle" style="font-size:11px">${fmt(rate)}</text>
    </g>`)
  })

  // ─── 2. Host PROXMOX — LEFT column, label/sub below ──────
  nodes.push(`<g>
    <circle class="nf-circle" cx="${HOST_X}" cy="${hostY}" r="${RAD_HOST}" stroke="${COLORS.host}" stroke-width="2.5" />
    ${svgIcon("host", HOST_X, hostY, 20, COLORS.host)}
    <text class="nf-label" x="${HOST_X}" y="${hostY + RAD_HOST + LABEL_OFFSET_Y}" text-anchor="middle" font-weight="700" style="font-size:13px">PROXMOX</text>
    <text class="nf-sub"   x="${HOST_X}" y="${hostY + RAD_HOST + SUB_OFFSET_Y}" text-anchor="middle" style="font-size:12.5px">${fmt((host?.rx || 0) + (host?.tx || 0))}</text>
  </g>`)

  // ─── 3. Bridges + guests, ARC layout around each bridge ──
  // Each bridge has its OWN sub-trunk at SUB_TRUNK_X. Guests are
  // distributed symmetrically around the bridge.cy (some above, some
  // below) — fans out in an arc, uses the vertical gap efficiently.
  let cursorY = hostY + RAD_HOST + 40
  type BridgeSlot = {
    b: Bridge
    cx: number; cy: number; r: number
    guests: Array<{ g: Guest; cx: number; cy: number; r: number }>
    rate: number
    sumRx: number
    sumTx: number
  }
  const bridgePos: BridgeSlot[] = []

  bridges.forEach((b) => {
    const guestsOfBridge = top.filter((c) => c.bridge === b.id && c.kind !== "host")
    const rate = guestsOfBridge.reduce((a, g) => a + g.rx + g.tx, 0)
    const sumRx = guestsOfBridge.reduce((a, g) => a + g.rx, 0)
    const sumTx = guestsOfBridge.reduce((a, g) => a + g.tx, 0)
    const N = guestsOfBridge.length
    const mid = (N - 1) / 2
    const topSpan = mid * GUEST_ROW_H
    const botSpan = (N - 1 - mid) * GUEST_ROW_H
    // Bridge sits below cursorY with enough top clearance for the
    // top-arc guest's label/sub.
    const topClearance = topSpan + 24
    const bCy = cursorY + Math.max(RAD_BRIDGE + 6, topClearance)
    const guests = guestsOfBridge.map((g, gi) => ({
      g, cx: GUEST_X, r: RAD_GUEST,
      cy: bCy + (gi - mid) * GUEST_ROW_H,
    }))
    bridgePos.push({ b, cx: BRIDGE_X, cy: bCy, r: RAD_BRIDGE, guests,
                     rate, sumRx, sumTx })
    const bottom = N > 0 ? bCy + botSpan + RAD_GUEST + 22 : bCy + RAD_BRIDGE + 22
    cursorY = bottom + BRIDGE_PITCH_PAD
  })

  // Host trunk — vertical line at HOST_X from host bottom down to the
  // last bridge's row. The trunk does NOT pass through any bridge:
  // bridges live in BRIDGE_X column.
  // Clears the host's sub label (rate "X KB/s") so the trunk doesn't
  // start touching the text. SUB_OFFSET_Y + ~8 px breathing room.
  const hostTrunkStartY = hostY + RAD_HOST + SUB_OFFSET_Y + 12
  if (bridgePos.length > 0) {
    const last = bridgePos[bridgePos.length - 1]
    linksStatic.push(`<path class="nf-link" d="M ${HOST_X} ${hostTrunkStartY} L ${HOST_X} ${last.cy}" stroke-width="2.5" />`)
  }

  // Per-bridge: host→bridge branch + sub-tree to guests.
  bridgePos.forEach(({ b, cx, cy, r, guests, rate, sumRx, sumTx }) => {
    // Host → bridge branch (elbow with Q corner) into bridge LEFT edge.
    const branchHB = elbow(HOST_X, hostTrunkStartY, cx - r - 4, cy)
    linksStatic.push(`<path class="nf-link" d="${branchHB}" stroke-width="2.5" />`)
    if (rate > PULSE_THRESHOLD) {
      if (sumRx > PULSE_THRESHOLD) linksPulse.push({ d: branchHB, type: "rx", strokeWidth: 3, key: `m-br-rx-${b.id}`, rate })
      if (sumTx > PULSE_THRESHOLD) linksPulse.push({ d: branchHB, type: "tx", strokeWidth: 3, key: `m-br-tx-${b.id}`, rate })
    }

    // Bridge node — label/sub BELOW.
    nodes.push(`<g data-node-id="${b.id}" data-node-kind="bridge" style="cursor:pointer">
      <circle class="nf-circle" cx="${cx}" cy="${cy}" r="${r}" stroke="${COLORS.bridge}" />
      ${svgIcon("bridge", cx, cy, 13, COLORS.bridge)}
      <text class="nf-label" x="${cx}" y="${cy + r + LABEL_OFFSET_Y}" text-anchor="middle" style="font-size:12.5px">${b.id}</text>
      <text class="nf-sub"   x="${cx}" y="${cy + r + SUB_OFFSET_Y}" text-anchor="middle" style="font-size:12.5px">${fmt(rate)}</text>
    </g>`)

    if (guests.length === 0) return

    // Per-guest path: exits bridge.right, runs horizontal to SUB_TRUNK_X,
    // Q-curves into the vertical spine, rises/falls to the guest's row,
    // Q-curves into the guest. Every elbow is Q — no sharp corners.
    // Multiple paths overlap on the vertical spine and visually read as
    // one continuous line.
    const spineEnterX = cx + r + 4
    const spineX = SUB_TRUNK_X
    guests.forEach(({ g, cx: gCx, cy: gCy, r: gR }) => {
      const enterX = gCx - gR - 4
      let d: string
      if (Math.abs(gCy - cy) < 2) {
        d = `M ${spineEnterX} ${cy} L ${enterX} ${gCy}`
      } else {
        const dy = gCy > cy ? 1 : -1
        d = [
          `M ${spineEnterX} ${cy}`,
          `L ${spineX - CORNER_R} ${cy}`,
          `Q ${spineX} ${cy} ${spineX} ${cy + dy * CORNER_R}`,
          `L ${spineX} ${gCy - dy * CORNER_R}`,
          `Q ${spineX} ${gCy} ${spineX + CORNER_R} ${gCy}`,
          `L ${enterX} ${gCy}`,
        ].join(" ")
      }
      linksStatic.push(`<path class="nf-link" d="${d}" stroke-width="2.5" />`)
      const gRate = g.rx + g.tx
      if (gRate > PULSE_THRESHOLD) {
        if (g.rx > PULSE_THRESHOLD) linksPulse.push({ d, type: "rx", strokeWidth: 3, key: `m-g-rx-${b.id}-${g.id}`, rate: gRate })
        if (g.tx > PULSE_THRESHOLD) linksPulse.push({ d, type: "tx", strokeWidth: 3, key: `m-g-tx-${b.id}-${g.id}`, rate: gRate })
      }
      const stroke = COLORS[g.kind] || COLORS.gray
      const haloSVG = gRate >= 5
        ? `<circle class="nf-guest-halo" cx="${gCx}" cy="${gCy}" r="${gR}" stroke="${stroke}" style="--halo-r0:${gR}px;--halo-r1:${gR + 12}px" />`
        : ""
      nodes.push(`<g data-node-id="${g.id}" data-node-kind="${g.kind}" style="cursor:pointer">
        ${haloSVG}
        <circle class="nf-circle" cx="${gCx}" cy="${gCy}" r="${gR}" stroke="${stroke}" />
        ${svgIcon(g.kind, gCx, gCy, 13, stroke)}
        <text class="nf-label" x="${gCx}" y="${gCy + gR + LABEL_OFFSET_Y}" text-anchor="middle" style="font-size:12.5px">${g.label}</text>
        <text class="nf-sub"   x="${gCx}" y="${gCy + gR + SUB_OFFSET_Y}" text-anchor="middle" style="font-size:12.5px">${fmt(gRate)}</text>
      </g>`)
    })
  })

  const lastSlot = bridgePos[bridgePos.length - 1]
  const lastBottomY = lastSlot
    ? (lastSlot.guests.length
        ? lastSlot.guests[lastSlot.guests.length - 1].cy + RAD_GUEST
        : lastSlot.cy + RAD_BRIDGE)
    : hostY + RAD_HOST
  const H = lastBottomY + 36

  return {
    svg: linksStatic.join("") + nodes.join(""),
    pulses: linksPulse,
    height: H,
    viewBox: `0 0 ${W} ${H}`,
  }
}

// ─── React component ────────────────────────────────────────
export function NetworkFlow({
  data, onNodeClick,
}: {
  data: NetworkFlowData
  // Fires when the user taps/clicks any circle in the diagram. The
  // parent component looks up the matching NetworkInterface and
  // opens the per-interface details modal.
  onNodeClick?: (name: string, kind: "nic" | "host" | "bond" | "bridge" | "lxc" | "vm") => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(1320)
  const [mode, setMode] = useState<"desktop" | "tablet" | "mobile">("desktop")

  useEffect(() => {
    const update = () => {
      const w = ref.current?.offsetWidth || window.innerWidth
      setWidth(w)
      if (w < 700) setMode("mobile")
      else if (w < 1100) setMode("tablet")
      else setMode("desktop")
    }
    update()
    window.addEventListener("resize", update)
    return () => window.removeEventListener("resize", update)
  }, [])

  // Stable memo key: the SVG is regenerated ONLY when something
  // structurally relevant changes (mode, width, who's online,
  // who's linked where, or a rate crossed into a different speed
  // bucket). Exact rate values are excluded so micro-fluctuations
  // between polls don't tear down the whole SVG (which would
  // restart every CSS animation — the "rebound/reset" effect).
  const memoKey = useMemo(() => {
    const SB = [0.3, 0.5, 0.75, 1.0, 1.4, 1.8, 2.5]
    const bucket = (rate: number) => {
      const raw = 1.8 / Math.log10(1 + Math.max(0, rate || 0) * 30)
      if (!isFinite(raw) || raw >= 2.5) return 2.5
      return SB.find((b) => b >= raw) ?? 2.5
    }
    const sig = (r: number) => (r > 0.005 ? 1 : 0)
    // bond + role are part of the signature so a failover (active ↔
    // standby, or a slave leaving the bond) redraws the diagram on the
    // very next poll instead of being masked by the rate bucketing.
    const nics = data.nics.map((n) =>
      `${n.id}:${n.status || ""}:${n.bond || ""}:${n.role || ""}:${bucket(n.rx)}:${bucket(n.tx)}:${sig(n.rx)}:${sig(n.tx)}`
    ).join("|")
    const bonds = (data.bonds || []).map((b) =>
      `${b.id}:${b.mode || ""}:${b.status || ""}:${bucket(b.rx)}:${bucket(b.tx)}:${sig(b.rx)}:${sig(b.tx)}`
    ).join("|")
    const guests = data.consumers.map((c) =>
      `${c.id}:${c.bridge}:${c.kind}:${c.offline ? 1 : 0}:${bucket(c.rx)}:${bucket(c.tx)}:${sig(c.rx)}:${sig(c.tx)}`
    ).join("|")
    const bridges = data.bridges.map((b) => `${b.id}:${b.parent || ""}`).join("|")
    return `${mode}|${width}|${nics}||${bonds}||${guests}||${bridges}`
  }, [data, mode, width])

  const { svgContent, pulses, viewBox, height } = useMemo(() => {
    if (mode === "mobile") {
      const out = renderVertical(data)
      return { svgContent: out.svg, pulses: out.pulses, viewBox: out.viewBox, height: out.height }
    }
    const W = mode === "tablet" ? 1100 : 1320
    const out = renderHorizontal(data, W)
    return { svgContent: out.svg, pulses: out.pulses, viewBox: `0 0 ${W} ${out.height}`, height: out.height }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memoKey])

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-foreground flex items-center text-base">
          <Activity className="h-5 w-5 mr-2" />
          Network Flow (PoC)
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div ref={ref} className="nf-wrap">
          <style>{`
            .nf-wrap svg { width: 100%; display: block; }
            .nf-circle { fill: #0d0d0d; stroke-width: 2; }
            .nf-label  { fill: var(--foreground); font-family: ui-monospace, "SF Mono", monospace; font-size: 12.5px; text-anchor: middle; dominant-baseline: middle; stroke: hsl(var(--card)); stroke-width: 8; paint-order: stroke; }
            .nf-sub    { fill: var(--muted-foreground); font-family: ui-monospace, monospace; font-size: 12.5px; text-anchor: middle; dominant-baseline: middle; stroke: hsl(var(--card)); stroke-width: 8; paint-order: stroke; }
            .nf-icon   { fill: none; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
            .nf-link   { fill: none; stroke: #2a2a2a; stroke-linecap: round; stroke-linejoin: round; stroke-opacity: 0.55; }
            /* MODE: beam — comet-trail style. The visual is a
               bright head followed by a softer, semi-transparent tail
               that fades to nothing.
               Implementation: THREE copies of the same dashed beam,
               each one progressively DELAYED in the animation
               (positive animation-delay makes the trail lag behind
               the head in space) and with lower opacity. Stroke-linecap
               round softens the tip of each segment for free.
               pathLength="100" keeps beam length proportional to the
               path so it doesn't vanish on short taps. */
            .nf-beam-rx, .nf-beam-tx {
              fill: none; stroke-linecap: round; stroke-linejoin: round;
              stroke-dasharray: 18 100;
              animation: nf-beam 1.5s linear infinite;
            }
            .nf-beam-rx { stroke: #10b981; }
            .nf-beam-tx { stroke: #3b82f6; animation-direction: reverse; }
            @keyframes nf-beam { to { stroke-dashoffset: -118; } }

            /* The head — sharp, bright, with a subtle glow. */
            .nf-beam-head-rx, .nf-beam-head-tx {
              fill: none; stroke-linecap: round; stroke-linejoin: round;
              stroke-dasharray: 8 110;
              animation: nf-beam-head 1.5s linear infinite;
              filter: drop-shadow(0 0 2.5px currentColor);
            }
            .nf-beam-head-rx { stroke: #34d399; color: #10b981; }
            .nf-beam-head-tx { stroke: #60a5fa; color: #3b82f6; animation-direction: reverse; }
            @keyframes nf-beam-head { to { stroke-dashoffset: -118; } }

            /* Beam head intensity tiers — applied additively on top
               of the base head when the guest's rate crosses a
               threshold. "warm" softens the glow up; "hot" doubles
               it for the heaviest consumers. */
            .nf-beam-head-warm { filter: drop-shadow(0 0 4.5px currentColor); }
            .nf-beam-head-hot  { filter: drop-shadow(0 0 6px currentColor) drop-shadow(0 0 12px currentColor); }

            /* "Hot guest" halo — concentric ring radiating from the
               guest circle when its rate is high. Pure visual signal:
               you spot heavy consumers without reading the label. */
            .nf-guest-halo {
              fill: none;
              stroke-width: 2;
              opacity: 0;
              animation: nf-halo 1.8s ease-out infinite;
              transform-box: fill-box;
              transform-origin: center;
            }
            @keyframes nf-halo {
              0%   { opacity: 0.55; r: var(--halo-r0, 22); }
              80%  { opacity: 0;    r: var(--halo-r1, 36); }
              100% { opacity: 0;    r: var(--halo-r1, 36); }
            }

            /* Dim base under the beam — same color, low opacity. */
            .nf-beam-base-rx { fill: none; stroke: #10b981; stroke-opacity: 0.18; stroke-linecap: round; stroke-linejoin: round; }
            .nf-beam-base-tx { fill: none; stroke: #3b82f6; stroke-opacity: 0.18; stroke-linecap: round; stroke-linejoin: round; }
          `}</style>
          <div
            className="relative"
            style={{ width: "100%" }}
            onClick={(e) => {
              // Event delegation — nodes are rendered inside an
              // innerHTML SVG string (not JSX), so React can't attach
              // per-node handlers directly. Each clickable node carries
              // data-node-id + data-node-kind; we find the closest one
              // from the click target.
              if (!onNodeClick) return
              const t = e.target as Element
              const hit = t.closest?.("[data-node-id]") as Element | null
              if (!hit) return
              const id = hit.getAttribute("data-node-id") || ""
              const kind = (hit.getAttribute("data-node-kind") || "") as
                "nic" | "host" | "bond" | "bridge" | "lxc" | "vm"
              if (id && kind) onNodeClick(id, kind)
            }}
          >
            {/* Layer 1 — static structure + nodes + text labels.
                Replaced via innerHTML; cheap and only refreshes on
                structural/bucket changes (see memoKey). */}
            <svg
              viewBox={viewBox}
              preserveAspectRatio="xMidYMin meet"
              style={{ height: "auto", display: "block", width: "100%" }}
              dangerouslySetInnerHTML={{ __html: svgContent }}
            />
            {/* Layer 2 — animated pulses, rendered as JSX so each
                path keeps its DOM identity across re-renders. CSS
                animations restart ONLY when this specific path's
                animation-duration changes, not on every poll. */}
            <svg
              viewBox={viewBox}
              preserveAspectRatio="xMidYMin meet"
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
            >
              {pulses.map((p) => {
                // Comet trail: dim base + three trailing copies that
                // progressively lag in space and fade out + bright
                // head on top. POSITIVE animation-delay shifts each
                // trail BEHIND the head by that fraction of the cycle.
                // pathLength=100 normalises the beam length across
                // all path sizes (so a short tap shows the same visible
                // beam as a long trunk).
                const baseClass = p.type === "rx" ? "nf-beam-base-rx" : "nf-beam-base-tx"
                const tailClass = p.type === "rx" ? "nf-beam-rx" : "nf-beam-tx"
                const headClass = p.type === "rx" ? "nf-beam-head-rx" : "nf-beam-head-tx"
                const dur = p.animDur ?? 1.5
                const t1 = `${(dur * 0.06).toFixed(3)}s`
                const t2 = `${(dur * 0.13).toFixed(3)}s`
                const t3 = `${(dur * 0.22).toFixed(3)}s`
                // Head glow tier — escalates with the guest's rate.
                const intensity = (p.rate || 0) >= 30
                  ? "nf-beam-head-hot"
                  : (p.rate || 0) >= 1 ? "nf-beam-head-warm" : ""
                const headWidth = (p.rate || 0) >= 30 ? p.strokeWidth + 1 : p.strokeWidth
                return (
                  <g key={p.key}>
                    <path className={baseClass} d={p.d} strokeWidth={p.strokeWidth} pathLength="100" />
                    <path className={tailClass} d={p.d} strokeWidth={p.strokeWidth} pathLength="100"
                          style={{ animationDuration: `${dur}s`, animationDelay: t3, opacity: 0.15 }} />
                    <path className={tailClass} d={p.d} strokeWidth={p.strokeWidth} pathLength="100"
                          style={{ animationDuration: `${dur}s`, animationDelay: t2, opacity: 0.35 }} />
                    <path className={tailClass} d={p.d} strokeWidth={p.strokeWidth} pathLength="100"
                          style={{ animationDuration: `${dur}s`, animationDelay: t1, opacity: 0.65 }} />
                    <path className={`${headClass} ${intensity}`} d={p.d} strokeWidth={headWidth}
                          pathLength="100" style={{ animationDuration: `${dur}s` }} />
                  </g>
                )
              })}
            </svg>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
