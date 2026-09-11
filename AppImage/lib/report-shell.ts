/**
 * Shared shell for ProxMenux Monitor reports.
 *
 * The SMART, latency and audit reports are one family: same header with
 * the product mark and a report identifier, numbered sections, the same
 * cards, tables and callouts, the same dark action bar on screen that
 * disappears when printing. This module holds that common language so a
 * new report joins the family instead of inventing its own.
 *
 * The stylesheet is the one the SMART report established, kept verbatim
 * so the two documents are indistinguishable side by side.
 */

export const REPORT_CSS = `  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1a1a2e; background: #fff; font-size: 13px; line-height: 1.5; }
  @page { margin: 10mm; size: A4; }

  /* === SCREEN: responsive layout === */
  @media screen {
    body { max-width: 1000px; margin: 0 auto; padding: 24px 32px; padding-top: 64px; overflow-x: hidden; }
  }
  @media screen and (max-width: 640px) {
    body { padding: 16px; padding-top: 64px; }
    .grid-4 { grid-template-columns: 1fr 1fr; }
    .grid-3 { grid-template-columns: 1fr 1fr; }
    .rpt-header { flex-direction: column; gap: 12px; align-items: flex-start; }
    .rpt-header-right { text-align: left; }
    .exec-box { flex-wrap: wrap; }
    .card-c .card-value { font-size: 16px; }
  }

  /* === PRINT: force desktop A4 layout from any device === */
  @media print {
    html, body { margin: 0 !important; padding: 0 !important; width: 100% !important; max-width: none !important; }
    .no-print { display: none !important; }
    .top-bar { display: none !important; }
    .page-break { page-break-before: always; }
    * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
    body { font-size: 11px; padding-top: 0 !important; }
    /* Force desktop grid layout regardless of viewport */
    .grid-4 { grid-template-columns: 1fr 1fr 1fr 1fr !important; }
    .grid-3 { grid-template-columns: 1fr 1fr 1fr !important; }
    .grid-2 { grid-template-columns: 1fr 1fr !important; }
    .rpt-header { flex-direction: row !important; align-items: center !important; }
    .rpt-header-right { text-align: right !important; }
    .exec-box { flex-wrap: nowrap !important; }
    .card-c .card-value { font-size: 20px !important; }
    /* Page break control */
    .section { page-break-inside: avoid; break-inside: avoid; margin-bottom: 15px; }
    .exec-box { page-break-inside: avoid; break-inside: avoid; }
    .card { page-break-inside: avoid; break-inside: avoid; }
    .grid-2, .grid-3, .grid-4 { page-break-inside: avoid; break-inside: avoid; }
    .section-title { page-break-after: avoid; break-after: avoid; }
    .attr-tbl tr { page-break-inside: avoid; break-inside: avoid; }
    .attr-tbl thead { display: table-header-group; }
    .rpt-footer { page-break-inside: avoid; break-inside: avoid; margin-top: 20px; }
    svg { max-width: 100%; height: auto; }
    /* Darken light grays for PDF readability */
    .rpt-header-left p, .rpt-header-right { color: #374151; }
    .rpt-header-right .rid { color: #4b5563; }
    .exec-text p { color: #374151; }
    .card-label { color: #4b5563; }
    .rpt-footer { color: #4b5563; }
    [style*="color:#64748b"] { color: #374151 !important; }
    [style*="color:#94a3b8"] { color: #4b5563 !important; }
    [style*="color: #64748b"] { color: #374151 !important; }
    [style*="color: #94a3b8"] { color: #4b5563 !important; }
    [style*="color:#16a34a"], [style*="color: #16a34a"] { color: #16a34a !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    [style*="color:#dc2626"] { color: #dc2626 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    [style*="color:#ca8a04"] { color: #ca8a04 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .health-ring, .card-value, .f-tag { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }

  /* Top bar for screen only */
  .top-bar {
    position: fixed; top: 0; left: 0; right: 0; background: #0f172a; color: #e2e8f0;
    padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; z-index: 100;
    font-size: 13px;
  }
  .top-bar-left { display: flex; align-items: center; gap: 12px; }
  .top-bar-title { font-weight: 600; }
  .top-bar-subtitle { font-size: 11px; color: #94a3b8; }
  .top-bar button {
    background: #06b6d4; color: #fff; border: none; padding: 8px 12px; border-radius: 6px;
    font-size: 14px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
  }
  .top-bar button:hover { background: #0891b2; }
  .top-bar .btn-group { display: flex; gap: 8px; }
  .top-bar button svg { width: 18px; height: 18px; display: block; }

  /* Header */
  .rpt-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 0; border-bottom: 3px solid #0f172a; margin-bottom: 22px;
  }
  .rpt-header-left { display: flex; align-items: center; gap: 14px; }
  .rpt-header-left img { height: 44px; width: auto; }
  .rpt-header-left h1 { font-size: 22px; font-weight: 700; color: #0f172a; }
  .rpt-header-left p { font-size: 11px; color: #64748b; }
  .rpt-header-right { text-align: right; font-size: 11px; color: #64748b; line-height: 1.6; }
  .rpt-header-right .rid { font-family: monospace; font-size: 10px; color: #94a3b8; }

  /* Sections */
  .section { margin-bottom: 22px; }
  .section-title {
    font-size: 14px; font-weight: 700; color: #0f172a; text-transform: uppercase;
    letter-spacing: 0.05em; padding-bottom: 5px; border-bottom: 2px solid #e2e8f0; margin-bottom: 12px;
  }

  /* Executive summary */
  .exec-box {
    display: flex; align-items: flex-start; gap: 20px; padding: 20px;
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 16px;
  }
  .health-ring {
    width: 96px; height: 96px; border-radius: 50%; display: flex; flex-direction: column;
    align-items: center; justify-content: center; border: 4px solid; flex-shrink: 0;
  }
  .health-icon { font-size: 32px; line-height: 1; }
  .health-lbl { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; margin-top: 4px; }
  .exec-text { flex: 1; min-width: 200px; }
  .exec-text h3 { font-size: 16px; margin-bottom: 4px; }
  .exec-text p { font-size: 12px; color: #64748b; line-height: 1.5; }

  /* Grids */
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .grid-4 { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px; }
  .card { padding: 10px 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; }
  .card-label { font-size: 10px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 2px; }
  .card-value { font-size: 13px; font-weight: 600; color: #0f172a; }
  .card-c { text-align: center; }
  .card-c .card-value { font-size: 20px; font-weight: 800; }

  /* Tags */
  .f-tag { font-size: 9px; padding: 2px 6px; border-radius: 4px; font-weight: 600; }

  /* Tables */
  .attr-tbl { width: 100%; border-collapse: collapse; font-size: 11px; }
  .attr-tbl th { text-align: left; padding: 6px 4px; font-size: 10px; color: #64748b; font-weight: 600; border-bottom: 2px solid #e2e8f0; background: #f1f5f9; }
  .attr-tbl td { padding: 5px 4px; border-bottom: 1px solid #f1f5f9; color: #1e293b; }
  .attr-tbl tr:hover { background: #f8fafc; }
  .attr-tbl .col-name { word-break: break-word; }
  .attr-tbl .col-raw { font-family: monospace; font-size: 10px; }

  /* Attribute explanation rows: full-width below the data row */
  .attr-explain-row td { padding-top: 0 !important; }
  .attr-explain-row:hover { background: transparent; }

  /* Recommendations */
  .rec-item { display: flex; align-items: flex-start; gap: 12px; padding: 12px; border-radius: 6px; margin-bottom: 8px; }
  .rec-icon { font-size: 18px; flex-shrink: 0; width: 24px; text-align: center; }
  .rec-item strong { display: block; margin-bottom: 2px; }
  .rec-item p { font-size: 12px; color: #64748b; margin: 0; }
  .rec-ok { background: #dcfce7; border: 1px solid #86efac; }
  .rec-ok .rec-icon { color: #16a34a; }
  .rec-warn { background: #fef3c7; border: 1px solid #fcd34d; }
  .rec-warn .rec-icon { color: #ca8a04; }
  .rec-critical { background: #fee2e2; border: 1px solid #fca5a5; }
  .rec-critical .rec-icon { color: #dc2626; }
  .rec-info { background: #e0f2fe; border: 1px solid #7dd3fc; }
  .rec-info .rec-icon { color: #0284c7; }

  /* Footer */
  .rpt-footer {
    margin-top: 32px; padding-top: 12px; border-top: 1px solid #e2e8f0;
    display: flex; justify-content: space-between; font-size: 10px; color: #94a3b8;
  }

  /* NOTE: No mobile-specific layout overrides — print layout is always A4/desktop
     regardless of the device generating the PDF. The @media print block above
     handles all necessary print adjustments. */`

