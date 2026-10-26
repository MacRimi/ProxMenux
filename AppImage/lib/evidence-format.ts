/**
 * Turns a finding's evidence into something a reader can read.
 *
 * Checks record evidence in whatever shape suits what they examined:
 * some serialise a list of objects, some an object of lists, some write
 * a few lines of text. Printing that verbatim shows the reader a JSON
 * dump and asks them to parse it — which defeats the purpose of evidence,
 * which is to let someone verify a conclusion without trusting it.
 *
 * The parser recognises those shapes and returns blocks: a table for a
 * list of records, labelled pairs for a single record, plain lines for
 * the rest. Field names are humanised and values are formatted according
 * to what the name says they are — a `_bytes` suffix is a size, `_hours`
 * a duration, an `_at` an instant — so the reader sees "1.2 TiB" where
 * the check wrote 1319413953331.
 *
 * Nothing is discarded: text the parser does not recognise is passed
 * through as lines, because evidence that has been silently dropped is
 * worse than evidence that is ugly.
 */

export type EvidenceBlock =
  | { kind: "table"; title?: string; columns: string[]; rows: string[][] }
  | { kind: "pairs"; title?: string; entries: Array<[string, string]> }
  | { kind: "text"; title?: string; lines: string[] }

/** `max_age_hours` reads as "Max age hours"; `vmid` stays "VMID". */
const ACRONYMS: Record<string, string> = {
  vmid: "VMID", id: "ID", cpu: "CPU", pci: "PCI", iommu: "IOMMU",
  smart: "SMART", zfs: "ZFS", arc: "ARC", ssh: "SSH", lxc: "LXC",
  pve: "PVE", pbs: "PBS", nfs: "NFS", url: "URL", os: "OS", ram: "RAM",
}

export function humanise(field: string): string {
  const parts = field.replace(/[_-]+/g, " ").trim().split(/\s+/)
  if (parts.length === 0) return field
  return parts
    .map((word, i) => {
      const known = ACRONYMS[word.toLowerCase()]
      if (known) return known
      return i === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word
    })
    .join(" ")
}

function sizeOf(value: number): string {
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
  let n = Math.abs(value), i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  const shown = n >= 100 || i < 2 ? Math.round(n) : Number(n.toFixed(1))
  return `${value < 0 ? "-" : ""}${shown} ${units[i]}`
}

export function durationOf(hours: number, locale: string): string {
  if (!Number.isFinite(hours) || hours < 0) return "—"
  const total = Math.round(hours * 60)
  const days = Math.floor(total / 1440), h = Math.floor(total % 1440 / 60)
  const unit = (v: number, name: string) => new Intl.NumberFormat(locale, {
    style: "unit", unit: name, unitDisplay: "short", maximumFractionDigits: 0,
  }).format(v)
  return [days ? unit(days, "day") : "", h || days ? unit(h, "hour") : "", unit(total % 60, "minute")].filter(Boolean).join(" ")
}

/**
 * Formats one value using what its field name says it is. The name is
 * the only type information a check leaves behind, so it is what the
 * formatter reads.
 */
