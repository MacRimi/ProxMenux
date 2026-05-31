import React from "react"
import { FolderOpen } from "lucide-react"
import { cn } from "@/lib/utils"

interface SectionBadgeProps {
  section: string
  className?: string
}

export const SectionBadge: React.FC<SectionBadgeProps> = ({ section, className }) => {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-800",
        className,
      )}
    >
      <FolderOpen className="h-3.5 w-3.5" aria-hidden="true" />
      {section}
    </span>
  )
}
