"use client"

import { useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Switch } from "./ui/switch"
import { Check, HardDrive, Settings2 } from "lucide-react"
import { useT } from "../lib/i18n/provider"
import { useGroupDisksByController } from "../lib/storage-display"

export function StorageDisplayCard() {
  const t = useT()
  const [groupByController, setGroupByController] = useGroupDisksByController()
  const [editMode, setEditMode] = useState(false)
  const [pending, setPending] = useState<boolean | null>(null)
  const [saved, setSaved] = useState(false)

  const handleCancel = () => {
    setPending(null)
    setEditMode(false)
  }

  const handleSave = () => {
    if (pending !== null && pending !== groupByController) {
      setGroupByController(pending)
    }
    setPending(null)
    setEditMode(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <HardDrive className="h-5 w-5 text-blue-500" />
            <CardTitle>{t("settings.storageDisplay.title")}</CardTitle>
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
                  disabled={pending === null || pending === groupByController}
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
        <CardDescription>{t("settings.storageDisplay.description")}</CardDescription>
      </CardHeader>
      <CardContent className={editMode ? "bg-accent" : undefined}>
        <div className="text-foreground flex items-center justify-between gap-4">
          <div className="flex items-center">{t("settings.storageDisplay.groupByController")}</div>
          <Switch
            checked={pending ?? groupByController}
            disabled={!editMode}
            onCheckedChange={(checked) => setPending(checked)}
            className={`data-[state=checked]:bg-blue-600 data-[state=unchecked]:bg-input border border-border ${!editMode ? "opacity-60" : ""}`}
          />
        </div>
      </CardContent>
    </Card>
  )
}
