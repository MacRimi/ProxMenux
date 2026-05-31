import React from "react"
import { Sparkles, Wrench, Zap } from "lucide-react"
import { cn } from "@/lib/utils"

export type Difficulty = "beginner" | "intermediate" | "advanced"

interface DifficultyBadgeProps {
  level: Difficulty
  className?: string
}

const levelConfig: Record<
  Difficulty,
  { label: string; style: string; Icon: React.ComponentType<{ className?: string }> }
> = {
  beginner: {
    label: "Beginner",
    style: "bg-emerald-100 text-emerald-800 border-emerald-200",
    Icon: Sparkles,
  },
  intermediate: {
    label: "Intermediate",
    style: "bg-amber-100 text-amber-800 border-amber-200",
    Icon: Wrench,
  },
  advanced: {
    label: "Advanced",
    style: "bg-red-100 text-red-800 border-red-200",
    Icon: Zap,
  },
}

export const DifficultyBadge: React.FC<DifficultyBadgeProps> = ({ level, className }) => {
  const { label, style, Icon } = levelConfig[level]
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        style,
        className,
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {label}
    </span>
  )
}
