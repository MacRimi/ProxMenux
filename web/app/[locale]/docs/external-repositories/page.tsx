import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.externalRepositories.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/external-repositories",
    },
  }
}

type RepoItem = { name: string; url: string; description: string; usedIn: string }

export default async function ExternalRepositoriesPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.externalRepositories" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: {
      externalRepositories: {
        integrated: { items: RepoItem[] }
        attribution: { items: string[] }
        candidate: { items: string[] }
      }
    }
  }
  const block = messages.docs.externalRepositories
  const repos = block.integrated.items
  const attributionItems = block.attribution.items
  const candidateItems = block.candidate.items

  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={3}
      />

      <Callout variant="info" title={t("practice.title")}>
        {t("practice.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("integrated.heading")}</h2>
      <div className="space-y-4 mb-8">
        {repos.map((r) => (
          <a
            key={r.url}
            href={r.url}
            target="_blank"
            rel="noopener noreferrer"
            className="block rounded-md border border-gray-200 bg-white p-4 transition-colors hover:border-blue-400 hover:bg-blue-50"
          >
            <div className="font-semibold text-gray-900 mb-1">{r.name}</div>
            <div className="text-sm text-gray-700 leading-snug mb-2">{r.description}</div>
            <div className="text-xs text-gray-500">
              <strong>{t("integrated.usedInLabel")}</strong> {r.usedIn}
            </div>
          </a>
        ))}
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("attribution.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {attributionItems.map((_, idx) => (
          <li key={idx}>{t(`attribution.items.${idx}`)}</li>
        ))}
      </ul>

      <Callout variant="warning" title={t("report.title")}>
        {t.rich("report.body", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("suggest.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("suggest.intro")}</p>
      <div className="grid gap-3 md:grid-cols-2 mb-6 not-prose">
        <a
          href="https://github.com/MacRimi/ProxMenux/discussions"
          target="_blank"
          rel="noopener noreferrer"
          className="block rounded-md border border-gray-200 bg-white p-4 transition-colors hover:border-blue-400 hover:bg-blue-50"
        >
          <div className="font-semibold text-gray-900 mb-1">{t("suggest.discussionTitle")}</div>
          <div className="text-xs text-gray-600">{t("suggest.discussionBody")}</div>
        </a>
        <a
          href="https://github.com/MacRimi/ProxMenux/issues"
          target="_blank"
          rel="noopener noreferrer"
          className="block rounded-md border border-gray-200 bg-white p-4 transition-colors hover:border-blue-400 hover:bg-blue-50"
        >
          <div className="font-semibold text-gray-900 mb-1">{t("suggest.issueTitle")}</div>
          <div className="text-xs text-gray-600">{t("suggest.issueBody")}</div>
        </a>
      </div>

      <Callout variant="tip" title={t("candidate.title")}>
        <ul className="list-disc pl-6 mb-0 space-y-1">
          {candidateItems.map((_, idx) => (
            <li key={idx}>{t(`candidate.items.${idx}`)}</li>
          ))}
        </ul>
      </Callout>
    </div>
  )
}
