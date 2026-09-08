"use client"

import { parseEvidence, type EvidenceBlock } from "../lib/evidence-format"

/**
 * Renders a finding's evidence as tables and labelled values.
 *
 * The evidence exists so a reader can verify the conclusion for
 * themselves. A JSON dump technically contains the same facts but asks
 * the reader to parse it first, which is the part they came here to
 * avoid.
 */
export function AuditEvidence({ evidence, locale }: {
  evidence: string | null
  locale: string
}) {
  const blocks = parseEvidence(evidence, locale)
  if (blocks.length === 0) return null

  return (
    <div className="space-y-3">
      {blocks.map((block, i) => <Block key={i} block={block} />)}
    </div>
  )
}

function Block({ block }: { block: EvidenceBlock }) {
  const title = block.title
    ? <p className="text-xs font-medium text-foreground mb-1">{block.title}</p>
    : null

  if (block.kind === "table") {
    return (
      <div>
        {title}
        {/* Wide evidence scrolls inside its own box so the page itself
            never scrolls sideways. */}
        {/* Evidence is the widest thing on the page; on a narrow screen
            it stacks like the rest rather than scrolling sideways. */}
        <div className="sm:hidden space-y-2">
          {block.rows.map((row, i) => (
            <div key={i} className="rounded-md border border-border p-2.5 space-y-1">
              {row.map((cell, j) => cell === "—" || cell === "" ? null : (
                <div key={j} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="text-xs text-muted-foreground shrink-0">
                    {block.columns[j]}</span>
                  <span className="text-xs text-foreground tabular-nums break-words min-w-0">
                    {cell}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="hidden sm:block overflow-x-auto rounded-md border border-border">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-muted/50">
                {block.columns.map((c) => (
                  <th key={c} className="text-left font-medium px-3 py-1.5
                                         text-muted-foreground whitespace-nowrap">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, i) => (
                <tr key={i} className="border-t border-border">
                  {row.map((cell, j) => (
                    <td key={j} className="px-3 py-1.5 align-top tabular-nums">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  if (block.kind === "pairs") {
    return (
      <div>
        {title}
        <dl className="grid grid-cols-[minmax(0,auto)_1fr] gap-x-4 gap-y-1 text-xs
                       rounded-md border border-border px-3 py-2">
          {block.entries.map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-muted-foreground whitespace-nowrap">{label}</dt>
              <dd className="text-foreground break-words tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    )
  }

  return (
    <div>
      {title}
      {block.lines.length > 0 && (
        <ul className="text-xs text-muted-foreground space-y-0.5 rounded-md
                       border border-border px-3 py-2">
          {block.lines.map((line, i) => (
            <li key={i} className="break-words">{line}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
