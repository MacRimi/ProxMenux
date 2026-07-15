// Shared usage-bar palette for storage capacity widgets. Extracted
// so the Storage page (overview cards + per-storage rows) and the
// Backups page (Available Archives → per-archive capacity bar) flag
// a full datastore with the same colour. Previously the Backups bar
// was hard-coded to blue, so a 100%-full PBS-Cloud appeared in red
// on Storage and in blue on Backups — same datastore, two different
// signals.
//
// Thresholds: < 75 % blue (normal — no alert), 75–89 % amber,
// ≥ 90 % red. Matches the Storage page palette: the normal state
// stays on the project's brand blue and only switches to amber/red
// when the operator should look at it. Green is reserved for OK
// signals where green has meaning (SMART status, wear level), not
// for ambient bars.

export type UsageBarColor = {
  /** Inline `background` value for SVG / style={} consumers. */
  hex: string
  /** Tailwind `bg-*` class for div consumers. */
  bgClass: string
  /** Tailwind `text-*` class for "Free" / counters that should
   *  share the urgency signal. */
  textClass: string
}

const BLUE: UsageBarColor = {
  hex: "#3b82f6",
  bgClass: "bg-blue-500",
  // No text-blue override for the "Free" counter — at normal usage
  // the foreground colour reads better than tinted text.
  textClass: "",
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
  return BLUE
}
