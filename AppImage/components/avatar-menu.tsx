"use client"

import { useEffect, useState } from "react"
import { User, Shield, LogOut } from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu"
import { fetchApi, getApiUrl, getAuthToken } from "../lib/api-config"

interface AuthStatus {
  auth_enabled?: boolean
  username?: string | null
}

interface ProfileData {
  success: boolean
  username?: string | null
  display_name?: string | null
  has_avatar?: boolean
  avatar_mtime?: number | null
}

interface AvatarMenuProps {
  /** Size of the avatar circle in the header trigger. */
  size?: "md" | "lg"
  /**
   * Callback used by the Security menu item. The Monitor renders its
   * Settings/Security panels inside the same dashboard route, not on
   * a separate URL, so navigation is handled by the parent that knows
   * how to switch tabs. Optional — when omitted the menu item is hidden.
   */
  onOpenSecurity?: () => void
  /**
   * Callback for "View profile". Same rationale: the parent decides how
   * to route there (modal, page, tab switch). Until Fase 2 lands the
   * caller typically passes an alert/toast that the page is coming.
   */
  onOpenProfile?: () => void
}

/**
 * AvatarMenu — user/account dropdown for the header.
 *
 * Self-fetches the current auth status to derive the username and the
 * initial that fills the avatar circle. Stays silent (renders nothing)
 * when authentication is disabled on this install — no point showing
 * an account menu for a "Sign out" that doesn't apply.
 *
 * Sign out clears the token from localStorage and reloads, mirroring
 * the existing `handleLogout` in `security.tsx`. That keeps a single
 * source of truth for the logout flow until Fase 2 introduces a
 * proper /api/auth/logout that revokes the JWT server-side too.
 */
