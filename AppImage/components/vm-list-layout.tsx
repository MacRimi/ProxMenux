"use client"

import { useEffect, useId, useRef, useState, type ComponentProps, type CSSProperties, type KeyboardEvent, type ReactElement, type ReactNode } from "react"
import * as Tooltip from "@radix-ui/react-tooltip"
import { ChevronDown, ChevronUp, ChevronsDownUp, ChevronsUpDown, GripVertical, TableProperties } from "lucide-react"
import { useT } from "@/lib/i18n/provider"
import styles from "./vm-list-layout.module.css"

const columns = ["name", "type", "ip", "cpu", "memory", "disk", "updates"] as const
type Column = (typeof columns)[number]
type SortDirection = "asc" | "desc"
type ListSort = { column: Column; direction: SortDirection }
const storageKey = "proxmenux.vmListLayout.v1"
const identityColumns = ["name", "type"] as const
const minimumWidth: Record<Column, number> = { name: 80, type: 66, ip: 104, cpu: 44, memory: 52, disk: 42, updates: 38 }
const maxWidth = 960
const tracks: Record<Column, [string, string?, string?]> = {
  name: ["minmax(92px, 1.8fr)", "minmax(84px, 1fr)", "minmax(68px, 1fr)"],
  type: ["88px", "84px", "58px"],
  ip: ["minmax(118px, 1fr)"],
  cpu: ["60px", "59px"],
  memory: ["77px", "71px"],
  disk: ["61px", "61px"],
  updates: ["55px", "53px", "40px"],
}

type Layout = {
  order: Column[]
  hidden: Column[]
  widths: Partial<Record<Column, number>>
  expanded: boolean
  exceptions: string[]
  sort: ListSort | null
}
const initialLayout: Layout = { order: [...columns], hidden: [], widths: {}, expanded: false, exceptions: [], sort: null }

