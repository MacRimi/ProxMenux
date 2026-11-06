import enMessages from "../messages/en/common.json"

type Translate = (key: string, params?: Record<string, string | number>) => string

// Descriptions are live server metadata. Translate only exact known wording;
// a newer script description must remain visible rather than become stale text.
export function optimizationDescription(description: string, t: Translate): string {
  const entries = Object.entries(enMessages.settings.optimizations.toolDescriptions)
  const match = entries.find(([, english]) => english === description)
  return match ? t(`settings.optimizations.toolDescriptions.${match[0]}`) : description
}

// Unknown tools retain the server's name until their key is translated.
export function optimizationToolName(tool: string, fallback: string, t: Translate): string {
  return Object.prototype.hasOwnProperty.call(enMessages.settings.optimizations.toolNames, tool)
    ? t(`settings.optimizations.toolNames.${tool}`)
    : fallback
}
