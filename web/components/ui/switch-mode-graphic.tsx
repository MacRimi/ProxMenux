import React from "react"
import { cn } from "@/lib/utils"

interface SwitchModeGraphicProps {
  mode: "lxc" | "vm"
  title: string
  description: string
  className?: string
}

const palette = {
  lxc: {
    active: "#60a5fa", // blue-400
    activeText: "text-blue-400",
  },
  vm: {
    active: "#c084fc", // purple-400
    activeText: "text-purple-400",
  },
} as const

const inactive = "#4b5563" // gray-600
const inactiveText = "text-gray-500"

export const SwitchModeGraphic: React.FC<SwitchModeGraphicProps> = ({
  mode,
  title,
  description,
  className,
}) => {
  const color = palette[mode].active
  const lxcColor = mode === "lxc" ? color : inactive
  const vmColor = mode === "vm" ? color : inactive
  const lxcLabelClass = mode === "lxc" ? palette.lxc.activeText : inactiveText
  const vmLabelClass = mode === "vm" ? palette.vm.activeText : inactiveText

  return (
    <div
      className={cn(
        "rounded-xl border border-gray-800 bg-gray-950 p-5 shadow-sm",
        className,
      )}
    >
      <p className="text-xs font-semibold tracking-wider text-gray-400 mb-4 uppercase m-0">
        Switch Mode
      </p>

      <div className="flex items-center gap-5">
        {/* Diagram */}
        <svg
          viewBox="0 0 240 150"
          xmlns="http://www.w3.org/2000/svg"
          className="flex-shrink-0"
          style={{ width: "150px", height: "auto" }}
          aria-hidden="true"
        >
          {/* GPU box */}
          <g>
            <rect
              x="4"
              y="55"
              width="60"
              height="40"
              rx="4"
              fill="none"
              stroke={color}
              strokeWidth="2.5"
            />
            {/* GPU "pins" top/bottom */}
            {[14, 22, 30, 38, 46, 54].map((x, i) => (
              <React.Fragment key={i}>
                <line x1={x} y1="50" x2={x} y2="55" stroke={color} strokeWidth="2" />
                <line x1={x} y1="95" x2={x} y2="100" stroke={color} strokeWidth="2" />
              </React.Fragment>
            ))}
            <text
              x="34"
              y="80"
              textAnchor="middle"
              fill={color}
              fontSize="12"
              fontWeight="700"
              fontFamily="ui-sans-serif, system-ui, sans-serif"
            >
              GPU
            </text>
          </g>

          {/* Horizontal line GPU → dot */}
          <line x1="64" y1="75" x2="114" y2="75" stroke={color} strokeWidth="2.5" />

          {/* Central dot */}
          <circle cx="118" cy="75" r="9" fill="none" stroke={color} strokeWidth="2.5" />
          <circle cx="118" cy="75" r="4" fill={color} />

          {/* Branch to LXC (top) */}
          <path
            d="M 127 75 L 145 75 L 170 45"
            fill="none"
            stroke={lxcColor}
            strokeWidth="2.5"
            strokeLinecap="round"
          />
          {/* LXC box (stacked rectangles icon) */}
          <g>
            <rect
              x="175"
              y="30"
              width="45"
              height="30"
              rx="3"
              fill="none"
              stroke={lxcColor}
              strokeWidth="2.5"
            />
            <line x1="181" y1="38" x2="189" y2="38" stroke={lxcColor} strokeWidth="2.5" strokeLinecap="round" />
            <circle cx="214" cy="38" r="1.5" fill={lxcColor} />
            <line x1="181" y1="46" x2="189" y2="46" stroke={lxcColor} strokeWidth="2.5" strokeLinecap="round" />
            <circle cx="214" cy="46" r="1.5" fill={lxcColor} />
            <line x1="181" y1="54" x2="189" y2="54" stroke={lxcColor} strokeWidth="2.5" strokeLinecap="round" />
            <circle cx="214" cy="54" r="1.5" fill={lxcColor} />
          </g>

          {/* Branch to VM (bottom) */}
          <path
            d="M 127 75 L 145 75 L 170 105"
            fill="none"
            stroke={vmColor}
            strokeWidth="2.5"
            strokeLinecap="round"
          />
          {/* VM box (monitor icon) */}
          <g>
            <rect
              x="175"
              y="90"
              width="45"
              height="28"
              rx="3"
              fill="none"
              stroke={vmColor}
              strokeWidth="2.5"
            />
            <line
              x1="175"
              y1="113"
              x2="220"
              y2="113"
              stroke={vmColor}
              strokeWidth="2.5"
              strokeLinecap="round"
            />
            <line x1="189" y1="125" x2="206" y2="125" stroke={vmColor} strokeWidth="2.5" strokeLinecap="round" />
            <line x1="197" y1="118" x2="197" y2="125" stroke={vmColor} strokeWidth="2.5" />
          </g>
        </svg>

        {/* Labels column */}
        <div className="flex flex-col gap-1 min-w-0">
          <div className="flex items-center gap-3">
            <span className={cn("text-sm font-semibold", lxcLabelClass)}>LXC</span>
          </div>
          <div className="flex items-center gap-3">
            <span className={cn("text-sm font-semibold", vmLabelClass)}>VM</span>
          </div>
          <p className={cn("text-base font-bold mt-2 mb-0", palette[mode].activeText)}>{title}</p>
          <p className="text-sm text-gray-400 m-0">{description}</p>
        </div>
      </div>
    </div>
  )
}
