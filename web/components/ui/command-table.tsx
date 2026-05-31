"use client"

import React, { useState } from "react"
import { Copy, Check } from "lucide-react"

export interface CommandEntry {
  command: string
  description: string
}

export interface CommandGroup {
  title: string
  commands: CommandEntry[]
}

interface CommandTableProps {
  groups: CommandGroup[]
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const copyToClipboard = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <button
      type="button"
      onClick={copyToClipboard}
      aria-label={copied ? "Copied" : "Copy to clipboard"}
      className="inline-flex items-center gap-1 rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-600 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 transition-colors"
    >
      {copied ? (
        <>
          <Check className="h-3.5 w-3.5 text-emerald-600" aria-hidden />
          <span>Copied</span>
        </>
      ) : (
        <>
          <Copy className="h-3.5 w-3.5" aria-hidden />
          <span>Copy</span>
        </>
      )}
    </button>
  )
}

export const CommandTable: React.FC<CommandTableProps> = ({ groups }) => {
  return (
    <div className="space-y-8">
      {groups.map((group, gi) => (
        <section key={gi}>
          <h2 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{group.title}</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm border border-gray-200 rounded-md">
              <thead className="bg-gray-50 text-gray-900">
                <tr>
                  <th className="text-left px-3 py-2 border-b border-gray-200 w-2/5">Command</th>
                  <th className="text-left px-3 py-2 border-b border-gray-200">Description</th>
                  <th className="text-left px-3 py-2 border-b border-gray-200 w-24">Action</th>
                </tr>
              </thead>
              <tbody className="text-gray-800">
                {group.commands.map((cmd, ci) => (
                  <tr key={ci} className="border-b border-gray-100 last:border-b-0">
                    <td className="px-3 py-2 align-top font-mono text-xs whitespace-pre-wrap break-all">
                      {cmd.command}
                    </td>
                    <td className="px-3 py-2 align-top text-gray-700">{cmd.description}</td>
                    <td className="px-3 py-2 align-top">
                      <CopyButton text={cmd.command} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  )
}
