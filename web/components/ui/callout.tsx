import React from "react"
import { Info, Lightbulb, CheckCircle2, AlertTriangle, AlertOctagon, Wrench } from "lucide-react"
import { cn } from "@/lib/utils"

type CalloutVariant = "info" | "tip" | "success" | "warning" | "danger" | "troubleshoot"

interface CalloutProps {
  variant?: CalloutVariant
  title?: string
  children: React.ReactNode
  className?: string
}

const variantStyles: Record<
  CalloutVariant,
  { container: string; icon: string; Icon: React.ComponentType<{ className?: string }> }
> = {
  info: {
    container: "bg-blue-50 border-blue-300 text-blue-900",
    icon: "text-blue-600",
    Icon: Info,
  },
  tip: {
    container: "bg-emerald-50 border-emerald-300 text-emerald-900",
    icon: "text-emerald-600",
    Icon: Lightbulb,
  },
  success: {
    container: "bg-green-50 border-green-300 text-green-900",
    icon: "text-green-600",
    Icon: CheckCircle2,
  },
  warning: {
    container: "bg-amber-50 border-amber-300 text-amber-900",
    icon: "text-amber-600",
    Icon: AlertTriangle,
  },
  danger: {
    container: "bg-red-50 border-red-300 text-red-900",
    icon: "text-red-600",
    Icon: AlertOctagon,
  },
  troubleshoot: {
    container: "bg-slate-50 border-slate-300 text-slate-900",
    icon: "text-slate-600",
    Icon: Wrench,
  },
}

export const Callout: React.FC<CalloutProps> = ({
  variant = "info",
  title,
  children,
  className,
}) => {
  const { container, icon, Icon } = variantStyles[variant]

  return (
    <div
      role="note"
      className={cn(
        "my-6 flex gap-3 rounded-lg border-l-4 p-4 [&_p]:my-1 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0",
        container,
        className,
      )}
    >
      <Icon className={cn("h-5 w-5 flex-shrink-0 mt-0.5", icon)} aria-hidden="true" />
      <div className="flex-1 min-w-0">
        {title && <p className="font-semibold mb-1">{title}</p>}
        <div className="text-sm leading-relaxed">{children}</div>
      </div>
    </div>
  )
}