/**
 * Additions the assessment document needs on top of the shared sheet:
 * state chips, findings, evidence and a frame for diagrams. Kept apart
 * from REPORT_CSS so the inherited stylesheet stays byte-identical to
 * the one the other reports use.
 */
export const REPORT_CSS_AUDIT = `
  .diagram { border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px;
             background: #ffffff; margin: 6px 0 14px; overflow-x: auto; }
  .diagram-note { font-size: 10.5px; color: #64748b; margin: 0 0 10px; }
  .chip { display: inline-block; padding: 2px 9px; border-radius: 999px;
          font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
          text-transform: uppercase; white-space: nowrap; }
  .chip.critical { background: #fee2e2; color: #991b1b; }
  .chip.warning { background: #fef3c7; color: #92400e; }
  .chip.observation { background: #dbeafe; color: #1e40af; }
  .chip.conformant { background: #dcfce7; color: #166534; }
  .chip.accepted { background: #e0e7ff; color: #3730a3; }
  .chip.unverified, .chip.not_applicable { background: #f1f5f9; color: #475569; }
  .finding { border: 1px solid #e2e8f0; border-left: 3px solid #cbd5e1;
             border-radius: 6px; padding: 11px 13px; margin-bottom: 9px;
             page-break-inside: avoid; break-inside: avoid; }
  .finding.critical { border-left-color: #dc2626; }
  .finding.warning { border-left-color: #ca8a04; }
  .finding.observation { border-left-color: #3b82f6; }
  .finding.conformant { border-left-color: #16a34a; }
  .finding.accepted { border-left-color: #4f46e5; }
  .finding-head { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
  .finding-head .title { font-weight: 700; font-size: 12.5px; color: #0f172a; }
  .finding-head .cid { font-size: 10px; color: #94a3b8; font-family: ui-monospace,
             SFMono-Regular, Menlo, monospace; }
  .finding p { margin: 6px 0 0; font-size: 12px; color: #334155; }
  .finding .rationale { font-size: 11px; color: #64748b; }
  .evidence { margin-top: 8px; background: #f8fafc; border: 1px solid #e2e8f0;
              border-radius: 5px; padding: 8px 10px; font-family: ui-monospace,
              SFMono-Regular, Menlo, monospace; font-size: 10px; color: #475569;
              white-space: pre-wrap; word-break: break-word; max-height: 260px;
              overflow: hidden; }
  /* The document is laid out for a page, but it is opened on phones
     too. Wide content keeps its own scroller so the page itself never
     moves sideways, and the header stacks instead of colliding. */
  @media screen and (max-width: 640px) {
    .rpt-header { flex-direction: column; align-items: flex-start; gap: 10px; }
    .rpt-header-right { text-align: left; }
    .attr-tbl { display: block; overflow-x: auto; white-space: nowrap; }
    .attr-tbl td, .attr-tbl th { white-space: normal; }
    .diagram { padding: 8px; }
    .top-bar-subtitle { display: none; }
  }
  .evidence-block { margin-top: 8px; }
  .evidence-block .attr-tbl { font-size: 10.5px; margin: 4px 0 8px; }
  .evidence-title { font-size: 11px; font-weight: 700; color: #334155;
                    margin: 8px 0 2px; }
  .evidence-list { margin: 4px 0 8px; padding-left: 18px; font-size: 10.5px;
                   color: #475569; }
  .evidence-list li { margin-bottom: 2px; word-break: break-word; }
  .evidence-excerpt-note { margin:7px 0 0 !important; padding-top:6px;
                           border-top:1px solid #e2e8f0; font-size:10px !important;
                           color:#64748b !important; }
  /* The inherited title is a block; the mark sits on its baseline. */
  .section-title { display: flex; align-items: center; }
  .sub-title { display: flex; align-items: center; font-size: 12px;
               margin: 14px 0 6px; color: #0f172a; }
  .muted { color: #64748b; }
  .sep { color: #94a3b8; padding: 0 6px; }
  .scope { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
           padding: 14px 16px; font-size: 11.5px; color: #475569; }
  .scope ul { margin: 6px 0 0; padding-left: 18px; }
  .audit-counters { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:14px 0; }
  .assessment-incomplete { font-weight:600; color:#475569; }
  .coverage-panel { border:1px solid #dbeafe; border-radius:8px; padding:14px; margin-bottom:14px; background:#f8fafc; }
  .coverage-panel h3 { font-size:13px; margin-bottom:10px; }
  .audit-meter { height:9px; background:#e2e8f0; border-radius:5px; overflow:hidden; margin:8px 0; }
  .audit-meter > span { display:block; height:100%; background:#3b82f6; }
  .coverage-labels { display:flex; justify-content:space-between; gap:15px; font-size:11px; margin-bottom:8px; }
  .capacity-item { display:grid; grid-template-columns:1fr 1fr; gap:4px 15px; margin:10px 0; font-size:11px; break-inside:avoid; }
  .capacity-item > span { text-align:right; }
  .capacity-item .audit-meter { grid-column:1 / -1; }
  .technical-ref { font-size:10px !important; }
  .technical-entry { margin-bottom:18px; }
  .technical-entry > .sub-title { break-after:avoid-page; page-break-after:avoid; }
  .audit-table-scroll { max-width:100%; min-width:0; overflow-x:auto; }
  .evidence-record { margin:8px 0 16px; }
  .evidence-record td:first-child { width:28%; color:#64748b; }
  .evidence-record td { overflow-wrap:anywhere; }
  .evidence-block .attr-tbl { table-layout:fixed; width:100%; }
  .evidence-block .attr-tbl td, .evidence-block .attr-tbl th { overflow-wrap:anywhere; word-break:normal; }
  .finding .attr-tbl { font-size:11px; }
  .finding .attr-tbl td { overflow-wrap:anywhere; }
  .finding .sub-title { break-after:avoid; }
  .health-ring .health-icon svg { margin-right:0 !important; }
  .audit-verification-ring { position:relative; width:126px; height:126px; flex:0 0 126px; color:#64748b; }
  .audit-verification-ring > svg { display:block; width:100%; height:100%; }
  .audit-verification-value { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; color:inherit; }
  .audit-verification-value strong { font-size:25px; line-height:1.3; }
  .audit-verification-value span { font-size:11px; max-width:100px; overflow-wrap:anywhere; }
  .audit-result-heading { display:flex; align-items:center; gap:8px; }
  .audit-result-heading svg { flex-shrink:0; }
  a { color:#2563eb; text-decoration:none; }
  @media print {
    .audit-table-scroll { overflow:visible; }
    .audit-verification-ring, .exec-text p.muted { color:#374151; }
    .section, .finding { break-inside:auto; page-break-inside:auto; }
    .finding-short { break-inside:avoid-page; page-break-inside:avoid; }
    .section-title, .sub-title, .finding-head { break-after:avoid-page; page-break-after:avoid; }
    .finding-head + p { break-after:avoid-page; }
    .attr-tbl { overflow:visible !important; }
    .attr-tbl thead { display:table-header-group; }
    .attr-tbl tr { break-inside:avoid-page; page-break-inside:avoid; }
    .technical-entry p, .finding p { orphans:3; widows:3; }
    .audit-counters, .coverage-panel { break-inside:avoid; }
    .diagram { break-inside: avoid; page-break-inside: avoid; }
    .chip, .finding { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .evidence { max-height: none; }
  }
`

