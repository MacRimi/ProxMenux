// Proxmox VE tag color scheme — 1:1 port of the algorithm in
// proxmoxlib.js (`Proxmox.Utils.stringToRGB` +
// `Proxmox.Utils.getTextContrastClass`). Same input → same color
// as the PVE web UI, so tags render identically in both places.

export type TagColor = {
  bg: string      // css `background-color`
  fg: string      // css `color` — auto-picked for contrast (SAPC)
  border: string  // css `border-color`
}

// Verbatim port of stringToRGB from proxmoxlib.js. The `+ 'prox'`
// suffix, the `<< 5` hash, and the `alpha=0.7 / bg=255` blend
// keep the output in the [76.5, 255] range per channel — that's
// why every PVE tag is a "washed" bright color instead of a raw
// hash-hue.
function stringToRGB(input: string): [number, number, number] {
  let hash = 0
  if (!input) return [255, 255, 255]
  const source = input + "prox"
  for (let i = 0; i < source.length; i++) {
    // eslint-disable-next-line no-bitwise
    hash = source.charCodeAt(i) + ((hash << 5) - hash)
    // eslint-disable-next-line no-bitwise
    hash = hash & hash
  }
  const alpha = 0.7
  const bg = 255
  return [
    // eslint-disable-next-line no-bitwise
    (hash & 255) * alpha + bg * (1 - alpha),
    // eslint-disable-next-line no-bitwise
    ((hash >> 8) & 255) * alpha + bg * (1 - alpha),
    // eslint-disable-next-line no-bitwise
    ((hash >> 16) & 255) * alpha + bg * (1 - alpha),
  ]
}

// SAPC-based light/dark text picker — verbatim port of
// getTextContrastClass. Same tag → same text color as PVE.
function getTextContrastClass(rgb: [number, number, number]): "light" | "dark" {
  const blkThrs = 0.022
  const blkClmp = 1.414
  const r = (rgb[0] / 255) ** 2.4
  const g = (rgb[1] / 255) ** 2.4
  const b = (rgb[2] / 255) ** 2.4
  let bg = r * 0.2126729 + g * 0.7151522 + b * 0.072175
  bg = bg > blkThrs ? bg : bg + (blkThrs - bg) ** blkClmp
  const contrastLight = bg ** 0.65 - 1
  const contrastDark = bg ** 0.56 - 0.046134502
  return Math.abs(contrastLight) >= Math.abs(contrastDark) ? "light" : "dark"
}

function rgbToCss(rgb: [number, number, number]): string {
  return `rgb(${Math.round(rgb[0])}, ${Math.round(rgb[1])}, ${Math.round(rgb[2])})`
}

export function tagToColor(tag: string): TagColor {
  const rgb = stringToRGB(tag)
  const bg = rgbToCss(rgb)
  const fg = getTextContrastClass(rgb) === "light" ? "#ffffff" : "#000000"
  return { bg, fg, border: bg }
}

// Split a PVE tags string into an array. PVE separators are ';' and
// ',' (both accepted); whitespace around tokens is stripped and
// empty tokens dropped.
export function parseTags(raw: string | null | undefined): string[] {
  if (!raw) return []
  return raw
    .split(/[;,]/)
    .map((t) => t.trim())
    .filter(Boolean)
}

// Join back into the canonical PVE format (';' separator).
export function stringifyTags(tags: string[]): string {
  return tags.map((t) => t.trim()).filter(Boolean).join(";")
}
