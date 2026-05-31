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
  const t = await getTranslations({ locale, namespace: "docs.network.diagnostics.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/network/diagnostics",
    },
  }
}

type ConnRow = { test: string; target: string; confirms: string }
type RelatedItem = { label: string; href: string; tail: string }

export default async function NetworkDiagnosticsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.network.diagnostics" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { network: { diagnostics: {
      connectivity: { rows: ConnRow[] }
      advanced: { items: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const connRows = messages.docs.network.diagnostics.connectivity.rows
  const advancedItems = messages.docs.network.diagnostics.advanced.items
  const relatedItems = messages.docs.network.diagnostics.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const monitoringLink = (chunks: React.ReactNode) => (
    <Link href="/docs/network/monitoring" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const backupLink = (chunks: React.ReactNode) => (
    <Link href="/docs/network/backup-restore" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={3}
        scriptPath="menus/network_menu.sh"
      />

      <Callout variant="success" title={t("intro.title")}>
        {t.rich("intro.body", { strong, monitoringLink, backupLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("routing.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("routing.body", { code })}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`Total routes: 4

➡  default via 192.168.1.1 dev vmbr0 onlink
   • 10.10.10.0/24 dev vmbr1 proto kernel scope link src 10.10.10.1
   • 169.254.0.0/16 dev vmbr0 scope link metric 1000
   • 192.168.1.0/24 dev vmbr0 proto kernel scope link src 192.168.1.10

🌍 Default Gateway: 192.168.1.1`}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("connectivity.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("connectivity.intro", { code })}
      </p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("connectivity.headerTest")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("connectivity.headerTarget")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("connectivity.headerConfirms")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {connRows.map((row, idx) => (
              <tr key={row.test} className={idx < connRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.test}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono">{row.target}</td>
                <td className="px-3 py-2 align-top">{row.confirms}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Callout variant="info" title={t("connectivity.readingTitle")}>
        {t.rich("connectivity.readingBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("advanced.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("advanced.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        {advancedItems.map((_, idx) => (
          <li key={idx}>{t.rich(`advanced.items.${idx}`, { strong, code, em })}</li>
        ))}
      </ul>
      <Callout variant="warning" title={t("advanced.nmTitle")}>
        {t.rich("advanced.nmBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.gwTitle")}>
        {t.rich("troubleshoot.gwBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.dupTitle")}>
        {t.rich("troubleshoot.dupBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item) => (
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
