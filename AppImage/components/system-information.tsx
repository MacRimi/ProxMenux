"use client"

import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Cpu, CircuitBoard } from "lucide-react"
import { useI18n } from "../lib/i18n/provider"
import type { HardwareData } from "../types/hardware"

type TFunction = (key: string, params?: Record<string, string | number>) => string

// Values firmware leaves when the vendor filled nothing in.
const PLACEHOLDERS = new Set(["not specified", "not available", "to be filled by o.e.m.", "to be filled by oem", "default string", "system product name", "system manufacturer"])
const real = (value?: string | null) => {
  const text = value?.trim()
  return text && !PLACEHOLDERS.has(text.toLowerCase()) ? text : ""
}

// lscpu prints sizes as "256 KiB (8 instances)", "8 MiB" or, on older versions, "32K".
const toKiB = (value?: string | null): number => {
  const match = value?.match(/([\d.]+)\s*([KMG])?i?B?/i)
  if (!match) return 0
  const unit = (match[2] || "K").toUpperCase()
  return Number.parseFloat(match[1]) * (unit === "G" ? 1024 * 1024 : unit === "M" ? 1024 : 1)
}
const formatKiB = (kib: number): string => {
  const [value, unit] = kib >= 1024 * 1024 ? [kib / 1024 / 1024, "GiB"] : kib >= 1024 ? [kib / 1024, "MiB"] : [kib, "KiB"]
  return `${Number.isInteger(value) ? value : value.toFixed(1)} ${unit}`
}
const ghz = (mhz: number) => `${(mhz / 1000).toFixed(2).replace(/\.?0+$/, "")}`

// The BIOS date comes from dmidecode as MM/DD/YYYY.
const biosAge = (date: string | undefined, language: string): string => {
  const match = date?.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/)
  if (!match) return ""
  const released = new Date(Number(match[3]), Number(match[1]) - 1, Number(match[2]))
  const years = Math.floor((Date.now() - released.getTime()) / (365.25 * 24 * 3600 * 1000))
  try {
    const format = new Intl.RelativeTimeFormat(language, { numeric: "auto" })
    if (years >= 1) return format.format(-years, "year")
    const months = Math.max(0, Math.floor((Date.now() - released.getTime()) / (30.44 * 24 * 3600 * 1000)))
    return format.format(-months, "month")
  } catch {
    return ""
  }
}

function CacheBars({ levels }: { levels: { level: string; kib: number; color: string }[] }) {
  const largest = Math.max(...levels.map((item) => item.kib), 2)
  // Logarithmic: an L1 of a few hundred KiB stays visible next to an L3 of hundreds of MiB.
  return (
    <div className="space-y-1.5">
      {levels.map((item) => (
        <div key={item.level} className="grid grid-cols-[1.5rem_1fr_auto] items-center gap-2.5 text-xs">
          <span className="font-mono text-muted-foreground">{item.level}</span>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className={`h-full rounded-full ${item.color}`} style={{ width: `${Math.max(3, Math.log2(item.kib) / Math.log2(largest) * 100)}%` }} />
          </div>
          <span className="font-mono font-medium">{formatKiB(item.kib)}</span>
        </div>
      ))}
    </div>
  )
}

function CpuChip({ cores, threads, t }: { cores: number; threads: number; t: TFunction }) {
  const pins = [30, 45, 60, 75, 90].map((x) => `M${x} 4v10M${x} 106v10M4 ${x}h10M106 ${x}h10`).join("")
  return (
    <svg viewBox="0 0 120 120" className="h-auto w-[6.5rem] shrink-0" role="img" aria-label={`${cores} · ${threads}`}>
      <rect x="16" y="16" width="88" height="88" rx="10" className="fill-blue-500/10 stroke-blue-500" strokeWidth="2.5" />
      <path d={pins} className="stroke-blue-500" strokeWidth="2.5" />
      <text x="60" y="54" textAnchor="middle" className="fill-foreground" fontSize="26" fontWeight="700">{cores}</text>
      <text x="60" y="69" textAnchor="middle" className="fill-muted-foreground" fontSize="10.5">{t("hardware.systemInfo.coresWord")}</text>
      <text x="60" y="90" textAnchor="middle" className="fill-blue-500 font-mono" fontSize="13" fontWeight="600">{t("hardware.systemInfo.threads", { count: threads })}</text>
    </svg>
  )
}