export function AvatarMenu({ size = "lg", onOpenSecurity, onOpenProfile }: AvatarMenuProps) {
  // IMPORTANT — all hooks must run unconditionally on every render. The
  // previous version short-circuited with `if (!auth_enabled) return null`
  // BEFORE the avatar blob hooks, so the hook count changed between
  // renders the moment auth status loaded → React error #310 ("rendered
  // more hooks than during the previous render"). All `useState` and
  // `useEffect` calls now live above any early return; the null branch
  // is at the very end after the hooks.
  const [status, setStatus] = useState<AuthStatus | null>(null)
  const [profile, setProfile] = useState<ProfileData | null>(null)
  const [open, setOpen] = useState(false)
  const [avatarBlobUrl, setAvatarBlobUrl] = useState<string | null>(null)

  // Load both auth_status (to decide whether to render at all) and the
  // profile (to render display_name + avatar). Profile is fetched only
  // when auth is enabled — saves one roundtrip on installs without
  // auth where the menu won't show anyway.
  useEffect(() => {
    let cancelled = false
    fetchApi<AuthStatus>("/api/auth/status")
      .then(data => {
        if (cancelled) return
        setStatus(data)
        if (data?.auth_enabled && data?.username) {
          fetchApi<ProfileData>("/api/auth/profile")
            .then(p => {
              if (!cancelled) setProfile(p)
            })
            .catch(() => {
              // Profile fetch is best-effort. Falls back to username + initials.
            })
        }
      })
      .catch(() => {
        if (!cancelled) setStatus(null)
      })
    // Reload status + profile when the user updates the profile from
    // the /profile page OR completes first-time auth setup. Refreshing
    // status is what flips the menu visible after setup (when the
    // initial mount saw auth_enabled=false); refreshing profile is
    // what makes a new avatar/display name appear without a full
    // browser refresh.
    const handler = () => {
      fetchApi<AuthStatus>("/api/auth/status")
        .then(s => {
          if (cancelled) return
          setStatus(s)
          if (s?.auth_enabled && s?.username) {
            fetchApi<ProfileData>("/api/auth/profile")
              .then(p => {
                if (!cancelled) setProfile(p)
              })
              .catch(() => {})
          }
        })
        .catch(() => {})
    }
    if (typeof window !== "undefined") {
      window.addEventListener("proxmenux:profile-changed", handler)
    }
    return () => {
      cancelled = true
      if (typeof window !== "undefined") {
        window.removeEventListener("proxmenux:profile-changed", handler)
      }
    }
  }, [])

  // Avatar fetch — the endpoint requires the Bearer header, which
  // <img src=…> can't send, so we fetch as a blob and convert it to a
  // local object URL for rendering. The blob URL is revoked on cleanup
  // and on every refetch to avoid leaking memory.
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

  // ── Hooks finished. Safe to early-return now. ──
  // Hide the avatar entirely when auth isn't enabled on this install —
  // there's no user identity to surface and no Sign out to offer.
  if (!status?.auth_enabled || !status?.username) return null

  const username = status.username
  const displayName = profile?.display_name || username
  const initial = displayName.trim().charAt(0).toUpperCase() || "U"

  const handleSignOut = () => {
    try {
      localStorage.removeItem("proxmenux-auth-token")
      localStorage.removeItem("proxmenux-auth-setup-complete")
    } catch {
      // localStorage may be unavailable (private mode); fall through.
    }
    window.location.reload()
  }

  // Avatar size in the header trigger. The trigger has no chevron now —
  // removing it freed enough horizontal space to bump the avatar a
  // notch up (40 → 44 / 32 → 36) without nudging the Refresh / Theme
  // buttons sitting to its left.
  const avatarSize = size === "lg" ? "w-11 h-11 text-lg" : "w-9 h-9 text-sm"

  return (
    <>
      {/* Backdrop overlay — dim only (no blur). Mounted while the
          dropdown is open. `bg-black/40` dims the page enough to focus
          attention on the dropdown without distorting the content
          behind, which testers found annoying when full backdrop blur
          was used (especially on wider desktop viewports). `z-40`
          places it above the dashboard content but below the dropdown
          portal (`DropdownMenuContent` lands on z-[60]) and below the
          header (which stays on z-50 so the avatar trigger remains
          clickable). Clicking the backdrop closes the menu — the
          explicit `onClick` mirrors Radix's outside-click handler. */}
      {open && (
        <div
          aria-hidden="true"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-40 bg-black/40 animate-in fade-in-0 duration-150"
        />
      )}
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <button
            className="rounded-full hover:ring-2 hover:ring-cyan-500/30 transition-all relative z-50 focus:outline-none focus-visible:outline-none active:outline-none data-[state=open]:outline-none data-[state=open]:ring-0 select-none"
            aria-label="Open user menu"
            // WebKit ignores `outline` for the tap-highlight overlay
            // shown on iOS / Android Chrome after a touch. That overlay
            // was the white border that lingered on the avatar after
            // dismissing the dropdown without picking anything. Setting
            // `-webkit-tap-highlight-color` to transparent suppresses
            // it without affecting keyboard focus visibility (handled
            // separately by `focus-visible:outline-none` above).
            style={{ WebkitTapHighlightColor: "transparent" }}
          >
            {avatarBlobUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={avatarBlobUrl}
                alt=""
                className={`${avatarSize} rounded-full object-cover bg-cyan-500/10`}
              />
            ) : (
              <span
                className={`${avatarSize} rounded-full flex items-center justify-center font-semibold bg-cyan-500/15 text-cyan-600 dark:text-cyan-300`}
              >
                {initial}
              </span>
            )}
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72 z-[60]">
        <DropdownMenuLabel>
          <div className="flex items-center gap-3 py-1">
            {avatarBlobUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={avatarBlobUrl}
                alt=""
                className="w-20 h-20 rounded-full object-cover bg-cyan-500/10 shrink-0"
              />
            ) : (
              <span className="w-20 h-20 rounded-full bg-cyan-500/15 text-cyan-600 dark:text-cyan-300 flex items-center justify-center text-3xl font-semibold shrink-0">
                {initial}
              </span>
            )}
            <div className="min-w-0">
              <div className="text-base font-semibold truncate">{displayName}</div>
              {profile?.display_name && (
                <div className="text-xs text-muted-foreground truncate">{username}</div>
              )}
              {!profile?.display_name && (
                <div className="text-xs text-muted-foreground truncate">Signed in</div>
              )}
            </div>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {onOpenProfile && (
          <DropdownMenuItem onClick={onOpenProfile}>
            <User className="h-4 w-4 mr-2" />
            View profile
          </DropdownMenuItem>
        )}
        {onOpenSecurity && (
          <DropdownMenuItem onClick={onOpenSecurity}>
            <Shield className="h-4 w-4 mr-2" />
            Security
          </DropdownMenuItem>
        )}
        {(onOpenProfile || onOpenSecurity) && <DropdownMenuSeparator />}
        <DropdownMenuItem
          onClick={handleSignOut}
          className="text-red-600 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400"
        >
          <LogOut className="h-4 w-4 mr-2" />
          Sign out
        </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  )
}
