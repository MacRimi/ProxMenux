"use client"

import React, { useState, useRef, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import {
  Boxes,
  Check,
  ChevronDown,
  DatabaseBackup,
  GripVertical,
  Grid3x3,
  LayoutDashboard,
  Layers,
  RotateCcw,
  Server,
  Settings2,
  Terminal,
} from "lucide-react"
import { useT } from "../lib/i18n/provider"
import {
  DEFAULT_TAB_ORDER,
  useTabOrder,
  type TabId,
} from "../lib/tab-order"

// Long-press activation on touch — matches the delay platform UIs
// use so the user can still scroll a page that happens to start on a
// tab handle.
const TOUCH_ACTIVATION_MS = 250
const TOUCH_TOLERANCE_PX = 5

type TabMeta = {
  id: TabId
  Icon: React.ComponentType<{ className?: string }>
  labelKey: string
  hasDropdown: boolean
}

const META: Record<TabId, TabMeta> = {
  overview: { id: "overview", Icon: LayoutDashboard, labelKey: "navigation.overview",        hasDropdown: false },
  apps:     { id: "apps",     Icon: Grid3x3,         labelKey: "navigation.apps",            hasDropdown: false },
  vms:      { id: "vms",      Icon: Boxes,           labelKey: "navigation.virtualMachines", hasDropdown: false },
  node:     { id: "node",     Icon: Server,          labelKey: "navigation.node",            hasDropdown: true  },
  backup:   { id: "backup",   Icon: DatabaseBackup,  labelKey: "navigation.backup",          hasDropdown: false },
  terminal: { id: "terminal", Icon: Terminal,        labelKey: "navigation.terminal",        hasDropdown: false },
  admin:    { id: "admin",    Icon: Settings2,       labelKey: "navigation.admin",           hasDropdown: true  },
}

// Sortable list built on Pointer Events. Mouse activates on move
// (2px threshold to survive accidental clicks); touch activates on
// long-press after 250ms unless the finger moves past 5px, which is
// treated as a scroll intent and the drag is cancelled.
export function NavTabOrderCard() {
  const t = useT()
  const { order: savedOrder, setOrder, reset, isCustom } = useTabOrder()
  const [editMode, setEditMode] = useState(false)
  const [draft, setDraft] = useState<TabId[]>(savedOrder)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (!editMode) setDraft(savedOrder)
  }, [savedOrder, editMode])

  const handleCancel = () => {
    setDraft(savedOrder)
    setEditMode(false)
  }
  const handleSave = () => {
    setOrder(draft)
    setEditMode(false)
    setSaved(true)
    window.setTimeout(() => setSaved(false), 2000)
  }
  const handleReset = () => {
    setDraft([...DEFAULT_TAB_ORDER])
  }

  const draftIsChanged =
    draft.length !== savedOrder.length ||
    draft.some((id, i) => id !== savedOrder[i])
  const draftIsCustom =
    draft.length !== DEFAULT_TAB_ORDER.length ||
    draft.some((id, i) => id !== DEFAULT_TAB_ORDER[i])

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Layers className="h-5 w-5 text-blue-500" />
            <CardTitle>{t("settings.navOrder.title")}</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {saved && (
              <span className="flex items-center gap-1 text-xs text-green-500">
                <Check className="h-3.5 w-3.5" />
                {t("status.saved")}
              </span>
            )}
            {editMode ? (
              <>
                <button
                  className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors text-muted-foreground"
                  onClick={handleCancel}
                >
                  {t("actions.cancel")}
                </button>
                <button
                  className="h-7 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50 flex items-center gap-1.5"
                  onClick={handleSave}
                  disabled={!draftIsChanged}
                >
                  <Check className="h-3 w-3" />
                  {t("actions.save")}
                </button>
              </>
            ) : (
              <button
                className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors flex items-center gap-1.5"
                onClick={() => setEditMode(true)}
              >
                <Settings2 className="h-3 w-3" />
                {t("actions.edit")}
              </button>
            )}
          </div>
        </div>
        <CardDescription>{t("settings.navOrder.description")}</CardDescription>
      </CardHeader>
      <CardContent
        className={
          editMode
            ? "bg-accent"
            : undefined
        }
      >
        <SortableList
          items={editMode ? draft : savedOrder}
          onReorder={setDraft}
          editable={editMode}
          t={t}
        />
        {editMode && (
          <div className="mt-4 flex items-center justify-between">
            <button
              className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors flex items-center gap-1.5 text-muted-foreground disabled:opacity-50 disabled:pointer-events-none"
              onClick={handleReset}
              disabled={!draftIsCustom}
            >
              <RotateCcw className="h-3 w-3" />
              {t("settings.navOrder.reset")}
            </button>
            <span className="text-[11px] text-muted-foreground">
              {t("settings.navOrder.hint")}
            </span>
          </div>
        )}
        {!editMode && isCustom && (
          <div className="mt-3 text-[11px] text-muted-foreground">
            {t("settings.navOrder.customActive")}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// -----------------------------------------------------------------
// SortableList
// -----------------------------------------------------------------

type DragState = {
  fromIdx: number
  pointerY: number
  offsetY: number
  itemHeight: number
} | null

function SortableList({
  items,
  onReorder,
  editable,
  t,
}: {
  items: TabId[]
  onReorder: (next: TabId[]) => void
  editable: boolean
  t: (k: string) => string
}) {
  const [drag, setDrag] = useState<DragState>(null)
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const listRef = useRef<HTMLUListElement | null>(null)

  const commit = (from: number, to: number) => {
    if (from === to || to < 0 || to >= items.length) return
    const next = items.slice()
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    onReorder(next)
  }

  const handleDragMove = (clientY: number) => {
    if (!drag || !listRef.current) return
    const rows = Array.from(listRef.current.querySelectorAll<HTMLLIElement>("li[data-row]"))
    let target = drag.fromIdx
    for (let i = 0; i < rows.length; i++) {
      const rect = rows[i].getBoundingClientRect()
      const mid = rect.top + rect.height / 2
      if (clientY < mid) { target = i; break }
      target = i
    }
    setHoverIdx(target)
    setDrag((d) => (d ? { ...d, pointerY: clientY } : d))
  }

  const handleDragEnd = () => {
    if (drag && hoverIdx !== null) commit(drag.fromIdx, hoverIdx)
    setDrag(null)
    setHoverIdx(null)
  }

  return (
    <ul
      ref={listRef}
      className="flex flex-col gap-1.5 select-none"
      onPointerMove={(e) => { if (drag) handleDragMove(e.clientY) }}
      onPointerUp={handleDragEnd}
      onPointerCancel={handleDragEnd}
    >
      {items.map((id, idx) => {
        const isDragging = drag?.fromIdx === idx
        const meta = META[id]
        return (
          <SortableRow
            key={id}
            id={id}
            idx={idx}
            meta={meta}
            label={t(meta.labelKey)}
            editable={editable}
            isDragging={!!isDragging}
            hoverIdx={hoverIdx}
            drag={drag}
            onDragStart={(fromIdx, pointerY, offsetY, itemHeight) => {
              setDrag({ fromIdx, pointerY, offsetY, itemHeight })
              setHoverIdx(fromIdx)
            }}
          />
        )
      })}
    </ul>
  )
}

function SortableRow({
  id,
  idx,
  meta,
  label,
  editable,
  isDragging,
  hoverIdx,
  drag,
  onDragStart,
}: {
  id: TabId
  idx: number
  meta: TabMeta
  label: string
  editable: boolean
  isDragging: boolean
  hoverIdx: number | null
  drag: DragState
  onDragStart: (fromIdx: number, pointerY: number, offsetY: number, itemHeight: number) => void
}) {
  const rowRef = useRef<HTMLLIElement | null>(null)
  const longPressTimer = useRef<number | null>(null)
  const pointerStart = useRef<{ x: number; y: number } | null>(null)
  const activatedRef = useRef(false)

  const cancelLongPress = () => {
    if (longPressTimer.current !== null) {
      window.clearTimeout(longPressTimer.current)
      longPressTimer.current = null
    }
  }

  const beginDrag = (clientY: number) => {
    if (!rowRef.current) return
    const rect = rowRef.current.getBoundingClientRect()
    activatedRef.current = true
    onDragStart(idx, clientY, clientY - rect.top, rect.height)
  }

  const handlePointerDown = (e: React.PointerEvent<HTMLLIElement>) => {
    if (!editable) return
    if (e.button !== undefined && e.button !== 0) return
    pointerStart.current = { x: e.clientX, y: e.clientY }
    activatedRef.current = false
    if (e.pointerType === "touch") {
      longPressTimer.current = window.setTimeout(() => {
        longPressTimer.current = null
        beginDrag(e.clientY)
      }, TOUCH_ACTIVATION_MS)
    } else {
      // Mouse/pen: activate immediately on press.
      beginDrag(e.clientY)
    }
    ;(e.currentTarget as HTMLLIElement).setPointerCapture(e.pointerId)
  }

  const handlePointerMove = (e: React.PointerEvent<HTMLLIElement>) => {
    if (!editable) return
    if (!activatedRef.current && pointerStart.current) {
      const dx = e.clientX - pointerStart.current.x
      const dy = e.clientY - pointerStart.current.y
      if (Math.hypot(dx, dy) > TOUCH_TOLERANCE_PX) {
        // Movement before activation → scroll intent on touch. Cancel
        // the pending long-press so the page can scroll normally.
        cancelLongPress()
      }
    }
  }

  const handlePointerUp = () => {
    cancelLongPress()
    pointerStart.current = null
  }

  // Simple drag visual: ghost the row being dragged, show a blue
  // drop-line above or below the row the pointer is currently over.
  // No item swap animation — commit on release.
  const isTarget = drag && hoverIdx === idx && drag.fromIdx !== idx
  const dropAbove = isTarget && drag!.fromIdx > idx
  const dropBelow = isTarget && drag!.fromIdx < idx
  const RowIcon = meta.Icon

  return (
    <li
      ref={rowRef}
      data-row
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      className={[
        "relative rounded-md border transition-colors",
        editable
          ? "bg-background border-border cursor-grab active:cursor-grabbing touch-none"
          : "bg-card border-border/60",
        isDragging ? "opacity-40" : "",
      ].join(" ")}
    >
      {dropAbove && <div className="absolute -top-[3px] left-2 right-2 h-[2px] bg-blue-500 rounded-full pointer-events-none" />}
      {dropBelow && <div className="absolute -bottom-[3px] left-2 right-2 h-[2px] bg-blue-500 rounded-full pointer-events-none" />}
      <div className="flex items-center gap-3 p-2.5">
        <GripVertical
          className={
            "h-4 w-4 flex-shrink-0 " +
            (editable ? "text-muted-foreground" : "text-muted-foreground/40")
          }
        />
        <RowIcon className="h-4 w-4 flex-shrink-0 text-blue-500" />
        <div className="flex-1 min-w-0 flex items-center gap-2">
          <span className="text-sm font-medium text-foreground">{label}</span>
          {meta.hasDropdown && (
            <ChevronDown className="h-3 w-3 text-muted-foreground/70" />
          )}
        </div>
      </div>
    </li>
  )
}
