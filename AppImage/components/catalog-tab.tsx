"use client"

// Catalog tab: one place to find and open everything ProxMenux offers — the
// applications of the OCI manager, the scripts of Community Scripts and the
// options of the ProxMenux menu. A search on top, a space kept for the
// featured carousel, the categories of the applications, the tools that are
// not applications, and one sheet per item whose button runs the same flow
// as the menu.

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react"
import { ArrowLeft, BadgeCheck, Check, ChevronLeft, Container, Server, ChevronRight, ExternalLink, Loader2, Search, Settings2, X } from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useI18n, useT } from "../lib/i18n/provider"
import { useAccess } from "../lib/access"
import { categoryChipStyle, hueForCategory, useIsLightTheme } from "../lib/category-color"
import { getCategoryLabel } from "../lib/category-label"
import { ThemeAwareLogo } from "./lxc-app-panel"
import { CategoryIcon, CategoryTile } from "./category-icons"
import { Dialog, DialogContent, DialogTitle } from "./ui/dialog"
import { Switch } from "./ui/switch"
import { ScriptTerminalModal } from "./script-terminal-modal"

type Kind = "oci" | "cs" | "pmx"
type Group = "app" | "tool"

interface CatalogItem {
  key: string
  kind: Kind
  id: string
  name: string
  summary: string
  icon: string
  category: string
  architectures: string[]
  group: Group
  terms?: string
  multi?: boolean
  tested?: boolean
  privileged?: boolean
  type?: "lxc" | "vm" | "host" | "addon"
  updateable?: boolean
  // The section of a tool; whether opening that section lists it, as its
  // menu does, and its place there. A search finds it anyway.
  section?: string
  browse?: boolean
  order?: number
  // Where an add-on runs.
  runs_in?: string[]
  // Listed apart, as the menu lists its external scripts; and who maintains
  // a script that is not in the ProxMenux repository.
  apart?: boolean
  third_party?: Maintainer | null
  // The first screenshot of an application, for the featured banner.
  shot?: string
  // Who publishes the image of an OCI application, and how many LXC its
  // installation creates: one for each service.
  publisher?: { kind: "official" | "linuxserver" | "other"; name: string }
  containers?: number
}

// A section of the tools: one of the main menu of ProxMenux, with the
// Community Scripts scripts that menu offers itself, or a category of the
// Community Scripts scripts run on the host.
interface Section { key: string; kind: "pmx" | "cs"; title: string; external: string[] }

// The title of each section, for the chip of a tool.
const SectionTitles = createContext<Map<string, string>>(new Map())

interface Maintainer { name: string; url: string }

interface Note { type: "info" | "warning"; text: string; link?: string }

interface CatalogDetail extends CatalogItem {
  tagline?: string
  about: string
  explained?: string
  menu?: string
  notes: (string | Note)[]
  screenshots: string[]
  // Where each screenshot comes from, cited under it.
  screenshot_credits?: { label: string; url: string }[]
  links: { community?: string; website?: string; documentation?: string; repository?: string; script?: string; proxmenux?: string }
  image?: string
  ports: { port: number; protocol: string }[]
  resources: { cores?: number; memory_mb?: number; swap_mb?: number; disk_gb?: number; os?: string }
  unprivileged?: boolean
  volumes?: { path: string; mode: string; size_gb?: number; choices: string[] }[]
  services?: { name: string; role: string; main?: boolean; image?: string }[]
  suite?: { applications: { name: string; default: boolean }[]; players: string[] } | null
  releases?: string[]
  // Third-party scripts it runs in one of its steps.
  uses_third_party?: Maintainer[]
  // The settings a post-installation script applies, or offers to choose.
  includes?: { group: string; items: string[] }[]
  includes_kind?: "applies" | "offers"
  default_login?: { username: string; password: string } | null
  config_path?: string
  version?: string
  installable?: boolean
}

// A view of the tab: a category of applications, every application, or one
// of the groups of tools.
type View = { type: "category"; name: string } | { type: "all" } | { type: "section"; key: string }

const CS_LOGO = "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/community-scripts.webp"
const PMX_LOGO = "/images/proxmenux-logo.png"
const LSIO_LOGO = "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/linuxserver-io.webp"

// The same application from another source: OCI images of the project,
// a Community Scripts script, a VM ProxMenux creates. Names are compared
// without case or punctuation, and "Media Server" or "Dashboard" at the end.
function appKey(name: string) {
  let key = fold(name).replace(/[^a-z0-9]/g, "")
  // Community Scripts names its Alpine builds "Alpine-<application>".
  if (key.startsWith("alpine") && key.length > "alpine".length + 2) key = key.slice("alpine".length)
  for (const suffix of ["mediaserver", "dashboard"]) {
    if (key.endsWith(suffix) && key.length > suffix.length + 2) key = key.slice(0, -suffix.length)
  }
  return key
}

// Several images of one project share its name: the project's own comes
// first, then the one of LinuxServer.io, then any other publisher's.
const PUBLISHER_ORDER: Record<string, number> = { official: 0, linuxserver: 1, other: 2 }
const publisherRank = (item: CatalogItem) => item.publisher ? PUBLISHER_ORDER[item.publisher.kind] ?? 3 : 3
const RUN_SCRIPT = "/usr/local/share/proxmenux/scripts/catalog/run_item.sh"
const SETTINGS_KEY = "proxmenux-catalog-settings"

const itemsCache = new Map<string, { items: CatalogItem[]; sections: Section[]; catalog?: string }>()

const fold = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()

interface Settings { includeCs: boolean; broadSearch: boolean }
const DEFAULT_SETTINGS: Settings = { includeCs: true, broadSearch: false }

function readSettings(): Settings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY)
    if (!raw) return DEFAULT_SETTINGS
    const parsed = JSON.parse(raw)
    return {
      includeCs: typeof parsed.includeCs === "boolean" ? parsed.includeCs : DEFAULT_SETTINGS.includeCs,
      broadSearch: typeof parsed.broadSearch === "boolean" ? parsed.broadSearch : DEFAULT_SETTINGS.broadSearch,
    }
  } catch {
    return DEFAULT_SETTINGS
  }
}

function writeSettings(settings: Settings) {
  try { window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)) } catch { /* per-browser convenience */ }
}

// Every word of the query has to start a word of the text, as in the menu
// search: "tru" finds TrueNAS, not "intrusion".
// A name that joins its words with capitals, like ShareCoveX or CADCraft, also
// has each of them as a word: "share" and "cove", or "cad" and "craft".
const words = (text: string) => {
  const joined = fold(text).split(/[^a-z0-9]+/).filter(Boolean)
  const split = text.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
  const parts = fold(split).split(/[^a-z0-9]+/).filter(Boolean)
  return [...new Set([...joined, ...parts])]
}
function matchesAll(text: string, wanted: string[]) {
  const have = words(text)
  return wanted.every(term => have.some(word => word.startsWith(term)))
}

// Results come from ProxMenux first, then OCI manager and then Community
// Scripts, as in the menu search; within each, the best match first.
const SOURCE_ORDER: Record<Kind, number> = { pmx: 0, oci: 1, cs: 2 }

