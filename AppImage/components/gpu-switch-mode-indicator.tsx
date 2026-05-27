"use client"

import { cn } from "@/lib/utils"

interface SriovInfo {
  role: "vf" | "pf-active" | "pf-idle"
  physfn?: string   // VF only: parent PF BDF
  vfCount?: number  // PF only: active VF count
  totalvfs?: number // PF only: maximum VFs
}

interface GpuSwitchModeIndicatorProps {
  mode: "lxc" | "vm" | "sriov" | "unknown"
  isEditing?: boolean
  pendingMode?: "lxc" | "vm" | null
  onToggle?: (e: React.MouseEvent) => void
  className?: string
  sriovInfo?: SriovInfo
}

export function GpuSwitchModeIndicator({
  mode,
  isEditing = false,
  pendingMode = null,
  onToggle,
  className,
  sriovInfo,
}: GpuSwitchModeIndicatorProps) {
  // SR-IOV is a non-editable hardware state. Pending toggles don't apply here.
  const displayMode = mode === "sriov" ? "sriov" : (pendingMode ?? mode)
  const isLxcActive = displayMode === "lxc"
  const isVmActive = displayMode === "vm"
  const isSriovActive = displayMode === "sriov"
  const hasChanged =
    mode !== "sriov" && pendingMode !== null && pendingMode !== mode

  // Colors
  const sriovColor = "#14b8a6" // teal-500
  const activeColor = isSriovActive
    ? sriovColor
    : isLxcActive
      ? "#3b82f6"
      : isVmActive
        ? "#a855f7"
        : "#6b7280"
  const inactiveColor = "#374151" // gray-700 for dark theme
  const dimmedColor = "#4b5563"   // gray-600 for dashed SR-IOV branches
  const lxcColor = isLxcActive ? "#3b82f6" : inactiveColor
  const vmColor = isVmActive ? "#a855f7" : inactiveColor

  const handleClick = (e: React.MouseEvent) => {
    // SR-IOV state can't be toggled — swallow the click so it doesn't reach
    // the card (which would open the detail modal unexpectedly from this
    // area). For lxc/vm, preserve the original behavior.
    if (isSriovActive) {
      e.stopPropagation()
      return
    }
    if (isEditing) {
      e.stopPropagation()
      if (onToggle) {
        onToggle(e)
      }
    }
    // When not editing, let the click propagate to the card to open the modal
  }

  // Build the VF count label shown in the SR-IOV badge. For PFs we know
  // exactly how many VFs are active; for a VF we show its parent PF.
  const sriovBadgeText = (() => {
    if (!isSriovActive) return ""
    if (sriovInfo?.role === "vf") return "SR-IOV VF"
    if (sriovInfo?.vfCount && sriovInfo.vfCount > 0) return `SR-IOV ×${sriovInfo.vfCount}`
    return "SR-IOV"
  })()

  return (
    <div
      className={cn(
        // On very narrow containers (mobile, narrow modal), stack the SVG
        // above the status text so the 224px-wide SVG doesn't squeeze the
        // text into a 2-character-wide column. At sm+ we go back to the
        // original side-by-side layout.
        "flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:gap-6",
        isEditing && !isSriovActive && "cursor-pointer",
        className
      )}
      onClick={handleClick}
    >
      {/* Large SVG Diagram */}
      <svg
        viewBox="0 0 220 100"
        className="h-24 w-56 flex-shrink-0"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* GPU Chip - Large with "GPU" text */}
        <g transform="translate(0, 22)">
          {/* Main chip body */}
          <rect
            x="4"
            y="8"
            width="44"
            height="36"
            rx="6"
            fill={`${activeColor}20`}
            stroke={activeColor}
            strokeWidth="2.5"
            className="transition-all duration-300"
          />
          {/* Chip pins - top */}
          <line x1="14" y1="2" x2="14" y2="8" stroke={activeColor} strokeWidth="2.5" strokeLinecap="round" className="transition-all duration-300" />
          <line x1="26" y1="2" x2="26" y2="8" stroke={activeColor} strokeWidth="2.5" strokeLinecap="round" className="transition-all duration-300" />
          <line x1="38" y1="2" x2="38" y2="8" stroke={activeColor} strokeWidth="2.5" strokeLinecap="round" className="transition-all duration-300" />
          {/* Chip pins - bottom */}
          <line x1="14" y1="44" x2="14" y2="50" stroke={activeColor} strokeWidth="2.5" strokeLinecap="round" className="transition-all duration-300" />
          <line x1="26" y1="44" x2="26" y2="50" stroke={activeColor} strokeWidth="2.5" strokeLinecap="round" className="transition-all duration-300" />
          <line x1="38" y1="44" x2="38" y2="50" stroke={activeColor} strokeWidth="2.5" strokeLinecap="round" className="transition-all duration-300" />
          {/* GPU text */}
          <text
            x="26"
            y="32"
            textAnchor="middle"
            fill={activeColor}
            className="text-[14px] font-bold transition-all duration-300"
            style={{ fontFamily: 'system-ui, sans-serif' }}
          >
            GPU
          </text>
        </g>

        {/* Connection line from GPU to switch */}
        <line
          x1="52"
          y1="50"
          x2="78"
          y2="50"
          stroke={activeColor}
          strokeWidth="3"
          strokeLinecap="round"
          className="transition-all duration-300"
        />

        {/* Central Switch Node - Large circle with inner dot */}
        <circle
          cx="95"
          cy="50"
          r="14"
          fill={isEditing && !isSriovActive ? "#f59e0b20" : `${activeColor}20`}
          stroke={isEditing && !isSriovActive ? "#f59e0b" : activeColor}
          strokeWidth="3"
          className="transition-all duration-300"
        />
        <circle
          cx="95"
          cy="50"
          r="6"
          fill={isEditing && !isSriovActive ? "#f59e0b" : activeColor}
          className="transition-all duration-300"
        />

        {/* LXC Branch Line - going up-right.
            In SR-IOV mode the branch is dashed + dimmed to show that the
            target is theoretically reachable via a VF but not controlled
            by ProxMenux. */}
        <path
          d="M 109 42 L 135 20"
          fill="none"
          stroke={isSriovActive ? dimmedColor : lxcColor}
          strokeWidth={isLxcActive ? "3.5" : "2"}
          strokeLinecap="round"
          strokeDasharray={isSriovActive ? "3 3" : undefined}
          className="transition-all duration-300"
        />

        {/* VM Branch Line - going down-right (dashed/dimmed in SR-IOV). */}
        <path
          d="M 109 58 L 135 80"
          fill="none"
          stroke={isSriovActive ? dimmedColor : vmColor}
          strokeWidth={isVmActive ? "3.5" : "2"}
          strokeLinecap="round"
          strokeDasharray={isSriovActive ? "3 3" : undefined}
          className="transition-all duration-300"
        />

        {/* SR-IOV in-line connector + badge (only when mode === 'sriov').
            A horizontal line from the switch node leads to a pill-shaped
            badge carrying the "SR-IOV ×N" label. Placed on the GPU's
            baseline to visually read as an in-line extension, not as a
            third branch. */}
        {isSriovActive && (
          <>
            <line
              x1="109"
              y1="50"
              x2="130"
              y2="50"
              stroke={sriovColor}
              strokeWidth="3"
              strokeLinecap="round"
              className="transition-all duration-300"
            />
            <rect
              x="132"
              y="40"
              width="60"
              height="20"
              rx="10"
              fill={`${sriovColor}25`}
              stroke={sriovColor}
              strokeWidth="2"
              className="transition-all duration-300"
            />
            <text
              x="162"
              y="54"
              textAnchor="middle"
              fill={sriovColor}
              className="text-[11px] font-bold transition-all duration-300"
              style={{ fontFamily: 'system-ui, sans-serif' }}
            >
              {sriovBadgeText}
            </text>
          </>
        )}

        {/* LXC Container Icon - dimmed/smaller in SR-IOV mode. */}
        {!isSriovActive && (
          <g transform="translate(138, 2)">
            <rect
              x="0"
              y="0"
              width="32"
              height="28"
              rx="4"
              fill={isLxcActive ? `${lxcColor}25` : "transparent"}
              stroke={lxcColor}
              strokeWidth={isLxcActive ? "2.5" : "1.5"}
              className="transition-all duration-300"
            />
            <line x1="0" y1="10" x2="32" y2="10" stroke={lxcColor} strokeWidth={isLxcActive ? "1.5" : "1"} className="transition-all duration-300" />
            <line x1="0" y1="19" x2="32" y2="19" stroke={lxcColor} strokeWidth={isLxcActive ? "1.5" : "1"} className="transition-all duration-300" />
            <circle cx="7" cy="5" r="2" fill={lxcColor} className="transition-all duration-300" />
            <circle cx="7" cy="14.5" r="2" fill={lxcColor} className="transition-all duration-300" />
            <circle cx="7" cy="23.5" r="2" fill={lxcColor} className="transition-all duration-300" />
          </g>
        )}
        {/* SR-IOV: compact dimmed LXC glyph so the geometry stays recognizable
            but it's clearly not the active target. */}
        {isSriovActive && (
          <g transform="translate(138, 6)" opacity="0.35">
            <rect x="0" y="0" width="20" height="18" rx="3" fill="transparent" stroke={dimmedColor} strokeWidth="1.5" />
            <line x1="0" y1="6" x2="20" y2="6" stroke={dimmedColor} strokeWidth="1" />
            <line x1="0" y1="12" x2="20" y2="12" stroke={dimmedColor} strokeWidth="1" />
          </g>
        )}

        {/* LXC Label */}
        {!isSriovActive && (
          <text
            x="188"
            y="22"
            textAnchor="start"
            fill={lxcColor}
            className={cn(
              "transition-all duration-300",
              isLxcActive ? "text-[14px] font-bold" : "text-[12px] font-medium"
            )}
            style={{ fontFamily: 'system-ui, sans-serif' }}
          >
            LXC
          </text>
        )}
        {isSriovActive && (
          <text
            x="162"
            y="16"
            fill={dimmedColor}
            className="text-[9px] font-medium"
            style={{ fontFamily: 'system-ui, sans-serif' }}
          >
            LXC
          </text>
        )}

        {/* VM Monitor Icon - active view */}
        {!isSriovActive && (
          <g transform="translate(138, 65)">
            <rect
              x="2"
              y="0"
              width="28"
              height="18"
              rx="3"
              fill={isVmActive ? `${vmColor}25` : "transparent"}
              stroke={vmColor}
              strokeWidth={isVmActive ? "2.5" : "1.5"}
              className="transition-all duration-300"
            />
            <rect
              x="5"
              y="3"
              width="22"
              height="12"
              rx="1"
              fill={isVmActive ? `${vmColor}30` : `${vmColor}10`}
              className="transition-all duration-300"
            />
            <line x1="16" y1="18" x2="16" y2="24" stroke={vmColor} strokeWidth={isVmActive ? "2.5" : "1.5"} strokeLinecap="round" className="transition-all duration-300" />
            <line x1="8" y1="24" x2="24" y2="24" stroke={vmColor} strokeWidth={isVmActive ? "2.5" : "1.5"} strokeLinecap="round" className="transition-all duration-300" />
          </g>
        )}
        {/* SR-IOV: compact dimmed VM monitor glyph, mirror of the LXC glyph. */}
        {isSriovActive && (
          <g transform="translate(138, 72)" opacity="0.35">
            <rect x="0" y="0" width="20" height="13" rx="2" fill="transparent" stroke={dimmedColor} strokeWidth="1.5" />
            <line x1="10" y1="13" x2="10" y2="17" stroke={dimmedColor} strokeWidth="1.5" strokeLinecap="round" />
            <line x1="5" y1="17" x2="15" y2="17" stroke={dimmedColor} strokeWidth="1.5" strokeLinecap="round" />
          </g>
        )}

        {/* VM Label */}
        {!isSriovActive && (
          <text
            x="188"
            y="84"
            textAnchor="start"
            fill={vmColor}
            className={cn(
              "transition-all duration-300",
              isVmActive ? "text-[14px] font-bold" : "text-[12px] font-medium"
            )}
            style={{ fontFamily: 'system-ui, sans-serif' }}
          >
            VM
          </text>
        )}
        {isSriovActive && (
          <text
            x="162"
            y="82"
            fill={dimmedColor}
            className="text-[9px] font-medium"
            style={{ fontFamily: 'system-ui, sans-serif' }}
          >
            VM
          </text>
        )}
      </svg>

      {/* Status Text - Large like GPU name */}
      <div className="flex flex-col gap-1 min-w-0 flex-1">
        <span
          className={cn(
            "text-base font-semibold transition-all duration-300",
            isSriovActive
              ? "text-teal-500"
              : isLxcActive
                ? "text-blue-500"
                : isVmActive
                  ? "text-purple-500"
                  : "text-muted-foreground"
          )}
        >
          {isSriovActive
            ? "SR-IOV active"
            : isLxcActive
              ? "Ready for LXC containers"
              : isVmActive
                ? "Ready for VM passthrough"
                : "Mode unknown"}
        </span>
        <span className="text-sm text-muted-foreground">
          {isSriovActive
            ? "Virtual Functions managed externally"
            : isLxcActive
              ? "Native driver active"
              : isVmActive
                ? "VFIO-PCI driver active"
                : "No driver detected"}
        </span>
        {isSriovActive && sriovInfo && (
          <span className="text-xs font-mono text-teal-600/80 dark:text-teal-400/80">
            {sriovInfo.role === "vf"
              ? `Virtual Function${sriovInfo.physfn ? ` · parent PF ${sriovInfo.physfn}` : ""}`
              : sriovInfo.vfCount !== undefined
                ? `1 PF + ${sriovInfo.vfCount} VF${sriovInfo.vfCount === 1 ? "" : "s"}${sriovInfo.totalvfs ? ` / ${sriovInfo.totalvfs} max` : ""}`
                : null}
          </span>
        )}
        {hasChanged && (
          <span className="text-sm text-amber-500 font-medium animate-pulse">
            Change pending...
          </span>
        )}
      </div>
    </div>
  )
}
