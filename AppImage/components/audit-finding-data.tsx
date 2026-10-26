"use client"

import { presentFinding, type PresentedFinding, type AuditTranslate } from "../lib/audit-presentation"

export function AuditFindingData({ finding, t, locale }: {
  finding: PresentedFinding; t: AuditTranslate; locale: string
}) {
  return <div className="space-y-4">{presentFinding(finding, t, locale).map((group, index) =>
    <section key={index}>
      <p className="text-sm font-medium mb-2">{group.title}</p>
      {group.note && <p className="text-sm text-muted-foreground mb-2">{group.note}</p>}
      {/* Wide on a screen that has the width; stacked where it does
          not, so a heading stays beside the value it belongs to instead
          of scrolling away from it. */}
      <div className="hidden sm:block overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-muted-foreground"><tr>{group.columns.map((column, i) =>
            <th key={i} className="px-3 py-2 text-left font-medium">{column}</th>)}</tr></thead>
          <tbody>{group.rows.map((row, i) => <tr key={i} className="border-t border-border">
            {row.cells.map((cell, j) => <td key={j} className="px-3 py-2 align-top break-words tabular-nums">{cell}</td>)}
          </tr>)}</tbody>
        </table>
      </div>
      <div className="sm:hidden space-y-2">{group.rows.map((row, i) =>
        <div key={i} className="rounded-md border border-border p-2.5 space-y-1">
          {row.cells.map((cell, j) => cell === "" || cell === "—" ? null : (
            <div key={j} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-xs text-muted-foreground shrink-0">{group.columns[j]}</span>
              <span className="text-sm text-foreground tabular-nums break-words min-w-0">{cell}</span>
            </div>
          ))}
        </div>)}</div>
    </section>)}</div>
}
