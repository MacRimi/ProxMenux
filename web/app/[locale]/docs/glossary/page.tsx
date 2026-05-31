import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.glossary.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/glossary",
    },
  }
}

type Category = "Proxmox" | "Virtualization" | "Storage" | "Network" | "Linux" | "ProxMenux"

type SeeAlso = { label: string; href: string }

type GlossaryEntry = {
  term: string
  aliases?: string[]
  category: Category
  definitionRich: string
  seeAlso?: SeeAlso[]
}

const categoryColor: Record<Category, string> = {
  Proxmox: "bg-red-50 text-red-700 border-red-200",
  Virtualization: "bg-blue-50 text-blue-700 border-blue-200",
  Storage: "bg-amber-50 text-amber-700 border-amber-200",
  Network: "bg-emerald-50 text-emerald-700 border-emerald-200",
  Linux: "bg-purple-50 text-purple-700 border-purple-200",
  ProxMenux: "bg-gray-100 text-gray-700 border-gray-300",
}

function CategoryBadge({ category }: { category: Category }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${categoryColor[category]}`}
    >
      {category}
    </span>
  )
}

export default async function GlossaryPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.glossary" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { glossary: { entries: GlossaryEntry[] } }
  }
  const entries = messages.docs.glossary.entries

  const sortedEntries = [...entries].sort((a, b) =>
    a.term.localeCompare(b.term, "en", { sensitivity: "base" })
  )

  const lettersInUse = Array.from(
    new Set(sortedEntries.map((e) => e.term[0].toUpperCase()))
  ).sort()

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const ext = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/MacRimi/ProxMenux/issues"
      target="_blank"
      rel="noopener noreferrer"
      className="text-emerald-700 hover:underline inline-flex items-center gap-1"
    >
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
        estimatedMinutes={5}
      />

      <Callout variant="info" title={t("callout.title")}>
        {t.rich("callout.bodyRich", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("jumpHeading")}</h2>
      <div className="flex flex-wrap gap-1.5 mb-8 not-prose">
        {lettersInUse.map((letter) => (
          <a
            key={letter}
            href={`#letter-${letter}`}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-gray-200 bg-white text-sm font-medium text-gray-700 hover:border-blue-400 hover:bg-blue-50 hover:text-blue-700 transition-colors"
          >
            {letter}
          </a>
        ))}
      </div>

      <div className="space-y-6">
        {sortedEntries.map((entry, i) => {
          const letter = entry.term[0].toUpperCase()
          const prevLetter = i > 0 ? sortedEntries[i - 1].term[0].toUpperCase() : null
          const isFirstOfLetter = letter !== prevLetter
          const entryIdx = entries.findIndex((e) => e.term === entry.term)

          return (
            <div key={entry.term}>
              {isFirstOfLetter && (
                <h2
                  id={`letter-${letter}`}
                  className="text-3xl font-bold text-gray-900 mt-12 mb-4 scroll-mt-24 border-b border-gray-200 pb-2"
                >
                  {letter}
                </h2>
              )}
              <article id={`term-${entry.term.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`} className="scroll-mt-24">
                <div className="flex flex-wrap items-baseline gap-2 mb-2">
                  <h3 className="text-lg font-semibold text-gray-900 m-0">{entry.term}</h3>
                  <CategoryBadge category={entry.category} />
                  {entry.aliases && entry.aliases.length > 0 && (
                    <span className="text-xs text-gray-500 italic">
                      {t("aliasesLabel")} {entry.aliases.join(" · ")}
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-800 leading-relaxed mb-2">
                  {t.rich(`entries.${entryIdx}.definitionRich`, { code, strong, em })}
                </p>
                {entry.seeAlso && entry.seeAlso.length > 0 && (
                  <p className="text-xs text-gray-600 m-0">
                    <span className="font-medium text-gray-700">{t("seeAlsoLabel")}</span>{" "}
                    {entry.seeAlso.map((s, idx) => (
                      <span key={s.href}>
                        <Link href={s.href} className="text-blue-600 hover:underline">
                          {s.label}
                        </Link>
                        {idx < entry.seeAlso!.length - 1 && " · "}
                      </span>
                    ))}
                  </p>
                )}
              </article>
            </div>
          )
        })}
      </div>

      <Callout variant="tip" title={t("missingCallout.title")} className="mt-12">
        {t.rich("missingCallout.leadRich", { ext, code })}
      </Callout>
    </div>
  )
}
