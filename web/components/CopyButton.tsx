"use client"

import { useState } from "react"
import { Copy, Check } from "lucide-react"

/**
 * Copy-to-clipboard button used by the (server-rendered) CopyableCode
 * wrapper. Kept as a tiny client component so the parent can stay on
 * the server side and run Shiki's syntax-highlighter at build time
 * (no highlighter JS in the client bundle, just the pre-coloured
 * HTML).
 */
export function CopyButton({ text }: { text: string }) {
  const [isCopied, setIsCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setIsCopied(true)
      setTimeout(() => setIsCopied(false), 2000)
    } catch {
      // clipboard may be unavailable on insecure origins; swallow.
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 p-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-md transition-colors"
      aria-label="Copy code"
    >
      {isCopied ? (
        <Check className="h-4 w-4 text-green-400" />
      ) : (
        <Copy className="h-4 w-4 text-gray-300" />
      )}
    </button>
  )
}
