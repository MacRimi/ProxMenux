"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import useSWR from "swr"
import { ArrowUpCircle, Check, ExternalLink, Pencil, Plus, Search } from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"
import { ThemeAwareLogo } from "./lxc-app-panel"
import { CustomLinkEditor, type CustomLink, type GuestOption } from "./custom-link-editor"
import { Button } from "./ui/button"
import { categoryChipStyle, useIsLightTheme } from "../lib/category-color"

// ─── Local subset of /api/vms shape ─────────────────────────────
// Kept narrow on purpose — this component only needs what feeds a
// launcher card. Full VMData / LxcAppWatch types live in
// virtual-machines.tsx.

interface AppPort {
  port: number
  description?: string
  scheme?: "http" | "https"
  web_path?: string
  logo_url?: string | null
  category?: string
  custom_url?: string
}

interface AppWatch {
  id: string
  name: string | null
  logo_url?: string | null
  ports?: AppPort[]
  installed_version: string | null
  latest_version: string | null
  update_available: boolean | null
  managed_oci_app_id?: string | null
  helper_slug?: string
}

interface DockerImageUpdate {
  reference: string
  display_name?: string | null
  used_by?: string[]
  update_available: boolean | null
}

// Locate the docker_inventory image whose lifecycle matches a given
// Web Link. The port's `description` is a user-typed label (e.g.
// "Paperless") so exact match on `used_by` (real container names
// like "paperless-webserver-1") almost never hits. Fall back through:
//   1. exact match in `used_by`
//   2. case-insensitive substring either way in `used_by`
//   3. substring in `display_name`
//   4. substring in `reference` (the full image path)
// Returns undefined when nothing matches — the caller treats that as
// "no upstream update signal for this port".
function findDockerImageForPort(
  port: AppPort,
  images: DockerImageUpdate[],
): DockerImageUpdate | undefined {
  const desc = (port.description || "").trim().toLowerCase()
  if (!desc || !images.length) return undefined
  const exact = images.find((i) =>
    (i.used_by || []).some((c) => c.toLowerCase() === desc),
  )
  if (exact) return exact
  const inclUsedBy = images.find((i) =>
    (i.used_by || []).some((c) => {
      const cl = c.toLowerCase()
      return cl.includes(desc) || desc.includes(cl)
    }),
  )
  if (inclUsedBy) return inclUsedBy
  const byDisplay = images.find((i) => {
    const d = (i.display_name || "").toLowerCase()
    return !!d && (d.includes(desc) || desc.includes(d))
  })
  if (byDisplay) return byDisplay
  return images.find((i) => (i.reference || "").toLowerCase().includes(desc))
}

interface VM {
  vmid: number
  name: string
  ip?: string
  type: string
  app_watches?: AppWatch[]
  docker_inventory?: { images?: DockerImageUpdate[] }
}

interface LaunchLink {
  key: string
  // Present for LXC-registered apps and for custom links with a
  // guest binding. Absent when the link is an unbound custom entry
  // (e.g. an external service).
  vmid: number | null
  guestType: "lxc" | "qemu" | null
  ctName: string
  appName: string
  logoUrl: string | null
  weblink: string
  category: string
  updateAvailable: boolean
  // Set for user-defined custom links so the card can offer edit
  // and delete actions in edit mode.
  isCustom: boolean
  customId?: string
}

// ─── Helpers ─────────────────────────────────────────────────────

// Same URL construction as the Web Link row in the App tab.
// Duplicated (small) on purpose — buildWebUrl in lxc-app-panel.tsx
// is scoped to that module, and copying keeps this component free of
// hidden cross-file dependencies. A per-port `custom_url` overrides
// the ip:port composition entirely — used for apps served behind a
// reverse-proxy domain.
function buildWebUrl(ip: string | undefined, port: AppPort): string | null {
  const custom = (port.custom_url || "").trim()
  if (custom) return custom
  const raw = (ip || "").trim().split("/")[0]
  if (!raw || raw === "DHCP" || !port?.port) return null
  const host = raw.includes(":") && !raw.startsWith("[") ? `[${raw}]` : raw
  const scheme = port.scheme || ([443, 8443, 9443].includes(port.port) ? "https" : "http")
  const path = port.web_path ? `/${port.web_path.replace(/^\/+/, "")}` : ""
  return `${scheme}://${host}:${port.port}${path}`
}

