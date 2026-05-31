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
  const t = await getTranslations({ locale, namespace: "docs.settings.showVersionInformation.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/settings/show-version-information",
    },
  }
}

type ReportRow = { section: string; source: string; content?: string; contentRich?: string }
type RelatedItem = { href: string; label: string; tail?: string }

export default async function ShowVersionInformationPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.settings.showVersionInformation" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { settings: { showVersionInformation: {
      reports: { rows: ReportRow[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const reportRows = messages.docs.settings.showVersionInformation.reports.rows
  const relatedItems = messages.docs.settings.showVersionInformation.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={2}
        scriptPath="menus/config_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("reports.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("reports.headerSection")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("reports.headerSource")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("reports.headerContent")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {reportRows.map((row, idx) => (
              <tr key={row.section} className={idx < reportRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.section}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.source}</td>
                <td className="px-3 py-2 align-top">
                  {row.contentRich ? t.rich(`reports.rows.${idx}.contentRich`, { code }) : row.content}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("sampleHeading")}</h2>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`Current ProxMenux version: 1.2.3

Installation type:
✓ Translation Version (Multi-language support)

Installed components:
✓ post_install_settings: installed
✓ post_install_system: installed
✓ post_install_security: installed
✓ proxmenux_monitor: installed
✓ fail2ban: installed
✗ lynis: removed

ProxMenux files:
✓ menu → /usr/local/bin/menu
✓ utils.sh → /usr/local/share/proxmenux/utils.sh
✓ config.json → /usr/local/share/proxmenux/config.json
✓ version.txt → /usr/local/share/proxmenux/version.txt
✓ cache.json → /usr/local/share/proxmenux/cache.json

Virtual Environment:
✓ Installed → /opt/googletrans-env
✓ pip: Installed → /opt/googletrans-env/bin/pip

Current language:
es`}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manualHeading")}</h2>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`# Version
cat /usr/local/share/proxmenux/version.txt

# Install type detection (replicates the script's logic)
[[ -d /opt/googletrans-env ]] && echo "venv: yes" || echo "venv: no"
jq -r '.language // "missing"' /usr/local/share/proxmenux/config.json

# All component statuses
jq 'to_entries[] | "\\(.key): \\(.value)"' /usr/local/share/proxmenux/config.json

# Current language
jq -r '.language' /usr/local/share/proxmenux/config.json`}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.unknownTitle")}>
        {t.rich("troubleshoot.unknownBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.noConfigTitle")}>
        {t.rich("troubleshoot.noConfigBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.wrongStatusTitle")}>
        {t.rich("troubleshoot.wrongStatusBody", { code })}
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
