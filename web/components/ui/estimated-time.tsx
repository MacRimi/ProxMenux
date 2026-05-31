import React from "react"
import { Clock } from "lucide-react"
import { cn } from "@/lib/utils"

interface EstimatedTimeProps {
  minutes: number
  className?: string
}

export const EstimatedTime: React.FC<EstimatedTimeProps> = ({ minutes, className }) => {
  const label = minutes < 60 ? `~${minutes} min` : `~${Math.round(minutes / 60)} h`
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-2.5 py-0.5 text-xs font-medium text-gray-700",
        className,
      )}
    >
      <Clock className="h-3.5 w-3.5" aria-hidden="true" />
      {label}
    </span>
  )
}
