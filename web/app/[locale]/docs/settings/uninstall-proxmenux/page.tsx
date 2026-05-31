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
  const t = await getTranslations({ locale, namespace: "docs.settings.uninstallProxmenux.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/settings/uninstall-proxmenux",
    },
  }
}

type StringItem = string
type DepRow = { type: string; offered?: string; offeredRich?: string }
type RelatedItem = { href: string; label: string; tail?: string }

export default async function UninstallProxMenuxPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.settings.uninstallProxmenux" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { settings: { uninstallProxmenux: {
      flow: { items: StringItem[] }
      deps: { rows: DepRow[] }
      restored: { items: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const block = messages.docs.settings.uninstallProxmenux
  const flowItems = block.flow.items
  const depRows = block.deps.rows
  const restoredItems = block.restored.items
  const relatedItems = block.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={3}
        scriptPath="menus/config_menu.sh"
      />

      <Callout variant="warning" title={t("scopeWarn.title")}>
        {t.rich("scopeWarn.body", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("flow.heading")}</h2>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-2">
        {flowItems.map((_, idx) => (
          <li key={idx}>{t.rich(`flow.items.${idx}`, { code, strong })}</li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("deps.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("deps.intro", { strong })}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("deps.headerType")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("deps.headerOffered")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {depRows.map((row, idx) => (
              <tr key={row.type} className={idx < depRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.type}</strong></td>
                <td className="px-3 py-2 align-top">
                  {row.offeredRich ? t.rich(`deps.rows.${idx}.offeredRich`, { code }) : row.offered}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="warning" title={t("deps.warnTitle")}>
        {t.rich("deps.warnBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("removed.heading")}</h2>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("removed.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("restored.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {restoredItems.map((_, idx) => (
          <li key={idx}>{t.rich(`restored.items.${idx}`, { code, em })}</li>
        ))}
      </ul>

      <Callout variant="info" title={t("othersCallout.title")}>
        {t.rich("othersCallout.body", { strong, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("manual.intro", { code })}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("manual.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("reinstall.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("reinstall.body")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.hangTitle")}>
        {t.rich("troubleshoot.hangBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.aptTitle")}>
        {t.rich("troubleshoot.aptBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.motdTitle")}>
        {t.rich("troubleshoot.motdBody", { code })}
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
