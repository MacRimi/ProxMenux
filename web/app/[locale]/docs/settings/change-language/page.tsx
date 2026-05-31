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
  const t = await getTranslations({ locale, namespace: "docs.settings.changeLanguage.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/settings/change-language",
    },
  }
}

type LangRow = { code: string; lang: string; notes: string }
type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string }

export default async function ChangeLanguagePage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.settings.changeLanguage" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { settings: { changeLanguage: {
      supported: { rows: LangRow[] }
      underHood: { items: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const langRows = messages.docs.settings.changeLanguage.supported.rows
  const underHoodItems = messages.docs.settings.changeLanguage.underHood.items
  const relatedItems = messages.docs.settings.changeLanguage.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={1}
        scriptPath="menus/config_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <Callout variant="warning" title={t("warn.title")}>
        {t.rich("warn.body", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("supported.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("supported.headerCode")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("supported.headerLang")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("supported.headerNotes")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {langRows.map((row, idx) => (
              <tr key={row.code} className={idx < langRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono">{row.code}</td>
                <td className="px-3 py-2 align-top">{row.lang}</td>
                <td className="px-3 py-2 align-top">{row.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("englishTip.title")}>
        {t("englishTip.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("underHood.heading")}</h2>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {underHoodItems.map((_, idx) => (
          <li key={idx}>{t.rich(`underHood.items.${idx}`, { code, em })}</li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`# Set language to Spanish
tmp=$(mktemp)
jq --arg lang "es" '.language = $lang' /usr/local/share/proxmenux/config.json > "$tmp" \\
    && mv "$tmp" /usr/local/share/proxmenux/config.json

# Verify
jq -r '.language' /usr/local/share/proxmenux/config.json`}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.noOptionTitle")}>
        {t("troubleshoot.noOptionBody")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.stillEnglishTitle")}>
        {t.rich("troubleshoot.stillEnglishBody", { code })}
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
