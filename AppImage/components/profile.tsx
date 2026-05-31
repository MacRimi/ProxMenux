"use client"

import { useEffect, useRef, useState } from "react"
import {
  User as UserIcon,
  Upload,
  Trash2,
  Loader2,
  Check,
  AlertCircle,
  Shield,
  Lock,
  X,
  Settings2,
  CheckCircle2,
} from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Label } from "./ui/label"
import { fetchApi, getApiUrl, getAuthToken } from "../lib/api-config"

interface ProfileData {
  success: boolean
  username?: string | null
  display_name?: string | null
  has_avatar?: boolean
  avatar_mtime?: number | null
  avatar_content_type?: string | null
  message?: string
}

interface ProfileProps {
  /** Optional navigation hook so the page can link to Security for
   *  password / 2FA changes without redirecting through a URL. */
  onOpenSecurity?: () => void
}

/**
 * Profile page (Fase 2, v1.2.2).
 *
 * Lets the operator edit their **display name** and upload / remove
 * their **avatar**. Username is read-only (changing it requires
 * disabling and reconfiguring auth from Security). Password / 2FA
 * are intentionally not editable from this page — those live in
 * Security to keep the "account security" surface in one place.
 *
 * Layout: centered, two cards (Profile + Account security shortcut).
 * Display name uses the same Edit / Save / Cancel pattern as the
 * Health Thresholds / Notifications panels — read-only by default,
 * the operator hits Edit to start typing.
 */