type SortMode = "name" | "ct" | "category"
const SORT_STORAGE_KEY = "proxmenux-apps-sort"
const ALL_CATEGORIES = "__all__"

const fetcher = async (url: string) => fetchApi(url)

// ─── Component ───────────────────────────────────────────────────

export function AppsDashboard() {
  const t = useT()
  const { data: vms } = useSWR<VM[]>("/api/vms", fetcher, { refreshInterval: 5000, revalidateOnFocus: false })
  // Custom links persisted in /etc/proxmenux/custom_links.json. Small
  // and rarely changes, so we don't poll on an interval — mutate() is
  // called explicitly after create / update / delete.
  const { data: customLinks, mutate: mutateCustomLinks } = useSWR<CustomLink[]>(
    "/api/apps/custom-links", fetcher, { revalidateOnFocus: false },
  )
  // Category presets for the "+ Add link" modal.
  const { data: categoryPresets } = useSWR<string[]>(
    "/api/apps/categories", fetcher, { revalidateOnFocus: false },
  )

  const isLightTheme = useIsLightTheme()

  // Flatten VMs → LaunchLinks. One card per (app × port with weblink)
  // for LXC-registered apps, plus one card per user-defined custom
  // link. A custom link with a binding resolves its ctName from the
  // matching guest in `vms` so renames stay in sync automatically.
  const links = useMemo<LaunchLink[]>(() => {
    const out: LaunchLink[] = []
    const vmsList = Array.isArray(vms) ? vms : []
    for (const vm of vmsList) {
      const apps = vm.app_watches || []
      if (!apps.length) continue
      for (const app of apps) {
        // Skip the synthetic entry ProxMenux inserts for managed
        // OCI apps (Secure Gateway) — it has no user-assigned
        // Web Link and doesn't belong in a launcher.
        if (app.managed_oci_app_id) continue
        // `app.update_available` refers to the app itself. For a
        // Docker registration that app is the Docker engine, and its
        // ports are containers running INSIDE Docker (Portainer,
        // Frigate…) — each with an independent image update
        // lifecycle in `vm.docker_inventory.images[]`. Propagating
        // the engine-level flag to every container card would falsely
        // mark Portainer/Frigate as updatable when only the engine
        // needs bumping; missing the per-image flag would hide real
        // Portainer/Frigate updates that ARE tracked in the App tab
        // and fire notifications. Resolution: for each Docker port,
        // find the image entry whose `used_by` includes the port's
        // container name (== `port.description`) and use THAT image's
        // update_available. Engine update stays out of the port cards
        // — it belongs in the Updates tab.
        const isDockerApp = app.helper_slug === "docker"
        const dockerImages = vm.docker_inventory?.images || []
        for (const port of app.ports || []) {
          const url = buildWebUrl(vm.ip, port)
          if (!url) continue
          let updateAvailable = false
          if (isDockerApp) {
            const img = findDockerImageForPort(port, dockerImages)
            updateAvailable = img?.update_available === true
          } else {
            updateAvailable = app.update_available === true
          }
          out.push({
            key: `lxc-${vm.vmid}-${app.id}-${port.port}`,
            vmid: vm.vmid,
            guestType: "lxc",
            ctName: vm.name,
            appName: (port.description || app.name || vm.name || "").trim(),
            logoUrl: port.logo_url || app.logo_url || null,
            weblink: url,
            category: (port.category || "").trim(),
            updateAvailable,
            isCustom: false,
          })
        }
      }
    }
    // Merge user-defined custom links. Their `binding` decides how the
    // CT/VM reference renders and where clicking it navigates.
    const guestByVmid = new Map<number, { name: string; type: string }>()
    for (const vm of vmsList) guestByVmid.set(vm.vmid, { name: vm.name, type: vm.type })
    for (const link of customLinks || []) {
      let ctName = ""
      let vmid: number | null = null
      let guestType: "lxc" | "qemu" | null = null
      if (link.binding) {
        const guest = guestByVmid.get(link.binding.vmid)
        vmid = link.binding.vmid
        guestType = link.binding.guest_type
        ctName = guest?.name || ""
      }
      out.push({
        key: `custom-${link.id}`,
        vmid,
        guestType,
        ctName,
        appName: link.name,
        logoUrl: link.logo_url || null,
        weblink: link.url,
        category: (link.category || "").trim(),
        updateAvailable: false,
        isCustom: true,
        customId: link.id,
      })
    }
    return out
  }, [vms, customLinks])

  // Category list for the filter dropdown — built from the data so
  // it always reflects reality (presets and custom-entered names).
  const categoryCounts = useMemo(() => {
    const map = new Map<string, number>()
    for (const l of links) {
      const key = l.category || t("apps.uncategorized")
      map.set(key, (map.get(key) || 0) + 1)
    }
    return map
  }, [links, t])
  const sortedCategoryEntries = useMemo(
    () => Array.from(categoryCounts.entries()).sort((a, b) => a[0].localeCompare(b[0])),
    [categoryCounts],
  )

  // ─── Controls state ────────────────────────────────────────────

  const [query, setQuery] = useState("")
  const [currentCat, setCurrentCat] = useState<string>(ALL_CATEGORIES)
  const [sortMode, setSortMode] = useState<SortMode>("name")
  const [searchExpanded, setSearchExpanded] = useState(false)
  const searchInputRef = useRef<HTMLInputElement | null>(null)

  // Restore sort from localStorage on mount.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(SORT_STORAGE_KEY)
      if (saved === "name" || saved === "ct" || saved === "category") {
        setSortMode(saved)
      }
    } catch (_) { /* private mode / storage disabled — silent */ }
  }, [])

  // Persist sort choice — only this one preference survives reload;
  // category filter and search reset each visit so the dashboard
  // always opens showing every app.
  useEffect(() => {
    try { localStorage.setItem(SORT_STORAGE_KEY, sortMode) } catch (_) {}
  }, [sortMode])

  // Filter category resets if the user removes/renames the currently
  // selected one and it disappears from the list.
  useEffect(() => {
    if (currentCat === ALL_CATEGORIES) return
    if (!categoryCounts.has(currentCat)) setCurrentCat(ALL_CATEGORIES)
  }, [currentCat, categoryCounts])

  // ─── Custom link editor state ──────────────────────────────────

  const [editorOpen, setEditorOpen] = useState(false)
  const [editingLink, setEditingLink] = useState<CustomLink | null>(null)
  const [editMode, setEditMode] = useState(false)

  // Guest list feeds the binding dropdown in the editor modal.
  const guestOptions = useMemo<GuestOption[]>(() => {
    if (!Array.isArray(vms)) return []
    return vms
      .filter((v) => v.type === "lxc" || v.type === "qemu")
      .map((v) => ({
        vmid: v.vmid,
        name: v.name,
        type: v.type as "lxc" | "qemu",
      }))
  }, [vms])

  const openNewLink = () => {
    setEditingLink(null)
    setEditorOpen(true)
  }
  const openEditForLink = (customId: string) => {
    const found = (customLinks || []).find((l) => l.id === customId)
    if (!found) return
    setEditingLink(found)
    setEditorOpen(true)
  }

  // ─── Filter + sort ─────────────────────────────────────────────

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    const uncatKey = t("apps.uncategorized")
    let filtered = links
    if (currentCat !== ALL_CATEGORIES) {
      filtered = filtered.filter((l) => (l.category || uncatKey) === currentCat)
    }
    if (q) {
      filtered = filtered.filter((l) =>
        l.appName.toLowerCase().includes(q) ||
        (l.ctName || "").toLowerCase().includes(q) ||
        (l.vmid != null && String(l.vmid).includes(q)) ||
        (l.category || "").toLowerCase().includes(q)
      )
    }
    const sorted = [...filtered]
    sorted.sort((a, b) => {
      if (sortMode === "name") return a.appName.localeCompare(b.appName)
      if (sortMode === "ct") {
        // Unbound custom links have no vmid; sort them after every
        // bound entry, ordered alphabetically by app name.
        if (a.vmid == null && b.vmid == null) return a.appName.localeCompare(b.appName)
        if (a.vmid == null) return 1
        if (b.vmid == null) return -1
        return (a.vmid - b.vmid) || a.appName.localeCompare(b.appName)
      }
      // category — grouped alphabetically, then by app name inside
      const catA = a.category || uncatKey
      const catB = b.category || uncatKey
      const c = catA.localeCompare(catB)
      return c !== 0 ? c : a.appName.localeCompare(b.appName)
    })
    return sorted
  }, [links, query, currentCat, sortMode, t])

  // ─── Empty state ───────────────────────────────────────────────

  const hasAnyData = links.length > 0 || (customLinks && customLinks.length > 0)
  if (vms && !hasAnyData) {
    return (
      <>
        <div className="text-center text-muted-foreground py-16">
          <div className="text-sm">{t("apps.emptyTitle")}</div>
          <div className="text-xs mt-1 opacity-80">{t("apps.emptyHint")}</div>
          <Button
            onClick={openNewLink}
            variant="outline"
            className="mt-4"
          >
            <Plus className="h-4 w-4 mr-1.5" />
            {t("apps.customLinkAdd")}
          </Button>
        </div>
        <CustomLinkEditor
          open={editorOpen}
          onOpenChange={setEditorOpen}
          editing={editingLink}
          guests={guestOptions}
          categoryPresets={categoryPresets || []}
          onSaved={() => mutateCustomLinks()}
        />
      </>
    )
  }

  // ─── Render ────────────────────────────────────────────────────

  const countLabel = shown.length === 1
    ? t("apps.countOne")
    : t("apps.countMany", { n: shown.length })

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Search — icon-only until tapped on narrow screens */}
        <div className={`relative ${searchExpanded ? "flex-1 min-w-full sm:min-w-0 sm:flex-none sm:w-72" : "sm:flex-1 sm:min-w-40 sm:max-w-xs"}`}>
          {!searchExpanded && (
            <button
              type="button"
              onClick={() => {
                setSearchExpanded(true)
                requestAnimationFrame(() => searchInputRef.current?.focus())
              }}
              className="sm:hidden inline-flex items-center justify-center w-9 h-9 rounded-md border border-border bg-card text-muted-foreground hover:text-foreground hover:border-border/80 transition-colors"
              aria-label={t("apps.searchAriaLabel")}
            >
              <Search className="h-4 w-4" />
            </button>
          )}
          <div className={`relative ${searchExpanded ? "block" : "hidden sm:block"}`}>
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
            <input
              ref={searchInputRef}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onBlur={() => { if (!query.trim()) setSearchExpanded(false) }}
              placeholder={t("apps.searchPlaceholder")}
              aria-label={t("apps.searchAriaLabel")}
              className="w-full h-9 pl-8 pr-3 text-sm bg-card border border-border rounded-md text-foreground placeholder:text-muted-foreground focus:border-border/80 focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>

        {/* Category filter */}
        <select
          value={currentCat}
          onChange={(e) => setCurrentCat(e.target.value)}
          aria-label={t("apps.filterAriaLabel")}
          className="h-9 pl-3 pr-8 text-sm bg-card border border-border rounded-md text-foreground appearance-none cursor-pointer max-w-[9.5rem] sm:max-w-none truncate focus:border-border/80 focus:outline-none focus:ring-1 focus:ring-ring bg-no-repeat bg-[right_0.6rem_center]"
          style={{
            backgroundImage: "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'><path d='m6 9 6 6 6-6'/></svg>\")",
          }}
        >
          <option value={ALL_CATEGORIES}>{t("apps.filterAll")}</option>
          {sortedCategoryEntries.map(([cat, n]) => (
            <option key={cat} value={cat}>{`${cat} · ${n}`}</option>
          ))}
        </select>

        {/* Sort */}
        <select
          value={sortMode}
          onChange={(e) => setSortMode(e.target.value as SortMode)}
          aria-label={t("apps.sortAriaLabel")}
          className="h-9 pl-3 pr-8 text-sm bg-card border border-border rounded-md text-foreground appearance-none cursor-pointer max-w-[8rem] sm:max-w-none truncate focus:border-border/80 focus:outline-none focus:ring-1 focus:ring-ring bg-no-repeat bg-[right_0.6rem_center]"
          style={{
            backgroundImage: "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'><path d='m6 9 6 6 6-6'/></svg>\")",
          }}
        >
          <option value="name">{t("apps.sortName")}</option>
          <option value="ct">{t("apps.sortId")}</option>
          <option value="category">{t("apps.sortCategory")}</option>
        </select>

        {/* Count — desktop only. Mobile gives the horizontal room to
            the + button instead so everything stays on one line. */}
        <span className="ml-auto hidden sm:inline-flex items-center h-9 px-3 text-xs text-muted-foreground rounded-md bg-card border border-border font-mono tabular-nums">
          {countLabel}
        </span>

        {/* + Add custom link. Icon-only on mobile (mirrors the search
            icon-toggle pattern) so the toolbar fits in one line even
            in the narrowest viewport. On desktop shows label + icon. */}
        <Button
          type="button"
          variant="outline"
          onClick={openNewLink}
          className="sm:ml-2 ml-auto h-9 px-2.5 sm:px-3 flex-shrink-0"
          aria-label={t("apps.customLinkAdd")}
        >
          <Plus className="h-4 w-4 sm:mr-1.5" />
          <span className="hidden sm:inline">{t("apps.customLinkAdd")}</span>
        </Button>

        {/* Edit mode toggle — only shown when at least one custom link
            exists, since it's the only card type that carries per-card
            edit/delete actions. LXC-registered apps are edited in the
            LXC App tab of their guest modal. */}
        {(customLinks && customLinks.length > 0) && (
          <Button
            type="button"
            variant="outline"
            onClick={() => setEditMode((v) => !v)}
            className={`h-9 px-2.5 sm:px-3 flex-shrink-0 ${editMode ? "border-blue-500/60 text-blue-400" : ""}`}
            aria-pressed={editMode}
            aria-label={t("apps.editModeToggle")}
          >
            {editMode ? <Check className="h-4 w-4 sm:mr-1.5" /> : <Pencil className="h-4 w-4 sm:mr-1.5" />}
            <span className="hidden sm:inline">{editMode ? t("apps.editModeDone") : t("apps.editModeToggle")}</span>
          </Button>
        )}
      </div>

      {/* Grid — grouped headers when sorted by category */}
      <CardsGrid
        links={shown}
        grouped={sortMode === "category"}
        uncategorizedLabel={t("apps.uncategorized")}
        openLabel={t("apps.openAriaLabel")}
        isLightTheme={isLightTheme}
        editMode={editMode}
        onEditCustom={openEditForLink}
      />

      <CustomLinkEditor
        open={editorOpen}
        onOpenChange={setEditorOpen}
        editing={editingLink}
        guests={guestOptions}
        categoryPresets={categoryPresets || []}
        onSaved={() => mutateCustomLinks()}
      />
    </div>
  )
}

