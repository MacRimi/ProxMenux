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
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.systemOverview.meta" })
  return { title: t("title"), description: t("description") }
}

type TopRow = { card: string; what: string; source: string }
type DataRow = { card: string; endpoint: string; source: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function SystemOverviewTabPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.systemOverview" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { systemOverview: {
      topRow: { rows: TopRow[]; thresholdsItems: string[] }
      processes: { listItems: string[]; detailItems: string[] }
      bottom: { storageItems: string[] }
      refresh: { items: string[] }
      dataCollected: { rows: DataRow[] }
      whereNext: { items: WhereNextItem[] }
    } } } }
  }
  const so = messages.docs.monitor.dashboard.systemOverview
  const topRows = so.topRow.rows
  const thresholdsItems = so.topRow.thresholdsItems
  const processListItems = so.processes.listItems
  const processDetailItems = so.processes.detailItems
  const storageItems = so.bottom.storageItems
  const refreshItems = so.refresh.items
  const dataRows = so.dataCollected.rows
  const whereNextItems = so.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const green = () => <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500 align-middle mr-1" />
  const amber = () => <span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-500 align-middle mr-1" />
  const red = () => <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-500 align-middle mr-1" />
  const thresholdsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/settings#status-colours" className="text-blue-700 hover:underline">
      {chunks}
    </Link>
  )
  const storageLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const networkLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={6}
      />

      <Callout variant="info" title={t("readOnly.title")}>
        {t("readOnly.body")}
      </Callout>

      <figure className="my-8">
        <img
          src="/monitor/dashboard-home.png"
          alt={t("captureAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("captureCaption")}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("topRow.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("topRow.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("topRow.headerCard")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("topRow.headerWhat")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("topRow.headerSource")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {topRows.map((row, idx) => (
              <tr key={row.card} className={idx < topRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">
                  <strong>{row.card}</strong>
                </td>
                <td className="px-3 py-2 align-top">
                  {t.rich(`topRow.rows.${idx}.what`, { code, em })}
                </td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("topRow.thresholdsTitle")}>
        {t.rich("topRow.thresholdsIntro", { strong, green, amber, red })}
        <ul className="list-disc pl-6 mt-2 space-y-0.5">
          {thresholdsItems.map((_, idx) => (
            <li key={idx}>{t.rich(`topRow.thresholdsItems.${idx}`, { strong })}</li>
          ))}
        </ul>
        {t.rich("topRow.thresholdsOutro", { link: thresholdsLink })}
      </Callout>

      <Callout variant="tip" title={t("topRow.sparklineTitle")}>
        {t("topRow.sparklineBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("processes.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("processes.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("processes.listTitle")}</h3>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {processListItems.map((_, idx) => (
          <li key={idx}>{t.rich(`processes.listItems.${idx}`, { strong })}</li>
        ))}
      </ul>

      <figure className="my-6">
        <img
          src="/monitor/system-overview-top-processes.png"
          alt={t("processes.captureListAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("processes.captureListCaption")}
        </figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("processes.detailTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("processes.detailIntro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {processDetailItems.map((_, idx) => (
          <li key={idx}>{t.rich(`processes.detailItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("processes.detailRefresh", { em, code })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/system-overview-process-detail.png"
          alt={t("processes.captureDetailAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("processes.captureDetailCaption")}
        </figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("processes.sourceTitle")}</h3>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("processes.sourceBody", { code, em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("middle.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("middle.body1", { code, em })}
      </p>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t("middle.body2")}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("bottom.heading")}</h2>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("bottom.storageTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("bottom.storageIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {storageItems.map((_, idx) => (
          <li key={idx}>{t.rich(`bottom.storageItems.${idx}`, { strong })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("bottom.storageDrillIn", { link: storageLink })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("bottom.networkTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("bottom.networkBody1", { code })}
      </p>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("bottom.networkBody2", { link: networkLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("refresh.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("refresh.intro", { code, em })}
      </p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {refreshItems.map((_, idx) => (
          <li key={idx}>{t.rich(`refresh.items.${idx}`, { strong })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("dataCollected.heading")}</h2>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerCard")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerEndpoint")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerSource")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {dataRows.map((row, idx) => (
              <tr key={row.card} className={idx < dataRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top">{row.card}</td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.endpoint}</td>
                <td className="px-3 py-2 align-top">
                  {t.rich(`dataCollected.rows.${idx}.source`, { code })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CopyableCode
        code={`${t("dataCollected.codeComment1")}
curl http://<host>:8008/api/health   ${t("dataCollected.codeComment2")}

${t("dataCollected.codeComment3")}
curl -H "Authorization: Bearer <token>" \\
  http://<host>:8008/api/system | jq '.cpu,.memory,.uptime'`}
        className="my-4"
      />

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