export function formatValue(field: string, value: unknown, locale: string,
                            units?: string): string {
  if (value === null || value === undefined || value === "") return "—"
  // A recorded `false` is an answer, and it used to render as the same
  // dash as "nothing was recorded": a table of seven archives that are
  // definitely gone read as seven about which nothing was known.
  if (typeof value === "boolean") return value ? "✓" : "✗"

  const name = field.toLowerCase()
  if (typeof value === "number") {
    // The field name is read before the record's declared units: a
    // record of sizes still carries a timestamp and a percentage, and
    // those are not sizes.
    if (name.endsWith("_hours") || name === "hours") return durationOf(value, locale)
    if (name.endsWith("_days") || name === "days") return `${Number(value.toFixed(1))} d`
    if (name.endsWith("_percent") || name.endsWith("_pct")) {
      return `${Number(value.toFixed(1))} %`
    }
    // A check records instants as epoch seconds under names like
    // `last_backup` or `collected_at`, so both the name and the
    // magnitude have to agree before a number is shown as a date.
    const temporal = /(^|_)(at|time|date|seen|since|backup|run|checked|updated)$/
    if (temporal.test(name) && Number.isFinite(value)
        && value > 1_000_000_000 && value < 4_000_000_000) {
      return new Date(value * 1000).toLocaleString(locale)
    }
    if (name.endsWith("_bytes") || name === "bytes" || name.endsWith("_size")
        || units === "bytes") {
      return sizeOf(value)
    }
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return "—"
    const shown = value.slice(0, 3).map((v) => {
      if (v === null || typeof v !== "object") return String(v)
      // Inside a cell, name each record by whatever identifies it
      // rather than spelling out every field.
      const record = v as Record<string, unknown>
      const key = ["vmid", "id", "name", "device", "storage", "volume", "job"]
        .find((k) => record[k] !== undefined)
      return key ? String(record[key])
        : Object.entries(record).map(([k, x]) => `${humanise(k)} ${String(x)}`).join(" ")
    })
    return shown.join(", ") + (value.length > 3 ? ` +${value.length - 3}` : "")
  }

  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${humanise(k)}: ${formatValue(k, v, locale)}`)
      .join(" · ")
  }

  return String(value)
}

function isRecordList(value: unknown): value is Array<Record<string, unknown>> {
  return Array.isArray(value) && value.length > 0 &&
    value.every((v) => v !== null && typeof v === "object" && !Array.isArray(v))
}

function tableFrom(records: Array<Record<string, unknown>>, locale: string,
                   title?: string): EvidenceBlock[] {
  // Union of the keys, in first-seen order: records from one check are
  // uniform in practice, but a missing key must not shift a column.
  const columns: string[] = []
  for (const record of records) {
    for (const key of Object.keys(record)) {
      if (!columns.includes(key)) columns.push(key)
    }
  }
  const cells = records.map((r) => {
    const units = typeof r.units === "string" ? r.units : undefined
    return Object.fromEntries(
      columns.map((c) => [c, formatValue(c, r[c], locale, units)]))
  })

  // A column holding the same value in every row is a property of the
  // whole set, not of any row. Stating it once keeps the table narrow
  // enough to read; it only pays off once the table is already wide.
  const constant: Array<[string, string]> = []
  const varying = columns.filter((c) => {
    if (columns.length <= 6 || records.length < 2) return true
    const first = cells[0][c]
    if (!cells.every((row) => row[c] === first) || first === "—") return true
    constant.push([humanise(c), first])
    return false
  })

  const rows = cells.map((row) => varying.map((c) => row[c]))
  return constant.length
    ? [{ kind: "pairs" as const, title, entries: constant },
       { kind: "table" as const, columns: varying.map(humanise), rows }]
    : [{ kind: "table" as const, title, columns: varying.map(humanise), rows }]
}

function blocksFromValue(value: unknown, locale: string,
                         title?: string): EvidenceBlock[] {
  if (isRecordList(value)) return tableFrom(value, locale, title)

  if (Array.isArray(value)) {
    return value.length
      ? [{ kind: "text", title, lines: value.map((v) => formatValue("", v, locale)) }]
      : []
  }

  if (value !== null && typeof value === "object") {
    const blocks: EvidenceBlock[] = []
    const pairs: Array<[string, string]> = []
    const record = value as Record<string, unknown>
    const units = typeof record.units === "string" ? record.units : undefined
    for (const [key, inner] of Object.entries(record)) {
      // A nested list of records earns its own table under its own name;
      // everything else stays a labelled pair.
      if (isRecordList(inner)) {
        blocks.push(...tableFrom(inner, locale, humanise(key)))
      } else {
        pairs.push([humanise(key), formatValue(key, inner, locale, units)])
      }
    }
    if (pairs.length) blocks.unshift({ kind: "pairs", title, entries: pairs })
    return blocks
  }

  return [{ kind: "text", title, lines: [formatValue("", value, locale)] }]
}

/**
 * Text evidence: lines like `label:` introduce the indented lines under
 * them, which is the shape checks write by hand.
 */
function blocksFromText(text: string, locale: string): EvidenceBlock[] {
  const lines = text.split("\n")
  const blocks: EvidenceBlock[] = []
  let title: string | undefined
  let buffer: string[] = []

  const flush = () => {
    const kept = buffer.filter((l) => l.trim())
    const joined = kept.join("\n").trim()
    // A section introduced by a heading gets the same treatment as
    // evidence that is JSON from the first character.
    let sectionTitle = title
    let source = joined
    if (joined && !/^[[{]/.test(joined)) {
      const at = joined.search(/:\s*[[{]/)
      // Only a short prefix is a label; a paragraph that happens to
      // mention a bracket is prose.
      if (at > 0 && at < 80) {
        sectionTitle = title || joined.slice(0, at).trim()
        source = joined.slice(joined.indexOf(joined[at] === ":" ? ":" : ":", at) + 1).trim()
      }
    }
    const split = source ? splitLeadingJson(source) : null
    if (split) {
      const [value, rest] = split
      blocks.push(...blocksFromValue(value, locale, sectionTitle))
      if (rest) blocks.push({ kind: "text", lines: rest.split("\n") })
      buffer = []
      return
    }
    if (kept.length || title) blocks.push({ kind: "text", title, lines: kept })
    buffer = []
  }

  for (const line of lines) {
    const heading = /^(\S[^:]*):\s*$/.exec(line)
    if (heading) {
      flush()
      title = heading[1]
      continue
    }
    buffer.push(line.replace(/^\s{1,4}/, ""))
  }
  flush()
  return blocks.filter((b) => b.kind !== "text" || b.lines.length || b.title)
}

/**
 * Splits a leading JSON document from whatever text follows it, by
 * balancing brackets outside of strings. Checks routinely serialise
 * their records and then add a line qualifying them, and both halves
 * are evidence.
 */
export function splitLeadingJson(text: string): [unknown, string] | null {
  const open = text[0]
  if (open !== "{" && open !== "[") return null
  const close = open === "{" ? "}" : "]"
  let depth = 0, inString = false, escaped = false, end = -1
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (escaped) { escaped = false; continue }
    if (c === "\\") { escaped = true; continue }
    if (c === '"') { inString = !inString; continue }
    if (inString) continue
    if (c === open) depth++
    else if (c === close && --depth === 0) { end = i + 1; break }
  }
  if (end < 0) return null
  try {
    return [JSON.parse(text.slice(0, end)), text.slice(end).trim()]
  } catch {
    return null
  }
}

/** Parses one finding's evidence into blocks a reader can read. */
export function parseEvidence(evidence: string | null,
                              locale = "en"): EvidenceBlock[] {
  if (!evidence) return []
  const text = evidence.trim()
  if (!text) return []

  const split = splitLeadingJson(text)
  if (split) {
    const [value, rest] = split
    const blocks = blocksFromValue(value, locale)
    return rest ? blocks.concat(blocksFromText(rest, locale)) : blocks
  }
  return blocksFromText(text, locale)
}
