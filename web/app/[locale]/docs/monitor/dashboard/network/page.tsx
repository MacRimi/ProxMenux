import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { Download } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.network.meta" })
  return { title: t("title"), description: t("description") }
}

type TopRow = { card: string; what: string }
type DrillRow = { block: string; contents: string }
type ThresholdRow = { status: string; range: string; impact: string }
type DataRow = { section: string; endpoint: string; source: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function NetworkTabPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.network" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { network: {
      topRow: { rows: TopRow[] }
      groups: { badges: string[] }
      drillIn: { rows: DrillRow[] }
      latency: {
        targets: string[]
        mode2Items: string[]
        thresholdRows: ThresholdRow[]
        sections: string[]
      }
      dataCollected: { rows: DataRow[] }
      whereNext: { items: WhereNextItem[] }
    } } } }
  }
  const net = messages.docs.monitor.dashboard.network
  const topRows = net.topRow.rows
  const badges = net.groups.badges
  const drillRows = net.drillIn.rows
  const targets = net.latency.targets
  const mode2Items = net.latency.mode2Items
  const thresholdRows = net.latency.thresholdRows
  const sections = net.latency.sections
  const dataRows = net.dataCollected.rows
  const whereNextItems = net.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={13}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("topRow.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("topRow.headerCard")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("topRow.headerWhat")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {topRows.map((row, idx) => (
              <tr key={row.card} className={idx < topRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.card}</strong></td>
                <td className="px-3 py-2 align-top">
                  {t.rich(`topRow.rows.${idx}.what`, { em, strong })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("groups.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("groups.intro", { strong })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {badges.map((_, idx) => (
          <li key={idx}>{t.rich(`groups.badges.${idx}`, { strong, code })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("groups.clickable", { strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("groups.physicalTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("groups.physicalBody", { code, strong, em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("groups.bridgeTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("groups.bridgeBody", { code, strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("groups.vmTitle")}</h3>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("groups.vmBody", { code, em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("drillIn.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("drillIn.intro")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("drillIn.headerBlock")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("drillIn.headerContents")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {drillRows.map((row, idx) => (
              <tr key={row.block} className={idx < drillRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.block}</strong></td>
                <td className="px-3 py-2 align-top">
                  {t.rich(`drillIn.rows.${idx}.contents`, { code })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("drillIn.inactiveTitle")}>
        {t.rich("drillIn.inactiveBody", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("latency.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("latency.intro", { em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("latency.targetsTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("latency.targetsIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {targets.map((_, idx) => (
          <li key={idx}>{t.rich(`latency.targets.${idx}`, { strong })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("latency.mode1Title")}</h3>

      <figure className="my-4">
        <img
          src="/monitor/network-latency-historical.png"
          alt={t("latency.mode1Alt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("latency.mode1Caption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("latency.mode1Body1", { em })}
      </p>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("latency.mode1Body2", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("latency.mode2Title")}</h3>

      <figure className="my-4">
        <img
          src="/monitor/network-latency-realtime.png"
          alt={t("latency.mode2Alt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("latency.mode2Caption", { em })}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("latency.mode2Intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {mode2Items.map((_, idx) => (
          <li key={idx}>{t.rich(`latency.mode2Items.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("latency.thresholdsTitle")}</h3>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("latency.headerStatus")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("latency.headerRange")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("latency.headerImpact")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {thresholdRows.map((row, idx) => (
              <tr key={row.status} className={idx < thresholdRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.status}</strong></td>
                <td className="px-3 py-2 align-top">{row.range}</td>
                <td className="px-3 py-2 align-top">{row.impact}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("latency.reportTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("latency.reportIntro", { strong })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/network-latency-report-preview.png"
          alt={t("latency.reportPreviewAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("latency.reportPreviewCaption")}
        </figcaption>
      </figure>

      <div className="my-6">
        <a
          href="/monitor/sample-network-latency-report.pdf"
          download
          className="inline-flex items-center gap-2 px-4 py-2 rounded-md border border-blue-200 bg-blue-50 text-blue-700 font-medium hover:bg-blue-100 transition-colors"
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          {t("latency.downloadLabel")}
        </a>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("latency.sectionsIntro")}</p>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {sections.map((_, idx) => (
          <li key={idx}>{t.rich(`latency.sections.${idx}`, { strong })}</li>
        ))}
      </ol>

      <Callout variant="tip" title={t("latency.useCaseTitle")}>
        {t.rich("latency.useCaseBody", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("excluding.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("excluding.body1", { code })}
      </p>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("excluding.body2", { strong, em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("dataCollected.heading")}</h2>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerSection")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerEndpoint")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerSource")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {dataRows.map((row, idx) => (
              <tr key={row.section} className={idx < dataRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top">{row.section}</td>
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
ip -br link
ip -br addr

${t("dataCollected.codeComment2")}
curl -H "Authorization: Bearer <token>" \\
  http://<host>:8008/api/network/latency/current | jq`}
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
