"use client"

import { useEffect, useId, useRef, useState, type ComponentProps, type CSSProperties, type KeyboardEvent, type ReactElement, type ReactNode } from "react"
import * as Tooltip from "@radix-ui/react-tooltip"
import { ChevronDown, ChevronUp, ChevronsDownUp, ChevronsUpDown, GripVertical, TableProperties } from "lucide-react"
import { useT } from "@/lib/i18n/provider"
import { OptionSelect } from "./option-select"
import styles from "./vm-list-layout.module.css"

const columns = ["name", "type", "state", "tags", "ip", "uptime", "cpu", "memory", "disk", "net", "io", "updates"] as const
type Column = (typeof columns)[number]
type SortDirection = "asc" | "desc"
type ListSort = { column: Column; direction: SortDirection }
const storageKey = "proxmenux.vmListLayout.v1"
const identityColumns = ["name", "type"] as const
const optionalColumns: Column[] = ["state", "tags", "uptime", "net", "io"]
const minimumWidth: Record<Column, number> = {
  name: 80, type: 66, state: 78, tags: 66, ip: 104, uptime: 94,
  cpu: 44, memory: 52, disk: 42, net: 144, io: 144, updates: 38,
}
const maxWidth = 960
// On a phone the name takes what is left and the other columns share three
// spaces; the wider ones take two, so nothing has to be cut short. Updates
// take no space: they show as a violet line next to the status line.
const phoneQuery = "(max-width: 639px)"
const phoneSpaces = 3
const phoneDefault: Column[] = ["cpu", "memory", "disk", "updates"]
const phoneCost: Record<Column, number> = {
  name: 0, type: 2, state: 2, tags: 1, ip: 2, uptime: 1,
  cpu: 1, memory: 1, disk: 1, net: 2, io: 2, updates: 0,
}
const phoneTracks: Record<Column, string> = {
  name: "minmax(0, 1fr)", type: "84px", state: "92px", tags: "56px", ip: "112px", uptime: "56px",
  cpu: "52px", memory: "52px", disk: "52px", net: "104px", io: "104px", updates: "44px",
}
const phoneUsed = (selection: Column[]) => selection.reduce((total, key) => total + phoneCost[key], 0)

function phoneSelection(value: unknown): Column[] {
  if (!Array.isArray(value)) return phoneDefault
  const result: Column[] = []
  for (const key of columns) {
    if (key !== "name" && value.includes(key) && phoneUsed([...result, key]) <= phoneSpaces) result.push(key)
  }
  return result
}

function usePhone() {
  const [phone, setPhone] = useState(false)
  useEffect(() => {
    const query = window.matchMedia(phoneQuery)
    const update = () => setPhone(query.matches)
    update()
    query.addEventListener("change", update)
    return () => query.removeEventListener("change", update)
  }, [])
  return phone
}
const tracks: Record<Column, [string, string?, string?]> = {
  name: ["minmax(92px, 1.8fr)", "minmax(84px, 1fr)", "minmax(68px, 1fr)"],
  type: ["88px", "84px", "58px"],
  state: ["86px", "82px"],
  tags: ["70px", "66px"],
  ip: ["minmax(118px, 1fr)"],
  uptime: ["102px", "94px"],
  cpu: ["60px", "59px"],
  memory: ["77px", "71px"],
  disk: ["61px", "61px"],
  net: ["152px", "144px"],
  io: ["152px", "144px"],
  updates: ["55px", "53px", "40px"],
}

type Layout = {
  order: Column[]
  hidden: Column[]
  widths: Partial<Record<Column, number>>
  expanded: boolean
  exceptions: string[]
  sort: ListSort | null
  phone: Column[]
}
const initialLayout: Layout = {
  order: [...columns], hidden: optionalColumns, widths: {}, expanded: false, exceptions: [], sort: null, phone: phoneDefault,
}

