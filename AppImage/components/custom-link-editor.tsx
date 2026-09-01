"use client"

import { useEffect, useState } from "react"
import { Trash2 } from "lucide-react"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"

// Minimal shape we need from the /api/vms poll. Kept narrow so this
// component stays independent of the fuller VMData type used in
// virtual-machines.tsx.
export interface GuestOption {
  vmid: number
  name: string
  type: "lxc" | "qemu"
}

export interface CustomLink {
  id: string
  name: string
  url: string
  logo_url: string
  category: string
  binding: { vmid: number; guest_type: "lxc" | "qemu" } | null
  created_at?: number
  updated_at?: number
}

export interface DraftCustomLink {
  name: string
  url: string
  logo_url: string
  category: string
  bindingKey: string
}

const UNBOUND_KEY = "__none__"

function buildKey(binding: CustomLink["binding"]): string {
  if (!binding) return UNBOUND_KEY
  return `${binding.guest_type}:${binding.vmid}`
}

function parseKey(key: string): CustomLink["binding"] {
  if (!key || key === UNBOUND_KEY) return null
  const [type, vmid] = key.split(":")
  if (type !== "lxc" && type !== "qemu") return null
  const n = Number(vmid)
  if (!Number.isFinite(n)) return null
  return { guest_type: type, vmid: n }
}

