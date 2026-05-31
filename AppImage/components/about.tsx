"use client"

import Image from "next/image"
import {
  Github,
  Heart,
  BookOpen,
  MessageSquare,
  Bug,
  Sparkles,
  Scale,
  ExternalLink,
} from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { APP_VERSION } from "./release-notes-modal"

// Issue #191: a dedicated About tab. Centralises project metadata
// (version, license, author) and every external link the project
// already exposes — GitHub, docs, donation. Replaces the lone
// "Support and contribute to the project" footer link with a proper
// information surface that's easy to extend with new social channels
// without re-cluttering the dashboard footer.

interface LinkRow {
  label: string
  description: string
  href: string
  Icon: React.ComponentType<{ className?: string }>
  accent?: keyof typeof ACCENT_CLASSES
}

// Tailwind only emits classes that appear as literal strings in the
// source. A dynamic `bg-${accent}/10` template does not survive the
// purge step, so each accent maps to a fully-spelled class pair below.
const ACCENT_CLASSES = {
  gray:   "bg-gray-500/10 text-gray-400",
  blue:   "bg-blue-500/10 text-blue-500",
  purple: "bg-purple-500/10 text-purple-400",
  red:    "bg-red-500/10 text-red-500",
  pink:   "bg-pink-500/10 text-pink-500",
} as const

const PROJECT_LINKS: LinkRow[] = [
  {
    label: "GitHub repository",
    description: "Source code, releases and issue tracker.",
    href: "https://github.com/MacRimi/ProxMenux",
    Icon: Github,
    accent: "gray",
  },
  {
    label: "Documentation",
    description: "Full user guide for ProxMenux and the Monitor.",
    href: "https://proxmenux.com",
    Icon: BookOpen,
    accent: "blue",
  },
  {
    label: "Discussions",
    description: "Ask questions, share custom AI prompts, swap ideas.",
    href: "https://github.com/MacRimi/ProxMenux/discussions",
    Icon: MessageSquare,
    accent: "purple",
  },
  {
    label: "Report a bug or request a feature",
    description: "Open an issue on GitHub — bugs, ideas, regressions.",
    href: "https://github.com/MacRimi/ProxMenux/issues",
    Icon: Bug,
    accent: "red",
  },
]

const SUPPORT_LINKS: LinkRow[] = [
  {
    label: "Support the project on Ko-fi",
    description: "ProxMenux is free and open source. Donations cover hosting and dev time.",
    href: "https://ko-fi.com/macrimi",
    Icon: Heart,
    accent: "pink",
  },
]

function LinkCard({ row }: { row: LinkRow }) {
  const accentClass = ACCENT_CLASSES[row.accent ?? "blue"]
  // Style mirrors the PCI Devices cards in the Hardware tab: subtle
  // translucent background by default, slightly lighter on hover, no
  // accent-coloured borders or text colour changes — keeps the look
  // consistent with the rest of the project.
  return (
    <a
      href={row.href}
      target="_blank"
      rel="noopener noreferrer"
      className="cursor-pointer flex items-start gap-3 rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 p-3 transition-colors"
    >
      <span
        className={`inline-flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md ${accentClass}`}
      >
        <row.Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-sm font-medium text-foreground">
          {row.label}
          <ExternalLink className="h-3 w-3 text-muted-foreground" />
        </div>
        <p className="text-xs text-muted-foreground mt-0.5 leading-snug">{row.description}</p>
      </div>
    </a>
  )
}

export function About() {
  return (
    <div className="space-y-4 md:space-y-6">
      {/* Hero — logo, name, version, one-line description. */}
      <Card>
        <CardContent className="pt-6 pb-6">
          <div className="flex flex-col md:flex-row items-center md:items-start gap-4 md:gap-6">
            <div className="relative w-24 h-24 md:w-28 md:h-28 flex-shrink-0">
              <Image
                src="/images/proxmenux-logo.png"
                alt="ProxMenux logo"
                fill
                priority
                className="object-contain"
              />
            </div>
            <div className="text-center md:text-left flex-1 min-w-0">
              <h2 className="text-2xl md:text-3xl font-semibold text-foreground">
                ProxMenux Monitor
              </h2>
              <p className="text-sm text-muted-foreground mt-1">
                A web dashboard and management layer for Proxmox VE — health monitoring,
                notifications, terminal, optimization tracker and more, packaged as a single
                AppImage.
              </p>
              <div className="flex flex-wrap items-center justify-center md:justify-start gap-2 mt-3">
                <span className="inline-flex items-center gap-1.5 rounded-md bg-blue-500/10 text-blue-500 border border-blue-500/30 px-2.5 py-1 text-xs font-mono">
                  <Sparkles className="h-3 w-3" />
                  v{APP_VERSION}
                </span>
                {/* Beta versions surface their pre-release notes on the
                    GitHub Releases page (where each beta is tagged + signed);
                    stable versions point at the canonical web changelog
                    which only carries shipped releases. Detection: the
                    APP_VERSION string carries a "-beta" / "-rc" /
                    "-alpha" suffix for any non-stable build. */}
                {(() => {
                  const isPrerelease = /-(beta|rc|alpha)/i.test(APP_VERSION)
                  const href = isPrerelease
                    ? "https://github.com/MacRimi/ProxMenux/releases"
                    : "https://proxmenux.com/en/changelog"
                  const label = isPrerelease ? "Release notes" : "Changelog"
                  return (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-md bg-muted hover:bg-muted/70 transition-colors text-foreground border border-border px-2.5 py-1 text-xs"
                    >
                      {label}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  )
                })()}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Project links — GitHub, docs, discussions, bug tracker. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Github className="h-4 w-4 text-muted-foreground" />
            Project
          </CardTitle>
          <CardDescription>Repository, documentation and community channels.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {PROJECT_LINKS.map(row => (
              <LinkCard key={row.href} row={row} />
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Support + License combined — donation link and licensing
          info in one card. The previous layout had a separate "Author"
          block that has been removed by request. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Heart className="h-4 w-4 text-pink-500" />
            Support &amp; License
          </CardTitle>
          <CardDescription>
            ProxMenux is free and open source under the GPL-3.0 license. If it&apos;s useful to
            you, a one-off contribution helps keep it that way.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-2">
            {SUPPORT_LINKS.map(row => (
              <LinkCard key={row.href} row={row} />
            ))}
            <a
              href="https://github.com/MacRimi/ProxMenux/blob/main/LICENSE"
              target="_blank"
              rel="noopener noreferrer"
              className="cursor-pointer flex items-start gap-3 rounded-lg border border-white/10 sm:border-border bg-white/5 sm:bg-card sm:hover:bg-white/5 p-3 transition-colors"
            >
              <span className="inline-flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-gray-500/10 text-gray-400">
                <Scale className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                  GPL-3.0 license
                  <ExternalLink className="h-3 w-3 text-muted-foreground" />
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 leading-snug">
                  Free software — see the LICENSE file for the full text.
                </p>
              </div>
            </a>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
