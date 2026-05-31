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
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.storage.meta" })
  return { title: t("title"), description: t("description") }
}

type DataRow = { section: string; endpoint: string; source: string }
type WhereNextItem = { label: string; href: string; tail?: string; tailRich?: string }

export default async function StorageTabPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.storage" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { storage: {
      thresholds: { items: string[] }
      topRow: { disksItems: string[] }
      pveStorage: { items: string[] }
      zfs: { items: string[] }
      physical: { items: string[] }
      drillIn: {
        overviewItems: string[]
        smartItems: string[]
        pdfSections: string[]
        historyItems: string[]
        scheduleItems: string[]
        tempShowsItems: string[]
        tempDiskTypes: string[]
        tempWhyItems: string[]
        obsWhatItems: string[]
        obsWhyItems: string[]
      }
      dataCollected: { rows: DataRow[] }
      whereNext: { items: WhereNextItem[] }
    } } } }
  }
  const s = messages.docs.monitor.dashboard.storage
  const thresholdsItems = s.thresholds.items
  const disksItems = s.topRow.disksItems
  const pveItems = s.pveStorage.items
  const zfsItems = s.zfs.items
  const physicalItems = s.physical.items
  const overviewItems = s.drillIn.overviewItems
  const smartItems = s.drillIn.smartItems
  const pdfSections = s.drillIn.pdfSections
  const historyItems = s.drillIn.historyItems
  const scheduleItems = s.drillIn.scheduleItems
  const tempShowsItems = s.drillIn.tempShowsItems
  const tempDiskTypes = s.drillIn.tempDiskTypes
  const tempWhyItems = s.drillIn.tempWhyItems
  const obsWhatItems = s.drillIn.obsWhatItems
  const obsWhyItems = s.drillIn.obsWhyItems
  const dataRows = s.dataCollected.rows
  const whereNextItems = s.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const green = () => <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500 align-middle mr-1" />
  const amber = () => <span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-500 align-middle mr-1" />
  const red = () => <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-500 align-middle mr-1" />
  const thresholdsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/settings#status-colours" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const zfsHmLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/health-monitor" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const physicalWarnLink = (chunks: React.ReactNode) => (
    <Link href="/docs/disk-manager/format-disk" className="text-amber-700 hover:underline">{chunks}</Link>
  )
  const hmLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/health-monitor" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={14}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <Callout variant="tip" title={t("thresholds.title")}>
        {t.rich("thresholds.intro", { strong, green, amber, red })}
        <ul className="list-disc pl-6 mt-2 space-y-0.5">
          {thresholdsItems.map((_, idx) => (
            <li key={idx}>{t.rich(`thresholds.items.${idx}`, { strong })}</li>
          ))}
        </ul>
        {t.rich("thresholds.outro", { link: thresholdsLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("topRow.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("topRow.intro")}</p>

      <figure className="my-6">
        <img
          src="/monitor/storage-top-row.png"
          alt={t("topRow.imageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("topRow.imageCaption")}
        </figcaption>
      </figure>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("topRow.headerCard")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("topRow.headerWhat")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            <tr className="border-b border-gray-100">
              <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{t("topRow.totalLabel")}</strong></td>
              <td className="px-3 py-2 align-top">{t("topRow.totalWhat")}</td>
            </tr>
            <tr className="border-b border-gray-100">
              <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{t("topRow.localLabel")}</strong></td>
              <td className="px-3 py-2 align-top">{t.rich("topRow.localWhat", { em })}</td>
            </tr>
            <tr className="border-b border-gray-100">
              <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{t("topRow.remoteLabel")}</strong></td>
              <td className="px-3 py-2 align-top">{t("topRow.remoteWhat")}</td>
            </tr>
            <tr>
              <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{t("topRow.disksLabel")}</strong></td>
              <td className="px-3 py-2 align-top">
                {t("topRow.disksIntro")}
                <ul className="list-disc pl-5 mt-2 space-y-0.5">
                  {disksItems.map((_, idx) => (
                    <li key={idx}>{t.rich(`topRow.disksItems.${idx}`, { strong, em })}</li>
                  ))}
                </ul>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("pveStorage.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pveStorage.intro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {pveItems.map((_, idx) => (
          <li key={idx}>{t.rich(`pveStorage.items.${idx}`, { strong })}</li>
        ))}
      </ul>

      <Callout variant="tip" title={t("pveStorage.calloutTitle")}>
        {t.rich("pveStorage.calloutBody", { em, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("zfs.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("zfs.intro")}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {zfsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`zfs.items.${idx}`, { strong })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("zfs.outro", { em, link: zfsHmLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("physical.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("physical.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {physicalItems.map((_, idx) => (
          <li key={idx}>{t.rich(`physical.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("physical.clickHint")}</p>

      <Callout variant="warning" title={t("physical.warningTitle")}>
        {t.rich("physical.warningBody", { strong, link: physicalWarnLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("external.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("external.body", { strong })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("drillIn.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.intro", { strong, em })}
      </p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.overviewTitle")}</h3>

      <figure className="my-4">
        <img
          src="/monitor/disk-modal-overview.png"
          alt={t("drillIn.overviewImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("drillIn.overviewImageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("drillIn.overviewIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {overviewItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.overviewItems.${idx}`, { strong, em })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.smartTitle")}</h3>

      <figure className="my-4">
        <img
          src="/monitor/disk-modal-smart.png"
          alt={t("drillIn.smartImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("drillIn.smartImageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("drillIn.smartIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {smartItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.smartItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.pdfTitle")}</h4>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.pdfIntro", { strong })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/smart-report-preview.png"
          alt={t("drillIn.pdfPreviewAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("drillIn.pdfPreviewCaption")}
        </figcaption>
      </figure>

      <div className="my-6">
        <a
          href="/monitor/sample-smart-report.pdf"
          download
          className="inline-flex items-center gap-2 px-4 py-2 rounded-md border border-blue-200 bg-blue-50 text-blue-700 font-medium hover:bg-blue-100 transition-colors"
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          {t("drillIn.pdfDownloadLabel")}
        </a>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("drillIn.pdfSectionsIntro")}</p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {pdfSections.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.pdfSections.${idx}`, { strong, em })}</li>
        ))}
      </ol>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("drillIn.pdfOutro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.historyTitle")}</h3>

      <figure className="my-4">
        <img
          src="/monitor/disk-modal-history.png"
          alt={t("drillIn.historyImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("drillIn.historyImageCaption", { code })}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.historyIntro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {historyItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.historyItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.scheduleTitle")}</h3>

      <figure className="my-4">
        <img
          src="/monitor/disk-modal-schedule.png"
          alt={t("drillIn.scheduleImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("drillIn.scheduleImageCaption", { code })}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("drillIn.scheduleIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {scheduleItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.scheduleItems.${idx}`, { strong, em })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("drillIn.scheduleOutro")}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.tempTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("drillIn.tempIntro")}</p>

      <figure className="my-4">
        <img
          src="/monitor/disk-modal-temperature.png"
          alt={t("drillIn.tempImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("drillIn.tempImageCaption")}
        </figcaption>
      </figure>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.tempShowsTitle")}</h4>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {tempShowsItems.map((_, idx) => (
          <li key={idx}>
            {t.rich(`drillIn.tempShowsItems.${idx}`, { strong, em })}
            {idx === 2 && (
              <ul className="list-disc pl-6 mt-1">
                {tempDiskTypes.map((_, didx) => (
                  <li key={didx}>{t.rich(`drillIn.tempDiskTypes.${didx}`, { strong })}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.tempConfigurable", { em })}
      </p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.tempWhyTitle")}</h4>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {tempWhyItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.tempWhyItems.${idx}`, { strong, em })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.obsTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.obsIntro", { strong, em })}
      </p>

      <figure className="my-4">
        <img
          src="/monitor/disk-modal-observations.png"
          alt={t("drillIn.obsImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("drillIn.obsImageCaption", { strong })}
        </figcaption>
      </figure>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.obsWhatTitle")}</h4>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.obsWhatIntro", { strong })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {obsWhatItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.obsWhatItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.obsWhyTitle")}</h4>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {obsWhyItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.obsWhyItems.${idx}`, { strong, em })}</li>
        ))}
      </ul>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.obsDedupTitle")}</h4>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.obsDedupBody1", { strong, code })}
      </p>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("drillIn.obsDedupBody2")}
      </p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.obsDismissTitle")}</h4>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.obsDismissBody1", { strong })}
      </p>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("drillIn.obsDismissBody2", { link: hmLink })}
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
                <td className="px-3 py-2 align-top">{t.rich(`dataCollected.rows.${idx}.source`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("dataCollected.outro")}</p>

      <CopyableCode
        code={`${t("dataCollected.codeComment1")}
curl -H "Authorization: Bearer <api-token>" \\
  http://<host>:8008/api/storage | jq '.disks[] | {name,model,smart_status}'

${t("dataCollected.codeComment2")}
lsblk -O
zpool status
journalctl -t smartd --since '1 day ago' | tail`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {whereNextItems.map((item, idx) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tailRich ? t.rich(`whereNext.items.${idx}.tailRich`, { code }) : item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
