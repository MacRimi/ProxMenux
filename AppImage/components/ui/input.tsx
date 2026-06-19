import * as React from "react"

import { cn } from "@/lib/utils"

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, type, ...props }, ref) => {
  return (
    <input
      type={type}
      className={cn(
        // The previous focus style was `ring-2 ring-ring ring-offset-2`, which
        // painted a 2px white ring with a 2px gap outside the border. Inside a
        // ScrollArea or any container with `overflow-hidden` the ring's left
        // edge got clipped and the result looked broken. We replace it with a
        // 1px blue ring + matching border so a focused input now sits at the
        // same visual weight as the colored card selectors used elsewhere
        // (Backend picker, etc.).
        "flex h-10 w-full rounded-lg border border-input bg-background px-4 py-2 text-sm shadow-sm transition-all file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-blue-500 focus-visible:border-blue-500 disabled:cursor-not-allowed disabled:opacity-50 hover:border-ring/50",
        className,
      )}
      ref={ref}
      {...props}
    />
  )
})
Input.displayName = "Input"

export { Input }