// ─── Cards grid + card ───────────────────────────────────────────

function CardsGrid({
  links,
  grouped,
  uncategorizedLabel,
  openLabel,
  isLightTheme,
  editMode,
  onEditCustom,
}: {
  links: LaunchLink[]
  grouped: boolean
  uncategorizedLabel: string
  openLabel: string
  isLightTheme: boolean
  editMode: boolean
  onEditCustom: (customId: string) => void
}) {
  if (!links.length) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
        <div className="col-span-full text-center text-muted-foreground text-sm py-8">
          {/* No results after filter/search */}
        </div>
      </div>
    )
  }

  if (!grouped) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
        {links.map((link) => (
          <AppCard key={link.key} link={link} openLabel={openLabel} isLightTheme={isLightTheme} editMode={editMode} onEditCustom={onEditCustom} />
        ))}
      </div>
    )
  }

  // Group by category, insert header rows spanning the full grid width.
  const groups: Array<[string, LaunchLink[]]> = []
  let currentCat: string | null = null
  let bucket: LaunchLink[] = []
  for (const link of links) {
    const cat = link.category || uncategorizedLabel
    if (cat !== currentCat) {
      if (bucket.length) groups.push([currentCat!, bucket])
      currentCat = cat
      bucket = []
    }
    bucket.push(link)
  }
  if (bucket.length) groups.push([currentCat!, bucket])

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
      {groups.map(([cat, items]) => (
        <div key={`grp-${cat}`} className="contents">
          <h3 className="col-span-full uppercase text-xs tracking-wider text-muted-foreground font-semibold pt-3 pb-1.5 border-b border-border/60 flex items-center gap-2">
            <span>{cat}</span>
            <span className="font-mono tabular-nums text-[10px] px-1.5 py-0.5 rounded bg-card border border-border/60 font-normal">{items.length}</span>
          </h3>
          {items.map((link) => (
            <AppCard key={link.key} link={link} openLabel={openLabel} isLightTheme={isLightTheme} editMode={editMode} onEditCustom={onEditCustom} />
          ))}
        </div>
      ))}
    </div>
  )
}