// A landscape mainboard drawn in lines. The sockets and the memory slots it
// draws follow this machine; the rest is the same on every board.
function BoardSchematic({ sockets, modules, label }: { sockets: number; modules: number; label: string }) {
  const slots = Math.min(8, Math.max(2, modules))
  const step = slots > 4 ? 10 : 12
  const line = "fill-none stroke-zinc-500/70"
  const used = "fill-blue-500/20 stroke-blue-500"
  return (
    <svg viewBox="0 0 280 200" className="h-auto w-full" role="img" aria-label={label}>
      <rect x="4" y="4" width="272" height="192" rx="10" className={line} strokeWidth="2" />
      <rect x="14" y="16" width="30" height="78" rx="3" className={line} strokeWidth="2" />
      <path d="M20 28h18M20 40h18M20 52h18M20 64h18M20 76h18" className="stroke-zinc-500/70" strokeWidth="2" />
      {sockets > 1 ? (
        <>
          <rect x="56" y="30" width="50" height="50" rx="5" className={used} strokeWidth="2" />
          <rect x="114" y="30" width="50" height="50" rx="5" className={used} strokeWidth="2" />
          <rect x="70" y="44" width="22" height="22" rx="3" className="fill-none stroke-blue-500" strokeWidth="2" />
          <rect x="128" y="44" width="22" height="22" rx="3" className="fill-none stroke-blue-500" strokeWidth="2" />
        </>
      ) : (
        <>
          <rect x="68" y="22" width="86" height="86" rx="6" className={used} strokeWidth="2" />
          <rect x="88" y="42" width="46" height="46" rx="4" className="fill-none stroke-blue-500" strokeWidth="2" />
          <path d="M100 30v8M111 30v8M122 30v8M100 92v8M111 92v8M122 92v8M76 54h8M76 65h8M76 76h8M138 54h8M138 65h8M138 76h8" className="stroke-blue-500" strokeWidth="2" />
        </>
      )}
      {Array.from({ length: slots }, (_, index) => (
        <rect key={index} x={172 + index * step} y="18" width={slots > 4 ? 6 : 7} height="92" rx="1.5"
          className={index < modules ? used : line} strokeWidth="2" />
      ))}
      <rect x="200" y="132" width="30" height="30" rx="4" className={line} strokeWidth="2" />
      <path d="M207 147h16M215 139v16" className="stroke-zinc-500/70" strokeWidth="2" />
      <rect x="30" y="128" width="140" height="9" rx="2" className={line} strokeWidth="2" />
      <rect x="30" y="150" width="140" height="9" rx="2" className={line} strokeWidth="2" />
      <rect x="30" y="172" width="96" height="9" rx="2" className={line} strokeWidth="2" />
      <rect x="140" y="172" width="44" height="9" rx="2" className={line} strokeWidth="2" />
      <circle cx="252" cy="146" r="11" className={line} strokeWidth="2" />
      <g className="fill-zinc-500/70"><circle cx="16" cy="182" r="3" /><circle cx="262" cy="18" r="3" /><circle cx="262" cy="182" r="3" /></g>
    </svg>
  )
}

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="flex justify-between gap-4 text-sm">
    <span className="shrink-0 text-muted-foreground">{label}</span>
    <span className="min-w-0 text-right font-medium [overflow-wrap:anywhere]">{children}</span>
  </div>
)

