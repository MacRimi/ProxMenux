"use client"

/**
 * LxcAppPanel — Body of the "App" tab in the LXC modal.
 *
 * Handles a LIST of apps per CT (one CT can host several services
 * — e.g. Frigate on port 5000 + go2rtc on 1984, or Docker + two
 * containerised apps).  Each app has:
 *   • an install method (dpkg / apk / file / binary / docker)
 *   • an optional GitHub repo for upstream version tracking
 *   • a list of ports, each with a description and web path
 *
 * Docker image updates live exclusively in the Updates tab.  The App
 * tab only registers the Docker engine/app identity and shows installed
 * metadata, so an unregistered detection can never create update noise.
 *
 * For ProxMenux-managed OCI CTs (Secure Gateway) the panel is
 * read-only — the actual update lifecycle lives in Security →
 * Secure Gateway.
 */

import { useCallback, useEffect, useMemo, useState } from "react"
import {
  Loader2, Save, RefreshCw, Trash2, Package, ExternalLink,
  AlertTriangle, Info, PlusCircle, Pencil, ChevronDown, ChevronRight, EyeOff,
  ArrowUpCircle, RotateCcw, Check, Settings2, ShieldCheck,
  Bell, BellOff, Search,
} from "lucide-react"
import { Card, CardContent } from "./ui/card"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Badge } from "./ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { fetchApi } from "../lib/api-config"
import { fetchLxcApps, getLxcAppsCached, setLxcAppsCached } from "../lib/lxc-apps-cache"
import { useT } from "@/lib/i18n/provider"

// installed_via is optional now — an empty value means "register only,
// no version tracking, no warnings, just a clickable link". Docker
// apps and casual "just want a link" registrations use this default.
type InstalledVia = "" | "dpkg" | "apk" | "file" | "binary" |
                    "python_dist" | "docker_label" | "docker_exec" |
                    "command" | "manual"
type GithubSource = "releases" | "tags"

interface PortEntry {
  port: number | ""
  description?: string
  scheme?: "http" | "https"
  web_path?: string
  logo_url?: string
}

interface AppConfig {
  name: string
  installed_via?: InstalledVia
  package?: string
  file_path?: string
  file_regex?: string
  binary_path?: string
  binary_args?: string[]
  python_path?: string
  distribution?: string
  container_name?: string
  label?: string
  command_argv?: string[]
  installed_version?: string
  installed_regex?: string
  // Upstream source discriminator + fields. When `upstream_type` is
  // "github" (default when `repo` is set) the classic repo /
  // github_source / tag_regex fields drive the check. "http_json" and
  // "docker_hub" open two new source types validated separately on
  // the backend.
  upstream_type?: "github" | "http_json" | "docker_hub" | ""
  repo?: string
  github_source?: GithubSource
  upstream_url?: string
  upstream_json_path?: string
  docker_image?: string
  tag_regex?: string
  ports: PortEntry[]
  health_path?: string
  logo_url?: string
  helper_slug?: string
  // Preserved here even though this editor does not execute updates.
  // The backend uses full-record replacement, so omitting these when
  // editing ports/tracking would silently erase the Updates-tab setup.
  update_command?: string
  hide_no_updater_notice?: boolean
  // Per-app opt-out for the `app_update_available` notification.
  // Absent / true = notify; false = silenced. Set from the bell
  // toggle on each app card and/or the Edit form's checkbox.
  notifications_enabled?: boolean
  // Per-app opt-out for the CT's aggregate updates badge (default
  // false = counted). Independent from `notifications_enabled`.
  exclude_from_badge?: boolean
}

interface DetectedApp {
  slug: string
  name: string
  logo_url?: string | null
  default_ports?: number[]
  tracking_suggestion?: TrackingSuggestion | null
}

interface AppState {
  installed_version: string | null
  latest_version: string | null
  latest_published_at?: string | null
  update_available: boolean | null
  error: string | null
  checked_at: string | null
}

interface AppEntry extends AppConfig {
  id: string
  state?: AppState
  created_at?: string
}

interface SidecarResponse {
  vmid: number
  apps: AppEntry[]
  dismissed_slugs?: string[]
  created_at?: string
  updated_at?: string
}

interface DetectorTestResult {
  valid: boolean
  persisted: false
  checked_at: string
  installed: {
    configured: boolean
    method: InstalledVia | null
    effective_regex: string | null
    version: string | null
    error: string | null
  }
  upstream: {
    configured: boolean
    type: "github" | "http_json" | "docker_hub" | null
    version: string | null
    published_at?: string | null
    error: string | null
  }
  update_available: boolean | null
}

interface TrackingSuggestion {
  installed_via: Exclude<InstalledVia, "">
  package?: string
  file_path?: string
  file_regex?: string
  binary_path?: string
  binary_args?: string[]
  python_path?: string
  distribution?: string
  container_name?: string
  label?: string
  command_argv?: string[]
  installed_version?: string
  installed_regex?: string
  upstream_type?: "github" | "http_json" | "docker_hub" | ""
  upstream_url?: string
  upstream_json_path?: string
  docker_image?: string
  repo?: string
  github_source?: "releases" | "tags"
  tag_regex?: string
  detected_version?: string
  detector_verified?: boolean
  detector_source?: "primary" | "alternative" | "helper_marker" | "legacy_fallback" | "runtime_probe" | "candidate"
  detector_error?: string
}

interface DockerTagPreview {
  image: string
  regex: string
  tags: Array<{ tag: string; version: string | null; moving: boolean }>
  matched_count: number
  scanned_count: number
  cached_for_seconds: number
}

interface DockerWebLinkSuggestion {
  container_name: string
  service_name: string
  service_slug?: string | null
  image: string
  host_port: number
  container_port: number
  scheme: "http" | "https"
  web_path: string
  logo_url?: string | null
}

interface Suggestions {
  ready?: boolean
  name_suggestion: string | null
  helper_slug: string | null
  port_suggestions: number[]
  web_path_hint: string | null
  tracking_suggestion?: TrackingSuggestion | null
  default_ports?: number[]
  logo_url?: string | null
  extras?: DetectedApp[]
  docker_web_links?: DockerWebLinkSuggestion[]
}

// Compact catalog entry — one row for every registerable app the
// picker can offer. Fetched once from /api/apps/catalog on panel
// mount, filtered client-side while the user types.
interface CatalogEntry {
  slug: string
  name: string
  logo: string
  default_port: number
  has_tracking: boolean
}

// Full detail for a picked catalog entry — server merges catalog
// metadata + curated tracking_suggestion (when available) so the
// editor can pre-fill every field in one round-trip.
interface CatalogDetail {
  slug: string
  name: string
  logo_url: string | null
  website: string
  default_ports: number[]
  tracking_suggestion?: TrackingSuggestion | null
}

interface ManagedAppInfo {
  managed_oci_app_id: string
  name: string
  installed_version?: string | null
  latest_version?: string | null
  update_available?: boolean | null
  checked_at?: string | null
  error?: string | null
}

interface Props {
  vmid: number
  ctIp?: string | null
  onChange?: () => void
  managed?: ManagedAppInfo | null
  // Optional seed payload from the parent's cross-open ref cache. When
  // supplied, the panel renders with real content on the very first
  // frame and only revalidates silently in the background — no
  // "Loading applications…" flash on tab switch or modal reopen. Must
  // include BOTH sidecar and suggestions — the panel's empty-state and
  // detected-chip strip both depend on suggestions, so seeding sidecar
  // alone briefly flashes "no apps registered" until suggestions
  // arrives from the network.
  initialData?: { sidecar: SidecarResponse; suggestions: Suggestions | null } | null
}

const EMPTY_APP: AppConfig = {
  name: "",
  installed_via: "",       // no tracking by default — just a link
  package: "",
  upstream_type: "",
  repo: "",
  github_source: "releases",
  upstream_url: "",
  upstream_json_path: "",
  docker_image: "",
  tag_regex: "v?(\\d+\\.\\d+\\.\\d+)",
  ports: [],
  logo_url: "",
}

const SELFHST_WEBP_BASE = "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp"
const SELFHST_THEME_LOGOS: Record<string, { lightTheme: string; darkTheme: string }> = {
  frigate: {
    lightTheme: `${SELFHST_WEBP_BASE}/frigate-dark.webp`,
    darkTheme: `${SELFHST_WEBP_BASE}/frigate-light.webp`,
  },
  portainer: {
    lightTheme: `${SELFHST_WEBP_BASE}/portainer-dark.webp`,
    darkTheme: `${SELFHST_WEBP_BASE}/portainer-light.webp`,
  },
  vaultwarden: {
    lightTheme: `${SELFHST_WEBP_BASE}/vaultwarden.webp`,
    darkTheme: `${SELFHST_WEBP_BASE}/vaultwarden-light.webp`,
  },
}

