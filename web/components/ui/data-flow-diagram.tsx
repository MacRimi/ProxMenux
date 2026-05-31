import React, { Fragment } from "react"
import { ArrowRight, ArrowDown, ArrowLeftRight, ArrowUpDown } from "lucide-react"
import { cn } from "@/lib/utils"

type NodeVariant = "source" | "bridge" | "target"

export interface DataFlowNode {
  label: string
  detail?: string
  variant?: NodeVariant
}

export interface DataFlowDiagramProps {
  nodes: DataFlowNode[]
  arrowLabel?: string
  bidirectional?: boolean
  command?: string
  caption?: string
  className?: string
}

const variantStyles: Record<NodeVariant, string> = {
  source: "border-blue-300 bg-blue-50",
  bridge: "border-gray-300 bg-gray-50",
  target: "border-amber-300 bg-amber-50",
}

const variantLabel: Record<NodeVariant, string> = {
  source: "text-blue-800",
  bridge: "text-gray-700",
  target: "text-amber-800",
}

export const DataFlowDiagram: React.FC<DataFlowDiagramProps> = ({
  nodes,
  arrowLabel,
  bidirectional = false,
  command,
  caption,
  className,
}) => {
  const HorizArrow = bidirectional ? ArrowLeftRight : ArrowRight
  const VertArrow = bidirectional ? ArrowUpDown : ArrowDown
  return (
    <div className={cn("my-6 not-prose", className)}>
      <div className="flex flex-col md:flex-row md:items-stretch gap-3">
        {nodes.map((node, i) => {
          const variant = node.variant ?? "bridge"
          return (
            <Fragment key={i}>
              <div
                className={cn(
                  "flex-1 min-w-0 rounded-lg border-2 p-4 flex flex-col",
                  variantStyles[variant],
                )}
              >
                <div
                  className={cn(
                    "text-xs font-semibold uppercase tracking-wide mb-2",
                    variantLabel[variant],
                  )}
                >
                  {node.label}
                </div>
                {node.detail && (
                  <div className="font-mono text-sm text-gray-800 whitespace-pre-line leading-relaxed">
                    {node.detail}
                  </div>
                )}
              </div>

              {i < nodes.length - 1 && (
                <div className="flex md:flex-col items-center justify-center text-gray-500 px-2">
                  <HorizArrow className="hidden md:block h-5 w-5" aria-hidden />
                  <VertArrow className="md:hidden h-5 w-5" aria-hidden />
                  {arrowLabel && (
                    <span className="ml-2 md:ml-0 md:mt-1 text-xs font-semibold tracking-wide">
                      {arrowLabel}
                    </span>
                  )}
                </div>
              )}
            </Fragment>
          )
        })}
      </div>

      {command && (
        <pre className="mt-4 rounded-md bg-gray-100 p-3 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">
          {command}
        </pre>
      )}

      {caption && (
        <p className="mt-2 text-xs text-gray-500 text-center">{caption}</p>
      )}
    </div>
  )
}