// Whether every word searched is a whole word of the item, not only the start
// of a longer one: "arch" is Arch Linux, not ArchiveBox.
function matchesWhole(item: CatalogItem, q: string, broad: boolean) {
  const have = words(`${item.name} ${item.id} ${item.terms || ""}${broad ? ` ${item.category} ${item.summary}` : ""}`)
  return words(q).every(term => have.includes(term))
}

// Name first; the broad search also looks at the category and the summary.
function rank(item: CatalogItem, q: string, broad: boolean): number {
  const wanted = words(q)
  if (!wanted.length) return -1
  const name = fold(item.name)
  if (name === q) return 0
  if (name.startsWith(q)) return 1
  if (matchesAll(item.name, wanted)) return 2
  if (matchesAll(`${item.name} ${item.id} ${item.terms || ""}`, wanted)) return 3
  if (!broad) return -1
  if (matchesAll(`${item.name} ${item.category}`, wanted)) return 4
  if (matchesAll(`${item.name} ${item.category} ${item.summary}`, wanted)) return 5
  return -1
}

function formatMemory(mb?: number) {
  if (!mb) return ""
  return mb >= 1024 ? `${+(mb / 1024).toFixed(1)} GB` : `${mb} MB`
}

// Where an item comes from, beside its name: the logo of Community Scripts,
// or the OCI mark. What carries no mark is ProxMenux's own.
// Who publishes the image of an OCI application: the project itself,
// LinuxServer.io with its logo, or another publisher by name.
function PublisherMark({ item }: { item: CatalogItem }) {
  const t = useT()
  const p = item.publisher
  if (!p) return null
  if (p.kind === "official") {
    return (
      <span title={t("catalog.publisherOfficialHint")} className="inline-flex items-center gap-0.5 text-sky-500">
        <BadgeCheck className="h-3.5 w-3.5" />{t("catalog.publisherOfficial")}
      </span>
    )
  }
  if (p.kind === "linuxserver") {
    return (
      <span title={p.name} className="inline-flex items-center gap-1">
        <img src={LSIO_LOGO} alt="" className="h-3.5 w-3.5 object-contain" />{p.name}
      </span>
    )
  }
  return <span title={p.name} className="max-w-[10rem] truncate">{p.name}</span>
}

function SourceMark({ item }: { item: CatalogItem }) {
  const t = useT()
  const kind = item.kind
  if (item.third_party) {
    return (
      <span title={`${t("catalog.thirdParty")}: ${item.third_party.name}`}
        className="flex-shrink-0 max-w-[45%] truncate rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold text-amber-500">
        {t("catalog.thirdParty")} · {item.third_party.name}
      </span>
    )
  }
  if (kind === "cs") {
    return <img src={CS_LOGO} alt={t("catalog.sourceCs")} title={t("catalog.sourceCs")} className="h-6 w-6 flex-shrink-0 rounded-md" />
  }
  if (kind === "oci") {
    return (
      <span title={t("catalog.sourceOci")}
        className="flex-shrink-0 rounded-full border border-blue-500/20 bg-blue-500/10 px-2 py-0.5 text-[11px] font-semibold tracking-wide text-blue-400">
        OCI
      </span>
    )
  }
  return null
}

// Icons come with different amounts of empty margin around the drawing, so
// the same box shows some of them smaller than others. The visible part of
// each icon is measured once and the icon is enlarged until it fills the box,
// like the icons that already do. An icon that cannot be measured (its server
// does not allow it) is left as it is.
const iconScales = new Map<string, number>()
const iconWaiters = new Map<string, ((scale: number) => void)[]>()

function measureIcon(src: string, done: (scale: number) => void) {
  const known = iconScales.get(src)
  if (known !== undefined) { done(known); return }
  const waiting = iconWaiters.get(src)
  if (waiting) { waiting.push(done); return }
  iconWaiters.set(src, [done])
  const finish = (scale: number) => {
    iconScales.set(src, scale)
    for (const callback of iconWaiters.get(src) || []) callback(scale)
    iconWaiters.delete(src)
  }
  const image = new Image()
  image.crossOrigin = "anonymous"
  image.onload = () => {
    try {
      const size = 64
      const canvas = document.createElement("canvas")
      canvas.width = canvas.height = size
      const context = canvas.getContext("2d", { willReadFrequently: true })
      if (!context) { finish(1); return }
      // Drawn the way object-contain draws it inside a square box.
      const ratio = Math.min(size / image.naturalWidth, size / image.naturalHeight)
      const w = image.naturalWidth * ratio, h = image.naturalHeight * ratio
      context.drawImage(image, (size - w) / 2, (size - h) / 2, w, h)
      const data = context.getImageData(0, 0, size, size).data
      let top = size, left = size, bottom = -1, right = -1
      for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
          if (data[(y * size + x) * 4 + 3] > 24) {
            if (y < top) top = y
            if (y > bottom) bottom = y
            if (x < left) left = x
            if (x > right) right = x
          }
        }
      }
      if (bottom < 0) { finish(1); return }
      const fill = Math.max(right - left + 1, bottom - top + 1) / size
      finish(fill >= 0.9 ? 1 : Math.min(1.7, 0.96 / fill))
    } catch {
      finish(1)
    }
  }
  image.onerror = () => finish(1)
  image.src = src
}

function useIconScale(src: string) {
  const [scale, setScale] = useState(() => iconScales.get(src) ?? 1)
  useEffect(() => {
    if (!src) return
    let active = true
    measureIcon(src, value => { if (active) setScale(value) })
    return () => { active = false }
  }, [src])
  return scale
}

function ItemIcon({ item, size }: { item: CatalogItem; size: "card" | "sheet" }) {
  const cls = size === "card" ? "w-9 h-9 object-contain" : "h-10 w-10 object-contain"
  // An option of the menu without a logo of its own: a tool shows the
  // ProxMenux logo, as a Community Scripts script shows its own; an
  // application, the icon of its category.
  const own = item.kind === "pmx" && !item.icon
  const src = own ? (item.group === "tool" ? PMX_LOGO : "") : item.icon
  const scale = useIconScale(src)
  if (own && item.group === "app") return <CategoryIcon category={item.category} className={size === "card" ? "h-8 w-8" : "h-9 w-9"} />
  if (!src) return <span className="text-[10px] font-mono text-muted-foreground uppercase">{item.name.slice(0, 2)}</span>
  return (
    <div className="grid place-items-center" style={scale !== 1 ? { transform: `scale(${scale})` } : undefined}>
      {own ? <img src={src} alt="" className={cls} /> : <ThemeAwareLogo src={src} className={cls} />}
    </div>
  )
}

function categoryText(t: (key: string) => string, item: CatalogItem, titles: Map<string, string>) {
  return item.group === "tool" ? titles.get(item.section || "") || "" : getCategoryLabel(t, item.category)
}

// The colour of the chip follows the category of an application, the section of a tool.
const chipKey = (item: CatalogItem) => item.group === "tool" ? `__section_${item.section}` : item.category

// What kind of script an application is; an add-on says where it is installed.
function typeLabel(t: (key: string) => string, item: CatalogItem) {
  if (item.type === "addon") {
    return (item.runs_in || []).some(where => where === "lxc" || where === "vm") ? t("catalog.addonInGuest") : t("catalog.addonOnHost")
  }
  return t(`catalog.type.${item.type}`)
}