export function SystemInformation({ data }: { data: HardwareData }) {
  const { t, language } = useI18n()
  const cpu = data.cpu && Object.keys(data.cpu).length > 0 ? data.cpu : null
  const board = data.motherboard && Object.keys(data.motherboard).length > 0 ? data.motherboard : null
  if (!cpu && !board) return null

  const sockets = Math.max(1, cpu?.sockets || 1)
  const perSocket = cpu?.cores_per_socket || 0
  const cores = perSocket * sockets
  const threads = cpu?.total_threads || 0
  const caches = [
    { level: "L1", kib: toKiB(cpu?.l1d_cache) + toKiB(cpu?.l1i_cache), color: "bg-cyan-500" },
    { level: "L2", kib: toKiB(cpu?.l2_cache), color: "bg-blue-500" },
    { level: "L3", kib: toKiB(cpu?.l3_cache), color: "bg-purple-500" },
  ].filter((item) => item.kib > 0)
  const minMHz = cpu?.min_mhz || 0
  const maxMHz = cpu?.max_mhz || 0
  const frequency = minMHz && maxMHz ? `${ghz(minMHz)} – ${ghz(maxMHz)} GHz` : maxMHz ? `${ghz(maxMHz)} GHz` : ""
  const socketText = t(sockets > 1 ? "hardware.systemInfo.sockets" : "hardware.systemInfo.socket", { count: sockets })
  const title = cpu?.model ? `${sockets > 1 ? `${sockets} × ` : ""}${cpu.model}` : "CPU"

  const boardName = [real(board?.manufacturer), real(board?.model)].filter(Boolean).join(" ")
  const biosVersion = real(board?.bios?.version)
  const biosVendor = real(board?.bios?.vendor)
  const biosDate = board?.bios?.date?.trim()
  const age = biosAge(biosDate, language)
  const modules = data.memory_modules?.length || 0

  const frequencyAndVirtualization = (
    <>
      {frequency && <Row label={t("hardware.systemInfo.frequency")}>{frequency}</Row>}
      {cpu?.virtualization && (
        <Row label={t("hardware.labels.virtualization")}>
          <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/20">{cpu.virtualization}</Badge>
        </Row>
      )}
    </>
  )

  return (
    <Card className="border-border/50 bg-card/50 p-6">
      <div className="mb-4 flex items-center gap-2">
        <Cpu className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold">{t("hardware.sections.systemInformation")}</h2>
        {cores > 0 && (
          <Badge variant="outline" className="ml-auto hidden whitespace-nowrap sm:inline-flex">{socketText} · {t("hardware.values.cores", { count: cores })}</Badge>
        )}
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        {cpu && (
          <div className="flex min-w-0 flex-col gap-4 rounded-lg border border-border/30 bg-background/60 p-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-semibold [overflow-wrap:anywhere]">
                <Cpu className="h-4 w-4 shrink-0 text-muted-foreground" />{title}
              </div>
              {perSocket > 0 && (
                <div className="mt-1 hidden pl-6 text-sm text-muted-foreground sm:block">
                  {t("hardware.values.cores", { count: perSocket })} · {t("hardware.systemInfo.threads", { count: Math.round(threads / sockets) })}
                </div>
              )}
            </div>

            {/* Desktop: one chip per socket with its cores and threads, the caches beside it. */}
            <div className="hidden flex-wrap items-center gap-4 sm:flex">
              {perSocket > 0 && (
                <div className="flex gap-2.5">
                  {Array.from({ length: sockets }, (_, index) => (
                    <CpuChip key={index} cores={perSocket} threads={Math.round(threads / sockets)} t={t} />
                  ))}
                </div>
              )}
              {caches.length > 0 && (
                <div className="min-w-[12rem] flex-1">
                  <div className="mb-2 text-xs text-muted-foreground">{t("hardware.systemInfo.cache")}</div>
                  <CacheBars levels={caches} />
                </div>
              )}
            </div>

            {/* Phone: the counts as figures, the caches below. */}
            <div className="flex flex-col gap-4 sm:hidden">
              <div className="grid grid-cols-3 gap-2">
                {[
                  [t("hardware.systemInfo.socketsLabel"), sockets],
                  [t("hardware.labels.cores"), cores],
                  [t("hardware.labels.threads"), threads],
                ].map(([label, value]) => (
                  <div key={String(label)} className="min-w-0 rounded-md bg-muted/50 px-3 py-2">
                    <div className="truncate text-xs text-muted-foreground">{label}</div>
                    <div className="text-xl font-bold tabular-nums">{value || "—"}</div>
                  </div>
                ))}
              </div>
              {caches.length > 0 && (
                <div>
                  <div className="mb-2 text-xs text-muted-foreground">{t("hardware.systemInfo.cache")}</div>
                  <CacheBars levels={caches} />
                </div>
              )}
            </div>

            {(frequency || cpu.virtualization) && (
              <div className="space-y-2 border-t border-border/50 pt-3">{frequencyAndVirtualization}</div>
            )}
          </div>
        )}

        {board && (
          <div className="flex min-w-0 flex-col gap-3 rounded-lg border border-border/30 bg-background/60 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <CircuitBoard className="h-4 w-4 shrink-0 text-muted-foreground" />{t("hardware.sections.motherboard")}
            </div>
            <div className="grid items-center gap-4 sm:grid-cols-[minmax(9rem,14rem)_1fr]">
              <div className="hidden sm:block">
                <BoardSchematic sockets={sockets} modules={modules} label={t("hardware.systemInfo.schematic")} />
                <div className="mt-1.5 flex flex-wrap justify-center gap-3 text-[11px] text-muted-foreground">
                  <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-sm border border-blue-500 bg-blue-500/40" />{socketText}</span>
                  {modules > 0 && (
                    <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-sm border border-blue-500 bg-blue-500/40" />{t("hardware.systemInfo.memoryModules", { count: modules })}</span>
                  )}
                </div>
              </div>
              <div className="min-w-0 space-y-2">
                <Row label={t("hardware.systemInfo.board")}>
                  {boardName || <span className="font-normal text-muted-foreground">{t("hardware.systemInfo.noBoardData")}</span>}
                </Row>
                {biosVersion && <Row label="BIOS">{biosVersion}</Row>}
                {biosDate && (
                  <Row label={t("hardware.systemInfo.biosDate")}>
                    {biosDate}{age && <span className="font-normal text-muted-foreground"> · {age}</span>}
                  </Row>
                )}
                {biosVendor && <Row label={t("hardware.systemInfo.biosVendor")}>{biosVendor}</Row>}
              </div>
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}
