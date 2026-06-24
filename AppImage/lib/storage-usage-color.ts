// Shared usage-bar palette for storage capacity widgets. Extracted
// so the Storage page (overview cards + per-storage rows) and the
// Backups page (Available Archives → per-archive capacity bar) flag
// a full datastore with the same colour. Previously the Backups bar
// was hard-coded to blue, so a 100%-full PBS-Cloud appeared in red
// on Storage and in blue on Backups — same datastore, two different
// signals.
//
// Thresholds: < 75 % green, 75–89 % amber, ≥ 90 % red. Matches the
// existing Storage page palette and the "Free" text colour on the
// Backups page (which was already amber/red, just disconnected from
// the bar).

export type UsageBarColor = {
  /** Inline `background` value for SVG / style={} consumers. */
  hex: string
  /** Tailwind `bg-*` class for div consumers. */
  bgClass: string
  /** Tailwind `text-*` class for "Free" / counters that should
   *  share the urgency signal. */
  textClass: string
}

const GREEN: UsageBarColor = {
  hex: "#22c55e",
  bgClass: "bg-green-500",
  textClass: "text-green-500",
}
const AMBER: UsageBarColor = {
  hex: "#f59e0b",
  bgClass: "bg-amber-500",
  textClass: "text-amber-400",
}
const RED: UsageBarColor = {
  hex: "#ef4444",
  bgClass: "bg-red-500",
  textClass: "text-red-400",
}

export function getStorageUsageColor(percent: number): UsageBarColor {
  if (percent >= 90) return RED
  if (percent >= 75) return AMBER
  return GREEN
}
