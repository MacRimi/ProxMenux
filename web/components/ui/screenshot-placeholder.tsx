import React from "react"
import { Camera } from "lucide-react"
import { cn } from "@/lib/utils"

interface ScreenshotPlaceholderProps {
  description: string
  filename?: string
  className?: string
}

export const ScreenshotPlaceholder: React.FC<ScreenshotPlaceholderProps> = ({
  description,
  filename,
  className,
}) => {
  return (
    <div
      className={cn(
        "my-6 flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-gray-50 p-8 text-center",
        className,
      )}
      role="img"
      aria-label={`Screenshot placeholder: ${description}`}
    >
      <Camera className="h-8 w-8 text-gray-400 mb-2" aria-hidden="true" />
      <p className="text-sm font-medium text-gray-700 m-0">Screenshot needed</p>
      <p className="text-sm text-gray-600 mt-1 max-w-md m-0">{description}</p>
      {filename && (
        <code className="mt-2 text-xs bg-white border border-gray-200 rounded px-2 py-0.5 text-gray-600">
          {filename}
        </code>
      )}
    </div>
  )
}
