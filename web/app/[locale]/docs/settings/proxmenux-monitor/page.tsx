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
  const t = await getTranslations({ locale, namespace: "docs.settings.proxmenuxMonitor.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/settings/proxmenux-monitor",
    },
  }
}

type StringItem = string
type ToggleRow = { state: string; label: string; action: string }
type RelatedItem = { href: string; label: string; tail?: string; tailRich?: string }

export default async function ProxmenuxMonitorPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.settings.proxmenuxMonitor" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { settings: { proxmenuxMonitor: {
      offers: { items: StringItem[] }
      toggle: { rows: ToggleRow[] }
      status: { items: StringItem[] }
      reset: { items: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const block = messages.docs.settings.proxmenuxMonitor
  const offersItems = block.offers.items
  const toggleRows = block.toggle.rows
  const statusItems = block.status.items
  const resetItems = block.reset.items
  const relatedItems = block.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const link = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/access-auth#recovering-password" className="text-blue-600 hover:underline">
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
        scriptPath="menus/config_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("offers.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {offersItems.map((_, idx) => (
          <li key={idx}>{t(`offers.items.${idx}`)}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("access.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("access.intro")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("access.url") as string}</pre>
      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">{t.rich("access.outro", { code })}</p>

      <Callout variant="warning" title={t("warnConditional.title")}>
        {t.rich("warnConditional.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("toggle.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("toggle.intro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("toggle.headerState")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("toggle.headerLabel")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("toggle.headerAction")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {toggleRows.map((row, idx) => (
              <tr key={row.state} className={idx < toggleRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.state}</strong></td>
                <td className="px-3 py-2 align-top">{row.label}</td>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-6 text-gray-800 leading-relaxed">{t.rich("toggle.outro", { em })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("status.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("status.intro", { em })}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {statusItems.map((_, idx) => (
          <li key={idx}>{t.rich(`status.items.${idx}`, { code, strong })}</li>
        ))}
      </ul>

      <Callout variant="tip" title={t("manual.title")}>
        {t("manual.intro")}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{t.raw("manual.code") as string}</pre>
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("reset.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("reset.intro")}</p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {resetItems.map((_, idx) => (
          <li key={idx}>{t.rich(`reset.items.${idx}`, { code, strong, em })}</li>
        ))}
      </ol>

      <Callout variant="info" title={t("reset.preservedTitle")}>
        {t.rich("reset.preservedBody", { code, strong })}
      </Callout>

      <Callout variant="warning" title={t("reset.trustTitle")}>
        {t.rich("reset.trustBody", { code })}
      </Callout>

      <p className="mb-6 text-gray-800 leading-relaxed">{t.rich("reset.seeAlso", { link })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("files.heading")}</h2>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("files.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.missingTitle")}>
        {t.rich("troubleshoot.missingBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.unreachableTitle")}>
        {t("troubleshoot.unreachableBody")}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{t.raw("troubleshoot.unreachableCmd") as string}</pre>
        {t.rich("troubleshoot.unreachableOutro", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.stopsTitle")}>
        {t.rich("troubleshoot.stopsBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item, idx) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tailRich ? t.rich(`related.items.${idx}.tailRich`, { code }) : item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
