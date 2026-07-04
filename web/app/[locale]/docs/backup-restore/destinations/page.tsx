import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.destinations.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox backup destinations",
      "proxmox local backup",
      "proxmox backup server",
      "borg backup proxmox",
      "tar zst backup",
      "pbs snapshot",
      "borg repository",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/backup-restore/destinations" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/backup-restore/destinations",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type ComparisonRow = {
  feature: string
  local: string
  pbs: string
  borg: string
}
type WhereNextItem = { label: string; href: string; tail: string }

export default async function DestinationsIndexPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.destinations" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { backupRestore: { destinations: {
      comparison: { rows: ComparisonRow[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const dest = messages.docs.backupRestore.destinations
  const rows = dest.comparison.rows
  const whereNextItems = dest.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={9}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("comparison.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("comparison.intro", { strong })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">
                {t("comparison.captionCode")}
              </th>
              <th className="text-left px-3 py-2 border-b border-gray-200">
                {t("comparison.captionLocal")}
              </th>
              <th className="text-left px-3 py-2 border-b border-gray-200">
                {t("comparison.captionPbs")}
              </th>
              <th className="text-left px-3 py-2 border-b border-gray-200">
                {t("comparison.captionBorg")}
              </th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {rows.map((row, idx) => (
              <tr key={row.feature} className={idx < rows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.feature}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`comparison.rows.${idx}.local`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`comparison.rows.${idx}.pbs`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`comparison.rows.${idx}.borg`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("sameArchive.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sameArchive.body", { code, em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("extractStandalone.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("extractStandalone.intro", { code, strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("comparison.captionLocal")}
      </h3>
      <CopyableCode code={t("extractStandalone.localCmd")} language="bash" />

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("comparison.captionPbs")}
      </h3>
      <CopyableCode code={t("extractStandalone.pbsCmd")} language="bash" />

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("comparison.captionBorg")}
      </h3>
      <CopyableCode code={t("extractStandalone.borgCmd")} language="bash" />

      <p className="mt-4 mb-6 text-sm text-gray-600 italic">
        {t.rich("extractStandalone.note", { em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("whereNext.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("whereNext.intro", { em })}
      </p>

      <ul className="mb-6 space-y-2">
        {whereNextItems.map((item) => (
          <li key={item.href} className="text-gray-800 leading-relaxed">
            <Link href={item.href} className="text-blue-600 hover:underline font-medium">
              {item.label}
            </Link>
            <span>{item.tail}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