export function CustomLinkEditor({
  open,
  onOpenChange,
  editing,
  guests,
  categoryPresets,
  onSaved,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  /** null = create; existing link = edit */
  editing: CustomLink | null
  /** VMs + LXCs from /api/vms so the user can bind a link to a guest */
  guests: GuestOption[]
  /** Populated from /api/apps/categories */
  categoryPresets: string[]
  /** Called on successful save/delete so the parent can refresh */
  onSaved: () => void
}) {
  const t = useT()
  const [draft, setDraft] = useState<DraftCustomLink>({
    name: "", url: "", logo_url: "", category: "", bindingKey: UNBOUND_KEY,
  })
  const [customCategoryMode, setCustomCategoryMode] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset the draft whenever the modal opens with a new target.
  useEffect(() => {
    if (!open) return
    setError(null)
    if (editing) {
      setDraft({
        name: editing.name,
        url: editing.url,
        logo_url: editing.logo_url || "",
        category: editing.category || "",
        bindingKey: buildKey(editing.binding),
      })
      setCustomCategoryMode(
        !!editing.category && !categoryPresets.includes(editing.category),
      )
    } else {
      setDraft({ name: "", url: "", logo_url: "", category: "", bindingKey: UNBOUND_KEY })
      setCustomCategoryMode(false)
    }
  }, [open, editing, categoryPresets])

  const canSave = draft.name.trim() && draft.url.trim() && !saving

  const handleSave = async () => {
    setError(null)
    setSaving(true)
    try {
      const payload = {
        name: draft.name.trim(),
        url: draft.url.trim(),
        logo_url: draft.logo_url.trim(),
        category: draft.category.trim(),
        binding: parseKey(draft.bindingKey),
      }
      if (editing) {
        await fetchApi(`/api/apps/custom-links/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
          headers: { "Content-Type": "application/json" },
        })
      } else {
        await fetchApi("/api/apps/custom-links", {
          method: "POST",
          body: JSON.stringify(payload),
          headers: { "Content-Type": "application/json" },
        })
      }
      onSaved()
      onOpenChange(false)
    } catch (e: any) {
      setError((e && e.message) || t("apps.customLinkSaveError"))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!editing) return
    setError(null)
    setDeleting(true)
    try {
      await fetchApi(`/api/apps/custom-links/${editing.id}`, { method: "DELETE" })
      onSaved()
      onOpenChange(false)
    } catch (e: any) {
      setError((e && e.message) || t("apps.customLinkDeleteError"))
    } finally {
      setDeleting(false)
    }
  }

  // Sort guests by vmid so the dropdown is easy to scan
  const sortedGuests = [...guests].sort((a, b) => a.vmid - b.vmid)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px] bg-accent [&_input]:bg-background [&_[role=combobox]]:bg-background">
        <DialogHeader>
          <DialogTitle>
            {editing ? t("apps.customLinkEditTitle") : t("apps.customLinkNewTitle")}
          </DialogTitle>
        </DialogHeader>

        <div className="grid gap-3 py-2">
          <div className="grid gap-1.5">
            <Label htmlFor="cl-name" className="text-xs uppercase tracking-wider text-muted-foreground">{t("apps.customLinkName")}</Label>
            <Input
              id="cl-name"
              autoFocus
              value={draft.name}
              onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
              placeholder={t("apps.customLinkNamePlaceholder")}
              maxLength={80}
              className="text-sm"
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="cl-url" className="text-xs uppercase tracking-wider text-muted-foreground">{t("apps.customLinkUrl")}</Label>
            <Input
              id="cl-url"
              type="url"
              value={draft.url}
              onChange={(e) => setDraft((d) => ({ ...d, url: e.target.value }))}
              placeholder="https://example.com"
              maxLength={512}
              className="text-sm font-mono"
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="cl-logo" className="text-xs uppercase tracking-wider text-muted-foreground">{t("apps.customLinkLogo")}</Label>
            <Input
              id="cl-logo"
              type="url"
              value={draft.logo_url}
              onChange={(e) => setDraft((d) => ({ ...d, logo_url: e.target.value }))}
              placeholder={t("apps.customLinkLogoPlaceholder")}
              maxLength={512}
              className="text-sm font-mono"
            />
          </div>

          <div className="grid gap-1.5">
            <Label className="text-xs uppercase tracking-wider text-muted-foreground">{t("apps.customLinkCategory")}</Label>
            {customCategoryMode ? (
              <Input
                autoFocus
                value={draft.category}
                onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value }))}
                placeholder={t("vmLxc.appEditor.portCategoryCustomPlaceholder")}
                maxLength={60}
                className="text-sm"
                onBlur={() => { if (!draft.category.trim()) setCustomCategoryMode(false) }}
              />
            ) : (
              <Select
                value={draft.category || "__none__"}
                onValueChange={(v) => {
                  if (v === "__add__") {
                    setCustomCategoryMode(true)
                    setDraft((d) => ({ ...d, category: "" }))
                  } else if (v === "__none__") {
                    setDraft((d) => ({ ...d, category: "" }))
                  } else {
                    setDraft((d) => ({ ...d, category: v }))
                  }
                }}
              >
                <SelectTrigger className="text-sm h-9">
                  <SelectValue placeholder={t("vmLxc.appEditor.portCategoryPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">{t("vmLxc.appEditor.portCategoryNone")}</SelectItem>
                  {categoryPresets.map((c) => (
                    <SelectItem key={c} value={c}>{c}</SelectItem>
                  ))}
                  <SelectItem value="__add__">{t("vmLxc.appEditor.portCategoryAddNew")}</SelectItem>
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="grid gap-1.5">
            <Label className="text-xs uppercase tracking-wider text-muted-foreground">{t("apps.customLinkBinding")}</Label>
            <Select
              value={draft.bindingKey}
              onValueChange={(v) => setDraft((d) => ({ ...d, bindingKey: v }))}
            >
              <SelectTrigger className="text-sm h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={UNBOUND_KEY}>{t("apps.customLinkBindingNone")}</SelectItem>
                {sortedGuests.map((g) => (
                  <SelectItem key={`${g.type}:${g.vmid}`} value={`${g.type}:${g.vmid}`}>
                    {g.type === "qemu" ? "VM" : "CT"} {g.vmid} · {g.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {t("apps.customLinkBindingHelp")}
            </p>
          </div>

          {error && (
            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded px-3 py-2">
              {error}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          {editing ? (
            <Button
              variant="ghost"
              onClick={handleDelete}
              disabled={deleting || saving}
              className="text-red-400 hover:text-red-300 hover:bg-red-500/10"
            >
              <Trash2 className="h-4 w-4 mr-1.5" />
              {t("apps.customLinkDelete")}
            </Button>
          ) : <div />}
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
              {t("apps.customLinkCancel")}
            </Button>
            <Button
              onClick={handleSave}
              disabled={!canSave}
              className="bg-blue-500 hover:bg-blue-600 !text-white"
            >
              {editing ? t("apps.customLinkSave") : t("apps.customLinkCreate")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
