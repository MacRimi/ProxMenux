import React from "react"
import { SectionBadge } from "./section-badge"
import { EstimatedTime } from "./estimated-time"
import { ScriptViewer } from "./script-viewer"
import { cn } from "@/lib/utils"

interface DocHeaderProps {
  title: string
  description?: string
  section?: string
  estimatedMinutes?: number
  scriptPath?: string
  className?: string
}

export const DocHeader: React.FC<DocHeaderProps> = ({
  title,
  description,
  section,
  estimatedMinutes,
  scriptPath,
  className,
}) => {
  const hasBadges = section || estimatedMinutes || scriptPath
  return (
    <header className={cn("mb-8", className)}>
      <h1 className="text-3xl font-bold text-gray-900 mb-2">{title}</h1>
      {hasBadges && (
        <div className="flex flex-wrap items-center gap-2 mb-3">
          {section && <SectionBadge section={section} />}
          {estimatedMinutes !== undefined && <EstimatedTime minutes={estimatedMinutes} />}
          {scriptPath && <ScriptViewer scriptPath={scriptPath} />}
        </div>
      )}
      {description && (
        <p className="text-gray-700 leading-relaxed m-0">{description}</p>
      )}
    </header>
  )
}