// The type of a guest wears the colours it has on the VMs and LXCs page:
// cyan for an LXC, purple for a VM; any other type is plain.
function TypeBadge({ item, size }: { item: CatalogItem; size: "card" | "sheet" }) {
  const t = useT()
  const box = size === "card" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-0.5 text-xs"
  if (item.type === "lxc" || item.type === "vm") {
    const lxc = item.type === "lxc"
    const Icon = lxc ? Container : Server
    return (
      <span className={`inline-flex items-center gap-1 rounded-full border font-medium ${box} ${lxc
        ? "bg-cyan-500/10 text-cyan-500 border-cyan-500/20" : "bg-purple-500/10 text-purple-500 border-purple-500/20"}`}>
        <Icon className="h-3 w-3" />{lxc ? "LXC" : "VM"}
      </span>
    )
  }
  return size === "card"
    ? <span className={item.type === "addon" ? "" : "font-mono uppercase"}>{typeLabel(t, item)}</span>
    : <span className={`rounded-full border border-border font-medium text-muted-foreground ${box}`}>{typeLabel(t, item)}</span>
}

function ItemCard({ item, onOpen }: { item: CatalogItem; onOpen: () => void }) {
  const t = useT()
  const isLight = useIsLightTheme()
  const titles = useContext(SectionTitles)
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group flex w-full min-w-0 flex-col gap-2 overflow-hidden p-3.5 text-left bg-card border border-border rounded-xl hover:bg-white/5 hover:border-border/80 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring active:translate-y-px"
    >
      <div className="flex w-full min-w-0 items-center gap-3">
        <div className="w-14 h-14 rounded-md bg-muted/40 grid place-items-center flex-shrink-0 overflow-hidden">
          <ItemIcon item={item} size="card" />
        </div>
        <span className="flex-1 min-w-0 text-base font-semibold text-foreground leading-tight line-clamp-2 break-words" title={item.name}>{item.name}</span>
        <SourceMark item={item} />
      </div>
      {item.summary && <p className="w-full text-sm text-muted-foreground line-clamp-2 m-0">{item.summary}</p>}
      <div className="flex w-full flex-wrap items-center gap-1.5 mt-auto pt-2 border-t border-dashed border-border/60 text-[11px] text-muted-foreground">
        {item.category && (
          <span className="max-w-full truncate rounded-full border px-2 py-0.5" style={categoryChipStyle(chipKey(item), isLight)}>
            {categoryText(t, item, titles)}
          </span>
        )}
        {item.kind !== "oci" && item.group === "app" && item.type && (
          <TypeBadge item={item} size="card" />
        )}
        {item.kind === "oci" && <PublisherMark item={item} />}
        {item.architectures.length > 0 && <span className="ml-auto font-mono text-indigo-400">{item.architectures.join(" · ")}</span>}
      </div>
    </button>
  )
}

// Featured applications: a few picked at random each time the tab is opened,
// those with a screenshot first.
function pickFeatured(apps: CatalogItem[], count = 6): CatalogItem[] {
  const shuffled = [...apps]
  for (let n = shuffled.length - 1; n > 0; n--) {
    const k = Math.floor(Math.random() * (n + 1));
    [shuffled[n], shuffled[k]] = [shuffled[k], shuffled[n]]
  }
  return [...shuffled.filter(i => i.shot), ...shuffled.filter(i => !i.shot)].slice(0, count)
}