function readLayout(): Layout {
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return initialLayout
    const saved = JSON.parse(raw) as Partial<Layout> | null
    const order = Array.isArray(saved?.order) ? [...new Set(saved.order.filter((key) => columns.includes(key)))] : []
    const hidden = columns.filter((key) => (
      (Array.isArray(saved?.hidden) && saved.hidden.includes(key))
      || (optionalColumns.includes(key) && !order.includes(key))
    ))
    const widths: Layout["widths"] = {}
    for (const key of columns) {
      const width = saved?.widths?.[key]
      if (typeof width === "number" && Number.isFinite(width)) {
        widths[key] = Math.max(minimumWidth[key], Math.min(maxWidth, Math.round(width)))
      }
    }
    const sort = saved?.sort
    return {
      order: [...order, ...columns.filter((key) => !order.includes(key))],
      hidden: identityColumns.every((key) => hidden.includes(key)) ? hidden.filter((key) => key !== "name") : hidden,
      widths,
      expanded: saved?.expanded === true,
      exceptions: Array.isArray(saved?.exceptions)
        ? [...new Set(saved.exceptions.filter((key) => typeof key === "string" && /^(?:lxc|qemu):[0-9]+$/.test(key)))]
        : [],
      sort: sort && columns.includes(sort.column) && !hidden.includes(sort.column) &&
        (sort.direction === "asc" || sort.direction === "desc") ? sort : null,
      phone: phoneSelection(saved?.phone),
    }
  } catch {
    return initialLayout
  }
}

export function useVmListLayout() {
  const [saved, setSaved] = useState<Layout | null>(null)
  useEffect(() => setSaved(readLayout()), [])
  useEffect(() => {
    if (!saved) return
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(saved))
    } catch {
      // The list still works for the current visit when local storage is unavailable.
    }
  }, [saved])

  const layout = saved ?? initialLayout
  const phone = usePhone()
  const change = (update: (current: Layout) => Layout) => setSaved((current) => update(current ?? initialLayout))
  const exceptions = new Set(layout.exceptions)
  const isExpanded = (key: string) => layout.expanded !== exceptions.has(key)
  const setExpanded = (keys: string[], expanded: boolean) => change((current) => {
    const next = new Set(current.exceptions)
    for (const key of keys) {
      if (expanded === current.expanded) next.delete(key)
      else next.add(key)
    }
    return { ...current, exceptions: [...next] }
  })

  const visible = phone
    ? layout.order.filter((key) => key === "name" || (key !== "updates" && layout.phone.includes(key)))
    : layout.order.filter((key) => !layout.hidden.includes(key))
  return {
    ...layout,
    phone,
    phoneColumns: layout.phone,
    phoneFree: phoneSpaces - phoneUsed(layout.phone),
    updateLine: phone && layout.phone.includes("updates"),
    visible,
    isExpanded,
    toggleRow: (key: string) => setExpanded([key], !isExpanded(key)),
    toggleAll: (keys: string[], expanded: boolean, filtered: boolean) => {
      if (filtered) setExpanded(keys, expanded)
      else change((current) => ({ ...current, expanded, exceptions: [] }))
    },
    toggleColumn: (column: Column) => change((current) => {
      if (phone) {
        if (column === "name") return current
        const selection = current.phone.includes(column)
          ? current.phone.filter((key) => key !== column)
          : phoneSelection([...current.phone, column])
        if (!selection.includes(column) && !current.phone.includes(column)) return current
        const sort = current.sort?.column === column && !selection.includes(column) ? null : current.sort
        return { ...current, phone: selection, sort }
      }
      const hidden = current.hidden.includes(column)
        ? current.hidden.filter((key) => key !== column)
        : [...current.hidden, column]
      if (identityColumns.every((key) => hidden.includes(key))) return current
      const sort = current.sort?.column === column && hidden.includes(column) ? null : current.sort
      return { ...current, hidden, sort }
    }),
    setSort: (sort: ListSort | null) => change((current) => ({ ...current, sort })),
    cycleSort: (column: Column) => change((current) => {
      const first = ["name", "type", "state", "tags", "ip"].includes(column) ? "asc" : "desc"
      const second = first === "asc" ? "desc" : "asc"
      const sort: ListSort | null = current.sort?.column !== column ? { column, direction: first }
        : current.sort.direction === first ? { column, direction: second } : null
      return { ...current, sort }
    }),
    moveColumn: (from: Column, to: Column) => change((current) => {
      if (from === to) return current
      const order = current.order.filter((key) => key !== from)
      order.splice(current.order.indexOf(to), 0, from)
      return { ...current, order }
    }),
    resizeColumn: (column: Column, width: number) => change((current) => ({
      ...current,
      widths: { ...current.widths, [column]: width },
    })),
  }
}

