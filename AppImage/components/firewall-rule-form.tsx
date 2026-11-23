"use client"

import type { ReactNode } from "react"
import { Check, Plus, Zap } from "lucide-react"
import { useT } from "@/lib/i18n/provider"
import { OptionSelect } from "./option-select"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"

export const FIREWALL_SAVE_CLASS = "border-green-500/30 text-green-700 hover:bg-green-500/10 dark:text-green-400"
export const FIREWALL_ADD_CLASS = "bg-orange-600 hover:bg-orange-700 text-white"
// Native Proxmox LOGID order (0 through 7).
export const FIREWALL_LOG_LEVELS = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"] as const

export type FirewallRuleDraft = {
  direction: string
  action: string
  protocol: string
  dport: string
  source: string
  iface: string
  comment: string
  log?: string
}

type Props = {
  draft: FirewallRuleDraft
  onChange: (draft: FirewallRuleDraft) => void
  onCancel: () => void
  onSubmit: () => void
  saving: boolean
  interfaces: { value: string; label: string }[]
  targetField?: ReactNode
  description?: ReactNode
  submitDisabled?: boolean
  hideIcmpPort?: boolean
  submitLabel?: string
  editing?: boolean
}

export function FirewallRuleForm({
  draft, onChange, onCancel, onSubmit, saving, interfaces, targetField,
  description, submitDisabled, hideIcmpPort, submitLabel, editing,
}: Props) {
  const t = useT()
  const st = (key: string) => t(`securityPage.${key}`)
  return (
    <div className={editing ? "space-y-3" : "border border-orange-500/30 rounded-lg p-4 bg-orange-500/5 space-y-4"}>
      {!editing && <div className="flex items-center gap-2 mb-1">
        <Plus className="h-4 w-4 text-orange-500" />
        <p className="text-sm font-semibold text-orange-500">{st("firewall.newRule")}</p>
      </div>}

      {description}
      {!editing && <div className="space-y-1.5">
        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{st("firewall.quickPresets")}</p>
        <div className="flex flex-wrap gap-1.5">
          {[
            { label: "HTTP", port: "80", proto: "tcp", comment: st("firewall.presets.httpWeb") },
            { label: "HTTPS", port: "443", proto: "tcp", comment: st("firewall.presets.httpsWeb") },
            { label: "SSH", port: "22", proto: "tcp", comment: st("firewall.presets.sshRemoteAccess") },
            { label: "DNS", port: "53", proto: "udp", comment: "DNS" },
            { label: "SMTP", port: "25", proto: "tcp", comment: st("firewall.presets.smtpMail") },
            { label: "NFS", port: "2049", proto: "tcp", comment: "NFS" },
            { label: "SMB", port: "445", proto: "tcp", comment: "SMB/CIFS" },
            { label: "Ping", port: "", proto: "icmp", comment: st("firewall.presets.icmpPing") },
          ].map((preset) => (
            <Button
              key={preset.label}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onChange({
                ...draft,
                dport: preset.port,
                protocol: preset.proto,
                comment: preset.comment,
                direction: "IN",
                action: "ACCEPT",
              })}
              className="h-6 text-[10px] px-2 text-muted-foreground border-border hover:text-orange-500 hover:border-orange-500/30 bg-transparent"
            >
              <Zap className="h-2.5 w-2.5 mr-1" />
              {preset.label}
            </Button>
          ))}
        </div>
      </div>}

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">{st("firewall.fields.direction")}</Label>
          <OptionSelect value={draft.direction} onChange={direction => onChange({...draft, direction})}
            ariaLabel={st("firewall.fields.direction")} className="bg-card"
            options={[{ value: "IN", label: `IN (${st("firewall.incomingLower")})` },
                      { value: "OUT", label: `OUT (${st("firewall.outgoingLower")})` }]} />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">{st("firewall.fields.action")}</Label>
          <OptionSelect value={draft.action} onChange={action => onChange({...draft, action})}
            ariaLabel={st("firewall.fields.action")} className="bg-card"
            options={[{ value: "ACCEPT", label: `ACCEPT (${st("firewall.allowLower")})` },
                      { value: "DROP", label: `DROP (${st("firewall.blockSilentlyLower")})` },
                      { value: "REJECT", label: `REJECT (${st("firewall.blockWithResponseLower")})` }]} />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">{st("firewall.fields.protocol")}</Label>
          <OptionSelect value={draft.protocol} onChange={protocol => onChange({ ...draft, protocol, dport: hideIcmpPort && protocol === "icmp" ? "" : draft.dport })}
            ariaLabel={st("firewall.fields.protocol")} className="bg-card"
            options={[{ value: "tcp", label: "TCP" }, { value: "udp", label: "UDP" }, { value: "icmp", label: "ICMP (ping)" }]} />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">{st("firewall.fields.destinationPort")}</Label>
          <Input
            placeholder={st("firewall.placeholders.destinationPort")}
            value={draft.dport}
            onChange={(e) => onChange({...draft, dport: e.target.value})}
            className="h-9 text-sm"
            disabled={hideIcmpPort && draft.protocol === "icmp"}
          />
          <p className="text-[10px] text-muted-foreground">{st("firewall.destinationPortHint")}</p>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">{st("firewall.fields.sourceAddress")}</Label>
          <Input
            placeholder={st("firewall.placeholders.sourceAddress")}
            value={draft.source}
            onChange={(e) => onChange({...draft, source: e.target.value})}
            className="h-9 text-sm"
          />
          <p className="text-[10px] text-muted-foreground">{st("firewall.sourceAddressHint")}</p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">{st("firewall.fields.interfaceOptional")}</Label>
          <OptionSelect value={draft.iface} onChange={iface => onChange({...draft, iface})}
            ariaLabel={st("firewall.fields.interfaceOptional")} className="bg-card"
            options={[{ value: "", label: st("firewall.anyInterface") },
                      ...interfaces]} />
        </div>
        {targetField}
        {draft.log !== undefined && (
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">{t("vmLxc.firewall.ruleLogLevel")}</Label>
            <OptionSelect value={draft.log} onChange={log => onChange({ ...draft, log })}
              ariaLabel={t("vmLxc.firewall.ruleLogLevel")} className="bg-card"
              options={[{ value: "nolog", label: t("vmLxc.firewall.noLog") },
                        ...FIREWALL_LOG_LEVELS.map(value => ({ value, label: value }))]} />
          </div>
        )}
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs text-muted-foreground">{st("firewall.fields.commentOptional")}</Label>
        <Input
          placeholder={st("firewall.placeholders.comment")}
          value={draft.comment}
          onChange={(e) => onChange({...draft, comment: e.target.value})}
          className="h-9 text-sm"
        />
      </div>

      <div className="flex gap-2 justify-end">
        <Button
          variant="ghost"
          size="sm"
          onClick={onCancel}
          className="text-muted-foreground"
        >
          {t("actions.cancel")}
        </Button>
        <Button
          size="sm"
          disabled={saving || submitDisabled}
          onClick={onSubmit}
          variant={editing ? "outline" : "default"}
          className={editing ? FIREWALL_SAVE_CLASS : FIREWALL_ADD_CLASS}
        >
          {saving ? (
            <div className="animate-spin h-3.5 w-3.5 border-2 border-white border-t-transparent rounded-full mr-1" />
          ) : editing ? <Check className="h-3.5 w-3.5 mr-1" /> : (
            <Plus className="h-3.5 w-3.5 mr-1" />
          )}
          {submitLabel ?? st("firewall.addRule")}
        </Button>
      </div>
    </div>
  )
}