/** Report identifiers follow the family format: prefix and a base-36 stamp. */
export function reportId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36).toUpperCase()}`
}

export function esc(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

/** Icon-only actions, as in the rest of the family: the browser's print
 *  dialog exposes "Save as PDF" as a destination, so one button covers both. */
const PRINTER_ICON = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>`
const PRINT_ICON = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>`

export interface ShellOptions {
  title: string
  subtitle: string
  /** Right-hand header rows, rendered in order. */
  meta: Array<[string, string]>
  reportId: string
  logoUrl: string
  topBarSubtitle?: string
  footerLeft: string
  footerRight: string
  lang: string
  body: string
  /** Extra stylesheet appended after the shared one. */
  extraCss?: string
}

export function renderReport(o: ShellOptions): string {
  const metaRows = o.meta
    .filter(([, v]) => v)
    .map(([k, v]) => `<div>${esc(k)}: ${esc(v)}</div>`).join("\n")

  return `<!doctype html>
<html lang="${esc(o.lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(o.title)}${o.topBarSubtitle ? ` - ${esc(o.topBarSubtitle)}` : ""}</title>
<style>${REPORT_CSS}${o.extraCss || ""}</style>
</head>
<body>
<script>
function pmxPrint(){ try { window.print(); } catch(e) {} }
</script>