export function sortVmRows<T>(
  rows: T[],
  sort: ListSort | null,
  language: string,
  getValue: (row: T, column: Column) => string | number | undefined,
) {
  if (!sort) return rows
  const collator = new Intl.Collator(language, { numeric: true, sensitivity: "base" })
  const sortKey = (row: T) => {
    const value = getValue(row, sort.column)
    return typeof value === "number" && !Number.isFinite(value) ? undefined : value
  }
  return rows.map((row) => ({ row, value: sortKey(row) })).sort((left, right) => {
    const a = left.value
    const b = right.value
    if (a === undefined || b === undefined) return Number(a === undefined) - Number(b === undefined)
    const result = typeof a === "number" && typeof b === "number" ? a - b : collator.compare(String(a), String(b))
    return sort.direction === "asc" ? result : -result
  }).map(({ row }) => row)
}

type ListLayout = ReturnType<typeof useVmListLayout>
type DraftWidth = { column: Column; width: number }

export function VmListToolbar({ actions, search, types, status }: {
  actions: ReactElement
  search: ReactElement
  types: ReactElement
  status: ReactElement
}) {
  const toolbar = useRef<HTMLDivElement>(null)
  const [tablet, setTablet] = useState(false)
  useEffect(() => {
    if (!toolbar.current) return
    const observer = new ResizeObserver(([entry]) => {
      const width = entry.contentRect.width
      setTablet(width >= 872 && width < 1040)
    })
    observer.observe(toolbar.current)
    return () => observer.disconnect()
  }, [])

  return (
    <div ref={toolbar} className={styles.toolbar} data-layout={tablet ? "tablet" : undefined}>
      {tablet ? [search, types, status, actions] : [actions, search, types, status]}
    </div>
  )
}

export function VmListActions({ layout, keys, filtered, pickerId, pickerOpen, onTogglePicker }: {
  layout: ListLayout
  keys: string[]
  filtered: boolean
  pickerId: string
  pickerOpen: boolean
  onTogglePicker: () => void
}) {
  const t = useT()
  const expand = t(filtered ? "vmLxc.layout.expandVisible" : "vmLxc.layout.expandAll")
  const collapse = t(filtered ? "vmLxc.layout.collapseVisible" : "vmLxc.layout.collapseAll")
  const settings = t("vmLxc.layout.settings")
  // In the standard view every card is open and there are no columns to choose.
  const standard = keys.length > 0 && keys.every(layout.isExpanded)
  const button = "inline-flex size-11 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40 sm:size-9"

  return (
    <div role="group" aria-label={t("vmLxc.layout.controls")} className="flex shrink-0 gap-1">
      <button type="button" className={button} title={settings} aria-label={settings}
        aria-controls={pickerId} aria-expanded={pickerOpen && !standard} disabled={standard} onClick={onTogglePicker}>
        <TableProperties aria-hidden="true" className="size-4" />
      </button>
      <button type="button" className={button} title={expand} aria-label={expand}
        disabled={keys.every(layout.isExpanded)} onClick={() => layout.toggleAll(keys, true, filtered)}>
        <ChevronsUpDown aria-hidden="true" className="size-4" />
      </button>
      <button type="button" className={button} title={collapse} aria-label={collapse}
        disabled={keys.every((key) => !layout.isExpanded(key))} onClick={() => layout.toggleAll(keys, false, filtered)}>
        <ChevronsDownUp aria-hidden="true" className="size-4" />
      </button>
    </div>
  )
}

