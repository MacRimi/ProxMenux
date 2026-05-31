import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.meta" })
  return {
    title: t("title"),
    description: t("description"),
  }
}

type TabRow = { name: string; linksTo?: string; owns: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function DashboardIndexPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: {
      tabs: { rows: TabRow[] }
      headerAnatomy: { items: string[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const tabRows = messages.docs.monitor.dashboard.tabs.rows
  const headerAnatomyItems = messages.docs.monitor.dashboard.headerAnatomy.items
  const whereNextItems = messages.docs.monitor.dashboard.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const link = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/health-monitor" className="text-blue-700 hover:underline">
      {chunks}
    </Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={3}
      />

      <Callout variant="info" title={t("oneHeader.title")}>
        {t.rich("oneHeader.body", { link })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("tabs.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("tabs.intro")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("tabs.headerTab")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("tabs.headerOwns")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {tabRows.map((row, idx) => (
              <tr
                key={row.name}
                className={idx < tabRows.length - 1 ? "border-b border-gray-100" : ""}
              >
                <td className="px-3 py-2 align-top whitespace-nowrap">
                  {row.linksTo ? (
                    <Link href={row.linksTo} className="text-blue-600 hover:underline font-semibold">
                      {row.name}
                    </Link>
                  ) : (
                    <strong>{row.name}</strong>
                  )}
                </td>
                <td className="px-3 py-2 align-top">
                  {t.rich(`tabs.rows.${idx}.owns`, { code })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("headerAnatomy.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {headerAnatomyItems.map((_, idx) => (
          <li key={idx}>{t.rich(`headerAnatomy.items.${idx}`, { code, strong, em })}</li>
        ))}
      </ul>

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
      </ul>
    </div>
  )
}