export function Profile({ onOpenSecurity }: ProfileProps) {
  const [profile, setProfile] = useState<ProfileData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Display name: read-only by default, editable after pressing Edit.
  // Mirrors the editMode pattern used in HealthThresholds / Notifications
  // so the operator never types into a field that isn't ready to be saved.
  const [displayEditMode, setDisplayEditMode] = useState(false)
  const [displayDraft, setDisplayDraft] = useState("")
  const [savingDisplay, setSavingDisplay] = useState(false)
  const [savedDisplay, setSavedDisplay] = useState(false)

  // Avatar state.
  const [uploadingAvatar, setUploadingAvatar] = useState(false)
  const [avatarError, setAvatarError] = useState<string | null>(null)
  const [avatarBlobUrl, setAvatarBlobUrl] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadProfile = async () => {
    try {
      const data = await fetchApi<ProfileData>("/api/auth/profile")
      setProfile(data)
      setDisplayDraft(data.display_name || "")
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProfile()
  }, [])

  // Avatar fetch. Same blob-URL pattern as in AvatarMenu — the endpoint
  // requires the Bearer header, which <img src=…> can't send. Plain
  // `<img>` would render a broken image icon (the bug the user reported).
  useEffect(() => {
    let cancelled = false
    let currentBlobUrl: string | null = null
    if (profile?.has_avatar) {
      const token = getAuthToken()
      const url = `${getApiUrl("/api/auth/profile/avatar")}?v=${profile.avatar_mtime || ""}`
      fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
        .then(r => (r.ok ? r.blob() : null))
        .then(blob => {
          if (cancelled || !blob) return
          currentBlobUrl = URL.createObjectURL(blob)
          setAvatarBlobUrl(currentBlobUrl)
        })
        .catch(() => {
          if (!cancelled) setAvatarBlobUrl(null)
        })
    } else {
      setAvatarBlobUrl(null)
    }
    return () => {
      cancelled = true
      if (currentBlobUrl) URL.revokeObjectURL(currentBlobUrl)
    }
  }, [profile?.has_avatar, profile?.avatar_mtime])

  const initial = (profile?.display_name || profile?.username || "U")
    .trim()
    .charAt(0)
    .toUpperCase()

  const hasDisplayChanges = displayDraft !== (profile?.display_name || "")

  const handleEditDisplay = () => {
    setDisplayEditMode(true)
    setSavedDisplay(false)
    setError(null)
  }

  const handleCancelDisplay = () => {
    setDisplayDraft(profile?.display_name || "")
    setDisplayEditMode(false)
    setError(null)
  }

  const handleSaveDisplayName = async () => {
    if (!hasDisplayChanges) {
      setDisplayEditMode(false)
      return
    }
    setSavingDisplay(true)
    setError(null)
    setSavedDisplay(false)
    try {
      const data = await fetchApi<ProfileData>("/api/auth/profile", {
        method: "PUT",
        body: JSON.stringify({ display_name: displayDraft }),
      })
      if (!data.success) {
        setError(data.message || "Failed to save display name")
        return
      }
      setProfile(data)
      setDisplayEditMode(false)
      setSavedDisplay(true)
      setTimeout(() => setSavedDisplay(false), 2500)
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("proxmenux:profile-changed"))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSavingDisplay(false)
    }
  }

  const handleAvatarPick = () => fileInputRef.current?.click()

  const handleAvatarFile = async (file: File) => {
    setUploadingAvatar(true)
    setAvatarError(null)
    try {
      const token = getAuthToken()
      const headers: Record<string, string> = {}
      if (token) headers["Authorization"] = `Bearer ${token}`
      // Raw upload (Content-Type = the image's own MIME) — simpler than
      // multipart and the backend handles both.
      headers["Content-Type"] = file.type
      const r = await fetch(getApiUrl("/api/auth/profile/avatar"), {
        method: "POST",
        headers,
        body: file,
      })
      const data: ProfileData = await r.json().catch(() => ({ success: false }))
      if (!r.ok || !data.success) {
        setAvatarError(data.message || `Upload failed (${r.status})`)
        return
      }
      setProfile(data)
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("proxmenux:profile-changed"))
      }
    } catch (e) {
      setAvatarError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploadingAvatar(false)
      // Reset the input so picking the same file twice in a row still
      // fires the change event.
      if (fileInputRef.current) fileInputRef.current.value = ""
    }
  }

  const handleAvatarDelete = async () => {
    setUploadingAvatar(true)
    setAvatarError(null)
    try {
      const token = getAuthToken()
      const headers: Record<string, string> = {}
      if (token) headers["Authorization"] = `Bearer ${token}`
      const r = await fetch(getApiUrl("/api/auth/profile/avatar"), {
        method: "DELETE",
        headers,
      })
      const data: ProfileData = await r.json().catch(() => ({ success: false }))
      if (!r.ok || !data.success) {
        setAvatarError(data.message || `Delete failed (${r.status})`)
        return
      }
      setProfile(data)
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("proxmenux:profile-changed"))
      }
    } catch (e) {
      setAvatarError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploadingAvatar(false)
    }
  }

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto">
        <Card>
          <CardContent className="p-8 flex items-center justify-center text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
            Loading profile…
          </CardContent>
        </Card>
      </div>
    )
  }

  if (error && !profile) {
    return (
      <div className="max-w-2xl mx-auto">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-start gap-2 text-red-500">
              <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
              <div>
                <div className="font-medium">Failed to load profile</div>
                <div className="text-xs text-muted-foreground mt-1 break-all">{error}</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <Card>
        <CardHeader>
          {/* Edit / Save / Cancel sit in the card header — same pattern
              as Health Thresholds and Notifications. Avatar actions
              (upload / remove) stay independent of editMode because
              they're explicit one-shot actions, not field edits. */}
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2">
              <UserIcon className="h-5 w-5 text-cyan-500" />
              <CardTitle>User Profile</CardTitle>
            </div>
            <div className="flex items-center gap-2">
              {savedDisplay && (
                <span className="flex items-center gap-1 text-xs text-green-500">
                  <Check className="h-3.5 w-3.5" />
                  Saved
                </span>
              )}
              {displayEditMode ? (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleCancelDisplay}
                    disabled={savingDisplay}
                    className="h-7 text-xs"
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleSaveDisplayName}
                    disabled={savingDisplay || !hasDisplayChanges}
                    className="h-7 text-xs bg-blue-600 hover:bg-blue-700"
                  >
                    {savingDisplay ? (
                      <Loader2 className="h-3 w-3 mr-1.5 animate-spin" />
                    ) : (
                      <CheckCircle2 className="h-3 w-3 mr-1.5" />
                    )}
                    Save
                  </Button>
                </>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleEditDisplay}
                  className="h-7 text-xs"
                >
                  <Settings2 className="h-3 w-3 mr-1.5" />
                  Edit
                </Button>
              )}
            </div>
          </div>
          <CardDescription>
            Personal details rendered in the header avatar menu. None of this is required —
            the username already covers identity. Display name and avatar are decorative.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-8">
          {/* ─── Avatar section ──────────────────────────────────────
              Big preview (160×160) so the operator can see the actual
              image they uploaded. `object-cover` keeps the aspect
              ratio and crops to fit the circle. */}
          <div>
            <Label className="text-sm">Avatar</Label>
            <div className="flex flex-col sm:flex-row items-start gap-6 mt-3">
              <div className="relative shrink-0">
                {avatarBlobUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={avatarBlobUrl}
                    alt=""
                    className="w-40 h-40 rounded-full object-cover border border-border bg-cyan-500/5"
                  />
                ) : (
                  <span className="w-40 h-40 rounded-full bg-cyan-500/15 text-cyan-600 dark:text-cyan-300 flex items-center justify-center text-6xl font-semibold border border-border">
                    {initial}
                  </span>
                )}
                {uploadingAvatar && (
                  <div className="absolute inset-0 rounded-full bg-black/50 flex items-center justify-center">
                    <Loader2 className="h-6 w-6 animate-spin text-white" />
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-2 min-w-0">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) handleAvatarFile(file)
                  }}
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleAvatarPick}
                  disabled={uploadingAvatar}
                  className="justify-start"
                >
                  <Upload className="h-3.5 w-3.5 mr-2" />
                  {profile?.has_avatar ? "Replace avatar" : "Upload avatar"}
                </Button>
                {profile?.has_avatar && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleAvatarDelete}
                    disabled={uploadingAvatar}
                    className="justify-start text-red-500 hover:text-red-500 hover:bg-red-500/10"
                  >
                    <Trash2 className="h-3.5 w-3.5 mr-2" />
                    Remove avatar
                  </Button>
                )}
                <p className="text-[11px] text-muted-foreground leading-relaxed max-w-xs">
                  PNG, JPEG, WebP or GIF. Up to 2 MB. The image isn&apos;t resized —
                  render it square or pre-crop for best results in the header.
                </p>
              </div>
            </div>
            {avatarError && (
              <div className="mt-3 text-xs text-red-500 flex items-start gap-1.5">
                <X className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                <span className="break-all">{avatarError}</span>
              </div>
            )}
          </div>

          {/* ─── Username (read-only) ─── */}
          <div>
            <Label className="text-sm" htmlFor="profile-username">Username</Label>
            <Input
              id="profile-username"
              value={profile?.username || ""}
              disabled
              className="mt-2 max-w-sm disabled:opacity-100 disabled:cursor-default"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              The login name. To change it, disable authentication and reconfigure from
              Security.
            </p>
          </div>

          {/* ─── Display name (Edit controls live in the card header) ─── */}
          <div>
            <Label className="text-sm" htmlFor="profile-display">
              Display name <span className="text-muted-foreground font-normal">(optional)</span>
            </Label>
            <Input
              id="profile-display"
              value={displayDraft}
              onChange={(e) => setDisplayDraft(e.target.value)}
              placeholder={profile?.username || "Display name"}
              maxLength={64}
              disabled={!displayEditMode || savingDisplay}
              className="mt-2 max-w-sm disabled:opacity-100 disabled:cursor-default"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Shown above the username inside the avatar menu. Leave empty to show the
              username itself. Up to 64 characters.
            </p>
            {error && displayEditMode && (
              <div className="mt-2 text-xs text-red-500 flex items-start gap-1.5">
                <X className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                <span className="break-all">{error}</span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ─── Account security shortcut ─── */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-orange-500" />
            <CardTitle>Account security</CardTitle>
          </div>
          <CardDescription>
            Password, two-factor authentication and API tokens live in the Security panel.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {onOpenSecurity ? (
            <Button variant="outline" onClick={onOpenSecurity}>
              <Lock className="h-4 w-4 mr-2" />
              Open Security settings
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">
              Open the Security tab from the navigation.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
