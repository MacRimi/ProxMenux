"use client"

import { useId, useState } from "react"
import { Info, ExternalLink, Check, Loader2, Trash2 } from "lucide-react"
import { Button } from "./ui/button"
import { Textarea } from "./ui/textarea"
import { Label } from "./ui/label"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./ui/dialog"
import { useT } from "@/lib/i18n/provider"

export type AppUpdateMethod = "none" | "helper" | "custom"

export function AppUpdaterEditor({ method, command, helperAvailable, helperSlug, configured, saving, changed,
  onMethodChange, onCommandChange, onSave, onCancel, onRemove }: {
  method: AppUpdateMethod
  command: string
  helperAvailable: boolean
  helperSlug?: string
  configured: boolean
  saving: boolean
  changed: boolean
  onMethodChange: (method: AppUpdateMethod) => void
  onCommandChange: (command: string) => void
  onSave: () => void
  onCancel: () => void
  onRemove: () => void
}) {
  const t = useT()
  const commandId = useId()
  const [help, setHelp] = useState<"helper" | "custom" | null>(null)
  const scriptUrl = helperSlug && /^[a-z0-9][a-z0-9._-]*$/.test(helperSlug)
    ? `https://github.com/community-scripts/ProxmoxVE/blob/main/ct/${helperSlug}.sh` : null
  // Keep the editable command readable. Download guards belong to the runner,
  // which also protects this literal launcher when saved as a custom command.
  const helperCommand = scriptUrl
    ? `PHS_SILENT=1 bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/${helperSlug}.sh)"`
    : null
  const valid = method === "helper" ? helperAvailable && !!helperCommand : method === "custom" && !!command.trim()
  const displayedCommand = method === "helper" ? (helperCommand || "") : command
  const editCommand = (value: string) => {
    // Edited launchers belong to the existing custom-command execution path.
    // Never leave the method as "helper": saving it would discard the edits.
    if (method === "helper") {
      if (value.trim() === (helperCommand || "").trim()) return
      onMethodChange("custom")
    }
    onCommandChange(value)
  }
  const customExamples = [
    { title: "customScriptTitle", description: "customScriptDescription", command: "/opt/my-app/update.sh" },
    { title: "customPackageTitle", description: "customPackageDescription", command: "apt-get update &&\napt-get install -y --only-upgrade my-package" },
    { title: "customBinaryTitle", description: "customBinaryDescription", command: "install -b -m 0755 /tmp/my-app.new /opt/my-app/my-app &&\nsystemctl restart my-app" },
  ]
  const onlineExampleCommand = `script=$(mktemp) || exit 1
trap 'rm -f "$script"' EXIT
curl -fsSL 'https://example.com/my-app/update.sh' -o "$script" &&
bash "$script"`

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">{t("vmLxc.updates.updaterChoiceHint")}</p>
      <div className="flex flex-wrap gap-2" role="group" aria-label={t("vmLxc.updates.updaterMethodLabel")}>
        {([...(helperAvailable ? ["helper" as const] : []), "custom" as const]).map((choice) => (
          <div key={choice} className="flex items-center gap-1">
            <Button type="button" size="sm" variant={method === choice ? "default" : "outline"}
              aria-pressed={method === choice} disabled={saving} onClick={() => onMethodChange(choice)}>
              {t(`vmLxc.updates.${choice === "helper" ? "helperMethod" : "customMethod"}`)}
            </Button>
            <Button type="button" size="icon" variant="ghost" className="text-blue-500 hover:text-blue-600 dark:hover:text-blue-400" onClick={() => setHelp(choice)}
              aria-label={t(`vmLxc.updates.${choice === "helper" ? "helperMethodHelp" : "customMethodHelp"}`)}>
              <Info className="h-4 w-4" />
            </Button>
          </div>
        ))}
      </div>
      {helperAvailable && <p className="text-xs text-muted-foreground">{t("vmLxc.updates.helperDetectedChoice")}</p>}
      {method === "helper" && (!helperAvailable || !helperCommand) && (
        <p className="text-xs text-amber-500">{t("vmLxc.updates.helperUnavailableChoice")}</p>
      )}
      {(method === "helper" || method === "custom") && (
        <div>
          <Label htmlFor={commandId} className="text-xs uppercase tracking-wider text-muted-foreground">
            {t(`vmLxc.updates.${method === "helper" ? "helperCommandLabel" : "customCommandLabel"}`)}
          </Label>
          <Textarea id={commandId} value={displayedCommand} onChange={(event) => editCommand(event.target.value)}
            placeholder={t("vmLxc.updates.customCommandPlaceholder")} disabled={saving}
            className="font-mono text-xs mt-2 min-h-[100px]" maxLength={4096} />
          {method === "helper" && helperCommand && (
            <p className="mt-2 text-xs text-muted-foreground">{t("vmLxc.updates.helperCommandEditHint")}</p>
          )}
        </div>
      )}
      <div className="flex items-center justify-between gap-2">
        <div>{configured && (
          <Button type="button" size="sm" variant="outline" className="text-red-400" disabled={saving} onClick={onRemove}>
            <Trash2 className="h-3.5 w-3.5 mr-1.5" />{t("vmLxc.updates.disableUpdater")}
          </Button>
        )}</div>
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="outline" disabled={saving} onClick={onCancel}>{t("vmLxc.updates.cancelButton")}</Button>
          <Button type="button" size="sm" className="bg-blue-500 hover:bg-blue-600 text-white" disabled={saving || !valid || !changed} onClick={onSave}>
            {saving ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Check className="h-3.5 w-3.5 mr-1.5" />}
            {t("vmLxc.updates.saveButton")}
          </Button>
        </div>
      </div>
      <Dialog open={help !== null} onOpenChange={(open) => { if (!open) setHelp(null) }}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t(`vmLxc.updates.${help === "helper" ? "helperMethod" : "customMethod"}`)}</DialogTitle>
            <DialogDescription>{t(`vmLxc.updates.${help === "helper" ? "helperMethodDescription" : "customMethodDescription"}`)}</DialogDescription>
          </DialogHeader>
          {help === "helper" ? (
            <div className="space-y-3 text-sm">
              {helperCommand && <div className="min-w-0 space-y-2">
                <p className="font-medium">{t("vmLxc.updates.helperCommandLabel")}</p>
                <pre className="rounded-md bg-muted p-3 text-xs whitespace-pre-wrap break-all"><code>{helperCommand}</code></pre>
                <p className="text-xs text-muted-foreground">{t("vmLxc.updates.helperCommandFallback")}</p>
              </div>}
              <p>{t("vmLxc.updates.updaterInstructions")}</p>
              <a className="text-blue-400 hover:text-blue-300 inline-flex items-center gap-1" href="https://community-scripts.org/docs/tools/pve/update-apps" target="_blank" rel="noopener noreferrer">
                {t("vmLxc.updates.helperDocumentation")}<ExternalLink className="h-4 w-4" />
              </a>
              {scriptUrl && <div><a className="text-blue-400 hover:text-blue-300 inline-flex items-center gap-1" href={scriptUrl} target="_blank" rel="noopener noreferrer">
                {t("vmLxc.updates.helperSource")}<ExternalLink className="h-4 w-4" />
              </a></div>}
            </div>
          ) : (
            <div className="space-y-4 text-sm">
              <p className="font-medium">{t("vmLxc.updates.customExamplesHeading")}</p>
              {customExamples.map((example) => <div key={example.title} className="min-w-0 space-y-2">
                <p className="font-medium">{t(`vmLxc.updates.${example.title}`)}</p>
                <p className="text-muted-foreground">{t(`vmLxc.updates.${example.description}`)}</p>
                <pre className="rounded-md bg-muted p-3 text-xs whitespace-pre-wrap break-all"><code>{example.command}</code></pre>
                {example.title === "customScriptTitle" && <>
                  <p className="text-muted-foreground">{t("vmLxc.updates.customOnlineDescription")}</p>
                  <pre className="rounded-md bg-muted p-3 text-xs whitespace-pre-wrap break-all"><code>{onlineExampleCommand}</code></pre>
                  <p className="text-xs text-muted-foreground">{t("vmLxc.updates.customOnlineExampleNote")}</p>
                </>}
              </div>)}
              <p className="text-muted-foreground">{t("vmLxc.updates.customMethodExample")}</p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
