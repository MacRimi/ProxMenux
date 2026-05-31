import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.aiAssistant.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox ai",
      "proxmox openai integration",
      "proxmox claude",
      "proxmox gemini",
      "proxmox ollama",
      "proxmox local ai",
      "proxmox groq",
      "proxmox openrouter",
      "proxmox notification rewrite",
      "proxmox llm",
      "proxmenux ai assistant",
      "proxmox ai prompt",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/monitor/ai-assistant" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/monitor/ai-assistant",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

const DEFAULT_SYSTEM_PROMPT = `You are a notification FORMATTER for ProxMenux Monitor (Proxmox VE).
Your job: translate alerts into {language} and enrich them with context when provided.

═══ ABSOLUTE CONSTRAINTS (NO EXCEPTIONS) ═══
- NO HALLUCINATIONS: Do not invent causes, solutions, or facts not present in the provided data
- NO SPECULATION: If something is unclear, state what IS known, not what MIGHT be
- NO CONVERSATIONAL TEXT: Never write "Here is...", "I've translated...", "Let me explain..."
- ONLY use information from: the message, journal context, and known error database (if provided)

═══ WHAT TO TRANSLATE ═══
Translate: labels, descriptions, status words, units (GB→Go in French, etc.)
DO NOT translate: hostnames, IPs, paths, VM/CT IDs, device names (/dev/sdX), technical identifiers

═══ CORE RULES ═══
1. Plain text only — NO markdown, no **bold**, no \`code\`, no bullet lists (use "• " for packages only)
2. Preserve severity: "failed" stays "failed", "warning" stays "warning" — never soften errors
3. Preserve structure: keep same fields and line order, only translate content
4. Detail level "{detail_level}" - controls AMOUNT OF EVENT INFO (not tips/suggestions):
   - brief: 1-2 lines max. Only: what happened + where
   - standard: 3-6 lines. Include: what, where, cause, affected devices
   - detailed: Full report with ALL info: what, where, cause, affected, logs, SMART data, history
5. DEDUPLICATION: merge duplicate facts from multiple sources into one clear statement
6. EMPTY LISTS: write translated "none" after label, never leave blank
7. Keep "hostname:" prefix in title — translate only the descriptive part
8. DO NOT add recommendations or suggestions UNLESS AI Suggestions mode is enabled below
9. ENRICHED CONTEXT: You may receive additional context data including:
   - "System uptime: X days (stable system)" → helps distinguish startup issues from runtime failures
   - "Event frequency: N occurrences, first seen X ago" → indicates recurring vs one-time issues
   - "SMART Health: PASSED/FAILED" with disk attributes → critical for disk errors
   - "KNOWN PROXMOX ERROR DETECTED" with cause/solution → YOU MUST USE this exact information

   How to use enriched context:
   - If uptime is <10min and error is service-related → mention "occurred shortly after boot"
   - If frequency shows recurring pattern → mention "recurring issue (N times in X hours)"
   - If SMART shows FAILED → treat as CRITICAL: "Disk failing - immediate attention required"
   - If KNOWN ERROR is provided → YOU MUST incorporate its Cause and Solution (translate, don't copy verbatim)

10. JOURNAL CONTEXT EXTRACTION: When journal logs are provided:
   - Extract specific IDs (VM/CT numbers, disk devices, service names)
   - Include relevant timestamps if they help explain the timeline
   - Identify root cause when logs clearly show it (e.g., "exit-code 255" -> "process crashed")
   - Translate technical terms: "Emask 0x10" -> "ATA bus error", "DRDY ERR" -> "drive not ready"
   - If logs show the same error repeating, state frequency: "occurred 15 times in 10 minutes"
   - IGNORE journal entries unrelated to the main event
11. OUTPUT ONLY the final result — no "Original:", no before/after comparisons
12. Unknown input: preserve as closely as possible, translate what you can
13. REDUNDANCY: Never repeat the same information twice. If title says "CT 103 failed", body should not start with "Container 103 failed"
{suggestions_addon}
═══ PROXMOX MAPPINGS (use directly, never explain) ═══
pve-container@XXXX → "CT XXXX" | qemu-server@XXXX → "VM XXXX" | vzdump → "backup"
pveproxy/pvedaemon/pvestatd → "Proxmox service" | corosync → "cluster service"
"ata8.00: exception Emask..." → "ATA error on port 8"
"blk_update_request: I/O error, dev sdX" → "I/O error on /dev/sdX"
{emoji_instructions}
═══ MESSAGE FORMATS ═══

BACKUP: List each VM/CT with status/size/duration/storage. End with summary.
  - Partial failure (some OK, some failed) = "Backup partially failed", not "failed"
  - NEVER collapse multi-VM backup into one line — show each VM separately
  - ALWAYS include storage path and summary line

UPDATES: Counts on own lines. Packages use "• " under header. No redundant summary.

DISK/SMART: Device + specific error. Deduplicate repeated info.

HEALTH: Category + severity + what changed. Duration if resolved.

VM/CT LIFECYCLE: Confirm event with key facts (1-2 lines).

═══ OUTPUT FORMAT (CRITICAL - MUST FOLLOW EXACTLY) ═══

Your response MUST have EXACTLY this structure:
[TITLE]
your translated title text
[BODY]
your translated body text

ABSOLUTE RULES (violations break the parser):
1. [TITLE] and [BODY] are INVISIBLE PARSING MARKERS — they separate title from body
2. Your actual title/body content must NEVER contain the words "[TITLE]" or "[BODY]"
3. Your actual title/body content must NEVER contain "Title:" or "Body:" prefixes
4. Line 1: write exactly [TITLE]
5. Line 2: write your title text (emoji + hostname: description)
6. Line 3: write exactly [BODY]
7. Line 4+: write your body text

- Output ONLY the formatted result — no explanations, no "Original:", no commentary`

