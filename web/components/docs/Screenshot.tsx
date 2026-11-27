import { closeSync, openSync, readSync } from "node:fs"
import { join } from "node:path"
import Image from "next/image"

/*
 * A documentation screenshot at its natural size: the PNG's pixel size
 * divided by the density of the screen it was captured on (2 for Retina,
 * the default; pass 1 for a 1x capture). It is centered, never wider than
 * the text column, and shrinks on narrow screens. Width and height are
 * read from the file in public/ at build time, so the browser reserves
 * the right box before the image loads.
 *
 * Server component only: client pages cannot read public/.
 */

const SITE = "https://macrimi.github.io/ProxMenux"

const warned = new Set<string>()

// Null when the file is missing, unreadable or not a PNG: docs PRs may name a
// screenshot the maintainer adds later, and that must not break the build.
function pngSize(src: string): { width: number; height: number } | null {
  const file = join(process.cwd(), "public", src.startsWith(SITE) ? src.slice(SITE.length) : src)
  const header = Buffer.alloc(24)
  try {
    const fd = openSync(file, "r")
    try {
      readSync(fd, header, 0, 24, 0)
    } finally {
      closeSync(fd)
    }
  } catch {
    header.fill(0)
  }
  // shortcut: PNG only (every docs screenshot is one); JPEG or WebP fall back to full width, add them when a page needs one.
  if (header.toString("latin1", 1, 4) === "PNG") return { width: header.readUInt32BE(16), height: header.readUInt32BE(20) }
  if (!warned.has(src)) {
    warned.add(src)
    console.warn(`Screenshot: ${src} is missing or not a PNG in public/, shown at full width`)
  }
  return null
}

export function Screenshot({
  src,
  alt,
  density = 2,
  className = "rounded-lg border border-gray-200 shadow-xs",
}: {
  src: string
  alt: string
  density?: number
  className?: string
}) {
  const size = pngSize(src)
  if (!size) {
    return <Image src={src} alt={alt} width={1600} height={1000} className={`${className} w-full h-auto`} />
  }
  return (
    <Image
      src={src}
      alt={alt}
      width={Math.round(size.width / density)}
      height={Math.round(size.height / density)}
      className={`mx-auto block h-auto max-w-full ${className}`}
    />
  )
}