function readLayout(): Layout {
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return initialLayout
    const saved = JSON.parse(raw) as Partial<Layout> | null
    const order = Array.isArray(saved?.order) ? [...new Set(saved.order.filter((key) => columns.includes(key)))] : []
    const hidden = columns.filter((key) => Array.isArray(saved?.hidden) && saved.hidden.includes(key))
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

  return {
    ...layout,
    visible: layout.order.filter((key) => !layout.hidden.includes(key)),
    isExpanded,
    toggleRow: (key: string) => setExpanded([key], !isExpanded(key)),
    toggleAll: (keys: string[], expanded: boolean, filtered: boolean) => {
      if (filtered) setExpanded(keys, expanded)
      else change((current) => ({ ...current, expanded, exceptions: [] }))
    },
    toggleColumn: (column: Column) => change((current) => {
      const hidden = current.hidden.includes(column)
        ? current.hidden.filter((key) => key !== column)
        : [...current.hidden, column]
      if (identityColumns.every((key) => hidden.includes(key))) return current
      const sort = current.sort?.column === column && hidden.includes(column) ? null : current.sort
      return { ...current, hidden, sort }
    }),
    setSort: (sort: ListSort | null) => change((current) => ({ ...current, sort })),
    cycleSort: (column: Column) => change((current) => {
      const first = column === "name" || column === "type" || column === "ip" ? "asc" : "desc"
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
  const button = "inline-flex size-11 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40 sm:size-9"

  return (
    <div role="group" aria-label={t("vmLxc.layout.controls")} className="flex shrink-0 gap-1">
      <button type="button" className={button} title={settings} aria-label={settings}
        aria-controls={pickerId} aria-expanded={pickerOpen} onClick={onTogglePicker}>
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
        {layout.order.map((key) => {
          const visible = !layout.hidden.includes(key)
          const required = (key === "name" || key === "type") && identityColumns.some((item) => layout.hidden.includes(item))
          return (
            <label key={key} className="flex min-h-11 items-center gap-2 text-sm sm:min-h-9">
              <input type="checkbox" checked={visible} disabled={visible && required} onChange={() => layout.toggleColumn(key)}
                className="size-4 accent-primary" />
              {t(`vmLxc.layout.columns.${key}`)}
            </label>
          )
        })}
      </div>
      <label className={styles.mobileSort}>
        {t("vmLxc.layout.sortBy")}
        <select className="min-h-11 rounded-md border border-border bg-card px-2"
          value={layout.sort ? `${layout.sort.column}:${layout.sort.direction}` : ""}
          onChange={(event) => {
            const [name, direction] = event.target.value.split(":")
            const column = layout.visible.find((key) => key === name)
            layout.setSort(column && (direction === "asc" || direction === "desc") ? { column, direction } : null)
          }}>
          <option value="">{t("vmLxc.layout.originalOrder")}</option>
          {layout.visible.flatMap((column) => (["asc", "desc"] as const).map((direction) => (
            <option key={`${column}:${direction}`} value={`${column}:${direction}`}>
              {t(`vmLxc.layout.columns.${column}`)} · {t(`vmLxc.layout.${direction}`)}
            </option>
          )))}
        </select>
      </label>
      <p className="text-xs text-muted-foreground">{t("vmLxc.layout.keepIdentity")}</p>
    </fieldset>
  )
}

function visibilityClass(column: Column) {
  if (column === "ip") return styles.ip
  return column === "cpu" || column === "memory" || column === "disk" ? styles.metric : undefined
}

export function VmListGrid({ layout, children }: { layout: ListLayout; children: ReactNode }) {
  const t = useT()
  const [draft, setDraft] = useState<DraftWidth | null>(null)
  const [drop, setDrop] = useState<{ column: Column; side: "before" | "after" } | null>(null)
  const dragging = useRef<Column | null>(null)
  const resizing = useRef<{ id: number; x: number; start: number; column: Column } | null>(null)
  const headings = useRef(new Map<Column, HTMLButtonElement>())
  const grid = useRef<HTMLDivElement>(null)
  const focusAfterMove = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    focusAfterMove.current?.focus()
    focusAfterMove.current = null
  }, [layout.order])
  const columnWidth = (column: Column, width: number) =>
    Math.max(minimumWidth[column], Math.min(maxWidth, (grid.current?.clientWidth ?? maxWidth) - 20, Math.round(width)))
  const resizeBy = (column: Column, event: { currentTarget: HTMLButtonElement }, delta: number) => {
    const start = event.currentTarget.parentElement?.getBoundingClientRect().width
    if (start !== undefined) layout.resizeColumn(column, columnWidth(column, start + delta))
  }
  const stylesForTracks = ["--vm-list-wide", "--vm-list-medium", "--vm-list-narrow"].map((name, viewport) => [
    name,
    layout.visible.map((column) => {
      const width = draft?.column === column ? draft.width : layout.widths[column]
      return viewport === 0 && width !== undefined ? `minmax(${minimumWidth[column]}px, ${width}px)` : tracks[column][viewport]
    }).filter(Boolean).join(" "),
  ])
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
    <div className={styles.inventory} style={Object.fromEntries(stylesForTracks) as CSSProperties} ref={grid}>
      <div className={`${styles.grid} ${styles.headings}`} role="group" aria-label={t("vmLxc.layout.visibleColumns")}>
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

type CollapseButtonProps = ComponentProps<"button"> & { "aria-label": string; "data-collapse-guest": true }

export function VmListRow({ layout, guestKey, name, status, statusLabel, cells, children }: {
  layout: ListLayout
  guestKey: string
  name: string
  status: string
  statusLabel: string
  cells: Record<Column, ReactNode>
  children: (collapseButton: CollapseButtonProps) => ReactNode
}) {
  const t = useT()
  const cardId = useId()
  const statusId = `${cardId}-status`
  const open = layout.isExpanded(guestKey)
  const statusColor = status === "running" ? "text-green-500" : status === "stopped" ? "text-red-500" : "text-muted-foreground"
  const rowRef = useRef<HTMLButtonElement>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const moveFocus = useRef(false)
  useEffect(() => {
    if (!moveFocus.current) return
    moveFocus.current = false
    const collapseButtons = cardRef.current?.querySelectorAll<HTMLButtonElement>("[data-collapse-guest]")
    const target = open && collapseButtons
      ? Array.from(collapseButtons).find((button) => button.getClientRects().length > 0)
      : rowRef.current
    target?.focus({ preventScroll: true })
  }, [open])

  const toggleRow = () => {
    moveFocus.current = true
    layout.toggleRow(guestKey)
  }
  const collapseLabel = t("vmLxc.layout.collapseGuest", { name })
  return (
    <div>
      {!open && <button ref={rowRef} type="button" className={`${styles.grid} ${styles.row}`} aria-expanded={false} aria-controls={cardId}
        aria-label={t("vmLxc.layout.expandGuest", { name })}
        aria-describedby={[statusId, ...layout.visible.filter((key) => key !== "name").map((key) => `${cardId}-${key}`)].join(" ")}
        onClick={toggleRow}>
        <VmCardTooltip label={statusLabel}>
          <span aria-hidden="true" className={`${styles.statusStripe} ${statusColor}`} />
        </VmCardTooltip>
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
      <div ref={cardRef} id={cardId} hidden={!open}>
        {open && children({
          type: "button",
          "aria-label": collapseLabel,
          "aria-describedby": statusId,
          "aria-expanded": true,
          "data-collapse-guest": true,
          onClick: toggleRow,
        })}
      </div>
    </div>
  )
}

export function VmListMetric({ value, color, fill }: { value: number; color: string; fill: string }) {
  return (
    <span className={`${styles.reading} ${color}`}>
      {Number.isFinite(value) ? `${value.toFixed(1)}%` : "—"}
      <span className={styles.track} aria-hidden="true">
        <span className={fill} style={{ width: `${Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0}%` }} />
      </span>
    </span>
  )
}
