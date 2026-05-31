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
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.systemLogs.meta" })
  return { title: t("title"), description: t("description") }
}

type DataRow = { subtab: string; endpoint: string; source: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function SystemLogsTabPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.systemLogs" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { systemLogs: {
      topRow: { items: string[] }
      subtabs: { logsFilters: string[]; fields: string[] }
      dataCollected: { rows: DataRow[] }
      whereNext: { items: WhereNextItem[] }
    } } } }
  }
  const sl = messages.docs.monitor.dashboard.systemLogs
  const topRowItems = sl.topRow.items
  const logsFilters = sl.subtabs.logsFilters
  const fields = sl.subtabs.fields
  const dataRows = sl.dataCollected.rows
  const whereNextItems = sl.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const link = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/notifications" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={7}
      />

      <Callout variant="info" title={t("readOnly.title")}>
        {t.rich("readOnly.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("topRow.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {topRowItems.map((_, idx) => (
          <li key={idx}>{t.rich(`topRow.items.${idx}`, { code, strong })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("subtabs.heading")}</h2>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("subtabs.logsTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("subtabs.logsIntro", { code })}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {logsFilters.map((_, idx) => (
          <li key={idx}>{t.rich(`subtabs.logsFilters.${idx}`, { code, strong })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("subtabs.logsRowsAfter", { code, strong })}
      </p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("subtabs.logDetailsModalTitle")}</h4>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("subtabs.logDetailsBody", { code, strong })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/log-details-modal.png"
          alt={t("subtabs.logDetailsImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("subtabs.logDetailsImageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("subtabs.fieldsIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {fields.map((_, idx) => (
          <li key={idx}>{t.rich(`subtabs.fields.${idx}`, { code, strong })}</li>
        ))}
      </ul>

      <Callout variant="tip" title={t("subtabs.maxLevelStoreTitle")}>
        {t.rich("subtabs.maxLevelStoreBody", { code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("subtabs.backupsTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("subtabs.backupsBody", { code, em })}</p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("subtabs.notificationsTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("subtabs.notificationsBody1")}</p>
      <p className="mb-6 text-gray-800 leading-relaxed">{t.rich("subtabs.notificationsBody2", { link })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("dataCollected.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerSubtab")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerEndpoint")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerSource")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {dataRows.map((row, idx) => (
              <tr
                key={row.endpoint}
                className={idx < dataRows.length - 1 ? "border-b border-gray-100" : ""}
              >
                <td className="px-3 py-2 align-top">{row.subtab}</td>
                <td className="px-3 py-2 align-top font-mono text-xs" dangerouslySetInnerHTML={{ __html: row.endpoint }} />
                <td className="px-3 py-2 align-top">
                  {t.rich(`dataCollected.rows.${idx}.source`, { code })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("dataCollected.apiIntro")}</p>
      <CopyableCode
        code={`${t("dataCollected.codeComment1")}
curl -H "Authorization: Bearer <token>" \\
  "http://<host>:8008/api/logs?severity=error&since=1h&search=zfs"

${t("dataCollected.codeComment2")}
curl -H "Authorization: Bearer <token>" \\
  -o pmx-journal.txt \\
  "http://<host>:8008/api/logs/download?since=6h"

${t("dataCollected.codeComment3")}
curl -H "Authorization: Bearer <token>" \\
  "http://<host>:8008/api/task-log/<upid>"`}
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
