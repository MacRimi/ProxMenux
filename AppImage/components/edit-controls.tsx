"use client"

// The Edit → Cancel / Save controls of a settings card, as the cards of
// Settings show them. While a card is not being edited everything in it stays
// visible but cannot be used: put its content in <EditableArea>.
import type React from "react"
import { Check, Loader2, Settings2 } from "lucide-react"
import { useT } from "../lib/i18n/provider"

// A card in edit mode stands out, and the fields to fill in look sunken in it.
export const EDIT_CONTENT_CLASS =
  "bg-accent [&_input]:bg-background [&_textarea]:bg-background [&_[role=combobox]]:bg-background"

// The canonical card toggle (see Settings → Network interfaces).
export const SWITCH_CLASS = "data-[state=checked]:bg-blue-600 data-[state=unchecked]:bg-input border border-border"

export function EditControls({ editing, onEdit, onCancel, onSave, saving = false, canSave = true, showSave = true }: {
  editing: boolean
  onEdit: () => void
  onCancel: () => void
  onSave?: () => void
  saving?: boolean
  canSave?: boolean
  // A card whose actions each confirm on their own has nothing to save.
  showSave?: boolean
}) {
  const t = useT()
  if (!editing) {
    return (
      <button type="button" onClick={onEdit}
        className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors flex items-center gap-1.5 shrink-0">
        <Settings2 className="h-3 w-3" />
        {t("actions.edit")}
      </button>
    )
  }
  return (
    <div className="flex items-center gap-2 shrink-0">
      <button type="button" onClick={onCancel} disabled={saving}
        className="h-7 px-3 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors text-muted-foreground">
        {t("actions.cancel")}
      </button>
      {showSave && (
        <button type="button" onClick={onSave} disabled={saving || !canSave}
          className="h-7 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50 flex items-center gap-1.5">
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
          {t("actions.save")}
        </button>
      )}
    </div>
  )
}

// What a card shows: usable only while it is being edited.
export function EditableArea({ editing, className, children }: {
  editing: boolean; className?: string; children: React.ReactNode
}) {
  return (
    <fieldset disabled={!editing} className={`min-w-0 m-0 p-0 border-0 ${className ?? ""}`}>
      {children}
    </fieldset>
  )
}
