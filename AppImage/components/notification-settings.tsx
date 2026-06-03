"use client"

import { useState, useEffect, useCallback } from "react"
import { useTheme } from "next-themes"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./ui/tabs"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./ui/dialog"
import { fetchApi } from "../lib/api-config"
import {
  Bell, BellOff, Send, CheckCircle2, XCircle, Loader2,
  AlertTriangle, Info, Settings2, Zap, Eye, EyeOff,
  Trash2, ChevronDown, ChevronUp, ChevronRight, TestTube2, Mail, Webhook,
  Copy, Server, Shield, ExternalLink, RefreshCw, Download, Upload,
  Cloud, Brain, Globe, MessageSquareText, Sparkles, Pencil, Save, RotateCcw, Lightbulb,
  Moon, Newspaper
} from "lucide-react"

interface ChannelConfig {
  enabled: boolean
  rich_format?: boolean
  bot_token?: string
  chat_id?: string
  topic_id?: string  // Telegram topic ID for supergroups with topics
  url?: string
  token?: string
  webhook_url?: string
  // Email channel fields
  host?: string
  port?: string
  username?: string
  password?: string
  tls_mode?: string
  from_address?: string
  to_addresses?: string
  subject_prefix?: string
  // Quiet hours: skip below-CRITICAL events between [start, end) local time
  quiet_enabled?: boolean
  quiet_start?: string  // "HH:MM"
  quiet_end?: string    // "HH:MM"
  // Daily digest: buffer INFO events and ship one summary at digest_time
  digest_enabled?: boolean
  digest_time?: string  // "HH:MM"
}

interface EventTypeInfo {
  type: string
  title: string
  default_enabled: boolean
}

interface ChannelOverrides {
  categories: Record<string, boolean>
  events: Record<string, boolean>
}

interface NotificationConfig {
  enabled: boolean
  channels: Record<string, ChannelConfig>
  event_categories: Record<string, boolean>
  event_toggles: Record<string, boolean>
  event_types_by_group: Record<string, EventTypeInfo[]>
  channel_overrides: Record<string, ChannelOverrides>
  ai_enabled: boolean
  ai_provider: string
  ai_api_keys: Record<string, string>  // Per-provider API keys
  ai_models: Record<string, string>    // Per-provider selected models
  ai_model: string                     // Current active model (for the selected provider)
  ai_language: string
  ai_ollama_url: string
  ai_openai_base_url: string
  ai_prompt_mode: string  // 'default' or 'custom'
  ai_custom_prompt: string  // User's custom prompt
  ai_allow_suggestions: string | boolean  // Enable AI suggestions (experimental)
  channel_ai_detail: Record<string, string>
  hostname: string
  webhook_secret: string
  webhook_allowed_ips: string
  pbs_host: string
  pve_host: string
  pbs_trusted_sources: string
}

interface ServiceStatus {
  enabled: boolean
  running: boolean
  channels: Record<string, boolean>
  queue_size: number
  last_sent: string | null
  total_sent_24h: number
}

interface HistoryEntry {
  id: number
  event_type: string
  channel: string
  title: string
  severity: string
  sent_at: string
  success: boolean
  error_message: string | null
}

// Validation helpers for webhook/URL fields. The server still does the
// authoritative validation (see notification_manager.validate_config). These
// are defense-in-depth + immediate UX feedback so users notice typos / pasted
// internal endpoints before they hit Save.
const DISCORD_WEBHOOK_RE = /^https:\/\/(discord(app)?\.com|ptb\.discord\.com|canary\.discord\.com)\/api\/webhooks\/\d+\/[\w-]+$/

function validateDiscordWebhook(url: string): { error?: string } {
  if (!url) return {}
  if (!DISCORD_WEBHOOK_RE.test(url.trim())) {
    return { error: "Must be a Discord webhook URL (https://discord.com/api/webhooks/<id>/<token>)" }
  }
  return {}
}

function validateGotifyUrl(url: string): { error?: string; warning?: string } {
  if (!url) return {}
  let parsed: URL
  try {
    parsed = new URL(url.trim())
  } catch {
    return { error: "Not a valid URL" }
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { error: `Unsupported scheme "${parsed.protocol}" — only http(s) is allowed` }
  }
  // Block the obvious SSRF target: the local PVE API. RFC1918 ranges remain
  // allowed since self-hosted Gotify on a LAN is a normal deployment.
  const host = parsed.hostname.toLowerCase()
  const port = parsed.port
  if ((host === "localhost" || host === "127.0.0.1" || host === "::1") && (port === "8006" || port === "8007")) {
    return { error: "Cannot point at the local PVE API (localhost:8006/8007)" }
  }
  if (host === "169.254.169.254") {
    return { error: "Link-local metadata IP is not a valid Gotify endpoint" }
  }
  return {}
}

const EVENT_CATEGORIES = [
  { key: "vm_ct", label: "VM / CT", desc: "Start, stop, crash, migration" },
  { key: "backup", label: "Backups", desc: "Backup start, complete, fail" },
  { key: "resources", label: "Resources", desc: "CPU, memory, temperature" },
  { key: "storage", label: "Storage", desc: "Disk space, I/O, SMART" },
  { key: "network", label: "Network", desc: "Connectivity, bond, latency" },
  { key: "security", label: "Security", desc: "Auth failures, Fail2Ban, firewall" },
  { key: "cluster", label: "Cluster", desc: "Quorum, split-brain, HA fencing" },
  { key: "services", label: "Services", desc: "System services, shutdown, reboot" },
  { key: "health", label: "Health Monitor", desc: "Health checks, degradation, recovery" },
  { key: "updates", label: "Updates", desc: "System and PVE updates" },
  { key: "other", label: "Other", desc: "Uncategorized notifications" },
]

const CHANNEL_TYPES = ["telegram", "gotify", "discord", "email", "apprise"] as const

const AI_PROVIDERS = [
  { 
    value: "groq", 
    label: "Groq",
    description: "Very fast, generous free tier (30 req/min). Ideal to start.",
    keyUrl: "https://console.groq.com/keys",
    icon: "/icons/Groq Logo_White 25.svg",
    iconLight: "/icons/Groq Logo_Black 25.svg"
  },
  { 
    value: "openai", 
    label: "OpenAI",
    description: "Industry standard. Very accurate and widely used.",
    keyUrl: "https://platform.openai.com/api-keys",
    icon: "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/openai.webp",
    iconLight: "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/openai-light.webp"
  },
  { 
    value: "anthropic", 
    label: "Anthropic (Claude)",
    description: "Excellent for writing and translation. Fast and economical.",
    keyUrl: "https://console.anthropic.com/settings/keys",
    icon: "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/claude-light.webp",
    iconLight: "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/claude-dark.webp"
  },
  { 
    value: "gemini", 
    label: "Google Gemini",
    description: "Free tier available, great quality/price ratio.",
    keyUrl: "https://aistudio.google.com/app/apikey",
    icon: "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/google-gemini.webp",
    iconLight: "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/google-gemini.webp"
  },
  { 
    value: "ollama", 
    label: "Ollama (Local)",
    description: "Uses models available on your Ollama server. 100% local, no costs, total privacy.",
    keyUrl: "",
    icon: "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/ollama.webp",
    iconLight: "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/ollama-light.webp"
  },
  { 
    value: "openrouter", 
    label: "OpenRouter",
    description: "Aggregator with access to 100+ models using a single API key. Maximum flexibility.",
    keyUrl: "https://openrouter.ai/keys",
    icon: "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/openrouter-light.webp",
    iconLight: "https://cdn.jsdelivr.net/gh/selfhst/icons@main/webp/openrouter-dark.webp"
  },
]

const AI_LANGUAGES = [
  { value: "en", label: "English" },
  { value: "es", label: "Espanol" },
  { value: "fr", label: "Francais" },
  { value: "de", label: "Deutsch" },
  { value: "pt", label: "Portugues" },
  { value: "it", label: "Italiano" },
  { value: "ru", label: "Russkiy" },
  { value: "sv", label: "Svenska" },
  { value: "no", label: "Norsk" },
  { value: "ja", label: "Nihongo" },
  { value: "zh", label: "Zhongwen" },
  { value: "nl", label: "Nederlands" },
]

const AI_DETAIL_LEVELS = [
  { value: "brief", label: "Brief", desc: "2-3 lines, essential only" },
  { value: "standard", label: "Standard", desc: "Concise with basic context" },
  { value: "detailed", label: "Detailed", desc: "Complete technical details" },
]

// Example custom prompt for users to adapt
const EXAMPLE_CUSTOM_PROMPT = `You are a notification formatter for ProxMenux Monitor.

Your task is to translate and format server notifications.

RULES:
1. Translate to the user's preferred language
2. Use plain text only (no markdown, no bold, no italic)
3. Be concise and factual
4. Do not add recommendations or suggestions
5. Present only the facts from the input
6. Keep hostname prefix in titles (e.g., "pve01: ")

OUTPUT FORMAT:
[TITLE]
your translated title here
[BODY]
your translated message here

Detail levels:
- brief: 2-3 lines, essential only
- standard: short paragraph with key details
- detailed: full technical breakdown`

const DEFAULT_CONFIG: NotificationConfig = {
  enabled: false,
  channels: {
    telegram: { enabled: false },
    gotify: { enabled: false },
    discord: { enabled: false },
    email: { enabled: false },
    apprise: { enabled: false },
  },
  event_categories: {
    vm_ct: true, backup: true, resources: true, storage: true,
    network: true, security: true, cluster: true, services: true,
    health: true, updates: true, other: true,
  },
  event_toggles: {},
  event_types_by_group: {},
  channel_overrides: {
    telegram: { categories: {}, events: {} },
    gotify: { categories: {}, events: {} },
    discord: { categories: {}, events: {} },
    email: { categories: {}, events: {} },
    apprise: { categories: {}, events: {} },
  },
  ai_enabled: false,
  ai_provider: "groq",
  ai_api_keys: {
    groq: "",
    gemini: "",
    anthropic: "",
    openai: "",
    openrouter: "",
  },
  ai_models: {
    groq: "",
    ollama: "",
    gemini: "",
    anthropic: "",
    openai: "",
    openrouter: "",
  },
  ai_model: "",
  ai_language: "en",
  ai_ollama_url: "http://localhost:11434",
  ai_openai_base_url: "",
  ai_prompt_mode: "default",
  ai_custom_prompt: "",
  ai_allow_suggestions: "false",
  channel_ai_detail: {
    telegram: "brief",
    gotify: "brief",
    discord: "brief",
    email: "detailed",
    apprise: "brief",
  },
  hostname: "",
  webhook_secret: "",
  webhook_allowed_ips: "",
  pbs_host: "",
  pve_host: "",
  pbs_trusted_sources: "",
}

