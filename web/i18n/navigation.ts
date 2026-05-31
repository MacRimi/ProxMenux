import { createNavigation } from "next-intl/navigation"
import { routing } from "./routing"

/**
 * Locale-aware wrappers around `next/link`, `next/navigation` and
 * server-side `redirect()`. Import from here instead of `next/link`
 * for internal hrefs — these helpers automatically prepend the active
 * `[locale]` segment, so a component can write `<Link href="/docs">`
 * and the user sees `/en/docs` or `/es/docs` depending on context.
 *
 * External URLs and anchors (`href="#section"`) are left untouched.
 */
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing)