export function VmListColumnPicker({ id, open, layout }: { id: string; open: boolean; layout: ListLayout }) {
  const t = useT()
  return (
    <fieldset id={id} hidden={!open} className="min-w-0 rounded-md border border-border px-3 pb-2">
      <legend className="px-1 text-sm font-medium">{t("vmLxc.layout.visibleColumns")}</legend>
      <div className="flex flex-wrap gap-x-4">
        {layout.order.filter((key) => !layout.phone || key !== "name").map((key) => {
          const visible = layout.phone ? layout.phoneColumns.includes(key) : !layout.hidden.includes(key)
          const required = !layout.phone && (key === "name" || key === "type")
            && identityColumns.some((item) => layout.hidden.includes(item))
          const full = layout.phone && !visible && phoneCost[key] > layout.phoneFree
          return (
            <label key={key} className={`flex min-h-11 items-center gap-2 text-sm sm:min-h-9 ${full ? "text-muted-foreground" : ""}`}>
              <input type="checkbox" checked={visible} disabled={(visible && required) || full}
                onChange={() => layout.toggleColumn(key)} className="size-4 accent-primary" />
              {t(`vmLxc.layout.columns.${key}`)}
            </label>
          )
        })}
      </div>
      <div className={styles.mobileSort}>
        <span aria-hidden="true">{t("vmLxc.layout.sortBy")}</span>
        <OptionSelect
          ariaLabel={t("vmLxc.layout.sortBy")}
          className="min-h-11"
          value={layout.sort ? `${layout.sort.column}:${layout.sort.direction}` : ""}
          onChange={(value) => {
            const [name, direction] = value.split(":")
            const column = layout.visible.find((key) => key === name)
            layout.setSort(column && (direction === "asc" || direction === "desc") ? { column, direction } : null)
          }}
          options={[
            { value: "", label: t("vmLxc.layout.originalOrder") },
            ...layout.visible.flatMap((column) => (["asc", "desc"] as const).map((direction) => ({
              value: `${column}:${direction}`,
              label: `${t(`vmLxc.layout.columns.${column}`)} · ${t(`vmLxc.layout.${direction}`)}`,
            }))),
          ]}
        />
      </div>
      {!layout.phone && <p className="text-xs text-muted-foreground">{t("vmLxc.layout.keepIdentity")}</p>}
    </fieldset>
  )
}

function visibilityClass(column: Column) {
  if (column === "ip") return styles.ip
  return tracks[column][2] === undefined ? styles.metric : undefined
}