export function NotificationSettings() {
  const { resolvedTheme } = useTheme()
  const [config, setConfig] = useState<NotificationConfig>(DEFAULT_CONFIG)
  const [status, setStatus] = useState<ServiceStatus | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  // Save errors used to be silently swallowed — the user thought their
  // tokens / API keys were persisted when in fact the POST had failed.
  // Surface the failure as a banner so the user can retry. Audit residual
  // #notification-settings-handleSave-silent-fail.
  const [saveError, setSaveError] = useState<string | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ channel: string; success: boolean; message: string } | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({})
  const [editMode, setEditMode] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())
  const [originalConfig, setOriginalConfig] = useState<NotificationConfig>(DEFAULT_CONFIG)
  const [showProviderInfo, setShowProviderInfo] = useState(false)
  const [showTelegramHelp, setShowTelegramHelp] = useState(false)
  const [testingAI, setTestingAI] = useState(false)
  const [aiTestResult, setAiTestResult] = useState<{ success: boolean; message: string; model?: string } | null>(null)
  const [providerModels, setProviderModels] = useState<string[]>([])
  const [loadingProviderModels, setLoadingProviderModels] = useState(false)
  const [showCustomPromptInfo, setShowCustomPromptInfo] = useState(false)
  const [editingCustomPrompt, setEditingCustomPrompt] = useState(false)
  const [customPromptDraft, setCustomPromptDraft] = useState("")
  const [webhookSetup, setWebhookSetup] = useState<{
    status: "idle" | "running" | "success" | "failed"
    fallback_commands: string[]
    error: string
  }>({ status: "idle", fallback_commands: [], error: "" })
  const [systemHostname, setSystemHostname] = useState<string>("")
  // Mirrors the dedicated toggle from Settings → LXC Update Detection.
  // When false, the per-event toggle for `lxc_updates_available` is hidden
  // from every channel's category list (its DB preference is preserved).
  // Updated on mount via fetch and on the fly via a CustomEvent dispatched
  // by <LxcUpdateDetection /> when the user flips the switch.
  const [lxcDetectionEnabled, setLxcDetectionEnabled] = useState<boolean>(true)

  // Load system hostname for display name placeholder
  const loadSystemHostname = useCallback(async () => {
    try {
      const data = await fetchApi<{ hostname?: string }>("/api/system")
      if (data.hostname) {
        setSystemHostname(data.hostname)
      }
    } catch {
      // Ignore - will show generic placeholder
    }
  }, [])

  const loadConfig = useCallback(async () => {
    try {
      const data = await fetchApi<{ success: boolean; config: NotificationConfig }>("/api/notifications/settings")
      if (data.success && data.config) {
        // Ensure ai_api_keys, ai_models, and prompt settings exist (fallback for older configs)
        const configWithDefaults = {
          ...data.config,
          ai_api_keys: data.config.ai_api_keys || {
            groq: "",
            ollama: "",
            gemini: "",
            anthropic: "",
            openai: "",
            openrouter: "",
          },
          ai_models: data.config.ai_models || {
            groq: "",
            ollama: "",
            gemini: "",
            anthropic: "",
            openai: "",
            openrouter: "",
          },
          ai_prompt_mode: data.config.ai_prompt_mode || "default",
          ai_custom_prompt: data.config.ai_custom_prompt || "",
          ai_allow_suggestions: data.config.ai_allow_suggestions || "false",
        }
        // If ai_model exists but ai_models doesn't have it, save it
        if (configWithDefaults.ai_model && !configWithDefaults.ai_models[configWithDefaults.ai_provider]) {
          configWithDefaults.ai_models[configWithDefaults.ai_provider] = configWithDefaults.ai_model
        }
        setConfig(configWithDefaults)
        setOriginalConfig(configWithDefaults)
      }
    } catch (err) {
      console.error("Failed to load notification settings:", err)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadStatus = useCallback(async () => {
    try {
      const data = await fetchApi<{ success: boolean } & ServiceStatus>("/api/notifications/status")
      if (data.success) {
        setStatus(data)
      }
    } catch {
      // Service may not be running yet
    }
  }, [])

  const loadHistory = useCallback(async () => {
    try {
      const data = await fetchApi<{ success: boolean; history: HistoryEntry[]; total: number }>("/api/notifications/history?limit=20")
      if (data.success) {
        setHistory(data.history || [])
      }
    } catch {
      // Ignore
    }
  }, [])

  useEffect(() => {
    loadConfig()
    loadStatus()
    loadSystemHostname()
  }, [loadConfig, loadStatus, loadSystemHostname])

  // Track the LXC update-detection toggle so we can conditionally hide
  // the `lxc_updates_available` per-event toggle inside every channel's
  // category list. Fetched once on mount; live updates ride on a custom
  // event dispatched by <LxcUpdateDetection /> whenever the user flips
  // the switch upstream.
  useEffect(() => {
    let cancelled = false
    fetchApi<{ success: boolean; enabled?: boolean }>("/api/lxc-updates/detection")
      .then(data => {
        if (cancelled) return
        if (data.success && typeof data.enabled === "boolean") {
          setLxcDetectionEnabled(data.enabled)
        }
      })
      .catch(() => {
        // Default-true on fetch failure — matches the backend default and
        // avoids hiding a notification toggle the user might rely on if
        // the settings endpoint is transiently unreachable.
      })

    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail && typeof detail.enabled === "boolean") {
        setLxcDetectionEnabled(detail.enabled)
      }
    }
    if (typeof window !== "undefined") {
      window.addEventListener("proxmenux:lxc-detection-changed", handler)
    }
    return () => {
      cancelled = true
      if (typeof window !== "undefined") {
        window.removeEventListener("proxmenux:lxc-detection-changed", handler)
      }
    }
  }, [])

  useEffect(() => {
    if (showHistory) loadHistory()
  }, [showHistory, loadHistory])

  // Auto-expand AI section when AI is enabled
  useEffect(() => {
    if (config.ai_enabled) {
      setShowAdvanced(true)
    }
  }, [config.ai_enabled])

  const updateConfig = (updater: (prev: NotificationConfig) => NotificationConfig) => {
    setConfig(prev => {
      const next = updater(prev)
      setHasChanges(true)
      return next
    })
  }

  const updateChannel = (channel: string, field: string, value: string | boolean) => {
    updateConfig(prev => ({
      ...prev,
      channels: {
        ...prev.channels,
        [channel]: { ...prev.channels[channel], [field]: value },
      },
    }))
  }

  const formatHHMM = (raw: string | undefined, fallback: string): string => {
    const v = (raw || fallback).match(/^(\d{1,2}):(\d{2})$/)
    if (!v) return fallback
    const hh = String(Math.min(23, Math.max(0, parseInt(v[1], 10)))).padStart(2, "0")
    const mm = String(Math.min(59, Math.max(0, parseInt(v[2], 10)))).padStart(2, "0")
    return `${hh}:${mm}`
  }

  const inQuietWindow = (start: string, end: string): boolean => {
    if (start === end) return false
    const now = new Date()
    const cur = now.getHours() * 60 + now.getMinutes()
    const [sh, sm] = start.split(":").map((x) => parseInt(x, 10))
    const [eh, em] = end.split(":").map((x) => parseInt(x, 10))
    const s = sh * 60 + sm
    const e = eh * 60 + em
    return s < e ? cur >= s && cur < e : cur >= s || cur < e
  }

  const renderQuietHours = (chName: string) => {
    const ch = config.channels[chName as keyof typeof config.channels] as ChannelConfig | undefined
    const enabled = !!ch?.quiet_enabled
    const start = formatHHMM(ch?.quiet_start, "22:00")
    const end = formatHHMM(ch?.quiet_end, "06:00")
    const sameTime = start === end
    const live = enabled && !sameTime && inQuietWindow(start, end)
    return (
      <div className="space-y-2 pt-2 border-t border-border/50">
        <div className="flex items-center justify-between py-1">
          <div>
            <Label className="text-xs sm:text-sm text-foreground/80 flex items-center gap-2">
              <Moon className="h-4 w-4 text-blue-400" />
              Quiet hours
            </Label>
            <p className="text-xs text-muted-foreground mt-1">
              During this window only CRITICAL events reach this channel.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            disabled={!editMode}
            className={`relative w-9 h-[18px] shrink-0 rounded-full transition-colors ${
              !editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
            } ${enabled ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"}`}
            onClick={() => { if (editMode) updateChannel(chName, "quiet_enabled", !enabled) }}
          >
            <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
              enabled ? "translate-x-[18px]" : "translate-x-0"
            }`} />
          </button>
        </div>
        {enabled && (
          <>
            {/* Inline label + intrinsic-width inputs. The previous
                `grid-cols-2 + full-width inputs` rendered weirdly on
                iOS Safari (the native time picker centered "22:00"
                inside a 200-px box with huge empty margins). flex +
                w-24/w-28 keeps the input tight to the HH:MM text on
                every viewport and the touch target stays comfortable. */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-1">
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground">From</Label>
                <Input
                  type="time"
                  value={start}
                  onChange={(e) => updateChannel(chName, "quiet_start", e.target.value)}
                  disabled={!editMode}
                  className="h-9 w-28 text-sm font-mono"
                />
              </div>
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground">Until</Label>
                <Input
                  type="time"
                  value={end}
                  onChange={(e) => updateChannel(chName, "quiet_end", e.target.value)}
                  disabled={!editMode}
                  className="h-9 w-28 text-sm font-mono"
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              {sameTime
                ? "Set a different start and end time to activate."
                : live
                  ? `Active right now — only CRITICAL events pass until ${end}.`
                  : `Inactive right now — will start at ${start}.`}
            </p>
          </>
        )}
      </div>
    )
  }

  const renderDailyDigest = (chName: string) => {
    const ch = config.channels[chName as keyof typeof config.channels] as ChannelConfig | undefined
    const enabled = !!ch?.digest_enabled
    const time = formatHHMM(ch?.digest_time, "09:00")
    let nextLabel = ""
    if (enabled) {
      const now = new Date()
      const cur = now.getHours() * 60 + now.getMinutes()
      const [hh, mm] = time.split(":").map((x) => parseInt(x, 10))
      const target = hh * 60 + mm
      const minsAway = target > cur ? target - cur : 24 * 60 - cur + target
      const h = Math.floor(minsAway / 60)
      const m = minsAway % 60
      nextLabel = `Next digest in ${h}h ${m}m (at ${time}).`
    }
    return (
      <div className="space-y-2 pt-2 border-t border-border/50">
        <div className="flex items-center justify-between py-1">
          <div>
            <Label className="text-xs sm:text-sm text-foreground/80 flex items-center gap-2">
              <Newspaper className="h-4 w-4 text-violet-400" />
              Daily digest of INFO events
            </Label>
            <p className="text-xs text-muted-foreground mt-1">
              All INFO events (backups OK, updates available, etc.) accumulate during the day and arrive once at this time as a single summary. CRITICAL and WARNING are never delayed.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            disabled={!editMode}
            className={`relative w-9 h-[18px] shrink-0 rounded-full transition-colors ${
              !editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
            } ${enabled ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"}`}
            onClick={() => { if (editMode) updateChannel(chName, "digest_enabled", !enabled) }}
          >
            <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
              enabled ? "translate-x-[18px]" : "translate-x-0"
            }`} />
          </button>
        </div>
        {enabled && (
          <>
            <div className="flex items-center gap-2 pt-1">
              <Label className="text-xs text-muted-foreground">Send at</Label>
              <Input
                type="time"
                value={time}
                onChange={(e) => updateChannel(chName, "digest_time", e.target.value)}
                disabled={!editMode}
                className="h-9 w-28 text-sm font-mono"
              />
            </div>
            <p className="text-xs text-muted-foreground">{nextLabel}</p>
          </>
        )}
      </div>
    )
  }

  /** Reusable 10+1 category block rendered inside each channel tab. */
  const renderChannelCategories = (chName: string) => {
    const overrides = config.channel_overrides?.[chName] || { categories: {}, events: {} }
    const evtByGroup = config.event_types_by_group || {}

    return (
      <div className="space-y-1.5 border-t border-border/30 pt-3 mt-3">
        <div className="flex items-center gap-2 mb-2">
          <Bell className="h-3.5 w-3.5 text-muted-foreground" />
          <Label className="text-[11px] text-muted-foreground">Notification Categories</Label>
        </div>
        <div className="space-y-2">
          {EVENT_CATEGORIES.filter(cat => cat.key !== "other").map(cat => {
            const isEnabled = overrides.categories[cat.key] ?? true
            const isExpanded = expandedCategories.has(`${chName}.${cat.key}`)
            // Hide the LXC update toggle when the user has disabled the
            // dedicated detection setting upstream. The backend still
            // returns the event type in the catalog (so its stored
            // preference survives), but we filter it out of every
            // channel's UI list so the operator never sees a notification
            // toggle whose underlying scan is paused.
            const rawEventsForGroup = evtByGroup[cat.key] || []
            const eventsForGroup = lxcDetectionEnabled
              ? rawEventsForGroup
              : rawEventsForGroup.filter(e => e.type !== "lxc_updates_available")
            const enabledCount = eventsForGroup.filter(
              e => (overrides.events?.[e.type] ?? e.default_enabled)
            ).length

            return (
              <div key={cat.key} className="rounded-lg border border-border transition-all duration-150 hover:border-muted-foreground/60 hover:bg-muted">
                {/* Category row -- entire block is clickable to expand/collapse */}
                <div
                  className="flex items-center gap-2.5 py-2.5 px-3 cursor-pointer"
                  onClick={() => {
                    if (!isEnabled) return
                    setExpandedCategories(prev => {
                      const next = new Set(prev)
                      const key = `${chName}.${cat.key}`
                      if (next.has(key)) next.delete(key)
                      else next.add(key)
                      return next
                    })
                  }}
                >
                  {/* Expand arrow */}
                  <ChevronRight className={`h-3.5 w-3.5 shrink-0 transition-transform ${
                    isExpanded ? "rotate-90" : ""
                  } ${!isEnabled ? "opacity-20" : "text-muted-foreground"}`} />

                  {/* Label */}
                  <div className="flex-1 min-w-0">
                    <span className={`text-xs sm:text-sm font-medium block ${
                      isEnabled ? "text-green-500" : "text-foreground"
                    }`}>{cat.label}</span>
                  </div>

                  {/* Count badge */}
                  {isEnabled && eventsForGroup.length > 0 && (
                    <span className="text-[10px] text-muted-foreground tabular-nums">
                      {enabledCount}/{eventsForGroup.length}
                    </span>
                  )}

                  {/* Toggle -- same style as channel enable toggle */}
                  <button
                    type="button"
                    role="switch"
                    aria-checked={isEnabled}
                    disabled={!editMode}
                    className={`relative w-9 h-[18px] shrink-0 rounded-full transition-colors ${
                      !editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
                    } ${isEnabled ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"}`}
                    onClick={(e) => {
                      e.stopPropagation()
                      if (!editMode) return
                      updateConfig(p => {
                        const ch = { ...(p.channel_overrides?.[chName] || { categories: {}, events: {} }) }
                        const newEnabled = !isEnabled
                        const newEvents = { ...(ch.events || {}) }
                        if (newEnabled && eventsForGroup.length > 0) {
                          for (const evt of eventsForGroup) {
                            newEvents[evt.type] = true
                          }
                        }
                        return {
                          ...p,
                          channel_overrides: {
                            ...p.channel_overrides,
                            [chName]: { categories: { ...ch.categories, [cat.key]: newEnabled }, events: newEvents },
                          },
                        }
                      })
                    }}
                  >
                    <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                      isEnabled ? "translate-x-[18px]" : "translate-x-0"
                    }`} />
                  </button>
                </div>

                {/* Sub-event toggles */}
                {isEnabled && isExpanded && eventsForGroup.length > 0 && (
                  <div className="border-t border-border px-3 py-1.5 space-y-0.5">
                    {eventsForGroup.map(evt => {
                      const evtEnabled = overrides.events?.[evt.type] ?? evt.default_enabled
                      return (
                        <div key={evt.type} className="flex items-center justify-between py-1.5 px-2 rounded-md hover:bg-muted transition-colors">
                          <span className={`text-[11px] sm:text-xs ${evtEnabled ? "text-foreground" : "text-muted-foreground"}`}>
                            {evt.title}
                          </span>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={evtEnabled}
                            disabled={!editMode}
                            className={`relative w-9 h-[18px] shrink-0 rounded-full transition-colors ${
                              !editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
                            } ${evtEnabled ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"}`}
                            onClick={() => {
                              if (!editMode) return
                              updateConfig(p => {
                                const ch = { ...(p.channel_overrides?.[chName] || { categories: {}, events: {} }) }
                                return {
                                  ...p,
                                  channel_overrides: {
                                    ...p.channel_overrides,
                                    [chName]: { ...ch, events: { ...(ch.events || {}), [evt.type]: !evtEnabled } },
                                  },
                                }
                              })
                            }}
                          >
                            <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                              evtEnabled ? "translate-x-[18px]" : "translate-x-0"
                            }`} />
                          </button>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  /** Flatten the nested NotificationConfig into the flat key-value map the backend expects. */
  const flattenConfig = (cfg: NotificationConfig): Record<string, string> => {
  const flat: Record<string, string> = {
    enabled: String(cfg.enabled),
    ai_enabled: String(cfg.ai_enabled),
    ai_provider: cfg.ai_provider,
    ai_model: cfg.ai_model,
    ai_language: cfg.ai_language,
    ai_ollama_url: cfg.ai_ollama_url,
    ai_openai_base_url: cfg.ai_openai_base_url,
  ai_prompt_mode: cfg.ai_prompt_mode || "default",
  ai_custom_prompt: cfg.ai_custom_prompt || "",
  ai_allow_suggestions: String(cfg.ai_allow_suggestions === "true" || cfg.ai_allow_suggestions === true),
    hostname: cfg.hostname,
    webhook_secret: cfg.webhook_secret,
    webhook_allowed_ips: cfg.webhook_allowed_ips,
    pbs_host: cfg.pbs_host,
    pve_host: cfg.pve_host,
    pbs_trusted_sources: cfg.pbs_trusted_sources,
  }
    // Flatten per-provider API keys
    if (cfg.ai_api_keys) {
      for (const [provider, key] of Object.entries(cfg.ai_api_keys)) {
        if (key) {
          flat[`ai_api_key_${provider}`] = key
        }
      }
    }
    // Flatten per-provider selected models
    if (cfg.ai_models) {
      for (const [provider, model] of Object.entries(cfg.ai_models)) {
        if (model) {
          flat[`ai_model_${provider}`] = model
        }
      }
    }
    // Flatten channels: { telegram: { enabled, bot_token, chat_id } } -> telegram.enabled, telegram.bot_token, ...
    for (const [chName, chCfg] of Object.entries(cfg.channels)) {
      for (const [field, value] of Object.entries(chCfg)) {
        flat[`${chName}.${field}`] = String(value ?? "")
      }
    }
    // Per-channel category & event toggles: telegram.events.vm_ct, telegram.event.vm_start, etc.
    // Each channel independently owns its notification preferences.
    if (cfg.channel_overrides) {
      for (const [chName, overrides] of Object.entries(cfg.channel_overrides)) {
        if (overrides.categories) {
          for (const [cat, enabled] of Object.entries(overrides.categories)) {
            flat[`${chName}.events.${cat}`] = String(enabled)
          }
        }
        if (overrides.events) {
          for (const [evt, enabled] of Object.entries(overrides.events)) {
            flat[`${chName}.event.${evt}`] = String(enabled)
          }
        }
      }
    }
    // Per-channel AI detail level
    if (cfg.channel_ai_detail) {
      for (const [chName, level] of Object.entries(cfg.channel_ai_detail)) {
        flat[`${chName}.ai_detail_level`] = level
      }
    }
    return flat
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      // If notifications are being disabled, clean up PVE webhook first
      const wasEnabled = originalConfig.enabled
      const isNowDisabled = !config.enabled

      if (wasEnabled && isNowDisabled) {
        try {
          await fetchApi("/api/notifications/proxmox/cleanup-webhook", { method: "POST" })
        } catch {
          // Non-fatal: webhook cleanup failed but we still save settings
        }
      }

      const payload = flattenConfig(config)
      await fetchApi("/api/notifications/settings", {
        method: "POST",
        body: JSON.stringify(payload),
      })
      setOriginalConfig(config)
      setHasChanges(false)
      setEditMode(false)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      loadStatus()
    } catch (err) {
      console.error("Failed to save notification settings:", err)
      const msg = err instanceof Error ? err.message : "Failed to save notification settings"
      setSaveError(msg)
    } finally {
      setSaving(false)
    }
  }

  const handleCancel = () => {
    setConfig(originalConfig)
    setHasChanges(false)
    setEditMode(false)
  }

  const handleTest = async (channel: string) => {
    setTesting(channel)
    setTestResult(null)
    try {
      // Auto-save current config before testing so backend has latest channel data
      const payload = flattenConfig(config)
      await fetchApi("/api/notifications/settings", {
        method: "POST",
        body: JSON.stringify(payload),
      })
      setOriginalConfig(config)
      setHasChanges(false)
      
      const data = await fetchApi<{
        success: boolean
        message?: string
        error?: string
        results?: Record<string, { success: boolean; error?: string | null }>
      }>("/api/notifications/test", {
        method: "POST",
        body: JSON.stringify({ channel }),
      })
      
      // Extract message from the results object if present
      let message = data.message || ""
      if (!message && data.results) {
        const channelResult = data.results[channel]
        if (channelResult) {
          message = channelResult.success
            ? "Test notification sent successfully"
            : channelResult.error || "Test failed"
        }
      }
      if (!message && data.error) {
        message = data.error
      }
      if (!message) {
        message = data.success ? "Test notification sent successfully" : "Test failed"
      }
      
      setTestResult({ channel, success: data.success, message })
    } catch (err) {
      setTestResult({ channel, success: false, message: String(err) })
    } finally {
      setTesting(null)
      setTimeout(() => setTestResult(null), 8000)
    }
  }

  const fetchProviderModels = useCallback(async () => {
    const provider = config.ai_provider
    const apiKey = config.ai_api_keys?.[provider] || ""
    
    // For Ollama, we need the URL; for others, we need the API key
    if (provider === 'ollama') {
      if (!config.ai_ollama_url) return
    } else if (provider !== 'anthropic') {
      // Anthropic doesn't have a models list endpoint, skip validation
      if (!apiKey) return
    }
    
    setLoadingProviderModels(true)
    try {
      const data = await fetchApi<{ success: boolean; models: string[]; recommended: string; message: string }>("/api/notifications/provider-models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          provider,
          api_key: apiKey,
          ollama_url: config.ai_ollama_url,
          openai_base_url: config.ai_openai_base_url,
        }),
      })
      if (data.success && data.models && data.models.length > 0) {
        setProviderModels(data.models)
        // Auto-select recommended model if current selection is empty or not in the list
        updateConfig(prev => {
          if (!prev.ai_model || !data.models.includes(prev.ai_model)) {
            const modelToSelect = data.recommended || data.models[0]
            return { 
              ...prev, 
              ai_model: modelToSelect,
              ai_models: { ...prev.ai_models, [provider]: modelToSelect }
            }
          }
          return prev
        })
      } else {
        setProviderModels([])
      }
    } catch {
      setProviderModels([])
    } finally {
      setLoadingProviderModels(false)
    }
  }, [config.ai_provider, config.ai_api_keys, config.ai_ollama_url, config.ai_openai_base_url])
  
  // Note: Users use the "Load" button explicitly to fetch models.
  
  const handleTestAI = async () => {
    setTestingAI(true)
    setAiTestResult(null)
    try {
      // Get the API key for the current provider
      const currentApiKey = config.ai_api_keys?.[config.ai_provider] || ""
      // Use the model selected by the user (loaded from provider)
      const modelToUse = config.ai_model
      
      if (!modelToUse) {
        setAiTestResult({ success: false, message: "No model selected. Click 'Load' to fetch available models first." })
        return
      }
      
      const data = await fetchApi<{ success: boolean; message: string; model: string }>("/api/notifications/test-ai", {
        method: "POST",
        body: JSON.stringify({
          provider: config.ai_provider,
          api_key: currentApiKey,
          model: modelToUse,
          ollama_url: config.ai_ollama_url,
          openai_base_url: config.ai_openai_base_url,
        }),
      })
      setAiTestResult(data)
    } catch (err) {
      setAiTestResult({ success: false, message: String(err) })
    } finally {
      setTestingAI(false)
      setTimeout(() => setAiTestResult(null), 8000)
    }
  }

  const handleClearHistory = async () => {
    try {
      await fetchApi("/api/notifications/history", { method: "DELETE" })
      setHistory([])
    } catch {
      // Ignore
    }
  }

  const toggleSecret = (key: string) => {
    setShowSecrets(prev => ({ ...prev, [key]: !prev[key] }))
  }

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Bell className="h-5 w-5 text-blue-500" />
            <CardTitle>Notifications</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full" />
          </div>
        </CardContent>
      </Card>
    )
  }

  const activeChannels = Object.entries(config.channels).filter(([, ch]) => ch.enabled).length

  const handleEnable = async () => {
    setSaving(true)
    setWebhookSetup({ status: "running", fallback_commands: [], error: "" })
    try {
      // 1) Save enabled=true
      const newConfig = { ...config, enabled: true }
      await fetchApi("/api/notifications/settings", {
        method: "POST",
        body: JSON.stringify(newConfig),
      })
      setConfig(newConfig)
      setOriginalConfig(newConfig)

      // 2) Auto-configure PVE webhook
      try {
        const setup = await fetchApi<{
          configured: boolean
          secret?: string
          fallback_commands?: string[]
          error?: string
        }>("/api/notifications/proxmox/setup-webhook", { method: "POST" })

        if (setup.configured) {
          setWebhookSetup({ status: "success", fallback_commands: [], error: "" })
          // Update secret in local config if one was generated
          if (setup.secret) {
            const updated = { ...newConfig, webhook_secret: setup.secret }
            setConfig(updated)
            setOriginalConfig(updated)
          }
        } else {
          setWebhookSetup({
            status: "failed",
            fallback_commands: setup.fallback_commands || [],
            error: setup.error || "Unknown error",
          })
        }
      } catch {
        setWebhookSetup({
          status: "failed",
          fallback_commands: [],
          error: "Could not reach setup endpoint",
        })
      }

      setEditMode(true)
      loadStatus()
    } catch (err) {
      console.error("Failed to enable notifications:", err)
      setWebhookSetup({ status: "idle", fallback_commands: [], error: "" })
    } finally {
      setSaving(false)
    }
  }

  // ── Disabled state: show activation card ──
  if (!config.enabled && !editMode) {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <BellOff className="h-5 w-5 text-muted-foreground" />
            <CardTitle>Notifications</CardTitle>
            <Badge variant="outline" className="text-[10px] border-muted-foreground/30 text-muted-foreground">
              Disabled
            </Badge>
          </div>
          <CardDescription>
            Get real-time alerts about your Proxmox environment via Telegram, Discord, Gotify, or Email.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex flex-col gap-3 p-4 bg-muted/50 rounded-lg border border-border">
              <div className="flex items-start gap-3">
                <Bell className="h-5 w-5 text-blue-500 mt-0.5 shrink-0" />
                <div className="space-y-1">
                  <p className="text-sm font-medium">Enable notification service</p>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    Monitor system health, VM/CT events, backups, security alerts, and cluster status.
                    PVE webhook integration is configured automatically.
                  </p>
                </div>
              </div>
              <div className="flex flex-col sm:flex-row items-start gap-2">
                <button
                  className="h-8 px-4 text-sm rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors w-full sm:w-auto disabled:opacity-50 flex items-center justify-center gap-2"
                  onClick={handleEnable}
                  disabled={saving}
                >
                  {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bell className="h-3.5 w-3.5" />}
                  {saving ? "Configuring..." : "Enable Notifications"}
                </button>
              </div>

              {/* Webhook setup result */}
              {webhookSetup.status === "success" && (
                <div className="flex items-start gap-2 p-2 rounded-md bg-green-500/10 border border-green-500/20">
                  <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0 mt-0.5" />
                  <p className="text-[11px] text-green-400 leading-relaxed">
                    PVE webhook configured automatically. Proxmox will send notifications to ProxMenux.
                  </p>
                </div>
              )}
              {webhookSetup.status === "failed" && (
                <div className="space-y-2">
                  <div className="flex items-start gap-2 p-2 rounded-md bg-amber-500/10 border border-amber-500/20">
                    <AlertTriangle className="h-3.5 w-3.5 text-amber-400 shrink-0 mt-0.5" />
                    <div className="space-y-1">
                      <p className="text-[11px] text-amber-400 leading-relaxed">
                        Automatic PVE configuration failed: {webhookSetup.error}
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        Notifications are enabled. Run the commands below on the PVE host to complete webhook setup.
                      </p>
                    </div>
                  </div>
                  {webhookSetup.fallback_commands.length > 0 && (
                    <pre className="text-[11px] bg-background p-2 rounded border border-border overflow-x-auto font-mono">
{webhookSetup.fallback_commands.join('\n')}
                    </pre>
                  )}
                </div>
              )}
            </div>


          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <>
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bell className="h-5 w-5 text-blue-500" />
            <CardTitle>Notifications</CardTitle>
            {config.enabled && (
              <Badge variant="outline" className="text-[10px] border-green-500/30 text-green-500">
                Active
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            {saved && (
              <span className="flex items-center gap-1 text-xs text-green-500">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Saved
              </span>
            )}
            {saveError && (
              <span
                className="flex items-center gap-1 text-xs text-red-500 max-w-[40ch] truncate"
                title={saveError}
              >
                Save failed: {saveError}
              </span>
            )}
            {editMode ? (
              <>
                <button
                  className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors text-muted-foreground"
                  onClick={handleCancel}
                  disabled={saving}
                >
                  Cancel
                </button>
                <button
                  className="h-7 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50 flex items-center gap-1.5"
                  onClick={handleSave}
                  disabled={saving || !hasChanges}
                >
                  {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                  Save
                </button>
              </>
            ) : (
              <button
                className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors flex items-center gap-1.5"
                onClick={() => setEditMode(true)}
              >
                <Settings2 className="h-3 w-3" />
                Edit
              </button>
            )}
          </div>
        </div>
        <CardDescription>
          Configure notification channels and event filters. Receive alerts via Telegram, Gotify, Discord, or Email.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* ── Service Status ── */}
        {status && (
          <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/50 border border-border">
            <div className={`h-2.5 w-2.5 rounded-full ${status.running ? "bg-green-500" : "bg-red-500"}`} />
            <div className="flex-1 min-w-0">
              <span className="text-xs font-medium">
                {status.running ? "Service running" : "Service stopped"}
              </span>
              {status.total_sent_24h > 0 && (
                <span className="text-xs text-muted-foreground ml-2">
                  {status.total_sent_24h} sent in last 24h
                </span>
              )}
            </div>
            {activeChannels > 0 && (
              <Badge variant="outline" className="text-[10px]">
                {activeChannels} channel{activeChannels > 1 ? "s" : ""}
              </Badge>
            )}
          </div>
        )}

        {/* ── Enable/Disable ── */}
        <div className="flex items-center justify-between py-2 px-1">
          <div className="flex items-center gap-2">
            {config.enabled ? (
              <Bell className="h-4 w-4 text-blue-500" />
            ) : (
              <BellOff className="h-4 w-4 text-muted-foreground" />
            )}
            <div>
              <span className="text-sm font-medium">Enable Notifications</span>
              <p className="text-[11px] text-muted-foreground">Activate the notification service</p>
            </div>
          </div>
          <button
            className={`relative w-10 h-5 rounded-full transition-colors ${
              config.enabled ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"
            } ${!editMode ? "opacity-60 cursor-not-allowed" : "cursor-pointer"}`}
            onClick={() => editMode && updateConfig(p => ({ ...p, enabled: !p.enabled }))}
            disabled={!editMode}
            role="switch"
            aria-checked={config.enabled}
          >
            <span
              className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                config.enabled ? "translate-x-5" : "translate-x-0"
              }`}
            />
          </button>
        </div>

        {config.enabled && (
          <>
            {/* ── Channel Configuration ── */}
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Zap className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Channels</span>
              </div>

              <div className="rounded-lg border border-border/50 bg-muted/20 p-3">
              <Tabs defaultValue="telegram" className="w-full">
                <TabsList className="w-full grid grid-cols-5 h-8">
                  <TabsTrigger value="telegram" className="text-xs data-[state=active]:text-blue-500">
                    Telegram
                  </TabsTrigger>
                  <TabsTrigger value="gotify" className="text-xs data-[state=active]:text-green-500">
                    Gotify
                  </TabsTrigger>
                  <TabsTrigger value="discord" className="text-xs data-[state=active]:text-indigo-500">
                    Discord
                  </TabsTrigger>
                  <TabsTrigger value="email" className="text-xs data-[state=active]:text-amber-500">
                    Email
                  </TabsTrigger>
                  <TabsTrigger value="apprise" className="text-xs data-[state=active]:text-cyan-500">
                    Apprise
                  </TabsTrigger>
                </TabsList>

                {/* Telegram */}
                <TabsContent value="telegram" className="space-y-3 pt-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Label className="text-xs font-medium">Enable Telegram</Label>
                      <button
                        onClick={() => setShowTelegramHelp(true)}
                        className="text-[10px] text-blue-500 hover:text-blue-400 hover:underline"
                      >
                        +setup guide
                      </button>
                    </div>
                    <button
                      className={`relative w-9 h-[18px] rounded-full transition-colors ${
                        config.channels.telegram?.enabled ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"
                      } ${!editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                      onClick={() => { if (editMode) updateChannel("telegram", "enabled", !config.channels.telegram?.enabled) }}
                      disabled={!editMode}
                      role="switch"
                      aria-checked={config.channels.telegram?.enabled || false}
                    >
                      <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                        config.channels.telegram?.enabled ? "translate-x-[18px]" : "translate-x-0"
                      }`} />
                    </button>
                  </div>
                  {config.channels.telegram?.enabled && (
                    <>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] text-muted-foreground">Bot Token</Label>
                        <div className="flex items-center gap-1.5">
                          <Input
                            type={showSecrets["tg_token"] ? "text" : "password"}
                            className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                            placeholder="7595377878:AAGE6Fb2cy... (with or without 'bot' prefix)"
                            value={config.channels.telegram?.bot_token || ""}
                            onChange={e => updateChannel("telegram", "bot_token", e.target.value)}
                            disabled={!editMode}
                          />
                          <button
                            className="h-7 w-7 flex items-center justify-center rounded-md border border-border hover:bg-muted transition-colors shrink-0"
                            onClick={() => toggleSecret("tg_token")}
                          >
                            {showSecrets["tg_token"] ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                          </button>
                        </div>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] text-muted-foreground">Chat ID</Label>
                        <Input
                          className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                          placeholder="-1001234567890"
                          value={config.channels.telegram?.chat_id || ""}
                          onChange={e => updateChannel("telegram", "chat_id", e.target.value)}
                          disabled={!editMode}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] text-muted-foreground">Topic ID <span className="text-muted-foreground/60">(optional)</span></Label>
                        <Input
                          className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                          placeholder="123456"
                          value={config.channels.telegram?.topic_id || ""}
                          onChange={e => updateChannel("telegram", "topic_id", e.target.value)}
                          disabled={!editMode}
                        />
                        <p className="text-[10px] text-muted-foreground">For supergroups with topics enabled. Leave empty for regular chats.</p>
                      </div>
                      {/* Message format */}
                      <div className="flex items-center justify-between py-1">
                        <div>
                          <Label className="text-xs font-medium">Rich messages</Label>
                          <p className="text-[10px] text-muted-foreground">Enrich notifications with contextual emojis and icons</p>
                        </div>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={config.channels.telegram?.rich_format || false}
                          disabled={!editMode}
                          className={`relative w-9 h-[18px] shrink-0 rounded-full transition-colors ${
                            !editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
                          } ${config.channels.telegram?.rich_format ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"}`}
                          onClick={() => { if (editMode) updateChannel("telegram", "rich_format", !config.channels.telegram?.rich_format) }}
                        >
                          <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                            config.channels.telegram?.rich_format ? "translate-x-[18px]" : "translate-x-0"
                          }`} />
                        </button>
                      </div>
                      {renderChannelCategories("telegram")}
                      {renderQuietHours("telegram")}
                      {renderDailyDigest("telegram")}
                      {/* Send Test — channel-colored button (#226). All five
                          channels follow the same `bg-<channel>-600 ... text-white`
                          pattern; the color matches the active-tab tint above. */}
                      <div className="flex items-center gap-2 pt-2 border-t border-border/50">
                        <button
                          className="h-7 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors flex items-center gap-1.5 disabled:opacity-50"
                          onClick={() => handleTest("telegram")}
                          disabled={testing === "telegram" || !config.channels.telegram?.bot_token}
                        >
                          {testing === "telegram" ? <Loader2 className="h-3 w-3 animate-spin" /> : <TestTube2 className="h-3 w-3" />}
                          Send Test
                        </button>
                      </div>
                    </>
                  )}
                </TabsContent>

                {/* Gotify */}
                <TabsContent value="gotify" className="space-y-3 pt-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs font-medium">Enable Gotify</Label>
                    <button
                      className={`relative w-9 h-[18px] rounded-full transition-colors ${
                        config.channels.gotify?.enabled ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"
                      } ${!editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                      onClick={() => { if (editMode) updateChannel("gotify", "enabled", !config.channels.gotify?.enabled) }}
                      disabled={!editMode}
                      role="switch"
                      aria-checked={config.channels.gotify?.enabled || false}
                    >
                      <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                        config.channels.gotify?.enabled ? "translate-x-[18px]" : "translate-x-0"
                      }`} />
                    </button>
                  </div>
                  {config.channels.gotify?.enabled && (
                    <>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] text-muted-foreground">Server URL</Label>
                        <Input
                          className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                          placeholder="https://gotify.example.com"
                          value={config.channels.gotify?.url || ""}
                          onChange={e => updateChannel("gotify", "url", e.target.value)}
                          disabled={!editMode}
                        />
                        {(() => {
                          const v = validateGotifyUrl(config.channels.gotify?.url || "")
                          if (v.error) return <p className="text-[10px] text-red-500">{v.error}</p>
                          if (v.warning) return <p className="text-[10px] text-yellow-500">{v.warning}</p>
                          return null
                        })()}
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] text-muted-foreground">App Token</Label>
                        <div className="flex items-center gap-1.5">
                          <Input
                            type={showSecrets["gt_token"] ? "text" : "password"}
                            className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                            placeholder="A_valid_gotify_token"
                            value={config.channels.gotify?.token || ""}
                            onChange={e => updateChannel("gotify", "token", e.target.value)}
                            disabled={!editMode}
                          />
                          <button
                            className="h-7 w-7 flex items-center justify-center rounded-md border border-border hover:bg-muted transition-colors shrink-0"
                            onClick={() => toggleSecret("gt_token")}
                          >
                            {showSecrets["gt_token"] ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                          </button>
                        </div>
                      </div>
                      {/* Message format */}
                      <div className="flex items-center justify-between py-1">
                        <div>
                          <Label className="text-xs font-medium">Rich messages</Label>
                          <p className="text-[10px] text-muted-foreground">Enrich notifications with contextual emojis and icons</p>
                        </div>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={config.channels.gotify?.rich_format || false}
                          disabled={!editMode}
                          className={`relative w-9 h-[18px] shrink-0 rounded-full transition-colors ${
                            !editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
                          } ${config.channels.gotify?.rich_format ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"}`}
                          onClick={() => { if (editMode) updateChannel("gotify", "rich_format", !config.channels.gotify?.rich_format) }}
                        >
                          <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                            config.channels.gotify?.rich_format ? "translate-x-[18px]" : "translate-x-0"
                          }`} />
                        </button>
                      </div>
                      {renderChannelCategories("gotify")}
                      {renderQuietHours("gotify")}
                      {renderDailyDigest("gotify")}
                      {/* Send Test — channel-colored (see Telegram block). */}
                      <div className="flex items-center gap-2 pt-2 border-t border-border/50">
                        <button
                          className="h-7 px-3 text-xs rounded-md bg-green-600 hover:bg-green-700 text-white transition-colors flex items-center gap-1.5 disabled:opacity-50"
                          onClick={() => handleTest("gotify")}
                          disabled={testing === "gotify" || !config.channels.gotify?.url}
                        >
                          {testing === "gotify" ? <Loader2 className="h-3 w-3 animate-spin" /> : <TestTube2 className="h-3 w-3" />}
                          Send Test
                        </button>
                      </div>
                    </>
                  )}
                </TabsContent>

                {/* Discord */}
                <TabsContent value="discord" className="space-y-3 pt-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs font-medium">Enable Discord</Label>
                    <button
                      className={`relative w-9 h-[18px] rounded-full transition-colors ${
                        config.channels.discord?.enabled ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"
                      } ${!editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                      onClick={() => { if (editMode) updateChannel("discord", "enabled", !config.channels.discord?.enabled) }}
                      disabled={!editMode}
                      role="switch"
                      aria-checked={config.channels.discord?.enabled || false}
                    >
                      <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                        config.channels.discord?.enabled ? "translate-x-[18px]" : "translate-x-0"
                      }`} />
                    </button>
                  </div>
                  {config.channels.discord?.enabled && (
                    <>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] text-muted-foreground">Webhook URL</Label>
                        <div className="flex items-center gap-1.5">
                          <Input
                            type={showSecrets["dc_hook"] ? "text" : "password"}
                            className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                            placeholder="https://discord.com/api/webhooks/..."
                            value={config.channels.discord?.webhook_url || ""}
                            onChange={e => updateChannel("discord", "webhook_url", e.target.value)}
                            disabled={!editMode}
                          />
                          <button
                            className="h-7 w-7 flex items-center justify-center rounded-md border border-border hover:bg-muted transition-colors shrink-0"
                            onClick={() => toggleSecret("dc_hook")}
                          >
                            {showSecrets["dc_hook"] ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                          </button>
                        </div>
                        {(() => {
                          const v = validateDiscordWebhook(config.channels.discord?.webhook_url || "")
                          return v.error ? <p className="text-[10px] text-red-500">{v.error}</p> : null
                        })()}
                      </div>
                      {/* Message format */}
                      <div className="flex items-center justify-between py-1">
                        <div>
                          <Label className="text-xs font-medium">Rich messages</Label>
                          <p className="text-[10px] text-muted-foreground">Enrich notifications with contextual emojis and icons</p>
                        </div>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={config.channels.discord?.rich_format || false}
                          disabled={!editMode}
                          className={`relative w-9 h-[18px] shrink-0 rounded-full transition-colors ${
                            !editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
                          } ${config.channels.discord?.rich_format ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"}`}
                          onClick={() => { if (editMode) updateChannel("discord", "rich_format", !config.channels.discord?.rich_format) }}
                        >
                          <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                            config.channels.discord?.rich_format ? "translate-x-[18px]" : "translate-x-0"
                          }`} />
                        </button>
                      </div>
                      {renderChannelCategories("discord")}
                      {renderQuietHours("discord")}
                      {renderDailyDigest("discord")}
                      {/* Send Test — channel-colored (see Telegram block). */}
                      <div className="flex items-center gap-2 pt-2 border-t border-border/50">
                        <button
                          className="h-7 px-3 text-xs rounded-md bg-indigo-600 hover:bg-indigo-700 text-white transition-colors flex items-center gap-1.5 disabled:opacity-50"
                          onClick={() => handleTest("discord")}
                          disabled={testing === "discord" || !config.channels.discord?.webhook_url}
                        >
                          {testing === "discord" ? <Loader2 className="h-3 w-3 animate-spin" /> : <TestTube2 className="h-3 w-3" />}
                          Send Test
                        </button>
                      </div>
                    </>
                  )}
                </TabsContent>

                {/* Email */}
                <TabsContent value="email" className="space-y-3 pt-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs font-medium">Enable Email</Label>
                    <button
                      className={`relative w-9 h-[18px] rounded-full transition-colors ${
                        config.channels.email?.enabled ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"
                      } ${!editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                      onClick={() => { if (editMode) updateChannel("email", "enabled", !config.channels.email?.enabled) }}
                      disabled={!editMode}
                      role="switch"
                      aria-checked={config.channels.email?.enabled || false}
                    >
                      <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                        config.channels.email?.enabled ? "translate-x-[18px]" : "translate-x-0"
                      }`} />
                    </button>
                  </div>
                  {config.channels.email?.enabled && (
                    <>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        <div className="space-y-1.5">
                          <Label className="text-[11px] text-muted-foreground">SMTP Host</Label>
                          <Input
                            className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                            placeholder="smtp.gmail.com"
                            value={config.channels.email?.host || ""}
                            onChange={e => updateChannel("email", "host", e.target.value)}
                            disabled={!editMode}
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label className="text-[11px] text-muted-foreground">Port</Label>
                          <Input
                            className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                            placeholder="587"
                            value={config.channels.email?.port || ""}
                            onChange={e => updateChannel("email", "port", e.target.value)}
                            disabled={!editMode}
                          />
                        </div>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] text-muted-foreground">TLS Mode</Label>
                        <Select
                          value={config.channels.email?.tls_mode || "starttls"}
                          onValueChange={v => updateChannel("email", "tls_mode", v)}
                          disabled={!editMode}
                        >
                          <SelectTrigger className={`h-7 text-xs ${!editMode ? "opacity-50" : ""}`}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="starttls">STARTTLS (port 587)</SelectItem>
                            <SelectItem value="ssl">SSL/TLS (port 465)</SelectItem>
                            <SelectItem value="none">None (port 25)</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        <div className="space-y-1.5">
                          <Label className="text-[11px] text-muted-foreground">Username</Label>
                          <Input
                            className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                            placeholder="user@example.com"
                            value={config.channels.email?.username || ""}
                            onChange={e => updateChannel("email", "username", e.target.value)}
                            disabled={!editMode}
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label className="text-[11px] text-muted-foreground">Password</Label>
                          <div className="flex items-center gap-1.5">
                            <Input
                              type={showSecrets["em_pass"] ? "text" : "password"}
                              className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                              placeholder="App password"
                              value={config.channels.email?.password || ""}
                              onChange={e => updateChannel("email", "password", e.target.value)}
                              disabled={!editMode}
                            />
                            <button
                              className="h-7 w-7 flex items-center justify-center rounded-md border border-border hover:bg-muted transition-colors shrink-0"
                              onClick={() => toggleSecret("em_pass")}
                            >
                              {showSecrets["em_pass"] ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                            </button>
                          </div>
                        </div>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] text-muted-foreground">From Address</Label>
                        <Input
                          className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                          placeholder="proxmenux@yourdomain.com"
                          value={config.channels.email?.from_address || ""}
                          onChange={e => updateChannel("email", "from_address", e.target.value)}
                          disabled={!editMode}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] text-muted-foreground">To Addresses (comma-separated)</Label>
                        <Input
                          className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                          placeholder="admin@example.com, ops@example.com"
                          value={config.channels.email?.to_addresses || ""}
                          onChange={e => updateChannel("email", "to_addresses", e.target.value)}
                          disabled={!editMode}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] text-muted-foreground">Subject Prefix</Label>
                        <Input
                          className={`h-7 text-xs font-mono ${!editMode ? "opacity-50" : ""}`}
                          placeholder="[ProxMenux]"
                          value={config.channels.email?.subject_prefix || "[ProxMenux]"}
                          onChange={e => updateChannel("email", "subject_prefix", e.target.value)}
                          disabled={!editMode}
                        />
                      </div>
                      <div className="flex items-start gap-2 p-2 rounded-md bg-amber-500/10 border border-amber-500/20">
                        <Info className="h-3.5 w-3.5 text-amber-400 shrink-0 mt-0.5" />
                        <p className="text-[10px] text-amber-400/90 leading-relaxed">
                          Leave SMTP Host empty to use local sendmail (must be installed on the server).
                          For Gmail, use an App Password instead of your account password.
                        </p>
                      </div>
                      {renderChannelCategories("email")}
                      {renderQuietHours("email")}
                      {renderDailyDigest("email")}
                      {/* Send Test — channel-colored (see Telegram block). */}
                      <div className="flex items-center gap-2 pt-2 border-t border-border/50">
                        <button
                          className="h-7 px-3 text-xs rounded-md bg-amber-600 hover:bg-amber-700 text-white transition-colors flex items-center gap-1.5 disabled:opacity-50"
                          onClick={() => handleTest("email")}
                          disabled={testing === "email" || !config.channels.email?.to_addresses}
                        >
                          {testing === "email" ? <Loader2 className="h-3 w-3 animate-spin" /> : <TestTube2 className="h-3 w-3" />}
                          Send Test
                        </button>
                      </div>
                    </>
                  )}
                </TabsContent>

                {/* Apprise — issue #207. Single URL talks to ~80
                    notification services. The operator pastes one
                    `tgram://`, `discord://`, `ntfy://`, `matrix://`,
                    `pushover://` etc. URL and the AppriseChannel
                    backend handles the transport. Mirrors the same
                    Enable toggle + Test button pattern as the other
                    channels. */}
                <TabsContent value="apprise" className="space-y-3 pt-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Label className="text-xs font-medium">Enable Apprise</Label>
                      <a
                        href="https://github.com/caronc/apprise/wiki"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[10px] text-cyan-500 hover:text-cyan-400 hover:underline"
                      >
                        +URL formats
                      </a>
                    </div>
                    <button
                      className={`relative w-9 h-[18px] rounded-full transition-colors ${
                        config.channels.apprise?.enabled ? "bg-blue-600" : "bg-muted-foreground/20 border border-muted-foreground/40"
                      } ${!editMode ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                      onClick={() => { if (editMode) updateChannel("apprise", "enabled", !config.channels.apprise?.enabled) }}
                      disabled={!editMode}
                      role="switch"
                      aria-checked={config.channels.apprise?.enabled || false}
                    >
                      <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                        config.channels.apprise?.enabled ? "translate-x-[18px]" : "translate-x-0"
                      }`} />
                    </button>
                  </div>
                  {config.channels.apprise?.enabled && (
                    <>
                      <div className="space-y-1.5 min-w-0">
                        <Label className="text-[11px] text-muted-foreground">Apprise URL</Label>
                        <div className="flex items-center gap-1.5 min-w-0">
                          <Input
                            type={showSecrets["apprise_url"] ? "text" : "password"}
                            className={`h-7 text-xs font-mono min-w-0 flex-1 ${!editMode ? "opacity-50" : ""}`}
                            placeholder="tgram://bottoken/ChatID"
                            value={config.channels.apprise?.url || ""}
                            onChange={e => updateChannel("apprise", "url", e.target.value)}
                            disabled={!editMode}
                          />
                          <button
                            type="button"
                            className="h-7 w-7 shrink-0 flex items-center justify-center rounded-md border border-border hover:bg-muted text-muted-foreground"
                            onClick={() => setShowSecrets(s => ({ ...s, apprise_url: !s.apprise_url }))}
                            title={showSecrets["apprise_url"] ? "Hide URL" : "Show URL"}
                          >
                            {showSecrets["apprise_url"] ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                          </button>
                        </div>
                        {/* The examples row was overflowing on mobile because
                            every `<code>` token is atomic — the whole line
                            would scroll horizontally on narrow viewports.
                            `break-all` on the wrapper lets the layout break
                            mid-token if the viewport is really tight; on
                            wider screens the natural commas/spaces still
                            control wrapping. */}
                        <p className="text-[10px] text-muted-foreground leading-relaxed break-all min-w-0">
                          A single URL that Apprise routes to the right service. Examples:
                          <code className="text-foreground/80 mx-0.5">tgram://</code>,
                          <code className="text-foreground/80 mx-0.5">discord://</code>,
                          <code className="text-foreground/80 mx-0.5">slack://</code>,
                          <code className="text-foreground/80 mx-0.5">ntfy://</code>,
                          <code className="text-foreground/80 mx-0.5">matrix://</code>,
                          <code className="text-foreground/80 mx-0.5">pushover://</code>,
                          <code className="text-foreground/80 mx-0.5">mailto://</code>… See the
                          {" "}
                          <a
                            href="https://github.com/caronc/apprise/wiki"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-cyan-500 hover:underline"
                          >
                            full list
                          </a>.
                        </p>
                      </div>
                      {renderChannelCategories("apprise")}
                      {renderQuietHours("apprise")}
                      {renderDailyDigest("apprise")}
                      {/* Send Test — left-aligned + channel-colored, matching
                          the other four channels (was right-aligned, #226). */}
                      <div className="flex items-center gap-2 pt-2 border-t border-border/50">
                        <button
                          className="h-7 px-3 text-xs rounded-md bg-cyan-600 hover:bg-cyan-700 text-white transition-colors flex items-center gap-1.5 disabled:opacity-50"
                          onClick={() => handleTest("apprise")}
                          disabled={testing === "apprise" || !config.channels.apprise?.url}
                        >
                          {testing === "apprise" ? <Loader2 className="h-3 w-3 animate-spin" /> : <TestTube2 className="h-3 w-3" />}
                          Send Test
                        </button>
                      </div>
                    </>
                  )}
                </TabsContent>
              </Tabs>

              {/* Test Result */}
              {testResult && (
                <div className={`flex items-center gap-2 p-2.5 rounded-md text-xs mt-2 ${
                  testResult.success
                    ? "bg-green-500/10 border border-green-500/20 text-green-400"
                    : "bg-red-500/10 border border-red-500/20 text-red-400"
                }`}>
                  {testResult.success ? (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5 shrink-0" />
                  )}
                  <span>{testResult.message}</span>
                </div>
              )}
              </div>{/* close bordered channel container */}
            </div>

            {/* ── Display Name ── */}
            <div className="space-y-2 pb-3 border-b border-border/50">
              <div className="flex items-center gap-2">
                <Server className="h-4 w-4 text-blue-400" />
                <Label className="text-xs sm:text-sm text-foreground/80">Display Name</Label>
              </div>
              <Input
                className={`h-9 text-sm ${!editMode ? "opacity-50 cursor-not-allowed" : ""}`}
                placeholder={systemHostname || "System hostname"}
                value={config.hostname || (editMode ? "" : systemHostname)}
                onChange={e => updateConfig(p => ({ ...p, hostname: e.target.value }))}
                disabled={!editMode}
                readOnly={!editMode}
              />
              <p className="text-xs text-muted-foreground">
                Name shown in notifications. Edit to customize, or leave empty to use the system hostname.
              </p>
            </div>

            {/* ── Advanced: AI Enhancement ── */}
            <div>
              <div className="flex items-center justify-between py-1">
                <button
                  className="flex items-center gap-2 text-sm text-foreground hover:bg-muted/60 rounded-md px-2 py-1.5 -mx-2 transition-colors"
                  onClick={() => setShowAdvanced(!showAdvanced)}
                >
                  {showAdvanced ? (
                    <ChevronUp className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  )}
                  <Sparkles className="h-4 w-4 text-purple-400" />
                  <span className="font-medium">AI Enhancement</span>
                  {config.ai_enabled ? (
                    <Badge variant="outline" className="text-[10px] border-purple-500/40 text-purple-400 ml-1">
                      Active
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-[10px] border-border text-muted-foreground ml-1">
                      Optional
                    </Badge>
                  )}
                </button>
                {showAdvanced && (
                  <div className="flex items-center gap-2">
                    {editMode ? (
                      <>
                        <button
                          className="h-6 px-2 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors text-muted-foreground"
                          onClick={handleCancel}
                          disabled={saving}
                        >
                          Cancel
                        </button>
                        <button
                          className="h-6 px-2 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50 flex items-center gap-1"
                          onClick={handleSave}
                          disabled={saving || !hasChanges}
                        >
                          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                          Save
                        </button>
                      </>
                    ) : (
                      <button
                        className="h-6 px-2 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors flex items-center gap-1"
                        onClick={() => setEditMode(true)}
                      >
                        <Settings2 className="h-3 w-3" />
                        Edit
                      </button>
                    )}
                  </div>
                )}
              </div>

{showAdvanced && (
                  <div className="space-y-4 mt-3 p-4 rounded-lg bg-muted/30 border border-border/50">
                    <div className="flex items-center justify-between">
                      <div className="flex items-start gap-3">
                        <Sparkles className="h-5 w-5 text-purple-400 mt-0.5 shrink-0" />
                        <div>
                          <span className="text-sm font-medium">AI-Enhanced Messages</span>
                          <p className="text-xs sm:text-sm text-muted-foreground">Use AI to generate contextual notification messages</p>
                        </div>
                      </div>
                      <button
                      className={`relative w-9 h-[18px] rounded-full transition-colors ${
                        config.ai_enabled ? "bg-purple-600" : "bg-muted-foreground/20 border border-muted-foreground/40"
                      } ${!editMode ? "opacity-60 cursor-not-allowed" : "cursor-pointer"}`}
                      onClick={() => editMode && updateConfig(p => ({ ...p, ai_enabled: !p.ai_enabled }))}
                      disabled={!editMode}
                      role="switch"
                      aria-checked={config.ai_enabled}
                    >
                      <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                        config.ai_enabled ? "translate-x-[18px]" : "translate-x-0"
                      }`} />
                    </button>
                  </div>

                  {config.ai_enabled && (
                    <>
                      {/* Provider + Info button */}
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Cloud className="h-4 w-4 text-purple-400" />
                          <Label className="text-xs sm:text-sm text-foreground/80">Provider</Label>
                          <button
                            onClick={() => setShowProviderInfo(true)}
                            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                          >
                            +info
                          </button>
                        </div>
                        <Select
                          value={config.ai_provider}
                          onValueChange={v => {
                            // Save current model for current provider before switching
                            const currentProvider = config.ai_provider
                            const currentModel = config.ai_model
                            
                            // Restore previously saved model for the new provider (if any)
                            const savedModel = config.ai_models?.[v] || ''
                            
                            updateConfig(p => ({ 
                              ...p, 
                              ai_provider: v, 
                              ai_model: savedModel,
                              ai_models: {
                                ...p.ai_models,
                                [currentProvider]: currentModel  // Save old provider's model
                              }
                            }))
                            setProviderModels([])  // Clear loaded models list
                          }}
                          disabled={!editMode}
                        >
                          <SelectTrigger className="h-9 text-sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {AI_PROVIDERS.map(p => (
                              <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      
                      {/* Ollama URL (conditional) */}
                      {config.ai_provider === "ollama" && (
                        <div className="space-y-2">
                          <Label className="text-xs sm:text-sm text-foreground/80">Ollama URL</Label>
                          <Input
                            className="h-9 text-sm font-mono"
                            placeholder="http://localhost:11434"
                            value={config.ai_ollama_url}
                            onChange={e => updateConfig(p => ({ ...p, ai_ollama_url: e.target.value }))}
                            disabled={!editMode}
                          />
                        </div>
                      )}
                      
                      {/* Custom Base URL for OpenAI-compatible APIs */}
                      {config.ai_provider === "openai" && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2">
                            <Label className="text-xs sm:text-sm text-foreground/80">Custom Base URL</Label>
                            <span className="text-xs text-muted-foreground">(optional)</span>
                          </div>
                          <Input
                            className="h-9 text-sm font-mono"
                            placeholder="Leave empty for OpenAI, or enter custom endpoint"
                            value={config.ai_openai_base_url}
                            onChange={e => updateConfig(p => ({ ...p, ai_openai_base_url: e.target.value }))}
                            disabled={!editMode}
                          />
                          <p className="text-xs text-muted-foreground">
                            For OpenAI-compatible APIs: BytePlus, LocalAI, LM Studio, vLLM, etc.
                          </p>
                        </div>
                      )}
                      
                      {/* API Key (not shown for Ollama) */}
                      {config.ai_provider !== "ollama" && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2">
                            <Label className="text-xs sm:text-sm text-foreground/80">API Key</Label>
                            {AI_PROVIDERS.find(p => p.value === config.ai_provider)?.keyUrl && (
                              <a
                                href={AI_PROVIDERS.find(p => p.value === config.ai_provider)?.keyUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-blue-400 hover:text-blue-300 transition-colors flex items-center gap-1"
                              >
                                Get key <ExternalLink className="h-3 w-3" />
                              </a>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                        <Input
                          type={showSecrets["ai_key"] ? "text" : "password"}
                          className="h-9 text-sm font-mono"
                          placeholder="sk-..."
                          value={config.ai_api_keys?.[config.ai_provider] || ""}
                          onChange={e => updateConfig(p => ({ 
                            ...p, 
                            ai_api_keys: { 
                              ...p.ai_api_keys, 
                              [p.ai_provider]: e.target.value 
                            } 
                          }))}
                          disabled={!editMode}
                        />
                            <button
                              className="h-9 w-9 flex items-center justify-center rounded-md border border-border hover:bg-muted transition-colors shrink-0"
                              onClick={() => toggleSecret("ai_key")}
                            >
                              {showSecrets["ai_key"] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                            </button>
                          </div>
                        </div>
                      )}
                      
                      {/* Model - selector with Load button for all providers */}
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Brain className="h-4 w-4 text-blue-400" />
                          <Label className="text-xs sm:text-sm text-foreground/80">Model</Label>
                        </div>
                        <div className="flex items-center gap-2">
                          <Select
                            value={config.ai_model || ""}
                            onValueChange={v => updateConfig(p => ({ 
                              ...p, 
                              ai_model: v,
                              ai_models: { ...p.ai_models, [p.ai_provider]: v }  // Also save per-provider
                            }))}
                            disabled={!editMode || loadingProviderModels || providerModels.length === 0}
                          >
                            <SelectTrigger className="h-9 text-sm font-mono flex-1">
                              <SelectValue placeholder={providerModels.length === 0 ? "Click 'Load' to fetch models" : "Select model"}>
                                {config.ai_model || (providerModels.length === 0 ? "Click 'Load' to fetch models" : "Select model")}
                              </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                              {providerModels.length > 0 ? (
                                providerModels.map(m => (
                                  <SelectItem key={m} value={m} className="font-mono">{m}</SelectItem>
                                ))
                              ) : (
                                <SelectItem value="_none" disabled className="text-muted-foreground">
                                  No models loaded - click Load button
                                </SelectItem>
                              )}
                            </SelectContent>
                          </Select>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-9 px-3 shrink-0"
                            onClick={() => fetchProviderModels()}
                            disabled={
                              loadingProviderModels || 
                              (config.ai_provider === 'ollama' && !config.ai_ollama_url) ||
                              (config.ai_provider !== 'ollama' && config.ai_provider !== 'anthropic' && !config.ai_api_keys?.[config.ai_provider])
                            }
                          >
                            {loadingProviderModels ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <>
                                <RefreshCw className="h-4 w-4 mr-1" />
                                Load
                              </>
                            )}
                          </Button>
                        </div>
                        {providerModels.length > 0 && (
                          <p className="text-xs text-green-500">{providerModels.length} models available</p>
                        )}
                      </div>
                      
                      {/* Prompt Mode section */}
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <MessageSquareText className="h-4 w-4 text-amber-400" />
                          <Label className="text-xs sm:text-sm text-foreground/80">Prompt Mode</Label>
                        </div>
                        <Select
                          value={config.ai_prompt_mode || "default"}
                          onValueChange={v => {
                            updateConfig(p => ({ ...p, ai_prompt_mode: v }))
                            // Show info modal when switching to custom for the first time
                            if (v === "custom" && !config.ai_custom_prompt) {
                              setShowCustomPromptInfo(true)
                            }
                          }}
                          disabled={!editMode}
                        >
                          <SelectTrigger className="h-9 text-sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="default">Default Prompt</SelectItem>
                            <SelectItem value="custom">Custom Prompt</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      
                      {/* Default mode options: Language and Detail Level per Channel */}
                      {(config.ai_prompt_mode || "default") === "default" && (
                        <div className="space-y-3 pt-3 border-t border-border/50">
                          {/* Language selector - only for default mode */}
                          <div className="space-y-2">
                            <div className="flex items-center gap-2">
                              <Globe className="h-4 w-4 text-green-400" />
                              <Label className="text-xs sm:text-sm text-foreground/80">Language</Label>
                            </div>
                            <Select
                              value={config.ai_language || "en"}
                              onValueChange={v => updateConfig(p => ({ ...p, ai_language: v }))}
                              disabled={!editMode}
                            >
                              <SelectTrigger className="h-9 text-sm">
                                <SelectValue placeholder="Select language">
                                  {AI_LANGUAGES.find(l => l.value === (config.ai_language || "en"))?.label || "English"}
                                </SelectValue>
                              </SelectTrigger>
                              <SelectContent>
                                {AI_LANGUAGES.map(l => (
                                  <SelectItem key={l.value} value={l.value}>{l.label}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                          
                          {/* Detail Level per Channel */}
                          <div className="space-y-3">
                            <Label className="text-xs sm:text-sm text-foreground/80">Detail Level per Channel</Label>
                            <div className="grid grid-cols-2 gap-3">
                              {CHANNEL_TYPES.map(ch => (
                                <div key={ch} className="flex items-center justify-between gap-2 px-3 py-2 rounded bg-muted/30">
                                  <span className="text-xs sm:text-sm text-foreground/70 capitalize">{ch}</span>
                                  <Select
                                    value={config.channel_ai_detail?.[ch] || "standard"}
                                    onValueChange={v => updateConfig(p => ({
                                      ...p,
                                      channel_ai_detail: { ...p.channel_ai_detail, [ch]: v }
                                    }))}
                                    disabled={!editMode}
                                  >
                                    <SelectTrigger className="h-7 w-[90px] text-xs px-2">
                                      <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {AI_DETAIL_LEVELS.map(l => (
                                        <SelectItem key={l.value} value={l.value} className="text-xs">
                                          {l.label}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </div>
                              ))}
                            </div>
                            <div className="flex items-start gap-2 p-3 rounded-md bg-purple-500/10 border border-purple-500/20">
                              <Info className="h-4 w-4 text-purple-400 shrink-0 mt-0.5" />
                              <p className="text-xs sm:text-sm text-purple-400/90 leading-relaxed">
                                AI translates and formats notifications to your selected language. Each channel can have different detail levels.
                              </p>
                            </div>
                          </div>
                          
                          {/* Experimental: AI Suggestions toggle */}
                          <div className="flex items-center justify-between pt-3 border-t border-border/50">
                            <div className="flex items-start gap-3">
                              <Lightbulb className="h-5 w-5 text-purple-400 mt-0.5 shrink-0" />
                              <div>
                                <div className="flex items-center gap-2">
                                  <span className="text-sm font-medium">AI Suggestions</span>
                                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400 font-medium">BETA</span>
                                </div>
                                <p className="text-xs sm:text-sm text-muted-foreground">
                                  Allow AI to add brief troubleshooting tips based on log context
                                </p>
                              </div>
                            </div>
                            <button
                              className={`relative w-9 h-[18px] rounded-full transition-colors ${
                                config.ai_allow_suggestions === "true" || config.ai_allow_suggestions === true
                                  ? "bg-purple-600"
                                  : "bg-muted-foreground/20 border border-muted-foreground/40"
                              } ${!editMode ? "opacity-60 cursor-not-allowed" : "cursor-pointer"}`}
                              onClick={() => {
                                if (editMode) {
                                  const newValue = config.ai_allow_suggestions === "true" || config.ai_allow_suggestions === true ? "false" : "true"
                                  updateConfig(p => ({ ...p, ai_allow_suggestions: newValue }))
                                }
                              }}
                              disabled={!editMode}
                              role="switch"
                              aria-checked={config.ai_allow_suggestions === "true" || config.ai_allow_suggestions === true}
                            >
                              <span className={`absolute top-[1px] left-[1px] h-4 w-4 rounded-full bg-white shadow transition-transform ${
                                config.ai_allow_suggestions === "true" || config.ai_allow_suggestions === true ? "translate-x-[18px]" : "translate-x-0"
                              }`} />
                            </button>
                          </div>
                        </div>
                      )}
                      
                      {/* Custom mode: Editable prompt textarea */}
                      {config.ai_prompt_mode === "custom" && (
                        <div className="space-y-3 pt-3 border-t border-border/50">
                            <div className="space-y-2">
                              <div className="flex items-center justify-between">
                                <Label className="text-xs sm:text-sm text-foreground/80">Custom Prompt</Label>
                                <div className="flex gap-1">
                                  {!editingCustomPrompt ? (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      onClick={() => {
                                        setCustomPromptDraft(config.ai_custom_prompt || "")
                                        setEditingCustomPrompt(true)
                                      }}
                                      className="h-7 px-2 text-xs flex items-center gap-1"
                                    >
                                      <Pencil className="h-3 w-3" />
                                      Edit
                                    </Button>
                                  ) : (
                                    <>
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => {
                                          setEditingCustomPrompt(false)
                                          setCustomPromptDraft("")
                                        }}
                                        className="h-7 px-2 text-xs"
                                      >
                                        Cancel
                                      </Button>
                                      <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => {
                                          updateConfig(p => ({ ...p, ai_custom_prompt: customPromptDraft }))
                                          setEditingCustomPrompt(false)
                                          handleSave()
                                        }}
                                        className="h-7 px-2 text-xs flex items-center gap-1 bg-blue-600 hover:bg-blue-700 text-white border-blue-600"
                                      >
                                        <Save className="h-3 w-3" />
                                        Save
                                      </Button>
                                    </>
                                  )}
                                </div>
                              </div>
                              <textarea
                                value={editingCustomPrompt ? customPromptDraft : (config.ai_custom_prompt || "")}
                                onChange={e => setCustomPromptDraft(e.target.value)}
                                disabled={!editingCustomPrompt}
                                placeholder="Enter your custom prompt instructions for the AI..."
                                className="w-full h-48 px-3 py-2 text-sm rounded-md border border-border bg-background resize-y focus:outline-none focus:ring-2 focus:ring-purple-500/50 disabled:opacity-50 disabled:cursor-not-allowed"
                              />
                            </div>
                            <div className="flex gap-2">
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={editingCustomPrompt}
                                onClick={() => {
                                  const blob = new Blob([config.ai_custom_prompt || ""], { type: "text/plain" })
                                  const url = URL.createObjectURL(blob)
                                  const a = document.createElement("a")
                                  a.href = url
                                  a.download = "proxmenux_custom_prompt.txt"
                                  a.click()
                                  URL.revokeObjectURL(url)
                                }}
                                className="flex items-center gap-1"
                              >
                                <Download className="h-4 w-4" />
                                Export
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={editingCustomPrompt}
                                onClick={() => {
                                  const input = document.createElement("input")
                                  input.type = "file"
                                  input.accept = ".txt,.md"
                                  input.onchange = async (e) => {
                                    const file = (e.target as HTMLInputElement).files?.[0]
                                    if (file) {
                                      const text = await file.text()
                                      updateConfig(p => ({ ...p, ai_custom_prompt: text }))
                                      handleSave()
                                    }
                                  }
                                  input.click()
                                }}
                                className="flex items-center gap-1"
                              >
                                <Upload className="h-4 w-4" />
                                Import
                              </Button>
                              <a
                                href="https://github.com/MacRimi/ProxMenux/discussions/categories/share-custom-prompts-for-ai-notifications"
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-purple-400 hover:text-purple-300 transition-colors flex items-center gap-1"
                              >
                                Community prompts <ExternalLink className="h-3 w-3" />
                              </a>
                            </div>
                            <div className="flex items-start gap-2 p-3 rounded-md bg-purple-500/10 border border-purple-500/20">
                              <Info className="h-4 w-4 text-purple-400 shrink-0 mt-0.5" />
                              <p className="text-xs sm:text-sm text-purple-400/90 leading-relaxed">
                                Define your own prompt rules and format. You control the detail level and style of all notifications. Export to share with others or import prompts from the community.
                              </p>
                          </div>
                        </div>
                      )}
                      
                      {/* Test Connection button - moved to end */}
                      <div className="space-y-3 pt-3 border-t border-border/50">
                        <button
                          onClick={handleTestAI}
                          disabled={
                            !editMode || 
                            testingAI || 
                            !config.ai_model ||
                            (config.ai_provider !== "ollama" && !config.ai_api_keys?.[config.ai_provider])
                          }
                          className="w-full h-9 flex items-center justify-center gap-2 rounded-md text-sm font-medium bg-purple-600 hover:bg-purple-700 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          {testingAI ? (
                            <><Loader2 className="h-4 w-4 animate-spin" /> Testing...</>
                          ) : (
                            <><Zap className="h-4 w-4" /> Test Connection</>
                          )}
                        </button>
                        
                        {/* Test result */}
                        {aiTestResult && (
                          <div className={`flex items-start gap-2 p-3 rounded-md ${
                            aiTestResult.success 
                              ? "bg-green-500/10 border border-green-500/20" 
                              : "bg-red-500/10 border border-red-500/20"
                          }`}>
                            {aiTestResult.success 
                              ? <CheckCircle2 className="h-4 w-4 text-green-400 shrink-0 mt-0.5" />
                              : <XCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
                            }
                            <p className={`text-xs sm:text-sm leading-relaxed ${
                              aiTestResult.success ? "text-green-400/90" : "text-red-400/90"
                            }`}>
                              {aiTestResult.message}
                              {aiTestResult.model && ` (${aiTestResult.model})`}
                            </p>
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>


          </>
        )}

        {/* ── Footer info ── */}
        <div className="flex items-start gap-2 pt-3 border-t border-border">
          <Info className="h-4 w-4 text-blue-400 shrink-0 mt-0.5" />
          <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">
            {config.enabled
              ? "Notifications are active. Each channel sends events based on its own category and event selection."
              : "Enable notifications to receive alerts about system events, health status changes, and security incidents via Telegram, Gotify, Discord, or Email."}
          </p>
        </div>
      </CardContent>
    </Card>
    
      {/* AI Provider Information Modal */}
      <Dialog open={showProviderInfo} onOpenChange={setShowProviderInfo}>
        <DialogContent className="max-w-[90vw] sm:max-w-xl md:max-w-2xl lg:max-w-3xl">
          <DialogHeader>
            <DialogTitle className="text-base sm:text-lg">AI Providers Information</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
            {AI_PROVIDERS.map(provider => (
              <div 
                key={provider.value} 
                className="p-4 rounded-lg bg-muted/50 border border-border hover:border-muted-foreground/40 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {/* Provider icon with theme support */}
                    <div className="w-10 h-10 rounded-md bg-background flex items-center justify-center border border-border shrink-0">
                      <img 
                        src={resolvedTheme === 'light' ? provider.iconLight : provider.icon} 
                        alt={provider.label}
                        className="w-7 h-7 object-contain"
                        onError={(e) => {
                          // Fallback if icon fails to load
                          (e.target as HTMLImageElement).style.display = 'none'
                        }}
                      />
                    </div>
                    <span className="font-medium text-sm sm:text-base">{provider.label}</span>
                  </div>
                  {provider.value === "ollama" && (
                    <Badge variant="outline" className="text-xs px-2 py-0.5">Local</Badge>
                  )}
                </div>
                <p className="text-xs sm:text-sm text-muted-foreground mt-2 ml-[52px] leading-relaxed">
                  {provider.description}
                </p>
                <p className="text-xs text-muted-foreground/70 mt-1 ml-[52px]">
                  Click &apos;Load&apos; to fetch available models from this provider.
                </p>
                {/* OpenAI compatibility note */}
                {provider.value === "openai" && (
                  <div className="mt-3 ml-[52px] p-3 rounded-md bg-blue-500/10 border border-blue-500/20">
                    <p className="text-xs sm:text-sm text-blue-400 font-medium mb-1">OpenAI-Compatible APIs</p>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      You can use any OpenAI-compatible API by setting a custom Base URL. Compatible services include:
                    </p>
                    <ul className="text-xs text-muted-foreground mt-1.5 space-y-0.5 ml-3">
                      <li>BytePlus/ByteDance (Kimi K2.5)</li>
                      <li>LocalAI, LM Studio, vLLM</li>
                      <li>Together AI, Fireworks AI</li>
                      <li>Any service using OpenAI format</li>
                    </ul>
                  </div>
                )}
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      {/* Telegram Setup Guide Modal */}
      <Dialog open={showTelegramHelp} onOpenChange={setShowTelegramHelp}>
        <DialogContent className="max-w-[90vw] sm:max-w-xl md:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="text-base sm:text-lg">Telegram Bot Setup Guide</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-1 text-sm">
            {/* Step 1 */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="h-6 w-6 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center">1</span>
                <h4 className="font-medium">Create a Bot with BotFather</h4>
              </div>
              <div className="ml-8 space-y-1 text-muted-foreground text-xs">
                <p>1. Open Telegram and search for <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">@BotFather</a></p>
                <p>2. Send the command <code className="bg-muted px-1 rounded">/newbot</code></p>
                <p>3. Choose a name for your bot (e.g., "ProxMenux Notifications")</p>
                <p>4. Choose a username ending in "bot" (e.g., "proxmenux_alerts_bot")</p>
              </div>
            </div>

            {/* Step 2 */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="h-6 w-6 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center">2</span>
                <h4 className="font-medium">Get the Bot Token</h4>
              </div>
              <div className="ml-8 space-y-1 text-muted-foreground text-xs">
                <p>After creating the bot, BotFather will give you a token like:</p>
                <code className="block bg-muted px-2 py-1 rounded text-[11px] mt-1">xxxxxxxxx:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</code>
                <p className="mt-1">Copy this token and paste it in the <strong>Bot Token</strong> field.</p>
              </div>
            </div>

            {/* Step 3 */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="h-6 w-6 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center">3</span>
                <h4 className="font-medium">Get Your Chat ID</h4>
              </div>
              <div className="ml-8 space-y-2 text-muted-foreground text-xs">
                <p className="font-medium text-foreground/80">Option A: Using a Bot (Easiest)</p>
                <p>1. Search for <a href="https://t.me/userinfobot" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">@userinfobot</a> or <a href="https://t.me/getmyid_bot" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">@getmyid_bot</a> on Telegram</p>
                <p>2. Send any message and it will reply with your Chat ID</p>
                
                <p className="font-medium text-foreground/80 mt-2">Option B: Manual Method</p>
                <p>1. Send a message to your new bot</p>
                <p>2. Open this URL in your browser (replace YOUR_TOKEN):</p>
                <code className="block bg-muted px-2 py-1 rounded text-[11px] break-all">https://api.telegram.org/botYOUR_TOKEN/getUpdates</code>
                <p>3. Look for <code className="bg-muted px-1 rounded">"chat":&#123;"id": XXXXXX&#125;</code> - that number is your Chat ID</p>
              </div>
            </div>

            {/* Step 4 */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="h-6 w-6 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center">4</span>
                <h4 className="font-medium">For Groups or Channels</h4>
              </div>
              <div className="ml-8 space-y-1 text-muted-foreground text-xs">
                <p>1. Add your bot to the group/channel as administrator</p>
                <p>2. Send a message in the group</p>
                <p>3. Use the getUpdates URL method above to find the group Chat ID</p>
                <p>4. Group IDs are negative numbers (e.g., <code className="bg-muted px-1 rounded">-1001234567890</code>)</p>
              </div>
            </div>

            {/* Summary */}
            <div className="mt-4 p-3 rounded-md bg-blue-500/10 border border-blue-500/20">
              <p className="text-xs text-blue-400 font-medium mb-1">Quick Summary</p>
              <ul className="text-xs text-muted-foreground space-y-0.5">
                <li><strong>Bot Token:</strong> Identifies your bot (from BotFather)</li>
                <li><strong>Chat ID:</strong> Where to send messages (your ID or group ID)</li>
              </ul>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Custom Prompt Info Modal */}
      <Dialog open={showCustomPromptInfo} onOpenChange={setShowCustomPromptInfo}>
        <DialogContent className="max-w-[90vw] sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-lg">
              <Settings2 className="h-5 w-5 text-purple-400" />
              Custom Prompt Mode
            </DialogTitle>
            <DialogDescription className="text-muted-foreground">
              Create your own AI prompt for ProxMenux Monitor notifications
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 text-sm">
            <div className="space-y-2">
              <h4 className="font-medium text-foreground/90">What is a custom prompt?</h4>
              <p className="text-muted-foreground text-xs leading-relaxed">
                The prompt defines how the AI formats your notifications. With a custom prompt, you control the style, detail level, and format of all messages.
              </p>
            </div>
            
            <div className="space-y-2">
              <h4 className="font-medium text-foreground/90">Important requirements</h4>
              <ul className="text-muted-foreground text-xs space-y-1.5">
                <li className="flex items-start gap-2">
                  <span className="text-purple-400 mt-0.5">1.</span>
                  <span>Your prompt must output in this format:<br/>
                    <code className="bg-muted px-1.5 py-0.5 rounded text-[11px]">[TITLE]</code> followed by the title, then <code className="bg-muted px-1.5 py-0.5 rounded text-[11px]">[BODY]</code> followed by the message
                  </span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-purple-400 mt-0.5">2.</span>
                  <span>Use plain text only (no markdown) for compatibility with all channels</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-purple-400 mt-0.5">3.</span>
                  <span>The prompt receives raw Proxmox event data as input</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-purple-400 mt-0.5">4.</span>
                  <span>Define the output language in your prompt (the Language selector only applies to Default mode)</span>
                </li>
              </ul>
            </div>

            <div className="space-y-2">
              <h4 className="font-medium text-foreground/90">Getting started</h4>
              <p className="text-muted-foreground text-xs leading-relaxed">
                We have added an example prompt to get you started. You can adapt it, export it to share with others, or import prompts from the community.
              </p>
            </div>

            <div className="flex gap-2 pt-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  updateConfig(p => ({ ...p, ai_custom_prompt: EXAMPLE_CUSTOM_PROMPT }))
                  setCustomPromptDraft(EXAMPLE_CUSTOM_PROMPT)
                  setEditingCustomPrompt(true)
                  setShowCustomPromptInfo(false)
                }}
                className="flex-1"
              >
                Load Example
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setCustomPromptDraft("")
                  setEditingCustomPrompt(true)
                  setShowCustomPromptInfo(false)
                }}
                className="flex-1 bg-purple-600 hover:bg-purple-700 text-white"
              >
                Start from Scratch
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