const SUGGESTIONS_ADDON = `═══ AI SUGGESTIONS MODE (ENABLED) ═══
You MAY add ONE brief, actionable tip at the END of the body using this exact format:

💡 Tip: [your concise suggestion here]

Rules for the tip:
- ONLY include if the log context or Known Error database clearly points to a specific fix
- Keep under 100 characters
- Be specific: "Run 'pvecm status' to check quorum" NOT "Check cluster status"
- If Known Error provides a solution, YOU MUST USE IT (don't invent your own)
- Never guess — skip the tip if the cause/solution is unclear`

const EXAMPLE_CUSTOM_PROMPT = `You are a notification formatter for ProxMenux Monitor.

Your task is to translate and format server notifications.

RULES:
1. Translate to the user's preferred language
2. Use plain text only (no markdown, no bold, no italic)
3. Be concise and factual
4. Do not add recommendations or suggestions
5. Present only the facts from the input
6. Keep hostname prefix in titles (e.g., "pve01: ")

OUTPUT FORMAT:
[TITLE]
your translated title here
[BODY]
your translated message here

Detail levels:
- brief: 2-3 lines, essential only
- standard: short paragraph with key details
- detailed: full technical breakdown`

type ContextRow = { block: string; when: string; what: string }
type CapRow = { level: string; cap: string; consumption: string }
type DetailRow = { level: string; label: string; cap: string; produce: string }
type PrivacyRow = { provider: string; destination: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function AIAssistantPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.aiAssistant" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { aiAssistant: {
      howItWorks: { steps: string[]; notes: string[] }
      context: { rows: ContextRow[] }
      tokens: { items: string[]; capRows: CapRow[] }
      providers: {
        groq: { items: string[] }
        openai: { items: string[] }
        anthropic: { items: string[] }
        gemini: { items: string[] }
        openrouter: { items: string[] }
        ollama: { items: string[] }
      }
      models: { consequences: string[] }
      defaultPrompt: { passages: string[] }
      customPrompt: { changes: string[] }
      suggestions: { rules: string[] }
      detailLevel: { rows: DetailRow[]; defaults: string[] }
      language: { rules: string[] }
      privacy: { rows: PrivacyRow[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const ai = messages.docs.monitor.aiAssistant
  const howSteps = ai.howItWorks.steps
  const howNotes = ai.howItWorks.notes
  const contextRows = ai.context.rows
  const tokensItems = ai.tokens.items
  const tokensCapRows = ai.tokens.capRows
  const groqItems = ai.providers.groq.items
  const openaiItems = ai.providers.openai.items
  const anthropicItems = ai.providers.anthropic.items
  const geminiItems = ai.providers.gemini.items
  const openrouterItems = ai.providers.openrouter.items
  const ollamaItems = ai.providers.ollama.items
  const modelsConsequences = ai.models.consequences
  const defaultPassages = ai.defaultPrompt.passages
  const customChanges = ai.customPrompt.changes
  const suggestionsRules = ai.suggestions.rules
  const detailLevelRows = ai.detailLevel.rows
  const detailLevelDefaults = ai.detailLevel.defaults
  const languageRules = ai.language.rules
  const privacyRows = ai.privacy.rows
  const whereNextItems = ai.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const detailLink = (chunks: React.ReactNode) => (
    <Link href="#detail-level-per-channel" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const notifLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/notifications" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  const providerLink = (href: string) => (chunks: React.ReactNode) =>
    (
      <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
        {chunks}
        <ExternalLink className="w-3 h-3" />
      </a>
    )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={25}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howItWorks.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("howItWorks.intro")}</p>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        {howSteps.map((_, idx) => (
          <li key={idx}>{t.rich(`howItWorks.steps.${idx}`, { strong, code, em })}</li>
        ))}
      </ol>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("howItWorks.notesIntro")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {howNotes.map((_, idx) => (
          <li key={idx}>{t.rich(`howItWorks.notes.${idx}`, { strong })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("enabling.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("enabling.intro", { em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/settings/ai-enhancement-collapsed.png" alt={t("enabling.collapsedAlt")} width={2000} height={244} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("enabling.collapsedCaption")}</figcaption>
      </figure>

      <figure className="my-4">
        <Image src="/monitor/settings/ai-enhancement-panel.png" alt={t("enabling.panelAlt")} width={2000} height={1854} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("enabling.panelCaption")}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("enabling.outro", { em })}
      </p>

      <h2 id="what-context-the-ai-receives" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("context.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("context.intro")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("context.headerBlock")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("context.headerWhen")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("context.headerWhat")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {contextRows.map((row, idx) => (
              <tr key={row.block} className={idx < contextRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.block}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`context.rows.${idx}.when`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`context.rows.${idx}.what`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("context.afterBlocks")}</p>

      <CopyableCode
        code={`Severity: WARNING
Title: pve01: Disk I/O error
Message:
I/O error on /dev/sda — 1 sector pending reallocation.

Journal log context:
Event frequency: 5 occurrences, first seen 2h ago, recurring

SMART Health: PASSED
SMART attribute Reallocated_Sector_Ct: 1 (raw 1)
SMART attribute Current_Pending_Sector: 1 (raw 1)

Journal logs:
ata8.00: exception Emask 0x10 SAct 0x0 SErr 0x400000 action 0x6
blk_update_request: I/O error, dev sda, sector 4205312
ata8.00: error: { ICRC ABRT }`}
        className="my-4"
      />

      <Callout variant="info" title={t("context.calloutTitle")}>
        {t("context.calloutBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("tokens.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("tokens.intro1", { em })}</p>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("tokens.intro2")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {tokensItems.map((_, idx) => (
          <li key={idx}>{t.rich(`tokens.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("tokens.capsIntro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("tokens.headerLevel")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("tokens.headerCap")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("tokens.headerConsumption")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {tokensCapRows.map((row, idx) => (
              <tr key={row.level} className={idx < tokensCapRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><code>{row.level}</code></td>
                <td className="px-3 py-2 align-top">{row.cap}</td>
                <td className="px-3 py-2 align-top">{row.consumption}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("tokens.customNote")}</p>

      <Callout variant="tip" title={t("tokens.sizingTitle")}>
        {t.rich("tokens.sizingBody", { code, link: detailLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("providers.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("providers.intro")}</p>

      <figure className="my-4">
        <Image src="/monitor/settings/ai-providers-information.png" alt={t("providers.imageAlt")} width={1602} height={2138} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto mx-auto max-w-2xl" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("providers.imageCaption")}</figcaption>
      </figure>

      <h3 id="provider-groq" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("providers.groq.heading")}</h3>
      <p className="mb-2 text-gray-800 leading-relaxed"><em>{t("providers.groq.tagline")}</em></p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {groqItems.map((_, idx) => (
          <li key={idx}>{t.rich(`providers.groq.items.${idx}`, { code, strong, a: providerLink("https://console.groq.com/keys") })}</li>
        ))}
      </ul>

      <h3 id="provider-openai" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("providers.openai.heading")}</h3>
      <p className="mb-2 text-gray-800 leading-relaxed"><em>{t("providers.openai.tagline")}</em></p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {openaiItems.map((_, idx) => (
          <li key={idx}>{t.rich(`providers.openai.items.${idx}`, { code, strong, a: providerLink("https://platform.openai.com/api-keys") })}</li>
        ))}
      </ul>

      <Callout variant="tip" title={t("providers.openai.baseUrlTitle")}>
        {t.rich("providers.openai.baseUrlBody", { em, strong, code })}
      </Callout>

      <h3 id="provider-anthropic" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("providers.anthropic.heading")}</h3>
      <p className="mb-2 text-gray-800 leading-relaxed"><em>{t("providers.anthropic.tagline")}</em></p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {anthropicItems.map((_, idx) => (
          <li key={idx}>{t.rich(`providers.anthropic.items.${idx}`, { code, strong, a: providerLink("https://console.anthropic.com/settings/keys") })}</li>
        ))}
      </ul>

      <h3 id="provider-gemini" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("providers.gemini.heading")}</h3>
      <p className="mb-2 text-gray-800 leading-relaxed"><em>{t("providers.gemini.tagline")}</em></p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {geminiItems.map((_, idx) => (
          <li key={idx}>{t.rich(`providers.gemini.items.${idx}`, { code, strong, a: providerLink("https://aistudio.google.com/app/apikey") })}</li>
        ))}
      </ul>

      <h3 id="provider-openrouter" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("providers.openrouter.heading")}</h3>
      <p className="mb-2 text-gray-800 leading-relaxed"><em>{t("providers.openrouter.tagline")}</em></p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {openrouterItems.map((_, idx) => (
          <li key={idx}>{t.rich(`providers.openrouter.items.${idx}`, { code, strong, a: providerLink("https://openrouter.ai/keys") })}</li>
        ))}
      </ul>

      <h3 id="provider-ollama" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("providers.ollama.heading")}</h3>
      <p className="mb-2 text-gray-800 leading-relaxed"><em>{t("providers.ollama.tagline")}</em></p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {ollamaItems.map((_, idx) => (
          <li key={idx}>{t.rich(`providers.ollama.items.${idx}`, { code, strong, em, a: providerLink("https://ollama.com/download") })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("models.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("models.intro", { code })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("models.consequencesIntro")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {modelsConsequences.map((_, idx) => (
          <li key={idx}>{t.rich(`models.consequences.${idx}`, { strong })}</li>
        ))}
      </ul>

      <Callout variant="info" title={t("models.ollamaTitle")}>
        {t("models.ollamaBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("defaultPrompt.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("defaultPrompt.intro", { em, code })}
      </p>

      <details className="mb-4 rounded-md border border-gray-200 bg-gray-50">
        <summary className="cursor-pointer px-4 py-3 font-medium text-gray-900 hover:bg-gray-100 rounded-md">
          {t("defaultPrompt.showFullSummary")}
        </summary>
        <div className="px-4 pb-4">
          <pre className="text-xs font-mono text-gray-800 whitespace-pre-wrap leading-relaxed bg-white border border-gray-200 rounded p-3 overflow-x-auto">
{DEFAULT_SYSTEM_PROMPT}
          </pre>
        </div>
      </details>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("defaultPrompt.passagesIntro", { em })}
      </p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {defaultPassages.map((_, idx) => (
          <li key={idx}>{t.rich(`defaultPrompt.passages.${idx}`, { strong })}</li>
        ))}
      </ul>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("defaultPrompt.suggestionsPlaceholder", { code })}
      </p>

      <details className="mb-4 rounded-md border border-gray-200 bg-gray-50">
        <summary className="cursor-pointer px-4 py-3 font-medium text-gray-900 hover:bg-gray-100 rounded-md">
          {t("defaultPrompt.showAddonSummary")}
        </summary>
        <div className="px-4 pb-4">
          <pre className="text-xs font-mono text-gray-800 whitespace-pre-wrap leading-relaxed bg-white border border-gray-200 rounded p-3 overflow-x-auto">
{SUGGESTIONS_ADDON}
          </pre>
        </div>
      </details>

      <h2 id="custom-prompt-mode" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("customPrompt.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("customPrompt.intro", { em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/settings/ai-custom-prompt.png" alt={t("customPrompt.imageAlt")} width={2000} height={987} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("customPrompt.imageCaption", { em })}</figcaption>
      </figure>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("customPrompt.changesTitle")}</h3>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        {customChanges.map((_, idx) => (
          <li key={idx}>{t.rich(`customPrompt.changes.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("customPrompt.starterTitle")}</h3>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("customPrompt.starterIntro", { em })}
      </p>

      <details className="mb-4 rounded-md border border-gray-200 bg-gray-50">
        <summary className="cursor-pointer px-4 py-3 font-medium text-gray-900 hover:bg-gray-100 rounded-md">
          {t("customPrompt.showStarterSummary")}
        </summary>
        <div className="px-4 pb-4">
          <pre className="text-xs font-mono text-gray-800 whitespace-pre-wrap leading-relaxed bg-white border border-gray-200 rounded p-3 overflow-x-auto">
{EXAMPLE_CUSTOM_PROMPT}
          </pre>
        </div>
      </details>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("customPrompt.shareTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("customPrompt.shareIntro", { em, code })}
      </p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        <li>
          <a
            href="https://github.com/MacRimi/ProxMenux/discussions/categories/share-custom-prompts-for-ai-notifications"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline inline-flex items-center gap-1"
          >
            {t("customPrompt.shareLinkLabel")}
            <ExternalLink className="w-3 h-3" />
          </a>
        </li>
      </ul>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("customPrompt.shareOutro")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("suggestions.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("suggestions.intro", { strong, em })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("suggestions.formatIntro")}</p>

      <CopyableCode
        code={`💡 Tip: Run 'pvecm status' to check quorum`}
        className="my-4"
      />

      <p className="mb-4 text-gray-800 leading-relaxed">{t("suggestions.rulesIntro")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {suggestionsRules.map((_, idx) => (
          <li key={idx}>{t.rich(`suggestions.rules.${idx}`, { em })}</li>
        ))}
      </ul>

      <Callout variant="warning" title={t("suggestions.betaTitle")}>
        {t("suggestions.betaBody")}
      </Callout>

      <h2 id="detail-level-per-channel" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("detailLevel.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("detailLevel.intro")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("detailLevel.headerLevel")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("detailLevel.headerLabel")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("detailLevel.headerCap")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("detailLevel.headerProduce")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {detailLevelRows.map((row, idx) => (
              <tr key={row.level} className={idx < detailLevelRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><code>{row.level}</code></td>
                <td className="px-3 py-2 align-top">{row.label}</td>
                <td className="px-3 py-2 align-top">{row.cap}</td>
                <td className="px-3 py-2 align-top">{row.produce}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("detailLevel.defaultsIntro")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {detailLevelDefaults.map((_, idx) => (
          <li key={idx}>{t.rich(`detailLevel.defaults.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <Callout variant="info" title={t("detailLevel.emailTitle")}>
        {t.rich("detailLevel.emailBody", { code })}
      </Callout>

      <h2 id="language" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("language.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("language.intro", { code, em })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("language.list", { code })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("language.rulesIntro")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {languageRules.map((_, idx) => (
          <li key={idx}>{t.rich(`language.rules.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("language.customNote", { strong })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("templates.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("templates.body1", { code })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("templates.body2", { link: notifLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("privacy.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("privacy.intro")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("privacy.headerProvider")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("privacy.headerDestination")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {privacyRows.map((row, idx) => (
              <tr key={row.provider} className={idx < privacyRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.provider}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`privacy.rows.${idx}.destination`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="warning" title={t("privacy.calloutTitle")}>
        {t("privacy.calloutBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {whereNextItems.map((item) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tail}
          </li>
        ))}
        <li>
          <a
            href="https://github.com/MacRimi/ProxMenux/discussions/categories/share-custom-prompts-for-ai-notifications"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline inline-flex items-center gap-1"
          >
            {t("whereNext.communityLabel")}
            <ExternalLink className="w-3 h-3" />
          </a>
          {t("whereNext.communityTail")}
        </li>
      </ul>
    </div>
  )
}