export function VmListGrid({ layout, headings: showHeadings = true, children }: {
  layout: ListLayout
  headings?: boolean
  children: ReactNode
}) {
  const t = useT()
  const [draft, setDraft] = useState<DraftWidth | null>(null)
  const [drop, setDrop] = useState<{ column: Column; side: "before" | "after" } | null>(null)
  const dragging = useRef<Column | null>(null)
  const resizing = useRef<{ id: number; x: number; start: number; column: Column } | null>(null)
  const headings = useRef(new Map<Column, HTMLButtonElement>())
  const focusAfterMove = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    focusAfterMove.current?.focus()
    focusAfterMove.current = null
  }, [layout.order])
  const columnWidth = (column: Column, width: number) =>
    Math.max(minimumWidth[column], Math.min(maxWidth, Math.round(width)))
  const resizeBy = (column: Column, event: { currentTarget: HTMLButtonElement }, delta: number) => {
    const start = event.currentTarget.parentElement?.getBoundingClientRect().width
    if (start !== undefined) layout.resizeColumn(column, columnWidth(column, start + delta))
  }
  const phoneWidths = layout.visible.map((column) => phoneTracks[column])
  const stylesForTracks = ["wide", "medium", "narrow"].flatMap((name, viewport) => {
    const widths = layout.visible.map((column) => {
      const width = draft?.column === column ? draft.width : layout.widths[column]
      return viewport === 0 && width !== undefined ? `${width}px` : tracks[column][viewport]
    }).filter((width): width is string => width !== undefined)
    const gap = viewport === 0 ? 8 : 5
    const minimum = widths.reduce((total, width) => total + Number(width.match(/\d+(?=px)/)?.[0]), 20)
    return [
      [`--vm-list-${name}`, widths.join(" ")],
      [`--vm-list-min-${name}`, `${minimum + Math.max(0, widths.length - 1) * gap}px`],
    ]
  })
  const clearDrag = () => {
    dragging.current = null
    setDrop(null)
  }
  const clearResize = (pointerId: number) => {
    if (resizing.current?.id !== pointerId) return
    resizing.current = null
    setDraft(null)
  }
  const moveByKeyboard = (event: KeyboardEvent<HTMLButtonElement>, column: Column) => {
    if (!event.shiftKey || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return
    event.preventDefault()
    const shown = layout.visible.filter((key) => headings.current.get(key)?.getClientRects().length)
    const target = shown[shown.indexOf(column) + (event.key === "ArrowLeft" ? -1 : 1)]
    if (!target) return
    focusAfterMove.current = event.currentTarget
    layout.moveColumn(column, target)
  }

  return (
    <div className={styles.inventory} role="region" aria-label={t("vmLxc.listTitle")} data-phone={layout.phone || undefined}
      data-updates={layout.updateLine || undefined}
      style={{ ...Object.fromEntries(stylesForTracks), "--vm-list-phone": phoneWidths.join(" ") } as CSSProperties}>
      <div className={`${styles.grid} ${styles.headings}`} role="group" aria-label={t("vmLxc.layout.visibleColumns")}
        hidden={!showHeadings}>
        {layout.visible.map((column) => {
          const label = t(`vmLxc.layout.columns.${column}`)
          const resize = t("vmLxc.layout.resizeColumn", { column: label })
          const move = t("vmLxc.layout.moveColumn", { column: label })
          const direction = layout.sort?.column === column ? layout.sort.direction : undefined
          const sortLabel = direction ? `${label}, ${t(`vmLxc.layout.${direction}`)}` : label
          return (
            <div key={column} className={`${styles.headingCell} ${visibilityClass(column) ?? ""}`}
                data-drop={drop?.column === column ? drop.side : undefined}
                onDragOver={(event) => {
                  const from = dragging.current
                  if (!from || from === column) return
                  event.preventDefault()
                  event.dataTransfer.dropEffect = "move"
                  const side = layout.order.indexOf(from) < layout.order.indexOf(column) ? "after" : "before"
                  setDrop((current) => current?.column === column && current.side === side ? current : { column, side })
                }}
                onDragLeave={(event) => {
                  if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return
                  setDrop((current) => current?.column === column ? null : current)
                }}
                onDrop={(event) => {
                  if (!dragging.current) return
                  event.preventDefault()
                  layout.moveColumn(dragging.current, column)
                  clearDrag()
                }}>
              <button type="button" draggable className={styles.drag} aria-label={move} title={move}
                aria-keyshortcuts="Shift+ArrowLeft Shift+ArrowRight"
                onDragStart={(event) => {
                  dragging.current = column
                  event.dataTransfer.setData("text/plain", column)
                  event.dataTransfer.effectAllowed = "move"
                }}
                onDragEnd={clearDrag}
                onKeyDown={(event) => moveByKeyboard(event, column)}>
                <GripVertical aria-hidden="true" className="pointer-events-none size-3.5" />
              </button>
              <button type="button" className={styles.heading} data-sort-column={column} data-sort-direction={direction}
                aria-label={sortLabel} aria-pressed={Boolean(direction)} title={t("vmLxc.layout.sortColumn", { column: label })}
                aria-keyshortcuts="Shift+ArrowLeft Shift+ArrowRight"
                ref={(node) => { if (node) headings.current.set(column, node); else headings.current.delete(column) }}
                onClick={() => layout.cycleSort(column)} onKeyDown={(event) => moveByKeyboard(event, column)}>
                <span>{column === "updates" ? t("vmLxc.layout.updatesShort") : label}</span>
                {direction === "asc" && <ChevronUp className="size-3 shrink-0" aria-hidden="true" />}
                {direction === "desc" && <ChevronDown className="size-3 shrink-0" aria-hidden="true" />}
              </button>
              <button type="button" className={styles.resize} aria-label={resize} title={resize}
                aria-keyshortcuts="ArrowLeft ArrowRight"
                onPointerDown={(event) => {
                  if (event.button !== 0 || resizing.current) return
                  const start = event.currentTarget.parentElement?.getBoundingClientRect().width
                  if (start === undefined) return
                  event.preventDefault()
                  event.currentTarget.focus()
                  event.currentTarget.setPointerCapture(event.pointerId)
                  resizing.current = { id: event.pointerId, x: event.clientX, start, column }
                }}
                onPointerMove={(event) => {
                  const current = resizing.current
                  if (!current || current.id !== event.pointerId || current.column !== column) return
                  const delta = Math.round(event.clientX - current.x)
                  setDraft(delta === 0 ? null : { column, width: columnWidth(column, current.start + delta) })
                }}
                onPointerUp={(event) => {
                  const current = resizing.current
                  if (!current || current.id !== event.pointerId || current.column !== column) return
                  const delta = Math.round(event.clientX - current.x)
                  if (delta) layout.resizeColumn(column, columnWidth(column, current.start + delta))
                  clearResize(event.pointerId)
                }}
                onPointerCancel={(event) => clearResize(event.pointerId)}
                onLostPointerCapture={(event) => clearResize(event.pointerId)}
                onKeyDown={(event) => {
                  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return
                  event.preventDefault()
                  resizeBy(column, event, event.key === "ArrowLeft" ? -8 : 8)
                }} />
            </div>
          )
        })}
      </div>
      <Tooltip.Provider delayDuration={450} disableHoverableContent>
        <div className={styles.rows}>{children}</div>
      </Tooltip.Provider>
    </div>
  )
}

