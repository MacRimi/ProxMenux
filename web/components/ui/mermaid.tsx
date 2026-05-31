"use client"

import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"

interface MermaidProps {
  chart: string
  className?: string
}

export function Mermaid({ chart, className }: MermaidProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [rendered, setRendered] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function render() {
      try {
        const mermaid = (await import("mermaid")).default
        mermaid.initialize({
          startOnLoad: false,
          theme: "default",
          securityLevel: "strict",
          fontFamily:
            'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
          flowchart: {
            htmlLabels: true,
            curve: "basis",
            useMaxWidth: true,
          },
        })

        const id = `mmd-${Math.random().toString(36).slice(2, 10)}`
        const { svg } = await mermaid.render(id, chart)

        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg
          setRendered(true)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to render diagram")
        }
      }
    }

    render()

    return () => {
      cancelled = true
    }
  }, [chart])

  if (error) {
    return (
      <div
        className={cn(
          "my-6 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800",
          className,
        )}
      >
        <p className="font-medium mb-1">Diagram failed to render</p>
        <pre className="text-xs whitespace-pre-wrap">{error}</pre>
      </div>
    )
  }

  return (
    <div
      className={cn(
        "my-6 overflow-x-auto rounded-md border border-gray-200 bg-white p-4",
        !rendered && "min-h-[120px] flex items-center justify-center text-sm text-gray-500",
        className,
      )}
    >
      {!rendered && <span>Loading diagram…</span>}
      <div ref={containerRef} className="flex justify-center [&_svg]:max-w-full [&_svg]:h-auto" />
    </div>
  )
}