<div class="top-bar no-print">
  <div class="top-bar-left">
    <strong class="top-bar-title">${esc(o.title)}</strong>
    <span class="top-bar-subtitle">${esc(o.topBarSubtitle || "")}</span>
  </div>
  <div class="btn-group">
    <button onclick="pmxPrint()" title="Print" aria-label="Print">${PRINTER_ICON}</button>
    <button onclick="pmxPrint()" title="Save as PDF" aria-label="Save as PDF">${PRINT_ICON}</button>
  </div>
</div>

<div class="rpt-header">
  <div class="rpt-header-left">
    <img src="${esc(o.logoUrl)}" alt="ProxMenux" onerror="this.style.display='none'">
    <div>
      <h1>${esc(o.title)}</h1>
      <p>${esc(o.subtitle)}</p>
    </div>
  </div>
  <div class="rpt-header-right">
    ${metaRows}
    <div class="rid">ID: ${esc(o.reportId)}</div>
  </div>
</div>

${o.body}

<div class="rpt-footer">
  <span>${esc(o.footerLeft)}</span>
  <span>${esc(o.footerRight)}</span>
</div>
</body>
</html>`
}

/**
 * Section marks.
 *
 * A document of twelve sections is navigated by flicking through it, and
 * a shape is found faster than a word is read. Drawn in the title's own
 * grey at a single stroke weight so they mark the section without
 * competing with the states, which are the only colour that carries
 * meaning here.
 */
const ICON_PATHS: Record<string, string> = {
  summary: '<path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="m9 14 2 2 4-4"/>',
  node: '<rect x="2" y="4" width="20" height="7" rx="2"/><rect x="2" y="13" width="20" height="7" rx="2"/><path d="M6 8h.01M6 17h.01"/>',
  cluster: '<circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="19" r="2.5"/><circle cx="19" cy="19" r="2.5"/><path d="M12 7.5v4M12 11.5H6.5a1.5 1.5 0 0 0-1.5 1.5v3.5M12 11.5h5.5a1.5 1.5 0 0 1 1.5 1.5v3.5"/>',
  architecture: '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 2v3M14 2v3M10 19v3M14 19v3M2 10h3M2 14h3M19 10h3M19 14h3"/>',
  disks: '<rect x="2" y="4" width="20" height="7" rx="2"/><rect x="2" y="13" width="20" height="7" rx="2"/><path d="M17 7.5h.01M17 16.5h.01"/>',
  network: '<rect x="9" y="2" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="16" y="16" width="6" height="6" rx="1"/><path d="M12 8v4M5 16v-2h14v2"/>',
  storage: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  guests: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  passthrough: '<path d="M9 2v6M15 2v6"/><path d="M6 8h12v3a6 6 0 0 1-6 6 6 6 0 0 1-6-6V8Z"/><path d="M12 17v5"/>',
  software: '<path d="m12 2 8 4.5v9L12 20l-8-4.5v-9L12 2Z"/><path d="M12 20v-9M4 6.5l8 4.5 8-4.5"/>',
  findings: '<path d="m3 6 2 2 3-3M3 13l2 2 3-3M3 20l2 2 3-3"/><path d="M12 7h9M12 14h9M12 21h9"/>',
  scope: '<circle cx="12" cy="12" r="9.5"/><path d="M12 16v-5M12 8h.01"/>',
  memory: '<rect x="3" y="7" width="18" height="10" rx="1.5"/><path d="M7 17v3M12 17v3M17 17v3M6 11h2M11 11h2M16 11h2"/>',
  controller: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/>',
  adapter: '<rect x="2" y="8" width="20" height="8" rx="2"/><path d="M6 12h.01M10 12h.01M14 12h.01"/><path d="M18 8V5M18 19v-3"/>',
  bridge: '<path d="M2 17V9a10 10 0 0 1 20 0v8"/><path d="M2 13h20M7 13v4M12 13v4M17 13v4"/>',
  observation: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
  latency: '<path d="M3 18h4l3-11 4 16 3-9h4"/>',
}

/** An inline mark, sized to sit on the line of the text it precedes. */
export function icon(name: keyof typeof ICON_PATHS | string, size = 16,
                     color = "#64748b"): string {
  const path = ICON_PATHS[name]
  if (!path) return ""
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none"
    stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true" focusable="false"
    style="flex:none;vertical-align:-2px;margin-right:8px">${path}</svg>`
}