export function VmCardTooltip({ label, children }: { label: string; children: ReactElement }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const timeout = window.setTimeout(() => setOpen(false), 2500)
    return () => window.clearTimeout(timeout)
  }, [open])

  return (
    <Tooltip.Root open={open} onOpenChange={setOpen}>
      <Tooltip.Trigger asChild data-vm-card-tooltip
        onFocus={(event) => {
          if (!event.currentTarget.matches(":focus-visible")) event.preventDefault()
        }}
        onPointerMove={(event) => {
          if (event.target instanceof Element && event.target.closest("[data-vm-card-tooltip]") !== event.currentTarget) {
            event.preventDefault()
          }
        }}>
        {children}
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content sideOffset={6} collisionPadding={8}
          className="pointer-events-none z-50 max-w-72 rounded-md border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-sm">
          {label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

type CardProps = ComponentProps<"div"> & { "aria-label": string }

// A guest opens its details from the compact row and from its card alike;
// the toolbar chooses between the compact and the standard view.
export function VmListRow({ layout, guestKey, name, status, statusLabel, updates, cells, onOpen, onPreview, children }: {
  layout: ListLayout
  guestKey: string
  name: string
  status: string
  statusLabel: string
  updates?: number
  cells: Record<Column, ReactNode>
  onOpen: (trigger: HTMLElement) => void
  onPreview?: () => void
  children: (card: CardProps) => ReactNode
}) {
  const t = useT()
  const cardId = useId()
  const statusId = `${cardId}-status`
  const open = layout.isExpanded(guestKey)
  const statusColor = status === "running" ? "text-green-500" : status === "stopped" ? "text-red-500" : "text-muted-foreground"
  const openLabel = t("vmLxc.layout.openGuestInfo", { name })
  return (
    <div>
      {!open && <button type="button" className={`${styles.grid} ${styles.row}`} aria-haspopup="dialog"
        aria-label={openLabel}
        aria-describedby={[statusId, ...(layout.updateLine && updates ? [`${cardId}-updates`] : []),
          ...layout.visible.filter((key) => key !== "name").map((key) => `${cardId}-${key}`)].join(" ")}
        onMouseEnter={onPreview}
        onClick={(event) => onOpen(event.currentTarget)}>
        <VmCardTooltip label={statusLabel}>
          <span aria-hidden="true" className={`${styles.statusStripe} ${statusColor}`} />
        </VmCardTooltip>
        {layout.updateLine && updates ? (
          <span aria-hidden="true" className={`${styles.updateStripe} text-violet-500`} />
        ) : null}
        {layout.visible.map((key) => {
          const cell = (
            <span key={key} id={`${cardId}-${key}`} className={`${styles.cell} ${visibilityClass(key) ?? ""}`}>
              {cells[key]}
            </span>
          )
          return key === "name" ? <VmCardTooltip key={key} label={name}>{cell}</VmCardTooltip> : cell
        })}
      </button>}
      <span id={statusId} className="sr-only">{statusLabel}</span>
      {layout.updateLine && updates ? (
        <span id={`${cardId}-updates`} className="sr-only">{`${t("vmLxc.layout.columns.updates")}: ${updates}`}</span>
      ) : null}
      <div className={styles.expandedCard} id={cardId} hidden={!open}>
        {open && children({
          role: "button",
          tabIndex: 0,
          "aria-label": openLabel,
          "aria-describedby": statusId,
          "aria-haspopup": "dialog",
          onMouseEnter: onPreview,
          onClick: (event) => onOpen(event.currentTarget),
          onKeyDown: (event) => {
            if (event.target !== event.currentTarget || (event.key !== "Enter" && event.key !== " ")) return
            event.preventDefault()
            onOpen(event.currentTarget)
          },
        })}
      </div>
    </div>
  )
}

// A phone has no column headings, so a reading shows what it measures with an
// icon and its bar instead of a bare percentage.
export function VmListMetric({ value, color, fill, icon, label, phone }: {
  value: number
  color: string
  fill: string
  icon: ReactNode
  label: string
  phone: boolean
}) {
  const reading = Number.isFinite(value) ? `${value.toFixed(1)}%` : "—"
  return (
    <span className={`${styles.reading} ${color}`}>
      {phone ? (
        <span className="flex items-center">
          {icon}
          <span className="sr-only">{`${label} ${reading}`}</span>
        </span>
      ) : reading}
      <span className={styles.track} aria-hidden="true">
        <span className={fill} style={{ width: `${Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0}%` }} />
      </span>
    </span>
  )
}

export function VmListTransfer({ counters, maximum, label, format }: {
  counters: readonly [number | undefined, number | undefined]
  maximum: number
  label: (first: string, second: string) => string
  format: (value: number) => string
}) {
  if (counters.every((value) => value === undefined)) return "—"
  const display = counters.map((value) => value === undefined ? "—" : format(value))
  const description = label(display[0], display[1])
  return (
    <VmCardTooltip label={description}>
      <span className={styles.transfer} role="img" aria-label={description}>
        {counters.map((value, index) => (
          <span className={styles.reading} key={index} aria-hidden="true">
            <span className="truncate">{index === 0 ? "↓" : "↑"} {display[index]}</span>
            <span className={styles.track}>
              <span className={index === 0 ? "bg-green-500" : "bg-blue-500"} style={{ width: `${100 * (value ?? 0) / maximum}%` }} />
            </span>
          </span>
        ))}
      </span>
    </VmCardTooltip>
  )
}