function Featured({ items, onOpen }: { items: CatalogItem[]; onOpen: (item: CatalogItem) => void }) {
  const t = useT()
  const [i, setI] = useState(0)
  const [paused, setPaused] = useState(false)
  // A screenshot that does not load (its server or a blocker refuses it)
  // leaves the application with its logo instead of an empty window.
  const [broken, setBroken] = useState<Set<string>>(new Set())
  useEffect(() => {
    if (paused || items.length < 2) return
    const timer = setInterval(() => setI(n => (n + 1) % items.length), 7000)
    return () => clearInterval(timer)
  }, [paused, items.length])
  if (!items.length) return null
  const item = items[i % items.length]
  const hue = hueForCategory(item.category)
  const show = (n: number) => setI((n + items.length) % items.length)
  return (
    <section aria-label={t("catalog.featured")} onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
      className="relative h-[240px] overflow-hidden rounded-2xl border border-border text-white sm:h-[260px]"
      style={{ background: `linear-gradient(120deg, hsl(${hue} 55% 28%), hsl(${hue} 45% 11%) 75%)` }}>
      {/* The application's screenshot, like a window rising from the bottom;
          without one, its logo in large. The shadow follows what it draws:
          a screenshot with its own frame and a transparent margin gets no
          second frame around it. */}
      {item.shot && !broken.has(item.shot) ? (
        <img key={item.shot} src={item.shot} alt="" onError={() => setBroken(b => new Set(b).add(item.shot!))}
          className="absolute right-6 top-8 hidden h-[calc(100%-8px)] w-[46%] rounded-t-lg object-cover object-left-top [filter:drop-shadow(0_18px_28px_rgba(0,0,0,0.45))] md:block" />
      ) : (
        <div className="absolute right-12 top-1/2 hidden h-36 w-36 -translate-y-1/2 place-items-center rounded-3xl border border-white/10 bg-card md:grid">
          <div className="scale-[2.2]"><ItemIcon item={item} size="card" /></div>
        </div>
      )}
      <div className="relative flex h-full flex-col justify-center gap-3 p-6 pb-12 md:max-w-[50%]">
        <span className="text-xs font-semibold uppercase tracking-wider text-white/70">{t("catalog.featured")}</span>
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid h-14 w-14 flex-shrink-0 place-items-center overflow-hidden rounded-xl border border-white/10 bg-card">
            <ItemIcon item={item} size="card" />
          </div>
          <h2 className="m-0 min-w-0 text-2xl font-bold leading-tight line-clamp-2 break-words">{item.name}</h2>
        </div>
        {item.summary && <p className="m-0 max-w-[60ch] text-sm leading-relaxed text-white/80 line-clamp-2">{item.summary}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" onClick={() => onOpen(item)}
            className="rounded-lg bg-white px-4 py-2 text-sm font-semibold text-black hover:bg-white/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70">
            {t("catalog.featuredOpen")}
          </button>
          <span className="text-xs text-white/70">{getCategoryLabel(t, item.category)}</span>
        </div>
      </div>
      {items.length > 1 && (
        <div className="absolute bottom-3 left-6 flex items-center gap-2">
          <button type="button" onClick={() => show(i - 1)} aria-label="‹"
            className="grid h-7 w-7 place-items-center rounded-full bg-black/30 hover:bg-black/50"><ChevronLeft className="h-4 w-4" /></button>
          {items.map((it, n) => (
            <button key={it.key} type="button" onClick={() => setI(n)} aria-label={it.name} aria-current={n === i}
              className={`h-1.5 rounded-full transition-all ${n === i ? "w-5 bg-white" : "w-1.5 bg-white/40 hover:bg-white/70"}`} />
          ))}
          <button type="button" onClick={() => show(i + 1)} aria-label="›"
            className="grid h-7 w-7 place-items-center rounded-full bg-black/30 hover:bg-black/50"><ChevronRight className="h-4 w-4" /></button>
        </div>
      )}
    </section>
  )
}

function Gallery({ shots: all, credits = [], name }: { shots: string[]; credits?: { label: string; url: string }[]; name: string }) {
  const t = useT()
  const [i, setI] = useState(0)
  // A shot that does not load is left out, and the gallery shows the next.
  const [broken, setBroken] = useState<Set<string>>(new Set())
  const shots = all.filter(s => !broken.has(s))
  const drop = (src: string) => setBroken(b => new Set(b).add(src))
  if (!shots.length) return null
  const at = i < shots.length ? i : 0
  const show = (n: number) => setI((n + shots.length) % shots.length)
  const credit = credits[all.indexOf(shots[at])]
  return (
    <div className="px-5 sm:px-6 grid gap-2.5">
      {/* The shot fills the frame by its width or by its height, whichever
          comes first, and never overflows it. */}
      <div className="relative w-full aspect-video max-h-[440px] rounded-lg border border-border bg-muted/30 overflow-hidden">
        {/* A shot narrower or lower than the frame leaves room at its sides:
            the same shot, enlarged and blurred, fills it with its colours. */}
        <img key={`${shots[at]}-backdrop`} src={shots[at]} alt="" aria-hidden
          className="absolute inset-0 h-full w-full scale-110 object-cover opacity-40 blur-2xl" />
        <img src={shots[at]} alt={`${name} ${at + 1}`} onError={() => drop(shots[at])} className="absolute inset-0 h-full w-full object-contain" />
        {shots.length > 1 && (
          <>
            <button type="button" onClick={() => show(at - 1)} aria-label="‹"
              className="absolute left-2.5 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full border border-border bg-card/85 grid place-items-center hover:bg-card">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button type="button" onClick={() => show(at + 1)} aria-label="›"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full border border-border bg-card/85 grid place-items-center hover:bg-card">
              <ChevronRight className="h-4 w-4" />
            </button>
            <span className="absolute top-2.5 right-2.5 rounded-full border border-border bg-card/85 px-2 py-0.5 text-xs font-mono tabular-nums">{at + 1} / {shots.length}</span>
          </>
        )}
      </div>
      {credit?.label && (
        <p className="m-0 text-xs text-muted-foreground">
          {t("catalog.sheet.imageSource")}:{" "}
          <a href={credit.url} target="_blank" rel="noopener noreferrer" className="underline-offset-2 hover:underline break-all">{credit.label}</a>
        </p>
      )}
      {shots.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-0.5">
          {shots.map((src, n) => (
            <button key={src} type="button" onClick={() => setI(n)} aria-current={n === at}
              className={`relative flex-shrink-0 h-[60px] w-24 rounded-md border-2 bg-muted/30 overflow-hidden ${n === at ? "border-foreground" : "border-transparent"}`}>
              <img src={src} alt="" onError={() => drop(src)} className="absolute inset-0 h-full w-full object-contain" />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

const Heading = ({ children }: { children: React.ReactNode }) => (
  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{children}</h3>
)

function Sheet({ item, onClose, onRun, related, onOpenOther }: {
  item: CatalogItem; onClose: () => void; onRun: (advanced: boolean) => void
  related: CatalogItem[]; onOpenOther: (item: CatalogItem) => void
}) {
  const t = useT()
  const titles = useContext(SectionTitles)
  const { language } = useI18n()
  const isLight = useIsLightTheme()
  // Installing or running opens a terminal on the host: a session that
  // cannot run anything reads the sheet without those buttons.
  const { capabilities } = useAccess()
  const [detail, setDetail] = useState<CatalogDetail | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    setDetail(null)
    setFailed(false)
    fetchApi<CatalogDetail>(`/api/catalog/items/${item.kind}/${encodeURIComponent(item.id)}?lang=${language}`)
      .then(d => { if (active) setDetail(d) })
      .catch(() => { if (active) setFailed(true) })
    return () => { active = false }
  }, [item.kind, item.id, language])

  const d = detail
  const r = d?.resources || {}
  const specs: [string, string][] = []
  if (r.cores) specs.push([String(r.cores), t("catalog.sheet.cores")])
  if (r.memory_mb) specs.push([formatMemory(r.memory_mb), t("catalog.sheet.ram")])
  if (r.swap_mb) specs.push([formatMemory(r.swap_mb), t("catalog.sheet.swap")])
  if (r.disk_gb) specs.push([`${r.disk_gb} GB`, t("catalog.sheet.disk")])
  if (r.os) specs.push([r.os, t("catalog.sheet.system")])

  const notes: Note[] = [
    ...(item.type === "addon" ? [{ type: "info" as const, text: t("catalog.sheet.addonNote") }] : []),
    ...(d?.notes || []).map(n => typeof n === "string" ? { type: "info" as const, text: n } : n),
    ...(d?.uses_third_party || []).map(m => ({ type: "warning" as const, text: t("catalog.sheet.usesThirdParty", { name: m.name }), link: m.url })),
  ]
  const links: [string, string][] = []
  if (d?.links.website) links.push([t("catalog.sheet.website"), d.links.website])
  if (d?.links.documentation) links.push([t("catalog.sheet.documentation"), d.links.documentation])
  if (d?.links.repository && !/hub\.docker\.com|ghcr\.io/.test(d.links.repository)) links.push([t("catalog.sheet.repository"), d.links.repository])
  if (d?.links.proxmenux) links.push([t("catalog.sheet.proxmenuxDocs"), d.links.proxmenux])
  const host = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, "") } catch { return url } }

  const badges = (
    <>
      {item.category && (
        <span className="rounded-full border px-2.5 py-0.5 text-xs font-medium" style={categoryChipStyle(chipKey(item), isLight)}>
          {categoryText(t, item, titles)}
        </span>
      )}
      {item.kind === "oci" && (
        <span className="rounded-full border border-blue-500/20 bg-blue-500/10 px-2.5 py-0.5 text-xs font-medium text-blue-400">
          {item.multi ? t("catalog.stack") : t("catalog.oneContainer")}
        </span>
      )}
      {item.kind !== "oci" && item.type && (
        <TypeBadge item={item} size="sheet" />
      )}
      {item.kind === "oci" && d && (
        <span className="rounded-full border border-green-500/30 bg-green-500/10 px-2.5 py-0.5 text-xs font-medium text-green-500">
          {d.unprivileged ? t("catalog.sheet.unprivileged") : t("catalog.sheet.privileged")}
        </span>
      )}
      {item.kind === "cs" && item.updateable && (
        <span className="rounded-full border border-green-500/30 bg-green-500/10 px-2.5 py-0.5 text-xs font-medium text-green-500">{t("catalog.updateable")}</span>
      )}
      {item.tested && (
        <span className="inline-flex items-center gap-1 rounded-full border border-green-500/30 bg-green-500/10 px-2.5 py-0.5 text-xs font-medium text-green-500">
          <Check className="h-3 w-3" />{t("catalog.tested")}
        </span>
      )}
      {item.architectures.length > 0 && (
        <span className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-0.5 text-xs font-mono text-indigo-400">{item.architectures.join(" · ")}</span>
      )}
    </>
  )

  return (
    <Dialog open onOpenChange={open => { if (!open) onClose() }}>
      <DialogContent hideClose className="max-w-5xl w-[calc(100vw-1.5rem)] p-0 gap-0 flex flex-col overflow-hidden h-[88vh] max-h-[calc(100dvh-env(safe-area-inset-top)-env(safe-area-inset-bottom)-24px)]">
        <div className="flex items-start gap-4 px-5 sm:px-6 pt-5 pb-3 sm:pb-4">
          <div className="h-[60px] w-[60px] flex-shrink-0 rounded-xl border border-border bg-muted/40 grid place-items-center overflow-hidden">
            <ItemIcon item={item} size="sheet" />
          </div>
          <div className="flex-1 min-w-0 grid gap-1.5">
            <DialogTitle className="text-xl font-bold leading-tight">{item.name}</DialogTitle>
            {(d?.tagline || ((item.kind !== "pmx" || item.third_party) && item.summary)) && (
              <p className="m-0 text-sm text-muted-foreground line-clamp-2">{d?.tagline || item.summary}</p>
            )}
            {/* Beside the icon on a wide screen; on a phone, in a row of their own below. */}
            <div className="hidden sm:flex flex-wrap gap-1.5">{badges}</div>
          </div>
          <button type="button" onClick={onClose} aria-label={t("actions.close")}
            className="h-9 w-9 flex-shrink-0 rounded-lg border border-border grid place-items-center hover:bg-muted">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5 px-5 pb-4 sm:hidden">{badges}</div>

        <div className="flex-1 overflow-y-auto pb-6">
          {/* A script that is not in the ProxMenux repository says who
              maintains it: Community Scripts, or any other third party. */}
          {(item.kind === "cs" || item.third_party) && (() => {
            const cs = item.kind === "cs"
            const url = cs ? d?.links.community || "" : item.third_party?.url || ""
            return (
              <div className="mx-5 sm:mx-6 mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-border border-l-4 border-l-orange-400 bg-orange-500/5 px-3 py-2.5">
                {cs ? <img src={CS_LOGO} alt="" className="h-9 w-9 rounded-lg" />
                  : <div className="grid h-9 w-9 flex-shrink-0 place-items-center overflow-hidden rounded-lg bg-muted/40"><ItemIcon item={item} size="card" /></div>}
                <div className="flex-1 min-w-[10rem] grid">
                  <span className="text-xs text-muted-foreground">{t("catalog.sheet.scriptBy")}</span>
                  <strong className="text-base">{cs ? t("catalog.sourceCs") : item.third_party?.name}</strong>
                </div>
                {url && (
                  <span className="text-sm text-muted-foreground">
                    {t("catalog.sheet.moreInfo")}{" "}
                    <a href={url} target="_blank" rel="noopener noreferrer" className="font-semibold text-foreground whitespace-nowrap hover:underline">
                      {cs ? "community-scripts.org" : host(url)} ↗
                    </a>
                  </span>
                )}
              </div>
            )
          })()}

          {d && <Gallery shots={d.screenshots} credits={d.screenshot_credits} name={item.name} />}

          {!d && !failed && (
            <div className="grid place-items-center py-24 text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>
          )}
          {failed && <p className="px-6 py-12 text-center text-muted-foreground">{t("catalog.sheet.loadError")}</p>}

          {d && (
            <div className="grid gap-6 px-5 sm:px-6 pt-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
              {/* A long URL in a note or a description wraps anywhere, so it
                  never widens this column over the side panel. */}
              <div className="grid gap-6 content-start min-w-0 [&>*]:min-w-0 [overflow-wrap:anywhere]">
                <section>
                  <Heading>{item.group === "tool" ? t("catalog.sheet.whatItDoes") : t("catalog.sheet.whatItIs")}</Heading>
                  <p className="m-0 leading-relaxed max-w-[68ch] whitespace-pre-line">{d.about || item.summary}</p>
                  {d.explained && <p className="mt-3 mb-0 leading-relaxed max-w-[68ch] text-muted-foreground">{d.explained}</p>}
                </section>
                {d.includes && d.includes.length > 0 && (
                  <section>
                    <Heading>{t(d.includes_kind === "applies" ? "catalog.sheet.settingsApplied" : "catalog.sheet.settingsOffered",
                      { count: d.includes.reduce((n, g) => n + g.items.length, 0) })}</Heading>
                    <div className="grid gap-4">
                      {d.includes.map(g => (
                        <div key={g.group || "all"} className="grid gap-1">
                          {g.group && <h4 className="m-0 text-sm font-semibold">{g.group}</h4>}
                          <ul className="m-0 grid gap-1 pl-5 list-disc text-sm marker:text-muted-foreground">
                            {g.items.map(name => <li key={name}>{name}</li>)}
                          </ul>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
                {/* An application of several services installs one LXC for
                    each: which ones, with their image, the main one first. */}
                {d.services && d.services.length > 1 && (
                  <section>
                    <Heading>{t("catalog.sheet.containersCreated", { count: d.services.length })}</Heading>
                    <p className="m-0 mb-3 max-w-[68ch] text-sm leading-relaxed text-muted-foreground">{t("catalog.sheet.containersIntro")}</p>
                    <div className="grid gap-1.5">
                      {d.services.map(service => (
                        <div key={service.name} className="flex min-w-0 items-center gap-3 rounded-md border border-border bg-muted/30 px-3 py-2">
                          <Container className="h-4 w-4 flex-shrink-0 text-cyan-500" />
                          <div className="grid min-w-0 flex-1">
                            <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                              {service.name}
                              {service.main && (
                                <span className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2 py-0 text-[11px] font-medium text-cyan-500">{t("catalog.sheet.mainContainer")}</span>
                              )}
                            </span>
                            {service.image && <code className="truncate font-mono text-xs text-muted-foreground" title={service.image}>{service.image}</code>}
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
                {notes.length > 0 && (
                  <section>
                    <Heading>{t("catalog.sheet.notes")}</Heading>
                    <div className="grid gap-2">
                      {notes.map((n, i) => (
                        <div key={i} className={`min-w-0 rounded-md border border-border border-l-[3px] bg-muted/30 px-3 py-2.5 text-sm ${n.type === "warning" ? "border-l-amber-500" : "border-l-cyan-500"}`}>
                          {n.text}
                          {n.link && <>{" "}<a href={n.link} target="_blank" rel="noopener noreferrer" className="whitespace-nowrap underline underline-offset-2 hover:text-foreground">{t("catalog.sheet.thirdPartyLink")} ↗</a></>}
                        </div>
                      ))}
                    </div>
                  </section>
                )}
                {d.default_login && (
                  <section>
                    <Heading>{t("catalog.sheet.defaultLogin")}</Heading>
                    <p className="m-0 font-mono text-sm">
                      {d.default_login.username && <>{t("catalog.sheet.user")}: {d.default_login.username}</>}
                      {d.default_login.username && d.default_login.password && " · "}
                      {d.default_login.password && <>{t("catalog.sheet.password")}: {d.default_login.password}</>}
                    </p>
                  </section>
                )}
              </div>

              <aside className="grid gap-4 content-start rounded-lg border border-border bg-muted/20 p-4 min-w-0">
                {specs.length > 0 && (
                  <section>
                    <Heading>{item.kind === "oci" ? t("catalog.sheet.suggested") : item.kind === "pmx" ? t("catalog.sheet.defaultSettings") : t("catalog.sheet.scriptResources")}</Heading>
                    <div className="grid grid-cols-2 gap-2">
                      {specs.map(([value, label]) => (
                        <div key={label} className="rounded-md border border-border bg-card px-2.5 py-2 grid">
                          <b className="text-base tabular-nums">{value}</b>
                          <span className="text-xs text-muted-foreground">{label}</span>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
                <dl className="grid gap-2.5 m-0 text-sm">
                  {d.menu && (
                    <div className="grid gap-0.5">
                      <dt className="text-xs text-muted-foreground">{t("catalog.sheet.whereInMenu")}</dt>
                      <dd className="m-0">{d.menu}</dd>
                    </div>
                  )}
                  {d.ports.map(p => (
                    <div key={`${p.port}/${p.protocol}`} className="grid gap-0.5">
                      <dt className="text-xs text-muted-foreground">{t("catalog.sheet.access")}</dt>
                      <dd className="m-0">{t("catalog.sheet.accessPort", { port: `${p.port}/${p.protocol}` })}</dd>
                    </div>
                  ))}
                  {(d.volumes || []).map(v => (
                    <div key={v.path} className="grid gap-0.5">
                      <dt className="text-xs text-muted-foreground">{t("catalog.sheet.storage")}</dt>
                      <dd className="m-0 break-words"><code className="font-mono text-[13px]">{v.path}</code> · {v.choices.includes("host-bind") && v.mode !== "host-bind"
                        ? t("catalog.sheet.volumeOrHost") : v.mode === "host-bind" ? t("catalog.sheet.hostFolder")
                        : t("catalog.sheet.volume", { size: v.size_gb ?? "" })}</dd>
                    </div>
                  ))}
                  {d.releases && d.releases.length > 0 && (
                    <div className="grid gap-1">
                      <dt className="text-xs text-muted-foreground">{t("catalog.sheet.releases")}</dt>
                      <dd className="m-0 flex flex-wrap gap-1.5">
                        {d.releases.map(r => (
                          <span key={r} className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">{r}</span>
                        ))}
                      </dd>
                    </div>
                  )}
                  {d.suite && (
                    <>
                      <div className="grid gap-1">
                        <dt className="text-xs text-muted-foreground">{t("catalog.sheet.suiteApps")}</dt>
                        <dd className="m-0 flex flex-wrap gap-1.5">
                          {d.suite.applications.map(a => (
                            <span key={a.name} title={a.default ? t("catalog.sheet.byDefault") : undefined}
                              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${a.default ? "border-green-500/30 bg-green-500/10 text-green-500" : "border-border text-muted-foreground"}`}>
                              {a.default && <Check className="h-3 w-3" />}{a.name}
                            </span>
                          ))}
                        </dd>
                        <dd className="m-0 text-xs text-muted-foreground">{t("catalog.sheet.suiteDefaults")}</dd>
                      </div>
                      {d.suite.players.length > 0 && (
                        <div className="grid gap-0.5">
                          <dt className="text-xs text-muted-foreground">{t("catalog.sheet.mediaServer")}</dt>
                          <dd className="m-0">{t("catalog.sheet.mediaServerChoice", { players: d.suite.players.join(", ") })}</dd>
                        </div>
                      )}
                    </>
                  )}
                  {item.publisher && (
                    <div className="grid gap-0.5">
                      <dt className="text-xs text-muted-foreground">{t("catalog.sheet.publisher")}</dt>
                      <dd className="m-0"><PublisherMark item={item} /></dd>
                    </div>
                  )}
                  {d.image && !(d.services && d.services.length > 1) && (
                    <div className="grid gap-0.5">
                      <dt className="text-xs text-muted-foreground">{t("catalog.sheet.image")}</dt>
                      <dd className="m-0 break-all"><code className="font-mono text-[13px]">{d.image}</code></dd>
                    </div>
                  )}
                  {d.config_path && (
                    <div className="grid gap-0.5">
                      <dt className="text-xs text-muted-foreground">{t("catalog.sheet.config")}</dt>
                      <dd className="m-0 break-all"><code className="font-mono text-[13px]">{d.config_path}</code></dd>
                    </div>
                  )}
                  {d.links.script && (
                    <div className="grid gap-0.5">
                      <dt className="text-xs text-muted-foreground">{t("catalog.sheet.script")}</dt>
                      <dd className="m-0"><a href={d.links.script} target="_blank" rel="noopener noreferrer" className="hover:underline">{t("catalog.sheet.viewCode")} ↗</a></dd>
                    </div>
                  )}
                  {d.version && (
                    <div className="grid gap-0.5">
                      <dt className="text-xs text-muted-foreground">{t("catalog.sheet.version")}</dt>
                      <dd className="m-0 font-mono text-[13px]">{d.version}</dd>
                    </div>
                  )}
                </dl>

                {capabilities.execute && <div className="grid gap-2">
                  {item.kind === "oci" ? (
                    <>
                      <button type="button" disabled={d.installable === false} onClick={() => onRun(false)}
                        className="rounded-md bg-green-600 hover:bg-green-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">
                        {t("catalog.sheet.install")}
                      </button>
                      <button type="button" disabled={d.installable === false} onClick={() => onRun(true)}
                        className="rounded-md border border-border bg-card px-4 py-2.5 text-sm font-semibold hover:bg-muted disabled:opacity-50">
                        {t("catalog.sheet.installAdvanced")}
                      </button>
                    </>
                  ) : (
                    <button type="button" onClick={() => onRun(false)}
                      className="rounded-md bg-green-600 hover:bg-green-700 px-4 py-2.5 text-sm font-semibold text-white">
                      {item.kind === "cs" ? t("catalog.sheet.runScript")
                        : item.kind === "pmx" && item.type === "vm" ? t("catalog.sheet.createVm") : t("catalog.sheet.open")}
                    </button>
                  )}
                </div>}

                {links.length > 0 && (
                  <section>
                    <Heading>{t("catalog.sheet.links")}</Heading>
                    <div className="grid gap-1.5">
                      {links.map(([label, url]) => (
                        <a key={url} href={url} target="_blank" rel="noopener noreferrer"
                          className="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-2.5 py-2 text-sm no-underline text-foreground hover:bg-muted">
                          <span>{label}</span>
                          <span className="flex items-center gap-1 text-muted-foreground truncate">{host(url)} <ExternalLink className="h-3.5 w-3.5 flex-shrink-0" /></span>
                        </a>
                      ))}
                    </div>
                  </section>
                )}
              </aside>
            </div>
          )}
          {related.length > 0 && (
            <section className="px-5 sm:px-6 pt-6">
              <Heading>{t("catalog.sheet.alsoAvailable")}</Heading>
              <div className="grid gap-2 sm:grid-cols-2">
                {related.map(other => (
                  <button key={other.key} type="button" onClick={() => onOpenOther(other)}
                    className="flex min-w-0 items-center gap-3 rounded-lg border border-border bg-card p-2.5 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    <div className="grid h-10 w-10 flex-shrink-0 place-items-center overflow-hidden rounded-md bg-muted/40">
                      <ItemIcon item={other} size="card" />
                    </div>
                    <div className="grid min-w-0 flex-1 gap-0.5">
                      <span className="truncate font-medium">{other.name}</span>
                      <span className="flex min-w-0 flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                        {other.kind === "oci" ? <PublisherMark item={other} />
                          : <span>{other.kind === "cs" ? t("catalog.sourceCs") : "ProxMenux"}{other.type ? ` · ${typeLabel(t, other)}` : ""}</span>}
                      </span>
                    </div>
                    <SourceMark item={other} />
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Tile({ icon, label, hint, onClick, disabled }: { icon: string; label: string; hint?: string; onClick?: () => void; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className="flex w-full min-w-0 items-center gap-3.5 rounded-xl border border-border bg-card p-3.5 text-left hover:bg-white/5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-55 disabled:hover:bg-card">
      <CategoryTile category={icon} />
      <span className="grid min-w-0">
        <b className="truncate font-semibold">{label}</b>
        {hint && <span className="text-sm text-muted-foreground">{hint}</span>}
      </span>
    </button>
  )
}

export function CatalogTab() {
  const t = useT()
  const { language } = useI18n()
  const [items, setItems] = useState<CatalogItem[] | null>(itemsCache.get(language)?.items || null)
  const [sections, setSections] = useState<Section[]>(itemsCache.get(language)?.sections || [])
  const [failed, setFailed] = useState(false)
  const [query, setQuery] = useState("")
  const [view, setView] = useState<View | null>(null)
  const [open, setOpen] = useState<CatalogItem | null>(null)
  const [run, setRun] = useState<{ item: CatalogItem; advanced: boolean } | null>(null)
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS)
  const [showSettings, setShowSettings] = useState(false)
  const settingsRef = useRef<HTMLDivElement>(null)

  useEffect(() => { setSettings(readSettings()) }, [])
  const updateSettings = (next: Settings) => { setSettings(next); writeSettings(next) }

  useEffect(() => {
    const cached = itemsCache.get(language)
    if (cached) { setItems(cached.items); setSections(cached.sections); return }
    setItems(null)
    setFailed(false)
    let active = true
    const timers: ReturnType<typeof setTimeout>[] = []
    const load = (quiet: boolean) =>
      fetchApi<{ items: CatalogItem[]; sections?: Section[]; catalog?: string; refreshing?: boolean }>(`/api/catalog/items?lang=${language}`)
        .then(data => {
          if (!active) return
          const previous = itemsCache.get(language)
          // A quiet reload only replaces the cards when a newer catalog arrived.
          if (quiet && previous?.catalog === data.catalog) return
          const loaded = { items: data.items || [], sections: data.sections || [], catalog: data.catalog }
          itemsCache.set(language, loaded)
          setItems(loaded.items)
          setSections(loaded.sections)
          // The catalog is being refreshed in the background: look again
          // later, without telling the user anything.
          if (!quiet && data.refreshing) timers.push(setTimeout(() => load(true), 45000), setTimeout(() => load(true), 120000))
        })
        .catch(() => { if (active && !quiet) setFailed(true) })
    load(false)
    return () => { active = false; timers.forEach(clearTimeout) }
  }, [language])

  useEffect(() => {
    if (!showSettings) return
    const close = (e: MouseEvent) => { if (!settingsRef.current?.contains(e.target as Node)) setShowSettings(false) }
    document.addEventListener("mousedown", close)
    return () => document.removeEventListener("mousedown", close)
  }, [showSettings])

  const visible = useMemo(() => (items || []).filter(i => settings.includeCs || i.kind !== "cs"), [items, settings.includeCs])
  const apps = useMemo(() => visible.filter(i => i.group === "app"), [visible])
  const featured = useMemo(() => pickFeatured(apps), [apps])
  // The applications that are the same one from another source.
  const sameApp = useMemo(() => {
    const groups = new Map<string, CatalogItem[]>()
    for (const item of apps) groups.set(appKey(item.name), [...(groups.get(appKey(item.name)) || []), item])
    for (const list of groups.values()) list.sort((a, b) => SOURCE_ORDER[a.kind] - SOURCE_ORDER[b.kind] || publisherRank(a) - publisherRank(b))
    return groups
  }, [apps])

  const categories = useMemo(() => {
    const counts = new Map<string, number>()
    for (const item of apps) counts.set(item.category, (counts.get(item.category) || 0) + 1)
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name)
  }, [apps])

  const q = fold(query.trim())
  const results = useMemo(() => {
    if (!q) return null
    // Who publishes an OCI image is searched too: "linuxserver" or "lsio"
    // finds the LinuxServer.io images, "official" the project's own.
    const publisherTerms = (item: CatalogItem) => !item.publisher ? ""
      : item.publisher.kind === "official" ? `official ${t("catalog.publisherOfficial")}`
      : item.publisher.kind === "linuxserver" ? `${item.publisher.name} lsio` : item.publisher.name
    const found = visible
      .map(item => item.publisher ? { ...item, terms: `${item.terms || ""} ${publisherTerms(item)}` } : item)
      .map(item => [item, rank(item, q, settings.broadSearch)] as const)
      .filter(([, r]) => r >= 0)
    // When what is typed is the name of an application as it is written
    // (the first word of its name, such as "arch" for Arch Linux), the items
    // that only have a longer word starting with it are left out: ArchiveBox
    // is not Arch. While a name is still being typed ("next" of Nextcloud),
    // every item that starts with it stays.
    const typed = fold(q).split(/[^a-z0-9]+/).filter(Boolean)[0] || ""
    const named = found.some(([item]) => fold(item.name).split(/[^a-z0-9]+/).filter(Boolean)[0] === typed)
    const whole = named ? found.filter(([item]) => matchesWhole(item, q, settings.broadSearch)) : []
    const ranked = (whole.length ? whole : found)
      .sort((a, b) => SOURCE_ORDER[a[0].kind] - SOURCE_ORDER[b[0].kind] || a[1] - b[1] || a[0].name.localeCompare(b[0].name)
        || publisherRank(a[0]) - publisherRank(b[0]))
      .map(([item]) => item)
    return {
      apps: ranked.filter(i => i.group === "app"),
      tools: ranked.filter(i => i.group === "tool"),
    }
  }, [visible, q, settings.broadSearch, t])

  // A section of the main menu lists what its menu lists, in its order, and
  // then the Community Scripts scripts that menu offers; a section of
  // Community Scripts, its scripts by name.
  const shownSections = useMemo(() => sections.filter(section =>
    visible.some(i => i.group === "tool" && i.section === section.key)), [sections, visible])
  const titles = useMemo(() => new Map(sections.map(section =>
    [section.key, section.kind === "cs" ? getCategoryLabel(t, section.title) : section.title] as [string, string])), [sections, t])

  const listed = useMemo(() => {
    if (!view || view.type === "section") return []
    const list = view.type === "category" ? apps.filter(i => i.category === view.name) : apps
    return [...list].sort((a, b) => a.name.localeCompare(b.name) || publisherRank(a) - publisherRank(b))
  }, [view, apps])

  const sectionView = useMemo(() => {
    if (view?.type !== "section") return null
    const section = sections.find(s => s.key === view.key)
    if (!section) return { own: [], external: [] }
    const listed = visible.filter(i => i.section === section.key && (section.kind === "cs" ? i.group === "tool" : !!i.browse))
      .sort((a, b) => section.kind === "cs" ? a.name.localeCompare(b.name) : (a.order ?? 0) - (b.order ?? 0))
    const byKey = new Map(visible.map(i => [i.key, i]))
    // Below its own options, the third-party scripts the menu lists apart, in
    // its order.
    const own = listed.filter(i => !i.apart)
    const external = section.external.map(key => byKey.get(key)).filter((i): i is CatalogItem => !!i)
    return { own, external }
  }, [view, sections, visible])


  const grid = (list: CatalogItem[]) => (
    <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      {list.map(item => <ItemCard key={item.key} item={item} onOpen={() => setOpen(item)} />)}
    </div>
  )

  const viewTitle = !view ? "" : view.type === "category" ? getCategoryLabel(t, view.name)
    : view.type === "all" ? t("catalog.allApps")
    : titles.get(view.key) || ""
  const viewIcon = !view ? "" : view.type === "category" ? view.name : view.type === "all" ? "__all"
    : `__section_${view.key}`
  const viewCount = sectionView ? sectionView.own.length + sectionView.external.length : listed.length

  return (
    <SectionTitles.Provider value={titles}>
    <div className="grid gap-6">
      <div className="relative flex gap-2" ref={settingsRef}>
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={t("catalog.searchPlaceholder")}
            aria-label={t("catalog.searchPlaceholder")}
            className="w-full rounded-xl border border-border bg-card py-3.5 pl-12 pr-4 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
        <button type="button" onClick={() => setShowSettings(s => !s)} aria-expanded={showSettings} aria-label={t("catalog.settings")} title={t("catalog.settings")}
          className={`h-[54px] w-[54px] flex-shrink-0 rounded-xl border border-border grid place-items-center hover:bg-muted ${showSettings ? "bg-muted" : "bg-card"}`}>
          <Settings2 className="h-5 w-5" />
        </button>
        {showSettings && (
          <div className="absolute right-0 top-[62px] z-20 w-[min(26rem,100%)] rounded-xl border border-border bg-card p-4 shadow-lg grid gap-4">
            <h2 className="m-0 text-base font-semibold">{t("catalog.settings")}</h2>
            <div className="flex items-start justify-between gap-4">
              <div className="grid gap-0.5">
                <span className="font-medium">{t("catalog.settingsIncludeCs")}</span>
                <span className="text-sm text-muted-foreground">{t("catalog.settingsIncludeCsHint")}</span>
              </div>
              <Switch checked={settings.includeCs} onCheckedChange={v => updateSettings({ ...settings, includeCs: v })}
                className="data-[state=checked]:bg-blue-600 data-[state=unchecked]:bg-input border border-border" />
            </div>
            <div className="flex items-start justify-between gap-4">
              <div className="grid gap-0.5">
                <span className="font-medium">{t("catalog.settingsBroad")}</span>
                <span className="text-sm text-muted-foreground">{t("catalog.settingsBroadHint")}</span>
              </div>
              <Switch checked={settings.broadSearch} onCheckedChange={v => updateSettings({ ...settings, broadSearch: v })}
                className="data-[state=checked]:bg-blue-600 data-[state=unchecked]:bg-input border border-border" />
            </div>
          </div>
        )}
      </div>

      {!items && !failed && (
        <div className="grid place-items-center py-24 text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>
      )}
      {failed && <p className="py-16 text-center text-muted-foreground">{t("catalog.loadError")}</p>}

      {items && results && (
        <div className="grid gap-6">
          {!results.apps.length && !results.tools.length && (
            <p className="py-12 text-center text-muted-foreground">{t("catalog.noResults", { query: query.trim() })}</p>
          )}
          {([["apps", t("catalog.groups.apps")], ["tools", t("catalog.groups.tools")]] as const)
            .filter(([key]) => results[key].length > 0)
            .map(([key, label]) => (
              <section key={key} className="grid gap-3">
                <h2 className="m-0 text-sm font-medium text-muted-foreground">{label} · {results[key].length}</h2>
                {grid(results[key].slice(0, 120))}
              </section>
            ))}
        </div>
      )}

      {items && !results && !view && (
        <>
          <Featured items={featured} onOpen={setOpen} />
          <section className="grid gap-3">
            <h2 className="m-0 text-lg font-semibold">{t("catalog.toolsPmx")}</h2>
            <div className="grid gap-3 grid-cols-1 min-[420px]:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {shownSections.filter(section => section.kind === "pmx").map(section => (
                <Tile key={section.key} icon={`__section_${section.key}`} label={section.title} onClick={() => setView({ type: "section", key: section.key })} />
              ))}
              <Tile icon="__plugins" label={t("catalog.plugins")} hint={t("catalog.pluginsSoon")} disabled />
            </div>
          </section>
          {shownSections.some(section => section.kind === "cs") && (
            <section className="grid gap-3">
              <h2 className="m-0 text-lg font-semibold">{t("catalog.toolsCs")}</h2>
              <div className="grid gap-3 grid-cols-1 min-[420px]:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {shownSections.filter(section => section.kind === "cs").map(section => (
                  <Tile key={section.key} icon={`__section_${section.key}`} label={titles.get(section.key) || section.title}
                    onClick={() => setView({ type: "section", key: section.key })} />
                ))}
              </div>
            </section>
          )}
          <section className="grid gap-3">
            <h2 className="m-0 text-lg font-semibold">{t("catalog.categories")}</h2>
            <div className="grid gap-3 grid-cols-1 min-[420px]:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              <Tile icon="__all" label={t("catalog.allApps")} onClick={() => setView({ type: "all" })} />
              {categories.map(name => (
                <Tile key={name} icon={name} label={getCategoryLabel(t, name)} onClick={() => setView({ type: "category", name })} />
              ))}
            </div>
          </section>
        </>
      )}

      {items && !results && view && (
        <section className="grid gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" onClick={() => setView(null)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-sm hover:bg-muted">
              <ArrowLeft className="h-4 w-4" />{t("catalog.back")}
            </button>
            <CategoryTile category={viewIcon} size="sm" />
            <h2 className="m-0 text-lg font-semibold">{viewTitle}</h2>
            <span className="text-sm text-muted-foreground tabular-nums">{t("catalog.itemsCount", { count: viewCount })}</span>
          </div>
          {sectionView ? (
            <>
              {sectionView.own.length > 0 && grid(sectionView.own)}
              {sectionView.external.length > 0 && (
                <div className="grid gap-3">
                  <h3 className="m-0 text-sm font-medium text-muted-foreground">{t("catalog.externalScripts")}</h3>
                  {grid(sectionView.external)}
                </div>
              )}
              {!viewCount && <p className="py-12 text-center text-muted-foreground">{t("catalog.emptyView")}</p>}
            </>
          ) : listed.length ? grid(listed) : <p className="py-12 text-center text-muted-foreground">{t("catalog.emptyView")}</p>}
        </section>
      )}

      {open && <Sheet key={open.key} item={open} onClose={() => setOpen(null)} onRun={advanced => { setRun({ item: open, advanced }); setOpen(null) }}
        related={(sameApp.get(appKey(open.name)) || []).filter(other => other.key !== open.key)} onOpenOther={setOpen} />}

      {run && (
        <ScriptTerminalModal
          open
          onClose={() => setRun(null)}
          scriptPath={RUN_SCRIPT}
          scriptName="catalog_run_item"
          title={run.item.kind === "oci" ? t("catalog.terminalInstall", { name: run.item.name })
            : run.item.kind === "cs" ? t("catalog.terminalRun", { name: run.item.name })
            : t("catalog.terminalOpen", { name: run.item.name })}
          description={t("catalog.terminalDescription")}
          params={{ KIND: run.item.kind, ITEM: run.item.id, ADVANCED: run.advanced ? "1" : "0" }}
          cancelledExitCode={130}
        />
      )}
    </div>
    </SectionTitles.Provider>
  )
}
