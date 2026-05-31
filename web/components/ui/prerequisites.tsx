import React from "react"
import { CheckCircle2, ListChecks } from "lucide-react"
import { cn } from "@/lib/utils"

interface PrerequisiteItem {
  label: React.ReactNode
  check?: string
}

interface PrerequisitesProps {
  title?: string
  items: PrerequisiteItem[]
  className?: string
}

export const Prerequisites: React.FC<PrerequisitesProps> = ({
  title = "Before you start",
  items,
  className,
}) => {
  return (
    <div
      className={cn(
        "my-6 rounded-lg border border-gray-200 bg-gray-50 p-5",
        className,
      )}
    >
      <div className="flex items-center gap-2 mb-3">
        <ListChecks className="h-5 w-5 text-gray-700" aria-hidden="true" />
        <h4 className="font-semibold text-gray-900 m-0">{title}</h4>
      </div>
      <ul className="space-y-2 list-none pl-0">
        {items.map((item, idx) => (
          <li key={idx} className="flex items-start gap-2">
            <CheckCircle2
              className="h-4 w-4 text-emerald-600 flex-shrink-0 mt-1"
              aria-hidden="true"
            />
            <div className="flex-1 text-sm text-gray-800">
              <div>{item.label}</div>
              {item.check && (
                <code className="mt-1 inline-block text-xs bg-white border border-gray-200 rounded px-1.5 py-0.5 text-gray-700">
                  {item.check}
                </code>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