// hueForCategory / categoryChipStyle / readIsLightTheme moved to
// lib/category-color.ts so the LXC App tab can render the same chip.

// Dispatch the pair of events that jumps from the Apps dashboard to
// the VMs modal on the App tab for a given CT. Two events by design:
// `changeTab` switches the outer tab (dashboard-level) and
// `openLxcAppModal` tells VirtualMachines which guest to open and on
// which inner tab to land. Both fire in the same tick.
function openLxcModalOnAppTab(vmid: number) {
  window.dispatchEvent(new CustomEvent("changeTab", { detail: { tab: "vms" } }))
  window.dispatchEvent(new CustomEvent("openLxcAppModal", { detail: { vmid } }))
}

// Same pattern for a QEMU guest: land on the modal's Status tab
// (QEMU guests don't have the App tab). Used by custom links whose
// binding is a VM instead of an LXC.
function openVmModalOnStatusTab(vmid: number) {
  window.dispatchEvent(new CustomEvent("changeTab", { detail: { tab: "vms" } }))
  window.dispatchEvent(new CustomEvent("openVmStatusModal", { detail: { vmid } }))
}

function AppCard({
  link,
  openLabel,
  isLightTheme,
  editMode,
  onEditCustom,
}: {
  link: LaunchLink
  openLabel: string
  isLightTheme: boolean
  editMode: boolean
  onEditCustom: (customId: string) => void
}) {
  const t = useT()
  // Navigate to the bound guest's modal on the appropriate inner tab:
  // LXC → App tab (where the weblink was registered), VM → Status tab
  // (VMs don't have an App tab). Unbound custom links have no CT ref
  // to click, so this handler is only wired when `link.vmid` exists.
  const goToBoundGuest = (e: React.MouseEvent | React.KeyboardEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (link.vmid == null) return
    if (link.guestType === "qemu") {
      openVmModalOnStatusTab(link.vmid)
    } else {
      openLxcModalOnAppTab(link.vmid)
    }
  }

  const goToEditor = (e: React.MouseEvent | React.KeyboardEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (link.customId) onEditCustom(link.customId)
  }

  const guestPrefix = link.guestType === "qemu" ? "VM" : "CT"
  const hasBinding = link.vmid != null

  return (
    <a
      href={link.weblink}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={openLabel.replace("{name}", link.appName)}
      className="group relative flex flex-col gap-2 p-3.5 bg-card border border-border rounded-xl no-underline text-foreground hover:bg-white/5 hover:border-border/80 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring active:translate-y-px"
    >
      {/* Head: logo + name (+ update icon) */}
      <div className="flex items-center gap-3">
        <div className="w-14 h-14 rounded-md bg-muted/40 grid place-items-center flex-shrink-0 overflow-hidden">
          {link.logoUrl ? (
            <ThemeAwareLogo src={link.logoUrl} className="w-9 h-9 object-contain" />
          ) : (
            <span className="text-[10px] font-mono text-muted-foreground uppercase">{link.appName.slice(0, 2)}</span>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-base font-semibold text-foreground truncate leading-tight">{link.appName}</div>
        </div>
        {/* Edit mode on a custom card takes over the update-icon slot
            with a proper edit button — custom links never carry the
            update signal, so nothing is displaced. Falls back to the
            update icon in every other case. */}
        {editMode && link.isCustom ? (
          <button
            type="button"
            onClick={goToEditor}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") goToEditor(e) }}
            className="h-8 w-8 rounded-md border border-border bg-background hover:bg-muted flex items-center justify-center flex-shrink-0 self-start text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={t("apps.customLinkEditAria", { name: link.appName })}
            title={t("actions.edit")}
          >
            <Pencil className="h-4 w-4" />
          </button>
        ) : link.updateAvailable && (
          <ArrowUpCircle className="h-5 w-5 text-purple-400 flex-shrink-0 self-start mt-0.5" aria-hidden="true" />
        )}
      </div>

      {/* Foot: weblink + CT ref + category chip */}
      <div className="flex flex-col gap-1.5 mt-auto pt-2 border-t border-dashed border-border/60">
        <div className="flex items-center gap-1.5 text-blue-400 text-sm font-mono truncate">
          <ExternalLink className="h-3.5 w-3.5 flex-shrink-0 opacity-80" />
          <span className="truncate">{link.weblink}</span>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          {/* Guest ref → click opens that guest's modal (LXC → App
              tab, VM → Status tab). stopPropagation keeps the outer
              anchor from firing at the same time. Unbound custom
              links: in edit mode show the edit button here, otherwise
              show nothing. */}
          {hasBinding && (
            <button
              type="button"
              onClick={goToBoundGuest}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") goToBoundGuest(e) }}
              className="inline-flex items-center gap-1.5 min-w-0 rounded hover:text-blue-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
              aria-label={t("apps.openGuestAriaLabel", {
                name: link.ctName || String(link.vmid),
                type: guestPrefix,
                id: link.vmid!,
              })}
            >
              <span className="font-mono px-1.5 py-0.5 rounded bg-muted/40 text-muted-foreground/90 flex-shrink-0">{link.vmid}</span>
              <span className="truncate min-w-0">{link.ctName || `${guestPrefix} ${link.vmid}`}</span>
            </button>
          )}
          {link.category && (
            <span
              style={categoryChipStyle(link.category, isLightTheme)}
              className="ml-auto px-1.5 py-0.5 border rounded text-[10px] font-medium flex-shrink-0 truncate max-w-[45%]"
              title={link.category}
            >
              {link.category}
            </span>
          )}
        </div>
      </div>
    </a>
  )
}