export function section(index: number, title: string, body: string,
                        mark?: string): string {
  return `<div class="section">
  <div class="section-title">${mark ? icon(mark) : ""}${index}. ${esc(title)}</div>
  ${body}
</div>`
}

/** A heading inside a section, carrying its own mark. */
export function heading(title: string, mark?: string, note?: string): string {
  return `<h3 class="sub-title">${mark ? icon(mark, 14) : ""}${esc(title)}${
    note ? `<span class="muted" style="font-weight:400"> — ${esc(note)}</span>` : ""}</h3>`
}

export function card(label: string, value: string, opts: { center?: boolean; color?: string } = {}): string {
  const cls = opts.center ? "card card-c" : "card"
  const style = opts.color ? ` style="color:${opts.color}"` : ""
  return `<div class="${cls}">
    <div class="card-label">${esc(label)}</div>
    <div class="card-value"${style}>${value}</div>
  </div>`
}

export function grid(columns: 2 | 3 | 4, cards: string[]): string {
  return `<div class="grid-${columns}">${cards.join("")}</div>`
}

/** Callout in the family's four tones: ok, warn, critical, info. */
export function callout(tone: "ok" | "warn" | "critical" | "info",
                        title: string, body: string): string {
  const icon = { ok: "&#10003;", warn: "&#9888;", critical: "&#10007;", info: "&#9432;" }[tone]
  return `<div class="rec-item rec-${tone}">
    <div class="rec-icon">${icon}</div>
    <div><strong>${esc(title)}</strong><p>${body}</p></div>
  </div>`
}