function selfhstThemeLogos(src: string) {
  if (!src.toLowerCase().includes("cdn.jsdelivr.net/gh/selfhst/icons")) return null
  const match = src.toLowerCase().match(/\/(frigate|portainer|vaultwarden)(?:-(?:dark|light))?\.webp(?:[?#].*)?$/)
  return match ? SELFHST_THEME_LOGOS[match[1]] : null
}

export function ThemeAwareLogo({ src, className }: { src: string; className: string }) {
  const themed = selfhstThemeLogos(src)
  const hideBroken = (e: React.SyntheticEvent<HTMLImageElement>) => {
    e.currentTarget.style.display = "none"
  }
  if (!themed) {
    return <img src={src} alt="" className={className} onError={hideBroken} />
  }
  return (
    <>
      <img src={themed.lightTheme} alt="" className={`${className} block dark:hidden`} onError={hideBroken} />
      <img src={themed.darkTheme} alt="" className={`${className} hidden dark:block`} onError={hideBroken} />
    </>
  )
}

// Default scheme heuristic for freshly-added ports — only used to
// pre-select the dropdown. The user always has the final say via
// the http/https selector next to the port input.
const HTTPS_HINT_PORTS = new Set([443, 4443, 8443, 9443])
const defaultSchemeFor = (port: number | ""): "http" | "https" =>
  HTTPS_HINT_PORTS.has(Number(port)) ? "https" : "http"

function buildWebUrl(ip: string | undefined | null, port: number | "", scheme?: "http" | "https") {
  if (!ip || ip === "DHCP" || !port) return null
  return `${scheme || defaultSchemeFor(port)}://${ip}:${port}`
}

// Suggest a dpkg/apk package name from a friendly app name — lowercase,
// spaces and slashes to hyphens, drop punctuation. Only used as a
// placeholder / auto-fill; user can always override.
function suggestPackageName(name: string) {
  return name
    .trim()
    .toLowerCase()
    .replace(/[\s/]+/g, "-")
    .replace(/[^a-z0-9._+@:-]/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "")
}

export function LxcAppPanel({ vmid, ctIp, onChange, managed, initialData }: Props) {
  const t = useT()
  // Seed from `initialData` first, then fall back to the shared cache
  // module. Together those two sources cover every reopen scenario
  // without flashing a spinner — see lxc-apps-cache.ts for the dedup
  // logic that also keeps concurrent fetches from racing.
  const seed = initialData ?? getLxcAppsCached(vmid) ?? null
  const [loading, setLoading] = useState(!seed)
  const [sidecar, setSidecar] = useState<SidecarResponse | null>(seed?.sidecar ?? null)
  const [suggestions, setSuggestions] = useState<Suggestions | null>(seed?.suggestions ?? null)
  const [error, setError] = useState<string | null>(null)
  const [searchingApplications, setSearchingApplications] = useState(false)
  const [detectionNotice, setDetectionNotice] = useState<{ found: boolean; text: string } | null>(null)
  // Editor state
  const [editing, setEditing] = useState<{ appId: string | null; draft: AppConfig } | null>(null)
  const [saving, setSaving] = useState(false)
  const [testingDetector, setTestingDetector] = useState(false)
  const [detectorTest, setDetectorTest] = useState<DetectorTestResult | null>(null)
  const [busyAppId, setBusyAppId] = useState<string | null>(null)
  // Advanced section (version tracking) is collapsed by default so the
  // basic Name + Ports flow stays approachable. Auto-expanded when
  // editing an app that already has installed_via set, or when the
  // user clicked Register on an auto-detected chip whose hint carries
  // tracking metadata — the user sees the fields we auto-filled and
  // can tweak or opt out before saving.
  const [showAdvanced, setShowAdvanced] = useState(false)

  // Catalog picker: 700+ apps fetched once from /api/apps/catalog and
  // filtered client-side while the user types in the Name input. The
  // dropdown shows top 20 matches. Selecting one calls the detail
  // endpoter to seed name / logo / ports / tracking_suggestion at once.
  const [catalog, setCatalog] = useState<CatalogEntry[]>([])
  const [pickerOpen, setPickerOpen] = useState(false)

  // "Register a different app" browse panel: when the user has hidden
  // some detections we surface them here with a Restore button before
  // falling through to the blank-form path. If there's nothing to
  // restore, this panel is skipped entirely and the button opens the
  // editor directly (fast path for the common case).
  const [browseOpen, setBrowseOpen] = useState(false)
  const [dockerTagPreview, setDockerTagPreview] = useState<DockerTagPreview | null>(null)
  const [dockerTagPreviewLoading, setDockerTagPreviewLoading] = useState(false)
  const [dockerTagPreviewError, setDockerTagPreviewError] = useState<string | null>(null)

  // Global "manage apps" mode. When ON, every app card grows a footer
  // with Remove / Check / Edit fields actions. When OFF the cards are
  // pure info; detector checks remain available after enabling Edit.
  // Toggled from a single button next to
  // "Add another application".
  const [editMode, setEditMode] = useState(false)

  const load = useCallback(async () => {
    if (managed) { setLoading(false); return }
    // Only show the spinner on cold loads. When we came in seeded via
    // `initialData` or the shared cache, the sidecar is already
    // populated and the user shouldn't see a flash of "Loading…"
    // while we revalidate.
    if (!sidecar) setLoading(true)
    setError(null)
    try {
      // `fetchLxcApps` bundles sidecar + suggestions in one shared
      // in-flight promise. If the parent already fired this fetch on
      // modal open (see prefetchVM / handleVMClick in
      // virtual-machines.tsx), we await the SAME promise instead of
      // duplicating the request against the backend — this eliminates
      // the "Loading applications…" flash that used to show while a
      // second, racing fetch caught up.
      const bundle = await fetchLxcApps(vmid)
      if (bundle) {
        setSidecar(bundle.sidecar)
        setSuggestions(bundle.suggestions)
      }
    } catch (e: any) {
      setError(e?.message || t("vmLxc.appEditor.loadFailed"))
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vmid, managed])

  useEffect(() => { load() }, [load])

  // Live Docker Hub preview. Debounced so typing an image/regex does not
  // issue one request per keystroke; the backend additionally caches the
  // raw tag list for 60 seconds per image.
  useEffect(() => {
    const draft = editing?.draft
    const image = (draft?.docker_image || "").trim()
    if (draft?.upstream_type !== "docker_hub" || !image) {
      setDockerTagPreview(null)
      setDockerTagPreviewError(null)
      setDockerTagPreviewLoading(false)
      return
    }
    let cancelled = false
    setDockerTagPreview(null)
    setDockerTagPreviewError(null)
    const timer = window.setTimeout(async () => {
      setDockerTagPreviewLoading(true)
      try {
        const result: DockerTagPreview = await fetchApi("/api/lxc-apps/dockerhub-tag-preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ image, regex: draft.tag_regex || "" }),
        })
        if (!cancelled) setDockerTagPreview(result)
      } catch (e: any) {
        if (!cancelled) setDockerTagPreviewError(e?.message || t("vmLxc.appEditor.dockerTagPreviewFailed"))
      } finally {
        if (!cancelled) setDockerTagPreviewLoading(false)
      }
    }, 500)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [editing?.draft.docker_image, editing?.draft.tag_regex, editing?.draft.upstream_type, t])

  // Turn a raw backend error string ("network error: The read operation
  // timed out", etc.) into a localized message. Upstream check errors
  // are surfaced verbatim by `lxc_apps.py:_fetch_upstream()`, and the
  // panel used to render them in English regardless of locale. Match
  // the two shapes the backend produces today and fall back to the
  // original string so unknown errors still show something useful.
  const localizeUpstreamError = (msg: string | null | undefined): string => {
    if (!msg) return ""
    const trimmed = msg.trim()
    const lower = trimmed.toLowerCase()
    if (lower.startsWith("network error:")) {
      const detail = trimmed.slice("network error:".length).trim()
      if (detail.toLowerCase().includes("timed out") || detail.toLowerCase().includes("timeout")) {
        return t("vmLxc.appEditor.upstreamErrorTimeout")
      }
      return t("vmLxc.appEditor.upstreamErrorNetwork", { detail })
    }
    return msg
  }

  const editorOpen = !!editing

  // The picker catalog is only needed after the user opens the editor.
  useEffect(() => {
    if (!editorOpen || catalog.length > 0) return
    let cancelled = false
    fetchApi<CatalogEntry[]>("/api/apps/catalog")
      .then((data: CatalogEntry[]) => {
        if (!cancelled && Array.isArray(data)) setCatalog(data)
      })
      .catch(() => { /* non-fatal */ })
    return () => { cancelled = true }
  }, [editorOpen, catalog.length])

  // Derived state — computed here BEFORE any conditional early
  // return so React sees the same hook order on every render.
  // Rules of Hooks: `useMemo` after an `if (loading) return …`
  // trips React error #310 the moment `loading` flips false.
  const apps = sidecar?.apps || []

  // Unified detection list — primary community-scripts install +
  // every other app whose install signature was found on the CT
  // (`extras[]` from the backend). Both use the same DetectedApp
  // shape so the empty state renders them uniformly.
  const detectedList: DetectedApp[] = useMemo(() => {
    if (!suggestions) return []
    const out: DetectedApp[] = []
    if (suggestions.helper_slug && suggestions.name_suggestion) {
      out.push({
        slug: suggestions.helper_slug,
        name: suggestions.name_suggestion,
        logo_url: suggestions.logo_url,
        default_ports: suggestions.default_ports,
        tracking_suggestion: suggestions.tracking_suggestion,
      })
    }
    const seen = new Set(out.map((d) => d.slug))
    for (const e of suggestions.extras || []) {
      if (!seen.has(e.slug)) {
        out.push(e)
        seen.add(e.slug)
      }
    }
    return out
  }, [suggestions])

  // Registered slugs — used to filter the detection list down to
  // what the user hasn't already registered on this CT.
  const registeredSlugs = useMemo(
    () => new Set(apps.map((a) => a.helper_slug).filter(Boolean) as string[]),
    [apps],
  )
  // Dismissed slugs — persisted in the sidecar. Chips the user
  // explicitly hid via the ✕ button stay hidden across reloads until
  // they register the app (which also un-dismisses implicitly).
  const dismissedSlugs = useMemo(
    () => new Set(sidecar?.dismissed_slugs || []),
    [sidecar],
  )
  const visibleDetected = detectedList.filter(
    (d) => !registeredSlugs.has(d.slug) && !dismissedSlugs.has(d.slug),
  )
  // Alias for pre-existing consumers (post-registration chip strip).
  const unregisteredDetected = visibleDetected
  // Detections the user hid and could restore from the Register-a-
  // different-app panel. Not affected by registration state.
  const hiddenDetections = detectedList.filter((d) => dismissedSlugs.has(d.slug))

  const searchInstalledApplications = async () => {
    const before = new Set(visibleDetected.map((item) => item.slug))
    setSearchingApplications(true)
    setDetectionNotice(null)
    setError(null)
    try {
      const result: Suggestions = await fetchApi(`/api/vms/${vmid}/apps/suggestions`, {
        method: "POST",
      })
      setSuggestions(result)
      if (sidecar) setLxcAppsCached(vmid, sidecar, result)

      const detected = new Set<string>()
      if (result.helper_slug) detected.add(result.helper_slug)
      for (const item of result.extras || []) detected.add(item.slug)
      const visible = [...detected].filter(
        (slug) => !registeredSlugs.has(slug) && !dismissedSlugs.has(slug),
      )
      const newCount = visible.filter((slug) => !before.has(slug)).length
      if (newCount === 1) {
        setDetectionNotice({ found: true, text: t("vmLxc.appEditor.oneNewApplicationDetected") })
      } else if (newCount > 1) {
        setDetectionNotice({
          found: true,
          text: t("vmLxc.appEditor.newApplicationsDetected", { count: newCount }),
        })
      } else {
        setDetectionNotice({
          found: false,
          text: t(visible.length === 0 && apps.length === 0
            ? "vmLxc.appEditor.noApplicationsDetected"
            : "vmLxc.appEditor.noNewApplicationsDetected"),
        })
      }
    } catch (e: any) {
      setError(e?.message || t("vmLxc.appEditor.detectionFailed"))
    } finally {
      setSearchingApplications(false)
    }
  }

  // "Register a different app" behavior: if there are hidden slugs,
  // surface them first (with Restore) so the user can bring one back
  // instead of typing everything by hand. If nothing to restore, go
  // straight to the blank editor.
  const openBrowseOrEditor = () => {
    if (hiddenDetections.length > 0) setBrowseOpen(true)
    else openEditor()
  }

  const openEditor = useCallback(async (
    existing?: AppEntry,
    opts?: { withTracking?: boolean, preset?: DetectedApp },
  ) => {
    let seed: AppConfig
    if (existing) {
      seed = {
        name: existing.name,
        installed_via: (existing.installed_via as InstalledVia) || "",
        package: existing.package || "",
        file_path: existing.file_path || "",
        file_regex: existing.file_regex || "",
        binary_path: existing.binary_path || "",
        binary_args: existing.binary_args ? [...existing.binary_args] : [],
        python_path: existing.python_path || "",
        distribution: existing.distribution || "",
        container_name: existing.container_name || "",
        label: existing.label || "",
        command_argv: existing.command_argv ? [...existing.command_argv] : [],
        installed_version: existing.installed_version || "",
        installed_regex: existing.installed_regex || "",
        upstream_type: existing.upstream_type || (existing.repo ? "github" : ""),
        repo: existing.repo || "",
        github_source: existing.github_source || "releases",
        upstream_url: existing.upstream_url || "",
        upstream_json_path: existing.upstream_json_path || "",
        docker_image: existing.docker_image || "",
        tag_regex: existing.tag_regex || "v?(\\d+\\.\\d+\\.\\d+)",
        ports: existing.ports?.length ? existing.ports.map((p) => ({ ...p })) : [],
        health_path: existing.health_path || "",
        logo_url: existing.logo_url || "",
        helper_slug: existing.helper_slug || "",
        update_command: existing.update_command || "",
        hide_no_updater_notice: existing.hide_no_updater_notice === true,
        notifications_enabled: existing.notifications_enabled !== false,
        exclude_from_badge: existing.exclude_from_badge === true,
      }
      // Editing an existing app: expand Advanced when tracking is on
      setShowAdvanced(!!seed.installed_via)
    } else {
      seed = { ...EMPTY_APP, ports: [] }
      let s = suggestions
      if (!s) {
        try {
          s = await fetchApi(`/api/vms/${vmid}/apps/suggestions`)
          setSuggestions(s)
        } catch { /* non-fatal */ }
      }
      // Preset path: a chip in the empty state (primary OR extra) was
      // clicked. Seed EVERYTHING from the preset so this works
      // regardless of whether it's the first or Nth app on the CT.
      // Primary detection is `{...suggestions}`-shaped, an extra is
      // `DetectedApp`-shaped — both carry name/logo/ports/tracking.
      if (opts?.preset) {
        const p = opts.preset
        seed.name = p.name
        seed.logo_url = p.logo_url || ""
        seed.helper_slug = p.slug
        // Docker endpoints come from the real published host-port mappings
        // listed under Web links.  Do not pre-save a catalog default such as
        // 9000; the user explicitly chooses which workload links to add.
        if (p.slug !== "docker" && p.default_ports?.length) {
          seed.ports = p.default_ports.map((port) => ({
            port,
            scheme: defaultSchemeFor(port),
            web_path: s?.web_path_hint || "",
          }))
        }
        if (opts.withTracking && p.tracking_suggestion) {
          const t = p.tracking_suggestion
          seed = {
            ...seed,
            installed_via: t.installed_via,
            package: t.package || "",
            file_path: t.file_path || "",
            file_regex: t.file_regex || "",
            binary_path: t.binary_path || "",
            binary_args: t.binary_args ? [...t.binary_args] : [],
            python_path: t.python_path || "",
            distribution: t.distribution || "",
            container_name: t.container_name || "",
            label: t.label || "",
            command_argv: t.command_argv ? [...t.command_argv] : [],
            installed_version: t.installed_version || "",
            installed_regex: t.installed_regex || "",
            upstream_type: (t as any).upstream_type || (t.repo ? "github" : ""),
            repo: t.repo || "",
            github_source: t.github_source || "releases",
            upstream_url: (t as any).upstream_url || "",
            upstream_json_path: (t as any).upstream_json_path || "",
            docker_image: (t as any).docker_image || "",
            tag_regex: t.tag_regex || "v?(\\d+\\.\\d+\\.\\d+)",
          }
          setShowAdvanced(true)
        } else {
          setShowAdvanced(false)
        }
      } else {
        // No preset (bare "+ Register application"): start empty so
        // the user types name/ports/logo for a custom app the auto-
        // detector doesn't know about.
        setShowAdvanced(false)
      }
    }
    setEditing({ appId: existing?.id || null, draft: seed })
    setDetectorTest(null)
    setError(null)
  }, [suggestions, vmid, sidecar])

  const closeEditor = () => {
    setEditing(null)
    setDetectorTest(null)
    setError(null)
  }

  const save = async () => {
    if (!editing) return
    setSaving(true)
    setError(null)
    try {
      const url = editing.appId
        ? `/api/vms/${vmid}/apps/${editing.appId}`
        : `/api/vms/${vmid}/apps`
      const method = editing.appId ? "PUT" : "POST"
      const r: SidecarResponse & { error?: string } = await fetchApi(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editing.draft),
      })
      if ((r as any).error) throw new Error((r as any).error)
      setSidecar(r)
      setLxcAppsCached(vmid, r, suggestions)
      setEditing(null)
      onChange?.()
    } catch (e: any) {
      setError(e?.message || t("vmLxc.appEditor.saveFailed"))
    } finally {
      setSaving(false)
    }
  }

  const testDetector = async () => {
    if (!editing?.draft.installed_via) return
    setTestingDetector(true)
    setDetectorTest(null)
    setError(null)
    try {
      const result: DetectorTestResult = await fetchApi(`/api/vms/${vmid}/apps/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editing.draft),
      })
      setDetectorTest(result)
    } catch (e: any) {
      setError(e?.message || t("vmLxc.appEditor.detectorTestFailed"))
    } finally {
      setTestingDetector(false)
    }
  }

  const checkOne = async (appId: string) => {
    setBusyAppId(appId)
    setError(null)
    try {
      const r: SidecarResponse = await fetchApi(`/api/vms/${vmid}/apps/${appId}/check`, {
        method: "POST",
      })
      setSidecar(r)
      setLxcAppsCached(vmid, r, suggestions)
      onChange?.()
    } catch (e: any) {
      setError(e?.message || t("vmLxc.appEditor.checkFailed"))
    } finally {
      setBusyAppId(null)
    }
  }

  // Silence / re-enable `app_update_available` for this specific
  // app. Full-record PUT because the backend replaces the whole
  // config on update — omit a field and it disappears. We hydrate
  // from the current app entry, flip the flag, and post it back.
  const toggleAppNotifications = async (app: AppEntry) => {
    setBusyAppId(app.id)
    setError(null)
    try {
      const { id: _id, state: _state, created_at: _created, ...rest } = app
      const nextEnabled = app.notifications_enabled === false
      const payload = { ...rest, notifications_enabled: nextEnabled }
      const r: SidecarResponse = await fetchApi(`/api/vms/${vmid}/apps/${app.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      setSidecar(r)
      setLxcAppsCached(vmid, r, suggestions)
      onChange?.()
    } catch (e: any) {
      setError(e?.message || t("vmLxc.appEditor.saveFailed"))
    } finally {
      setBusyAppId(null)
    }
  }

  const removeOne = async (appId: string) => {
    if (!confirm("Remove this application from the CT's App tab?")) return
    setBusyAppId(appId)
    setError(null)
    try {
      const r: SidecarResponse = await fetchApi(`/api/vms/${vmid}/apps/${appId}`, { method: "DELETE" })
      setSidecar(r)
      setLxcAppsCached(vmid, r, suggestions)
      onChange?.()
    } catch (e: any) {
      setError(e?.message || t("vmLxc.appEditor.deleteFailed"))
    } finally {
      setBusyAppId(null)
    }
  }

  // Hide an auto-detected chip. Optimistic UI: update the local
  // sidecar state immediately so the chip disappears without
  // waiting for the round-trip, then persist to the server. If the
  // POST fails, reload from server to resync.
  const dismissDetection = async (slug: string, name: string) => {
    if (!confirm(t("vmLxc.appEditor.confirmHide", { name }))) return
    setSidecar((prev) => prev
      ? { ...prev, dismissed_slugs: [...(prev.dismissed_slugs || []), slug] }
      : prev,
    )
    try {
      const r: SidecarResponse = await fetchApi(`/api/vms/${vmid}/apps/dismiss`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug, dismissed: true }),
      })
      setSidecar(r)
      setLxcAppsCached(vmid, r, suggestions)
    } catch (e: any) {
      setError(e?.message || t("vmLxc.appEditor.dismissFailed"))
      await load()  // resync on failure
    }
  }

  // Un-hide a previously dismissed slug. Used from the "Register a
  // different app" panel. Optimistically drops the slug from local
  // dismissed_slugs so the chip re-appears in the main list, then
  // persists.
  const restoreDetection = async (slug: string) => {
    setSidecar((prev) => prev
      ? { ...prev, dismissed_slugs: (prev.dismissed_slugs || []).filter((s) => s !== slug) }
      : prev,
    )
    try {
      const r: SidecarResponse = await fetchApi(`/api/vms/${vmid}/apps/dismiss`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug, dismissed: false }),
      })
      setSidecar(r)
      setLxcAppsCached(vmid, r, suggestions)
    } catch (e: any) {
      setError(e?.message || t("vmLxc.appEditor.restoreFailed"))
      await load()
    }
  }

  // ── Managed CT (Secure Gateway etc.) ──────────────────────────
  // Mirrors the visual identity of a regular app card so managed OCI
  // apps sit next to user-registered apps without a jarring style
  // shift. Version data comes from managed_installs.update_check
  // (already tracked by oci_manager — same source as the Security →
  // Secure Gateway page). No footer: no Edit, no Check, no Remove —
  // the whole lifecycle lives in Security → Secure Gateway.
  if (managed) {
    // Currently the only OCI managed app is Secure Gateway (Tailscale
    // in an Alpine CT). When we add more OCI apps we'll swap this to
    // a lookup keyed on managed_oci_app_id → catalog metadata.
    const isSecureGateway = managed.managed_oci_app_id === "secure-gateway"
    const displayName = isSecureGateway ? "Secure Gateway" : (managed.name || t("vmLxc.appEditor.managedApp"))
    const displaySubtitle = isSecureGateway ? "Tailscale VPN Gateway" : ""
    // Two variants — the selfh.st mark (dark logo on light bg) reads
    // better in light mode; the homarr-labs "-light" variant (light
    // logo on dark bg) reads better in dark mode. Both are rendered
    // and Tailwind's dark: class picks which one is visible.
    const upstreamLogoLightUrl = isSecureGateway
      ? "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/tailscale.webp"
      : ""
    const upstreamLogoDarkUrl = isSecureGateway
      ? "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/webp/tailscale-light.webp"
      : ""
    const upstreamName = isSecureGateway ? "Tailscale" : ""
    const repo = isSecureGateway ? "tailscale/tailscale" : ""
    const methodLine = isSecureGateway ? `apk · tailscale · ${t("vmLxc.appEditor.managedStatus")}` : t("vmLxc.appEditor.managedStatus")
    const hasUpdate = managed.update_available === true
    const showVersions = !!(managed.installed_version || managed.latest_version || repo)

    return (
      <div className="space-y-4">
        <Card className="border border-border bg-card/50">
          <CardContent className="p-4">
            {/* Block 1 — Secure Gateway identity (the ProxMenux
                product). Big shield, title, catalog subtitle. */}
            <div className="flex items-start gap-3">
              <div className="h-14 w-14 flex-shrink-0 rounded-md bg-cyan-500/10 flex items-center justify-center">
                <ShieldCheck className="h-11 w-11 text-cyan-500" />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-xl font-semibold text-foreground truncate">{displayName}</h3>
                {displaySubtitle && (
                  <div className="text-sm text-muted-foreground mt-0.5 truncate">{displaySubtitle}</div>
                )}
              </div>
            </div>

            {/* Block 2 — Underlying engine (Tailscale). Same visual
                pattern as a regular app card so it's clear this is
                what version tracking is anchored to. Repo link goes
                here (top-right on desktop / stacked on mobile) because
                the repo is the engine's, not Secure Gateway's. */}
            {upstreamName && (
              <div className="mt-4 pt-4 border-t border-border/50">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    {upstreamLogoLightUrl || upstreamLogoDarkUrl ? (
                      <>
                        {upstreamLogoLightUrl && (
                          <img
                            src={upstreamLogoLightUrl}
                            alt=""
                            className="h-10 w-10 flex-shrink-0 rounded-md object-contain block dark:hidden"
                            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }}
                          />
                        )}
                        {upstreamLogoDarkUrl && (
                          <img
                            src={upstreamLogoDarkUrl}
                            alt=""
                            className="h-10 w-10 flex-shrink-0 rounded-md object-contain hidden dark:block"
                            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }}
                          />
                        )}
                      </>
                    ) : (
                      <div className="h-10 w-10 flex-shrink-0 rounded-md bg-muted flex items-center justify-center">
                        <Package className="h-5 w-5 text-muted-foreground" />
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="text-base font-semibold text-foreground truncate">{upstreamName}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">{methodLine}</div>
                      {managed.checked_at && (
                        <div className="text-[10px] text-muted-foreground/80 mt-0.5">
                          {t("vmLxc.appEditor.checkedAt", { date: new Date(managed.checked_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) })}
                        </div>
                      )}
                      {repo && (
                        <a
                          href={`https://github.com/${repo}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="md:hidden mt-1 text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1 min-w-0"
                        >
                          <ExternalLink className="h-3 w-3 flex-shrink-0" />
                          <span className="truncate">{repo}</span>
                        </a>
                      )}
                    </div>
                  </div>
                  {repo && (
                    <a
                      href={`https://github.com/${repo}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hidden md:inline-flex text-xs text-muted-foreground hover:text-foreground items-center gap-1 flex-shrink-0 mt-1"
                    >
                      {repo}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
              </div>
            )}

            {showVersions && (managed.installed_version || repo) && (
              <div className={"mt-3 grid gap-3 " + (managed.installed_version && repo ? "grid-cols-2" : "grid-cols-1")}>
                {managed.installed_version && (
                  <div className="p-3 rounded-md bg-muted/40">
                    <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">{t("vmLxc.appEditor.installedStatus")}</div>
                    <div className="text-lg font-semibold font-mono text-foreground">
                      {managed.installed_version}
                    </div>
                  </div>
                )}
                {repo && (
                  <div className="p-3 rounded-md bg-muted/40">
                    <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">
                      {t("vmLxc.appEditor.latestUpstream")}
                    </div>
                    <div className={"text-lg font-semibold font-mono flex items-center gap-2 " + (hasUpdate ? "text-purple-400" : "text-foreground")}>
                      {managed.latest_version || <span className="text-muted-foreground text-base font-normal">{t("vmLxc.appEditor.checkingStatus")}</span>}
                      {hasUpdate && managed.latest_version && (
                        <ArrowUpCircle className="h-5 w-5 text-purple-400 flex-shrink-0" aria-label={t("vmLxc.appEditor.updateAvailableBadge")} />
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {managed.error && (
              <div className="mt-3 p-2 rounded-md bg-amber-500/10 border border-amber-500/30 flex items-start gap-2">
                <Info className="h-4 w-4 text-amber-400 flex-shrink-0 mt-0.5" />
                <div className="text-xs text-amber-300">{localizeUpstreamError(managed.error)}</div>
              </div>
            )}

            {/* Managed banner — green translucent badge signalling this
                CT's lifecycle is owned by ProxMenux (not user CRUD). */}
            <div className="mt-4 p-2.5 rounded-md bg-green-500/10 border border-green-500/30 flex items-center gap-2 text-sm">
              <ShieldCheck className="h-4 w-4 text-green-400 flex-shrink-0" />
              <span className="text-green-300">{t("vmLxc.appEditor.installedManaged")}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        {t("vmLxc.appEditor.loadingApplications")}
      </div>
    )
  }

  // ── Editor ─────────────────────────────────────────────────────
  if (editing) {
    const draft = editing.draft
    const method = draft.installed_via || ""
    const isPackaged = method === "dpkg" || method === "apk"
    const setField = (patch: Partial<AppConfig>) => {
      setDetectorTest(null)
      setEditing({ ...editing, draft: { ...draft, ...patch } })
    }
    // Editing the Name auto-fills the Package field on packaged
    // methods when it's still empty. Rationale: 90% of the time the
    // dpkg/apk package name mirrors the friendly app name (jellyfin,
    // adguardhome, portainer-ce). The user can still override.
    const setName = (name: string) => {
      const patch: Partial<AppConfig> = { name }
      if (isPackaged && !draft.package?.trim()) {
        patch.package = suggestPackageName(name)
      }
      setField(patch)
    }
    const setPort = (i: number, patch: Partial<PortEntry>) => {
      const ports = draft.ports.map((p, idx) => (idx === i ? { ...p, ...patch } : p))
      setField({ ports })
    }
    // "Add port" adds an EMPTY row for manual entry. Detected chips
    // ("+5000", "+1984"…) add the port directly with the port
    // pre-filled — no need for the user to open a row first.
    const addEmptyPort = () =>
      setField({ ports: [...draft.ports, { port: "", description: "", scheme: "http" }] })
    const addDetectedPort = (port: number) => {
      const scheme = defaultSchemeFor(port)
      // If the last row is still empty, fill it instead of appending
      // a duplicate. Avoids the two-lines-appear bug.
      const last = draft.ports[draft.ports.length - 1]
      if (last && last.port === "" && !last.description) {
        const ports = [...draft.ports]
        ports[ports.length - 1] = { port, description: "", scheme }
        setField({ ports })
      } else {
        setField({ ports: [...draft.ports, { port, description: "", scheme }] })
      }
    }
    const addDockerWebLink = (link: DockerWebLinkSuggestion) => {
      const entry: PortEntry = {
        port: link.host_port,
        description: link.service_name,
        scheme: link.scheme,
        web_path: link.web_path || "/",
        logo_url: link.logo_url || "",
      }
      const last = draft.ports[draft.ports.length - 1]
      if (last && last.port === "" && !last.description) {
        const ports = [...draft.ports]
        ports[ports.length - 1] = entry
        setField({ ports })
      } else {
        setField({ ports: [...draft.ports, entry] })
      }
    }
    const removePort = (i: number) =>
      setField({ ports: draft.ports.filter((_, idx) => idx !== i) })
    const usedPorts = new Set(draft.ports.map((p) => p.port))
    const isDockerDraft = draft.helper_slug === "docker" ||
      (draft.installed_via === "binary" && draft.binary_path?.endsWith("/docker"))
    const suggestableDockerLinks = isDockerDraft
      ? (suggestions?.docker_web_links || []).filter((link) => !usedPorts.has(link.host_port))
      : []
    // A Docker registration uses structured container → published-port
    // suggestions below.  Suppress the generic ss/netstat chips in that case
    // so the same endpoint is not presented twice without its workload name.
    const suggestable = isDockerDraft
      ? []
      : (suggestions?.port_suggestions || []).filter((p) => !usedPorts.has(p))

    return (
      <div className="space-y-4">
        {/* Editor card — raised to `bg-accent` (matches the tone
            clickable cards get on hover) so the `bg-background` inputs
            sit clearly recessed against it. The three descendant
            selectors push every Input / Textarea / SelectTrigger
            (role="combobox") under this card down to `bg-background`
            in one shot, so future fields inherit the sunken look
            without per-input styling. Reverts to `bg-card/50`
            automatically because this render branch only fires when
            `editing !== null`. */}
        <Card className="border border-border bg-accent [&_input]:bg-background [&_textarea]:bg-background [&_[role=combobox]]:bg-background">
          <CardContent className="p-4 space-y-4">
            <div className="relative">
              <Label htmlFor="app-name">{t("vmLxc.appEditor.nameLabel")}</Label>
              <Input
                id="app-name"
                value={draft.name}
                onChange={(e) => { setName(e.target.value); setPickerOpen(true) }}
                onFocus={() => setPickerOpen(true)}
                onBlur={() => setTimeout(() => setPickerOpen(false), 150)}
                placeholder={suggestions?.name_suggestion || t("vmLxc.appEditor.nameSearchPlaceholder")}
                maxLength={64}
                autoComplete="off"
              />
              {/* Catalog picker dropdown — filters the 700+ helpers_cache
                  entries by name substring while the user types. Top 20
                  matches shown. Click one to auto-fill name / logo /
                  ports / tracking hint in one shot. Empty query with
                  the input focused shows a "start typing" hint. */}
              {pickerOpen && catalog.length > 0 && (() => {
                const q = (draft.name || "").trim().toLowerCase()
                if (!q) return null
                const matches = catalog
                  .filter((c) => c.name.toLowerCase().includes(q) || c.slug.toLowerCase().includes(q))
                  .slice(0, 20)
                if (!matches.length) return null
                return (
                  <div className="absolute z-20 left-0 right-0 mt-1 max-h-72 overflow-y-auto rounded-md border border-border bg-popover shadow-lg">
                    <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border/60">
                      {matches.length === 20 ? t("vmLxc.appEditor.top20Matches") : t("vmLxc.appEditor.matchCount", { count: matches.length })}
                    </div>
                    {matches.map((c) => (
                      <button
                        key={c.slug}
                        type="button"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={async () => {
                          setPickerOpen(false)
                          try {
                            const detail: CatalogDetail = await fetchApi(`/api/apps/catalog/${c.slug}?vmid=${vmid}`)
                            // Seed the entire form from the picker detail.
                            const patch: Partial<AppConfig> = {
                              name: detail.name,
                              helper_slug: detail.slug,
                              logo_url: detail.logo_url || "",
                              ports: detail.slug !== "docker" && detail.default_ports?.length
                                ? detail.default_ports.map((p) => ({
                                    port: p,
                                    scheme: defaultSchemeFor(p),
                                    web_path: "",
                                  }))
                                : draft.ports,
                            }
                            if (detail.tracking_suggestion) {
                              const t = detail.tracking_suggestion as any
                              patch.installed_via = t.installed_via
                              patch.package = t.package || ""
                              patch.file_path = t.file_path || ""
                              patch.file_regex = t.file_regex || ""
                              patch.binary_path = t.binary_path || ""
                              patch.binary_args = t.binary_args || []
                              patch.python_path = t.python_path || ""
                              patch.distribution = t.distribution || ""
                              patch.container_name = t.container_name || ""
                              patch.label = t.label || ""
                              patch.installed_regex = t.installed_regex || ""
                              patch.upstream_type = (t as any).upstream_type || (t.repo ? "github" : "")
                              patch.repo = t.repo || ""
                              patch.github_source = t.github_source || "releases"
                              patch.upstream_url = (t as any).upstream_url || ""
                              patch.upstream_json_path = (t as any).upstream_json_path || ""
                              patch.docker_image = (t as any).docker_image || ""
                              patch.tag_regex = t.tag_regex || "v?(\\d+\\.\\d+\\.\\d+)"
                              setShowAdvanced(true)
                            }
                            setEditing((prev) => prev ? { ...prev, draft: { ...prev.draft, ...patch } } : prev)
                          } catch { /* non-fatal */ }
                        }}
                        className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-accent hover:text-accent-foreground transition-colors"
                      >
                        {c.logo && (
                          <img src={c.logo} alt="" className="h-6 w-6 flex-shrink-0 rounded object-contain"
                               onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none" }} />
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="text-sm text-foreground truncate">{c.name}</div>
                          <div className="text-[10px] text-muted-foreground">
                            {c.slug}
                            {c.default_port ? ` · ${t("vmLxc.appEditor.catalogPort", { port: c.default_port })}` : ""}
                            {c.has_tracking ? ` · ${t("vmLxc.appEditor.trackingAvailable")}` : ""}
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                )
              })()}
            </div>

            {/* App-level logo URL — optional. Auto-filled from the
                catalog for helper-scripts installs, blank otherwise.
                For a custom app the user can paste a URL (typically
                from https://selfh.st/icons); empty → no logo in the
                app card header. */}
            <div className="pt-2 border-t border-border/50">
              <Label htmlFor="app-logo" className="text-xs uppercase tracking-wider text-muted-foreground">
                {t("vmLxc.appEditor.logoUrlLabel")} <span className="normal-case tracking-normal text-[10px] opacity-70">{t("vmLxc.appEditor.optionalSuffix")}</span>
              </Label>
              <Input
                id="app-logo"
                type="url"
                value={draft.logo_url || ""}
                onChange={(e) => setField({ logo_url: e.target.value })}
                placeholder={t("vmLxc.appEditor.portLogoPlaceholder")}
                maxLength={512}
                className="text-sm mt-2 font-mono"
              />
            </div>

            {/* Web links — each port becomes a clickable link (built as
                http[s]://<ip>:<port>). Detected chips add the port
                directly (no need to first open an empty row). */}
            <div className="pt-2 border-t border-border/50">
              <div className="flex items-center justify-between mb-2">
                <Label className="text-xs uppercase tracking-wider text-muted-foreground">
                  {t("vmLxc.appEditor.webLinks")}
                </Label>
                <Button type="button" variant="ghost" size="sm" onClick={addEmptyPort}>
                  <PlusCircle className="h-3.5 w-3.5 mr-1" />
                  {t("vmLxc.appEditor.addPort")}
                </Button>
              </div>

              {suggestableDockerLinks.length > 0 && (
                <div className="mb-3 space-y-2">
                  <div>
                    <div className="text-xs font-medium text-foreground">
                      {t("vmLxc.appEditor.dockerPublishedServicesTitle")}
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-0.5 leading-relaxed max-w-2xl">
                      {t("vmLxc.appEditor.dockerPublishedServicesHelp")}
                    </p>
                  </div>
                  <div className="divide-y divide-border/50 border-y border-border/50">
                    {suggestableDockerLinks.map((link) => (
                      <div
                        key={`${link.container_name}:${link.host_port}`}
                        className="flex flex-col sm:flex-row sm:items-center gap-2 py-2"
                      >
                        {link.logo_url && (
                          <ThemeAwareLogo
                            src={link.logo_url}
                            className="h-7 w-7 rounded object-contain flex-shrink-0"
                          />
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="text-sm text-foreground truncate">{link.service_name}</div>
                          <div className="text-[10px] text-muted-foreground truncate" title={link.image}>
                            {link.image} · {t("vmLxc.appEditor.dockerPublishedPort", {
                              containerPort: link.container_port,
                              hostPort: link.host_port,
                            })}
                          </div>
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => addDockerWebLink(link)}
                          className="h-8 flex-shrink-0"
                        >
                          <PlusCircle className="h-3.5 w-3.5 mr-1" />
                          {t("vmLxc.appEditor.dockerPublishedAdd")}
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Detected chips FIRST — one-click add. Only shown when
                  there are chips left to suggest, so empty states stay
                  clean. Click on a chip: fills the current empty row
                  or adds a new one; never duplicates. */}
              {suggestable.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1 items-center">
                  <span className="text-[10px] text-muted-foreground pr-1">
                    {t("vmLxc.appEditor.detectedPorts")}
                  </span>
                  {suggestable.map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => addDetectedPort(p)}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-muted hover:bg-muted-foreground/20 text-foreground font-mono"
                    >
                      +{p}
                    </button>
                  ))}
                </div>
              )}

              {draft.ports.length === 0 && suggestable.length === 0 && suggestableDockerLinks.length === 0 && (
                <div className="text-xs text-muted-foreground italic">
                  {t("vmLxc.appEditor.noWebPorts")}
                </div>
              )}

              <div className="space-y-3">
                {draft.ports.map((entry, i) => (
                  <div
                    key={i}
                    className="grid grid-cols-[86px_86px_1fr_auto] gap-2 items-center gap-y-1.5"
                  >
                    <Select
                      value={entry.scheme || defaultSchemeFor(entry.port)}
                      onValueChange={(v) => setPort(i, { scheme: v as "http" | "https" })}
                    >
                      <SelectTrigger className="text-sm h-9"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="http">http</SelectItem>
                        <SelectItem value="https">https</SelectItem>
                      </SelectContent>
                    </Select>
                    <Input
                      type="number"
                      value={entry.port}
                      onChange={(e) => setPort(i, { port: e.target.value ? Number(e.target.value) : "" })}
                      placeholder={t("vmLxc.appEditor.portPortPlaceholder")}
                      min={1}
                      max={65535}
                      className="text-sm"
                    />
                    <Input
                      value={entry.description || ""}
                      onChange={(e) => setPort(i, { description: e.target.value })}
                      placeholder={t("vmLxc.appEditor.portDescriptionPlaceholder")}
                      maxLength={64}
                      className="text-sm"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => removePort(i)}
                      className="text-red-400 hover:text-red-300"
                      aria-label={t("vmLxc.appEditor.removePortTooltip")}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                    {/* Per-link logo URL — spans cols 1-3 so its
                        right edge lines up with the description input
                        above (never covers the trash column). */}
                    <Input
                      value={entry.logo_url || ""}
                      onChange={(e) => setPort(i, { logo_url: e.target.value })}
                      placeholder={t("vmLxc.appEditor.portLogoLabel")}
                      maxLength={512}
                      className="col-start-1 col-end-4 text-xs font-mono h-8 opacity-70 focus:opacity-100"
                      type="url"
                    />
                  </div>
                ))}
              </div>
            </div>

            {/* ── Advanced (Version tracking, optional) ──────────
                Collapsed by default so casual users never see the
                technical fields. Auto-expanded when editing an app
                that already has tracking configured, or when the
                user registered from an auto-detected chip whose
                hint carried tracking metadata. */}
            <div className="pt-2 border-t border-border/50">
              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-muted-foreground hover:text-foreground w-full"
              >
                {showAdvanced ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
                {t("vmLxc.appEditor.trackUpstream")}
                {!showAdvanced && !method && (
                  <span className="ml-auto text-[10px] normal-case tracking-normal">
                    {t("vmLxc.appEditor.trackOff")}
                  </span>
                )}
                {!showAdvanced && method && (
                  <span className="ml-auto text-[10px] normal-case tracking-normal text-emerald-400/80">
                    {t("vmLxc.appEditor.trackOn", { method })}
                  </span>
                )}
              </button>

              {showAdvanced && (
                <div className="mt-3 space-y-3">
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {t("vmLxc.appEditor.trackHelp")}
                  </p>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <Label htmlFor="app-method">{t("vmLxc.appEditor.installedViaLabel")}</Label>
                      <Select
                        value={method || "none"}
                        onValueChange={(v) =>
                          setField({ installed_via: v === "none" ? "" : (v as InstalledVia) })
                        }
                      >
                        <SelectTrigger id="app-method"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">{t("vmLxc.appEditor.methodNone")}</SelectItem>
                          <SelectItem value="dpkg">{t("vmLxc.appEditor.methodDpkg")}</SelectItem>
                          <SelectItem value="apk">{t("vmLxc.appEditor.methodApk")}</SelectItem>
                          <SelectItem value="binary">{t("vmLxc.appEditor.binaryVersionHint")}</SelectItem>
                          <SelectItem value="file">{t("vmLxc.appEditor.methodFile")}</SelectItem>
                          <SelectItem value="python_dist">{t("vmLxc.appEditor.methodPython")}</SelectItem>
                          <SelectItem value="docker_label">{t("vmLxc.appEditor.methodDockerLabel")}</SelectItem>
                          <SelectItem value="docker_exec">{t("vmLxc.appEditor.methodDockerExec")}</SelectItem>
                          <SelectItem value="command">{t("vmLxc.appEditor.methodCommand")}</SelectItem>
                          <SelectItem value="manual">{t("vmLxc.appEditor.methodManual")}</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    {isPackaged && (
                      <div>
                        <Label htmlFor="app-package">{t("vmLxc.appEditor.packageIdentifierLabel")}</Label>
                        <Input
                          id="app-package"
                          value={draft.package || ""}
                          onChange={(e) => setField({ package: e.target.value })}
                          placeholder={method === "dpkg" ? "e.g. jellyfin-server" : "e.g. tailscale"}
                        />
                        <div className="text-[10px] text-muted-foreground mt-1">
                          Auto-filled from Name. Verify with{" "}
                          <code className="text-foreground/70">
                            {method === "dpkg" ? "dpkg -l | grep <app>" : "apk info | grep <app>"}
                          </code>{" "}
                          inside the CT.
                        </div>
                      </div>
                    )}

                    {method === "binary" && (
                      <div>
                        <Label htmlFor="app-binary">{t("vmLxc.appEditor.binaryPathLabel")}</Label>
                        <Input
                          id="app-binary"
                          value={draft.binary_path || ""}
                          onChange={(e) => setField({ binary_path: e.target.value })}
                          placeholder={t("vmLxc.appEditor.binaryPathPlaceholder")}
                          className="font-mono text-xs"
                        />
                        <div className="text-[10px] text-muted-foreground mt-1">
                          Absolute path. Find it with{" "}
                          <code className="text-foreground/70">which &lt;app&gt;</code> or{" "}
                          <code className="text-foreground/70">systemctl show &lt;service&gt; -p ExecStart</code>.
                        </div>
                      </div>
                    )}
                  </div>

                  {method === "file" && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <Label htmlFor="app-file-path">{t("vmLxc.appEditor.filePathLabel")}</Label>
                        <Input
                          id="app-file-path"
                          value={draft.file_path || ""}
                          onChange={(e) => setField({ file_path: e.target.value })}
                          placeholder="/opt/app/VERSION"
                          className="font-mono text-xs"
                        />
                      </div>
                      <div>
                        <Label htmlFor="app-file-regex">{t("vmLxc.appEditor.regexCaptureGroupLabel")}</Label>
                        <Input
                          id="app-file-regex"
                          value={draft.file_regex || ""}
                          onChange={(e) => setField({ file_regex: e.target.value })}
                          placeholder={t("vmLxc.appEditor.regexPlaceholderVersion")}
                          className="font-mono text-xs"
                        />
                      </div>
                    </div>
                  )}

                  {method === "python_dist" && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <Label htmlFor="app-py-path">{t("vmLxc.appEditor.pythonInterpreterLabel")}</Label>
                        <Input
                          id="app-py-path"
                          value={draft.python_path || ""}
                          onChange={(e) => setField({ python_path: e.target.value })}
                          placeholder={t("vmLxc.appEditor.pythonInterpreterPlaceholder")}
                          className="font-mono text-xs"
                        />
                      </div>
                      <div>
                        <Label htmlFor="app-py-dist">{t("vmLxc.appEditor.pipDistLabel")}</Label>
                        <Input
                          id="app-py-dist"
                          value={draft.distribution || ""}
                          onChange={(e) => setField({ distribution: e.target.value })}
                          placeholder={t("vmLxc.appEditor.pipDistPlaceholder")}
                          className="font-mono text-xs"
                        />
                      </div>
                    </div>
                  )}

                  {method === "docker_label" && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <Label htmlFor="app-dl-container">{t("vmLxc.appEditor.containerNameLabel")}</Label>
                        <Input
                          id="app-dl-container"
                          value={draft.container_name || ""}
                          onChange={(e) => setField({ container_name: e.target.value })}
                          placeholder={t("vmLxc.appEditor.containerNamePlaceholder")}
                          className="font-mono text-xs"
                        />
                      </div>
                      <div>
                        <Label htmlFor="app-dl-label">{t("vmLxc.appEditor.ociLabelKeyLabel")}</Label>
                        <Input
                          id="app-dl-label"
                          value={draft.label || ""}
                          onChange={(e) => setField({ label: e.target.value })}
                          placeholder={t("vmLxc.appEditor.ociLabelPlaceholder")}
                          className="font-mono text-xs"
                        />
                      </div>
                    </div>
                  )}

                  {method === "docker_exec" && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <Label htmlFor="app-de-container">{t("vmLxc.appEditor.containerNameLabel")}</Label>
                        <Input
                          id="app-de-container"
                          value={draft.container_name || ""}
                          onChange={(e) => setField({ container_name: e.target.value })}
                          placeholder={t("vmLxc.appEditor.containerNamePlaceholder")}
                          className="font-mono text-xs"
                        />
                      </div>
                      <div>
                        <Label htmlFor="app-de-binary">{t("vmLxc.appEditor.binaryPathBare")}</Label>
                        <Input
                          id="app-de-binary"
                          value={draft.binary_path || ""}
                          onChange={(e) => setField({ binary_path: e.target.value })}
                          placeholder={t("vmLxc.appEditor.binaryPathBarePlaceholder")}
                          className="font-mono text-xs"
                        />
                      </div>
                      <div className="sm:col-span-2">
                        <Label htmlFor="app-de-args">{t("vmLxc.appEditor.binaryArgsLabel")}</Label>
                        <Input
                          id="app-de-args"
                          value={(draft.binary_args || []).join(", ")}
                          onChange={(e) => setField({
                            binary_args: e.target.value.split(",").map(s => s.trim()).filter(Boolean),
                          })}
                          placeholder={t("vmLxc.appEditor.binaryArgsPlaceholder")}
                          className="font-mono text-xs"
                        />
                        <div className="text-[10px] text-muted-foreground mt-1">
                          {t("vmLxc.appEditor.binaryArgsHintPrefix")} <code className="text-foreground/70">--version</code>. {t("vmLxc.appEditor.binaryArgsHintGrafana")} <code className="text-foreground/70">server, -v</code>.
                        </div>
                      </div>
                    </div>
                  )}

                  {method === "command" && (
                    <div>
                      <Label htmlFor="app-cmd-argv">{t("vmLxc.appEditor.commandLabel")}</Label>
                      <Input
                        id="app-cmd-argv"
                        value={(draft.command_argv || []).join(", ")}
                        onChange={(e) => setField({
                          command_argv: e.target.value.split(",").map(s => s.trim()).filter(Boolean),
                        })}
                        placeholder={t("vmLxc.appEditor.commandPlaceholder")}
                        className="font-mono text-xs"
                      />
                      <div className="text-[10px] text-muted-foreground mt-1">
                        {t("vmLxc.appEditor.commandSafetyHelp")}
                      </div>
                      <div className="mt-2">
                        <Label htmlFor="app-cmd-regex">{t("vmLxc.appEditor.installedVersionRegexLabel")}</Label>
                        <Input
                          id="app-cmd-regex"
                          value={draft.installed_regex || ""}
                          onChange={(e) => setField({ installed_regex: e.target.value })}
                          placeholder={t("vmLxc.appEditor.tagRegexBare")}
                          className="font-mono text-xs mt-1"
                        />
                      </div>
                    </div>
                  )}

                  {method === "manual" && (
                    <div>
                      <Label htmlFor="app-manual-ver">{t("vmLxc.appEditor.installedVersionLabel")}</Label>
                      <Input
                        id="app-manual-ver"
                        value={draft.installed_version || ""}
                        onChange={(e) => setField({ installed_version: e.target.value })}
                        placeholder="1.2.3"
                        maxLength={64}
                        className="font-mono text-xs"
                      />
                      <div className="text-[10px] text-muted-foreground mt-1">
                        {t("vmLxc.appEditor.manualVersionHelp")}
                      </div>
                    </div>
                  )}

                  {method && (() => {
                    // Upstream source selector — 3 methods (github,
                    // http_json, docker_hub). Legacy sidecars with a
                    // `repo` set but no `upstream_type` default to
                    // github so the classic behaviour keeps working
                    // until the user re-saves.
                    const upstreamType = draft.upstream_type
                      || (draft.repo ? "github" : "")
                    const setUpstream = (t: "" | "github" | "http_json" | "docker_hub") => {
                      // Clear other-type fields when switching so the
                      // backend doesn't receive stale data.
                      const patch: Partial<AppConfig> = { upstream_type: t }
                      if (t !== "github") {
                        patch.repo = ""
                        patch.github_source = "releases"
                      }
                      if (t !== "http_json") {
                        patch.upstream_url = ""
                        patch.upstream_json_path = ""
                      }
                      if (t !== "docker_hub") {
                        patch.docker_image = ""
                      }
                      if (!t) patch.tag_regex = ""
                      setField(patch)
                    }
                    return (
                      <>
                        <div>
                          <Label htmlFor="app-upstream-type">{t("vmLxc.appEditor.upstreamSourceLabel")}</Label>
                          <Select
                            value={upstreamType || "none"}
                            onValueChange={(v) => setUpstream(v === "none" ? "" : (v as any))}
                          >
                            <SelectTrigger id="app-upstream-type"><SelectValue /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value="none">{t("vmLxc.appEditor.upstreamNone")}</SelectItem>
                              <SelectItem value="github">{t("vmLxc.appEditor.upstreamGithub")}</SelectItem>
                              <SelectItem value="http_json">{t("vmLxc.appEditor.upstreamHttp")}</SelectItem>
                              <SelectItem value="docker_hub">{t("vmLxc.appEditor.upstreamDocker")}</SelectItem>
                            </SelectContent>
                          </Select>
                          <div className="text-[10px] text-muted-foreground mt-1">
                            {t("vmLxc.appEditor.upstreamHelp")}
                          </div>
                        </div>

                        {upstreamType === "github" && (
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <div>
                              <Label htmlFor="app-repo">{t("vmLxc.appEditor.githubRepoLabel")}</Label>
                              <Input
                                id="app-repo"
                                value={draft.repo || ""}
                                onChange={(e) => setField({ repo: e.target.value })}
                                placeholder={t("vmLxc.appEditor.githubRepoPlaceholder")}
                              />
                              <div className="text-[10px] text-muted-foreground mt-1">
                                {t("vmLxc.appEditor.githubRepoHelp")}
                              </div>
                            </div>
                            <div>
                              <Label htmlFor="app-source">{t("vmLxc.appEditor.latestFromLabel")}</Label>
                              <Select
                                value={draft.github_source || "releases"}
                                onValueChange={(v) => setField({ github_source: v as GithubSource })}
                              >
                                <SelectTrigger id="app-source"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="releases">{t("vmLxc.appEditor.sourceReleases")}</SelectItem>
                                  <SelectItem value="tags">{t("vmLxc.appEditor.sourceTags")}</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                          </div>
                        )}

                        {upstreamType === "http_json" && (
                          <div className="space-y-3">
                            <div>
                              <Label htmlFor="app-upstream-url">{t("vmLxc.appEditor.endpointUrlLabel")}</Label>
                              <Input
                                id="app-upstream-url"
                                type="url"
                                value={draft.upstream_url || ""}
                                onChange={(e) => setField({ upstream_url: e.target.value })}
                                placeholder={t("vmLxc.appEditor.endpointUrlPlaceholder")}
                                className="font-mono text-xs"
                                maxLength={512}
                              />
                              <div className="text-[10px] text-muted-foreground mt-1">
                                {t("vmLxc.appEditor.httpJsonHelp")}
                              </div>
                            </div>
                            <div>
                              <Label htmlFor="app-upstream-path">{t("vmLxc.appEditor.jsonPathLabel")}</Label>
                              <Input
                                id="app-upstream-path"
                                value={draft.upstream_json_path || ""}
                                onChange={(e) => setField({ upstream_json_path: e.target.value })}
                                placeholder={t("vmLxc.appEditor.jsonPathPlaceholder")}
                                className="font-mono text-xs"
                                maxLength={128}
                              />
                              <div className="text-[10px] text-muted-foreground mt-1">
                                {t("vmLxc.appEditor.jsonPathHelp")}
                              </div>
                            </div>
                          </div>
                        )}

                        {upstreamType === "docker_hub" && (
                          <div>
                            <Label htmlFor="app-docker-image">{t("vmLxc.appEditor.dockerImageLabel")}</Label>
                            <Input
                              id="app-docker-image"
                              value={draft.docker_image || ""}
                              onChange={(e) => setField({ docker_image: e.target.value })}
                              placeholder={t("vmLxc.appEditor.dockerImagePlaceholder")}
                              className="font-mono text-xs"
                              maxLength={255}
                            />
                            <div className="text-[10px] text-muted-foreground mt-1">
                              {t("vmLxc.appEditor.dockerVersionedTagsHelp")}
                            </div>
                          </div>
                        )}

                        {upstreamType && (
                          <div>
                            <Label htmlFor="app-tag-regex">
                              {upstreamType === "docker_hub" ? t("vmLxc.appEditor.tagFilterRegexOptional") : t("vmLxc.appEditor.versionRegexOptional")}
                            </Label>
                            <Input
                              id="app-tag-regex"
                              value={draft.tag_regex || ""}
                              onChange={(e) => setField({ tag_regex: e.target.value })}
                              placeholder={t("vmLxc.appEditor.tagRegexPlaceholder")}
                              className="font-mono text-xs"
                            />
                            {upstreamType === "docker_hub" && (
                              <div className="flex flex-wrap gap-1.5 mt-2">
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  className="h-7 text-[10px]"
                                  onClick={() => setField({ tag_regex: "^v?(\\d+\\.\\d+\\.\\d+)$" })}
                                >
                                  {t("vmLxc.appEditor.dockerPresetSemver")}
                                </Button>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  className="h-7 text-[10px]"
                                  onClick={() => setField({ tag_regex: "^v?(\\d+\\.\\d+\\.\\d+(?:[-+._][0-9A-Za-z.-]+)?)$" })}
                                >
                                  {t("vmLxc.appEditor.dockerPresetSemverSuffix")}
                                </Button>
                              </div>
                            )}
                            <div className="text-[10px] text-muted-foreground mt-1">
                              {upstreamType === "github" && "Extracts the version from the release tag name."}
                              {upstreamType === "http_json" && "Optional — extract a substring from the endpoint's value."}
                              {upstreamType === "docker_hub" && t("vmLxc.appEditor.dockerTagFilterHelp")}
                            </div>
                          </div>
                        )}

                        {upstreamType === "docker_hub" && draft.docker_image?.trim() && (
                          <div className="rounded-md border border-border/70 bg-background/50 p-3">
                            <div className="flex items-center justify-between gap-2 mb-2">
                              <div className="text-xs font-medium text-foreground">
                                {t("vmLxc.appEditor.dockerTagPreviewLabel")}
                              </div>
                              {dockerTagPreview && (
                                <span className="text-[10px] text-muted-foreground">
                                  {t("vmLxc.appEditor.dockerTagPreviewCount", {
                                    matched: dockerTagPreview.matched_count,
                                    scanned: dockerTagPreview.scanned_count,
                                  })}
                                </span>
                              )}
                            </div>
                            {dockerTagPreviewLoading ? (
                              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                {t("vmLxc.appEditor.dockerTagPreviewLoading")}
                              </div>
                            ) : dockerTagPreviewError ? (
                              <div className="text-xs text-amber-300">{dockerTagPreviewError}</div>
                            ) : dockerTagPreview?.tags.length ? (
                              <div className="flex flex-wrap gap-1.5">
                                {dockerTagPreview.tags.map((entry) => (
                                  <Badge
                                    key={entry.tag}
                                    variant="outline"
                                    className={entry.moving ? "border-amber-500/40 text-amber-300" : "font-mono"}
                                  >
                                    {entry.tag}{entry.moving ? ` · ${t("vmLxc.appEditor.dockerMovingTag")}` : ""}
                                  </Badge>
                                ))}
                              </div>
                            ) : (
                              <div className="text-xs text-muted-foreground">
                                {t("vmLxc.appEditor.dockerTagPreviewEmpty")}
                              </div>
                            )}
                            {dockerTagPreview?.tags.some((entry) => entry.moving) && (
                              <div className="mt-2 text-[10px] text-amber-300 leading-relaxed">
                                {t("vmLxc.appEditor.dockerMovingTagHelp")}
                              </div>
                            )}
                          </div>
                        )}
                      </>
                    )
                  })()}
                </div>
              )}
            </div>

            {/* Per-app notification opt-out. Only makes sense for
                apps with tracking configured — without an upstream
                source there's no `app_update_available` event to
                mute. Default is ON (checkbox checked); the bell
                toggle on each card is a shortcut to the same field.
                The second checkbox below controls the CT's aggregate
                updates badge independently — a user may want the
                outbound notification but hide the counter (or
                the reverse). */}
            {method && (
              <div className="pt-2 border-t border-border/50 space-y-3">
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={draft.notifications_enabled !== false}
                    onChange={(e) => setField({ notifications_enabled: e.target.checked })}
                    className="mt-0.5 h-4 w-4 rounded border-border accent-blue-500"
                  />
                  <div className="text-sm">
                    <div className="text-foreground">{t("vmLxc.appEditor.notifyUpstreamLabel")}</div>
                    <div className="text-xs text-muted-foreground mt-1">{t("vmLxc.appEditor.notifyUpstreamHelp")}</div>
                  </div>
                </label>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={draft.exclude_from_badge === true}
                    onChange={(e) => setField({ exclude_from_badge: e.target.checked })}
                    className="mt-0.5 h-4 w-4 rounded border-border accent-blue-500"
                  />
                  <div className="text-sm">
                    <div className="text-foreground">{t("vmLxc.appEditor.excludeFromBadgeLabel")}</div>
                    <div className="text-xs text-muted-foreground mt-1">{t("vmLxc.appEditor.excludeFromBadgeHelp")}</div>
                  </div>
                </label>
              </div>
            )}

            {detectorTest && (
              <div className="rounded-md border border-border/70 bg-background/60 p-3 space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs font-medium text-foreground">
                    {t("vmLxc.appEditor.detectorTestTitle")}
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <div className={"rounded-md border p-2.5 " + (detectorTest.installed.version ? "border-emerald-500/30 bg-emerald-500/5" : "border-amber-500/30 bg-amber-500/5")}>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                      {t("vmLxc.appEditor.installedStatus")}
                    </div>
                    {detectorTest.installed.version ? (
                      <div className="font-mono text-sm text-emerald-400">{detectorTest.installed.version}</div>
                    ) : (
                      <div className="text-xs text-amber-300">{detectorTest.installed.error || t("vmLxc.appEditor.detectorTestNoVersion")}</div>
                    )}
                    <div className="mt-1.5 text-[10px] text-muted-foreground break-all">
                      {detectorTest.installed.method || "—"}
                      {detectorTest.installed.effective_regex ? ` · ${detectorTest.installed.effective_regex}` : ""}
                    </div>
                  </div>
                  <div className={"rounded-md border p-2.5 " + (!detectorTest.upstream.configured || detectorTest.upstream.version ? "border-emerald-500/30 bg-emerald-500/5" : "border-amber-500/30 bg-amber-500/5")}>
                    <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
                      {t("vmLxc.appEditor.latestUpstream")}
                    </div>
                    {!detectorTest.upstream.configured ? (
                      <div className="text-xs text-muted-foreground">{t("vmLxc.appEditor.detectorTestNoUpstream")}</div>
                    ) : detectorTest.upstream.version ? (
                      <div className="font-mono text-sm text-emerald-400">{detectorTest.upstream.version}</div>
                    ) : (
                      <div className="text-xs text-amber-300">{detectorTest.upstream.error || t("vmLxc.appEditor.detectorTestNoVersion")}</div>
                    )}
                    {detectorTest.upstream.type && (
                      <div className="mt-1.5 text-[10px] text-muted-foreground">{detectorTest.upstream.type}</div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {error && (
              <div className="text-xs text-red-400 flex items-start gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <div className="flex flex-wrap gap-2 justify-end pt-2">
              {method && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={testDetector}
                  disabled={saving || testingDetector || !draft.name.trim()}
                  className="sm:mr-auto"
                >
                  {testingDetector ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <ShieldCheck className="h-4 w-4 mr-1.5" />}
                  {testingDetector ? t("vmLxc.appEditor.testingDetectorButton") : t("vmLxc.appEditor.testDetectorButton")}
                </Button>
              )}
              <Button variant="ghost" onClick={closeEditor} disabled={saving || testingDetector}>{t("vmLxc.appEditor.cancelButton")}</Button>
              <Button
                onClick={save}
                disabled={saving || testingDetector || !draft.name.trim()}
                className="bg-blue-500 hover:bg-blue-600 text-white"
              >
                {saving ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Save className="h-4 w-4 mr-1.5" />}
                {t("vmLxc.appEditor.saveButton")}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Restore chip — same visual shell as detection chip but the
  // action switches from Register/Hide to Restore. Used inside the
  // Register-a-different-app panel when hidden slugs exist.
  const renderRestoreChip = (d: DetectedApp) => (
    <div key={d.slug} className="p-3 rounded-md border border-border/60 bg-background/40">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          {d.logo_url && (
            <ThemeAwareLogo
              src={d.logo_url}
              className="h-14 w-14 flex-shrink-0 rounded-md object-contain"
            />
          )}
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground truncate">{d.name}</div>
            <div className="text-xs text-muted-foreground">{t("vmLxc.appEditor.hiddenBadge")}</div>
          </div>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => restoreDetection(d.slug)}
          className="w-full sm:w-auto"
        >
          <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
          {t("vmLxc.appEditor.restoreButton")}
        </Button>
      </div>
    </div>
  )

  // Uniform detection chip used in every context — empty state,
  // post-registration "also detected" strip, and the Register-a-
  // different-app panel. Actions layout responsive:
  //   • Desktop (sm+): Register + Hide side-by-side, both labeled
  //   • Mobile: same row, 3/4 Register (label+icon) + 1/4 Hide
  //     (eye icon only inside a red-translucent button)
  //
  // Single "Register" button covers both paths — with or without
  // tracking hint — the editor opens pre-filled with whatever data
  // we have, and the user can adjust in Advanced.
  const renderDetectionChip = (d: DetectedApp) => (
    <div key={d.slug} className="p-3 rounded-md border border-border/60 bg-background/40">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          {d.logo_url && (
            <ThemeAwareLogo
              src={d.logo_url}
              className="h-14 w-14 flex-shrink-0 rounded-md object-contain"
            />
          )}
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground truncate">{d.name}</div>
            <div className="text-xs text-emerald-400/90">
              {d.tracking_suggestion?.detector_verified
                ? t("vmLxc.appEditor.versionDetected", { version: d.tracking_suggestion.detected_version || "" })
                : t("vmLxc.appEditor.detectedInContainer")}
            </div>
            {d.tracking_suggestion?.detector_source === "legacy_fallback" && (
              <div className="text-[10px] text-amber-400/90 mt-0.5">
                {t("vmLxc.appEditor.legacyDetectorUsed")}
              </div>
            )}
          </div>
        </div>
        <div className="flex flex-row gap-2 flex-shrink-0 sm:justify-end w-full sm:w-auto">
          <Button
            size="sm"
            onClick={() => openEditor(undefined, { withTracking: !!d.tracking_suggestion, preset: d })}
            className="flex-[3] sm:flex-none bg-blue-500 hover:bg-blue-600 text-white"
          >
            <PlusCircle className="h-3.5 w-3.5 mr-1" />
            {t("vmLxc.appEditor.registerButton")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => dismissDetection(d.slug, d.name)}
            aria-label={`Hide ${d.name} detection`}
            title={t("vmLxc.appEditor.hidePermanentlyTooltip")}
            className="flex-1 sm:flex-none bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 hover:text-red-300"
          >
            <EyeOff className="h-3.5 w-3.5 sm:mr-1" />
            <span className="hidden sm:inline">{t("vmLxc.appEditor.hideButton")}</span>
          </Button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="space-y-4">
      {/* Browse panel — surfaces hidden detections with Restore
          before falling through to the blank-form path. Rendered
          before app cards / empty state so it takes precedence when
          open. Closes automatically once all hidden slugs are
          restored (nothing left to show → back to normal flow). */}
      {browseOpen && (
        <Card className="border border-border bg-card/50">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-foreground">{t("vmLxc.appEditor.registerDifferent")}</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {t(hiddenDetections.length === 1 ? "vmLxc.appEditor.hiddenDetectionsHelpSingular" : "vmLxc.appEditor.hiddenDetectionsHelpPlural", { count: hiddenDetections.length })}
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setBrowseOpen(false)}
                aria-label={t("vmLxc.appEditor.closePanel")}
                className="text-muted-foreground hover:text-foreground"
              >
                {t("vmLxc.appEditor.cancelButton")}
              </Button>
            </div>
            {hiddenDetections.length > 0 && (
              <div className="space-y-2">
                {hiddenDetections.map(renderRestoreChip)}
              </div>
            )}
            <div className="pt-1 flex justify-center">
              <Button
                onClick={() => { setBrowseOpen(false); openEditor() }}
                className="bg-blue-500 hover:bg-blue-600 text-white"
              >
                <PlusCircle className="h-4 w-4 mr-1.5" />
                {t("vmLxc.appEditor.registerCustom")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty state — always uniform chip list regardless of how
          many detections there are (0, 1, or many). Below the chips,
          a single "Register a different app" button lets the user
          add something the auto-detector doesn't know about. */}
      {apps.length === 0 && (
        <Card className="border border-border bg-card/50">
          <CardContent className="p-6 space-y-3">
            <div className="mx-auto p-2 rounded-full bg-emerald-500/10 w-fit">
              <Package className="h-5 w-5 text-emerald-400" />
            </div>
            <h3 className="text-sm font-semibold text-foreground text-center">
              {t("vmLxc.appEditor.noAppsTitle")}
            </h3>
            <p className="text-xs text-muted-foreground max-w-md mx-auto leading-relaxed text-center">
              {t("vmLxc.appEditor.noAppsBody")}
            </p>
            {visibleDetected.length > 0 && (
              <div className="space-y-2 pt-2">
                {visibleDetected.map(renderDetectionChip)}
              </div>
            )}
            <div className="pt-1 flex flex-wrap justify-center gap-2">
              <Button
                onClick={searchInstalledApplications}
                disabled={searchingApplications}
                className="bg-blue-500 hover:bg-blue-600 text-white"
              >
                {searchingApplications
                  ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                  : <Search className="h-4 w-4 mr-1.5" />}
                {searchingApplications
                  ? t("vmLxc.appEditor.searchingApplications")
                  : t("vmLxc.appEditor.searchApplications")}
              </Button>
              <Button
                onClick={openBrowseOrEditor}
                className="bg-blue-500 hover:bg-blue-600 text-white"
              >
                <PlusCircle className="h-4 w-4 mr-1.5" />
                {t("vmLxc.appEditor.registerApplication")}
                {hiddenDetections.length > 0 && (
                  <span className="ml-2 text-[10px] opacity-70">
                    · {t("vmLxc.appEditor.hiddenSuffix", { count: hiddenDetections.length })}
                  </span>
                )}
              </Button>
            </div>
            {detectionNotice && (
              <p className={`text-xs text-center ${detectionNotice.found ? "text-emerald-400" : "text-muted-foreground"}`}>
                {detectionNotice.text}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* App cards */}
      {apps.map((app) => {
        const st = app.state
        // Version tracking is on when installed_via is set. Without a
        // method the app is register-only — no cards, no warnings.
        const tracking = !!app.installed_via
        return (
          <Card key={app.id} className="border border-border bg-card/50">
            <CardContent className="p-4">
              <div className="flex items-start justify-between gap-3 mb-3">
                <div className="flex items-center gap-3 min-w-0 flex-1">
                  {app.logo_url && (
                    <ThemeAwareLogo
                      src={app.logo_url}
                      className="h-14 w-14 flex-shrink-0 rounded-md object-contain"
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <h3 className="text-lg font-semibold text-foreground truncate">{app.name}</h3>
                    {tracking && (
                      <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5 flex-wrap">
                        {app.installed_via === "dpkg" && app.package && <>dpkg · <code className="text-foreground/80">{app.package}</code></>}
                        {app.installed_via === "apk" && app.package && <>apk · <code className="text-foreground/80">{app.package}</code></>}
                        {app.installed_via === "file" && app.file_path && <>file · <code className="text-foreground/80">{app.file_path}</code></>}
                        {app.installed_via === "binary" && app.binary_path && <>binary · <code className="text-foreground/80">{app.binary_path}</code></>}
                      </div>
                    )}
                    {tracking && st?.checked_at && (
                      <div className="text-[10px] text-muted-foreground/80 mt-0.5">
                        {t("vmLxc.appEditor.checkedAt", { date: new Date(st.checked_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) })}
                      </div>
                    )}
                    {/* Mobile-only repo link: falls into the metadata
                        stack below Checked, full-width so long repo
                        names wrap cleanly instead of competing with
                        the top-right on narrow screens. */}
                    {app.repo && tracking && (
                      <a
                        href={`https://github.com/${app.repo}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="md:hidden mt-1 text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1 min-w-0"
                      >
                        <ExternalLink className="h-3 w-3 flex-shrink-0" />
                        <span className="truncate">{app.repo}</span>
                      </a>
                    )}
                  </div>
                </div>
                {/* Desktop-only repo link: same row as the title on md+,
                    hidden on mobile where the stacked variant above
                    handles it. */}
                {app.repo && tracking && (
                  <a
                    href={`https://github.com/${app.repo}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hidden md:inline-flex text-xs text-muted-foreground hover:text-foreground items-center gap-1 flex-shrink-0 mt-1"
                  >
                    {app.repo}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>

              {(() => {
                const hasUpstream = !!(app.repo || app.upstream_type)
                const hasUpdate = st?.update_available === true
                if (!tracking || !(st?.installed_version || hasUpstream)) return null
                return (
                  <div className={"mb-3 grid gap-3 " + (st?.installed_version && hasUpstream ? "grid-cols-2" : "grid-cols-1")}>
                    {st?.installed_version && (
                      <div className="p-3 rounded-md bg-muted/40">
                        <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">{t("vmLxc.appEditor.installedStatus")}</div>
                        <div className="text-lg font-semibold font-mono text-foreground">
                          {st.installed_version}
                        </div>
                      </div>
                    )}
                    {hasUpstream && (
                      <div className="p-3 rounded-md bg-muted/40">
                        <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">
                          {t("vmLxc.appEditor.latestUpstream")}
                        </div>
                        <div className={"text-lg font-semibold font-mono flex items-center gap-2 " + (hasUpdate ? "text-purple-400" : "text-foreground")}>
                          {st?.latest_version || <span className="text-muted-foreground text-base font-normal">{t("vmLxc.appEditor.checkingStatus")}</span>}
                          {hasUpdate && st?.latest_version && (
                            <ArrowUpCircle className="h-5 w-5 text-purple-400 flex-shrink-0" aria-label={t("vmLxc.appEditor.updateAvailableBadge")} />
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })()}

              {tracking && st?.error && (
                <div className="mb-3 p-2 rounded-md bg-amber-500/10 border border-amber-500/30 flex items-start gap-2">
                  <Info className="h-4 w-4 text-amber-400 flex-shrink-0 mt-0.5" />
                  <div className="text-xs text-amber-300">{localizeUpstreamError(st.error)}</div>
                </div>
              )}

              {/* Web links — one row per port. Each row:
                    [logo 56px]  Description or app name
                                 ↗ http://IP:PORT
                  Logo is optional (per-port `logo_url`); when absent
                  the row indents naturally to align with the text.
                  If we can't resolve an IP for the CT we hide the row. */}
              {app.ports && app.ports.length > 0 && (
                <div className="mb-3 space-y-4">
                  {app.ports.map((p) => {
                    const url = buildWebUrl(ctIp, p.port, p.scheme)
                    if (!url) return null
                    const label = p.description || app.name
                    return (
                      <div key={p.port} className="flex items-start gap-3 min-w-0">
                        {p.logo_url && (
                          <ThemeAwareLogo
                            src={p.logo_url}
                            className="h-14 w-14 flex-shrink-0 rounded-md object-contain"
                          />
                        )}
                        <div className="min-w-0 flex flex-col">
                          <span className="text-sm font-medium text-foreground truncate">{label}</span>
                          <a
                            href={url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-400 hover:text-blue-300 inline-flex items-center gap-1.5 min-w-0"
                            title={url}
                          >
                            <ExternalLink className="h-3.5 w-3.5 flex-shrink-0" />
                            <span className="font-mono text-sm truncate">{url}</span>
                          </a>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Footer with per-card actions — only rendered in the
                  global edit mode (toggled from the "Edit" button next
                  to Add another application). View mode keeps cards
                  chrome-free; Check remains available in edit mode.
                  Buttons match
                  the Settings-page section style (h-8, outline,
                  small icon + label) for visual consistency across
                  the app. */}
              {editMode && (
                <div className="flex flex-wrap gap-2 items-center mt-3 pt-3 border-t border-border/50">
                  <button
                    type="button"
                    onClick={() => removeOne(app.id)}
                    disabled={busyAppId === app.id}
                    className="h-8 px-3 text-xs rounded-md border border-red-500/30 bg-red-500/10 hover:bg-red-500/20 text-red-400 transition-colors inline-flex items-center gap-1.5 disabled:opacity-60"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {t("vmLxc.appEditor.removeButton")}
                  </button>
                  <div className="ml-auto flex flex-wrap gap-2">
                    {tracking && (
                      <button
                        type="button"
                        onClick={() => toggleAppNotifications(app)}
                        disabled={busyAppId === app.id}
                        title={
                          app.notifications_enabled === false
                            ? t("vmLxc.appEditor.notificationsMuted")
                            : t("vmLxc.appEditor.notificationsEnabled")
                        }
                        className={
                          app.notifications_enabled === false
                            ? "h-8 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors inline-flex items-center gap-1.5 disabled:opacity-60 text-muted-foreground"
                            : "h-8 px-3 text-xs rounded-md border border-blue-500/30 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 transition-colors inline-flex items-center gap-1.5 disabled:opacity-60"
                        }
                      >
                        {app.notifications_enabled === false
                          ? <BellOff className="h-3.5 w-3.5" />
                          : <Bell className="h-3.5 w-3.5" />}
                      </button>
                    )}
                    {tracking && (
                      <button
                        type="button"
                        onClick={() => checkOne(app.id)}
                        disabled={busyAppId === app.id}
                        className="h-8 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors inline-flex items-center gap-1.5 disabled:opacity-60"
                      >
                        {busyAppId === app.id
                          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          : <RefreshCw className="h-3.5 w-3.5" />}
                        {t("vmLxc.appEditor.checkButton")}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => openEditor(app)}
                      className="h-8 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors inline-flex items-center gap-1.5"
                    >
                      <Settings2 className="h-3.5 w-3.5" />
                      {t("vmLxc.appEditor.editFieldsButton")}
                    </button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )
      })}

      {/* Post-registration "also detected" strip — every hint slug
          whose install signature is present on the CT AND that
          hasn't been registered yet is shown as a chip with a
          one-click Register button. Filtered against the sidecar's
          `helper_slug` field so a registered app never re-appears. */}
      {apps.length > 0 && unregisteredDetected.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs uppercase tracking-wider text-muted-foreground">
            {t("vmLxc.appEditor.alsoDetectedContainer")}
          </div>
          {unregisteredDetected.map(renderDetectionChip)}
        </div>
      )}

      {/* Add-more + Edit toggle. Edit is a global toggle that reveals
          the per-card action footer (Remove / Check / Edit fields).
          Add-more is disabled while editing so the two flows don't
          overlap. Routes through the browse panel if there are hidden
          detections, so the user gets one-click Restore before hand-
          typing a custom app. */}
      {apps.length > 0 && (
        <div className="flex flex-col items-stretch gap-2 max-w-xs mx-auto sm:flex-row sm:flex-wrap sm:justify-end sm:items-center sm:max-w-none sm:mx-0">
          <Button
            variant="outline"
            size="sm"
            onClick={searchInstalledApplications}
            disabled={searchingApplications || editMode}
            className="w-full sm:w-auto order-2 sm:order-1"
          >
            {searchingApplications
              ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
              : <Search className="h-4 w-4 mr-1.5" />}
            {searchingApplications
              ? t("vmLxc.appEditor.searchingApplications")
              : t("vmLxc.appEditor.searchApplications")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={openBrowseOrEditor}
            disabled={editMode}
            className="w-full sm:w-auto order-3 sm:order-2"
          >
            <PlusCircle className="h-4 w-4 mr-1.5" />
            {t("vmLxc.appEditor.addAnotherApplication")}
            {hiddenDetections.length > 0 && (
              <span className="ml-2 text-[10px] opacity-70">
                · {t("vmLxc.appEditor.hiddenSuffix", { count: hiddenDetections.length })}
              </span>
            )}
          </Button>
          <button
            type="button"
            onClick={() => setEditMode((v) => !v)}
            className="h-9 px-3 text-sm rounded-md border border-border bg-background hover:bg-muted transition-colors inline-flex items-center justify-center gap-1.5 w-full sm:w-auto order-1 sm:order-3"
          >
            {editMode ? (
              <>
                <Check className="h-3.5 w-3.5" />
                {t("vmLxc.appEditor.doneButton")}
              </>
            ) : (
              <>
                <Pencil className="h-3.5 w-3.5" />
                {t("vmLxc.appEditor.editButton")}
              </>
            )}
          </button>
        </div>
      )}

      {apps.length > 0 && detectionNotice && (
        <p className={`text-xs text-right ${detectionNotice.found ? "text-emerald-400" : "text-muted-foreground"}`}>
          {detectionNotice.text}
        </p>
      )}

      {error && (
        <div className="text-xs text-red-400 flex items-start gap-1.5">
          <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}
    </div>
  )
}
