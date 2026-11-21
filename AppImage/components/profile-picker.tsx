"use client"

// The profile of an account: one of the fixed profiles, or a custom choice
// of areas and actions (see permissions.py). Shared by local users, the
// subjects of the OpenID Connect provider and Proxmox users and groups.
import useSWR from "swr"
import { Checkbox } from "./ui/checkbox"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { fetchApi } from "../lib/api-config"
import { useT } from "../lib/i18n/provider"

export const PROFILES = ["admin", "operator", "operator_no_terminal", "observer", "custom"] as const

export interface Custom { areas: string[]; actions: string[] }
export interface ProfileChoice { profile: string; custom: Custom | null }

export const EMPTY_CUSTOM: Custom = { areas: ["general"], actions: [] }

type Translate = (key: string, params?: Record<string, string | number>) => string

// The name of an area: the pages of a Proxmox Backup Server use the names of
// their tabs.
export function areaLabel(t: Translate, area: string): string {
  if (area === "datastores") return t("pbs.datastores")
  if (area === "tasks") return t("pbs.tasksTab")
  return t(`users.areas.${area}`)
}

// The areas and actions a custom profile offers come from the server, which
// knows the product: a Proxmox Backup Server has no apps, catalog or guests.
function useCustomChoices() {
  const { data } = useSWR<{ areas?: string[]; custom_actions?: string[] }>(
    "/api/auth/users", (url: string) => fetchApi(url), { revalidateOnFocus: false })
  return { areas: data?.areas ?? [], actions: data?.custom_actions ?? [] }
}

export function CustomChoice({ value, onChange, disabled, idPrefix = "custom" }: {
  value: Custom; onChange: (next: Custom) => void; disabled: boolean; idPrefix?: string
}) {
  const t = useT()
  const choices = useCustomChoices()
  const toggle = (list: string[], item: string, on: boolean) => on ? [...list, item] : list.filter(x => x !== item)
  const group = (title: string, items: readonly string[], key: "areas" | "actions", label: (item: string) => string) => (
    <fieldset className="space-y-2 min-w-0">
      <legend className="text-sm font-medium mb-1">{title}</legend>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {items.map(item => {
          const id = `${idPrefix}-${key}-${item}`
          return (
            <label key={item} htmlFor={id} className="flex items-center gap-2 text-sm min-w-0">
              <Checkbox id={id} checked={value[key].includes(item)} disabled={disabled}
                onCheckedChange={on => onChange({ ...value, [key]: toggle(value[key], item, on === true) })} />
              <span className="min-w-0 [overflow-wrap:anywhere]">{label(item)}</span>
            </label>
          )
        })}
      </div>
    </fieldset>
  )
  return (
    <div className="space-y-4 rounded-md border border-border bg-muted/40 p-3">
      {group(t("users.customAreas"), choices.areas, "areas", item => areaLabel(t, item))}
      {group(t("users.customActions"), choices.actions, "actions", item => t(`users.actions.${item}`))}
      <p className="text-xs text-muted-foreground">{t("users.customHint")}</p>
    </div>
  )
}

// A profile and, for a custom one, its areas and actions.
export function ProfilePicker({ value, onChange, disabled, id, idPrefix, showCustom = true }: {
  value: ProfileChoice; onChange: (next: ProfileChoice) => void; disabled: boolean; id?: string; idPrefix?: string
  // Off to show only the profile, as a card does while it is not edited.
  showCustom?: boolean
}) {
  const t = useT()
  return (
    <div className="space-y-2 min-w-0">
      <Select value={value.profile} disabled={disabled}
        onValueChange={profile => onChange({ profile, custom: profile === "custom" ? (value.custom ?? EMPTY_CUSTOM) : null })}>
        <SelectTrigger id={id} aria-label={t("users.profile")} className="w-full min-w-0 text-foreground">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PROFILES.map(p => <SelectItem key={p} value={p}>{t(`users.profiles.${p}`)}</SelectItem>)}
        </SelectContent>
      </Select>
      {showCustom && value.profile === "custom" && (
        <CustomChoice value={value.custom ?? EMPTY_CUSTOM} disabled={disabled} idPrefix={idPrefix}
          onChange={custom => onChange({ profile: "custom", custom })} />
      )}
    </div>
  )
}