export function table(headers: string[], rows: string[][]): string {
  // No headers means the first column labels the second: a record read
  // down rather than across.
  const head = headers.length
    ? `<thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>`
    : ""
  return `<table class="attr-tbl">${head}
  <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody>
</table>`
}

/**
 * Opens the report window on the click itself, before any data is
 * fetched, so the popup blocker sees the user gesture. The spinner is
 * what the reader looks at while the document is composed.
 */
export function openReportWindow(loadingText: string): Window | null {
  const w = window.open("about:blank", "_blank")
  if (w) {
    w.document.write(`<html><body style="background:#0f172a;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0"><div style="text-align:center"><div style="border:3px solid transparent;border-top-color:#06b6d4;border-radius:50%;width:40px;height:40px;animation:spin 1s linear infinite;margin:0 auto"></div><p style="margin-top:16px">${esc(loadingText)}</p><style>@keyframes spin{to{transform:rotate(360deg)}}</style></div></body></html>`)
  }
  return w
}

/**
 * Hands the composed document to the window that was opened on the click.
 *
 * The window is *navigated* to the document rather than written into.
 * Writing into an about:blank window leaves it, as far as the browser is
 * concerned, still on about:blank — no navigation happened — and an
 * installed web app then shows none of its own chrome, so on a phone the
 * report opens with no way back to the page that launched it. Navigating
 * to a blob URL is a real navigation, and the app supplies its close and
 * back controls exactly as it does for the other reports.
 */
export function writeReport(target: Window | null, html: string): void {
  const url = URL.createObjectURL(new Blob([html], { type: "text/html" }))
  if (target && !target.closed) {
    target.location.href = url
    return
  }
  // The window was blocked or the reader closed it while the document
  // was being composed.
  window.open(url, "_blank")
}
