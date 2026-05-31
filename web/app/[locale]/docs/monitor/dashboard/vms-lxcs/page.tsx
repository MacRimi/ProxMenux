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
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.vmsLxcs.meta" })
  return { title: t("title"), description: t("description") }
}

type LifecycleRow = { button: string; color: string; enabled: string; action: string }
type DataRow = { section: string; endpoint: string; source: string }
type WhereNextItem = { label: string; href: string; tailRich: string }

export default async function VmsLxcsTabPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.vmsLxcs" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { vmsLxcs: {
      topRow: { memoryItems: string[] }
      inventory: { rows: string[] }
      drillIn: {
        liveItems: string[]
        ioItems: string[]
        resourcesItems: string[]
        mountTypesItems: string[]
        mountStateItems: string[]
        backupsItems: string[]
        updatesPanelItems: string[]
        firewallItems: string[]
        lifecycleRows: LifecycleRow[]
      }
      dataCollected: { rows: DataRow[] }
      whereNext: { items: WhereNextItem[] }
    } } } }
  }
  const v = messages.docs.monitor.dashboard.vmsLxcs
  const memoryItems = v.topRow.memoryItems
  const inventoryRows = v.inventory.rows
  const liveItems = v.drillIn.liveItems
  const ioItems = v.drillIn.ioItems
  const resourcesItems = v.drillIn.resourcesItems
  const mountTypesItems = v.drillIn.mountTypesItems
  const mountStateItems = v.drillIn.mountStateItems
  const backupsItems = v.drillIn.backupsItems
  const updatesPanelItems = v.drillIn.updatesPanelItems
  const firewallItems = v.drillIn.firewallItems
  const lifecycleRows = v.drillIn.lifecycleRows
  const dataRows = v.dataCollected.rows
  const whereNextItems = v.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const green = () => <span className="inline-block w-2 h-2 rounded-full bg-green-500 align-middle mr-1" />
  const amber = () => <span className="inline-block w-2 h-2 rounded-full bg-amber-500 align-middle mr-1" />
  const red = () => <span className="inline-block w-2 h-2 rounded-full bg-red-500 align-middle mr-1" />
  const greenText = (chunks: React.ReactNode) => <span className="text-green-600 font-semibold">{chunks}</span>
  const amberText = (chunks: React.ReactNode) => <span className="text-amber-600 font-semibold">{chunks}</span>
  const redText = (chunks: React.ReactNode) => <span className="text-red-600 font-semibold">{chunks}</span>
  const orangeText = (chunks: React.ReactNode) => <span className="text-orange-600 font-semibold">{chunks}</span>
  const link = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/terminal" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  const buttonColorClass = (color: string) => {
    switch (color) {
      case "green":
        return "text-green-600 font-semibold"
      case "blue":
        return "text-blue-600 font-semibold"
      case "red":
        return "text-red-600 font-semibold"
      default:
        return "font-semibold"
    }
  }

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={12}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("topRow.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("topRow.intro")}</p>

      <figure className="my-6">
        <img
          src="/monitor/vms-top-row.png"
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
              <td className="px-3 py-2 align-top">{t.rich("topRow.totalWhat", { em })}</td>
            </tr>
            <tr className="border-b border-gray-100">
              <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{t("topRow.cpuLabel")}</strong></td>
              <td className="px-3 py-2 align-top">{t.rich("topRow.cpuWhat", { em })}</td>
            </tr>
            <tr className="border-b border-gray-100">
              <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{t("topRow.memoryLabel")}</strong></td>
              <td className="px-3 py-2 align-top">
                {t("topRow.memoryIntro")}
                <ul className="list-disc pl-5 mt-2 space-y-0.5">
                  {memoryItems.map((_, idx) => (
                    <li key={idx}>{t.rich(`topRow.memoryItems.${idx}`, { strong, em, code })}</li>
                  ))}
                </ul>
              </td>
            </tr>
            <tr>
              <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{t("topRow.diskLabel")}</strong></td>
              <td className="px-3 py-2 align-top">{t.rich("topRow.diskWhat", { em })}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("inventory.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("inventory.intro", { code })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/vms-inventory-mobile.png"
          alt={t("inventory.imageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full max-w-md mx-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("inventory.imageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("inventory.rowsIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {inventoryRows.map((_, idx) => (
          <li key={idx}>{t.rich(`inventory.rows.${idx}`, { strong, em })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("inventory.clickHint")}</p>

      <Callout variant="tip" title={t("inventory.mobileTitle")}>
        {t("inventory.mobileBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("drillIn.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.intro", { strong, em })}
      </p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.statusTitle")}</h3>

      <figure className="my-4">
        <img
          src="/monitor/vms-modal-status.png"
          alt={t("drillIn.statusImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("drillIn.statusImageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("drillIn.statusIntro")}</p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.liveTitle")}</h4>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {liveItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.liveItems.${idx}`, { strong, em })}</li>
        ))}
      </ul>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.ioTitle")}</h4>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {ioItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.ioItems.${idx}`, { strong })}</li>
        ))}
      </ul>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.resourcesTitle")}</h4>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.resourcesIntro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {resourcesItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.resourcesItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.ipsTitle")}</h4>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("drillIn.ipsBody")}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.mountsTitle")}</h3>

      <figure className="my-4">
        <img
          src="/monitor/vms-modal-mounts.png"
          alt={t("drillIn.mountsImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("drillIn.mountsImageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.mountsIntro", { strong, code })}
      </p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.mountTypesTitle")}</h4>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {mountTypesItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.mountTypesItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.mountStateTitle")}</h4>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {mountStateItems.map((_, idx) => (
          <li key={idx}>
            {t.rich(`drillIn.mountStateItems.${idx}`, { strong, em, code, green, amber, red })}
          </li>
        ))}
      </ul>

      <Callout variant="info" title={t("drillIn.mountsCalloutTitle")}>
        {t("drillIn.mountsCalloutBody")}
      </Callout>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.backupsTitle")}</h3>

      <figure className="my-4">
        <img
          src="/monitor/vms-modal-backups.png"
          alt={t("drillIn.backupsImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("drillIn.backupsImageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("drillIn.backupsIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {backupsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.backupsItems.${idx}`, { strong })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("drillIn.backupsOutro", { strong })}
      </p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.updatesTitle")}</h3>

      <figure className="my-4">
        <img
          src="/monitor/vms-modal-lxc-updates.png"
          alt={t("drillIn.updatesImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("drillIn.updatesImageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.updatesIntro", { strong, code })}
      </p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.updatesPanelTitle")}</h4>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {updatesPanelItems.map((_, idx) => (
          <li key={idx}>{t.rich(`drillIn.updatesPanelItems.${idx}`, { strong })}</li>
        ))}
      </ul>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.updatesScopeTitle")}</h4>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.updatesScopeBody", { strong, em, code })}
      </p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.updatesToggleTitle")}</h4>
      <Callout variant="info" title={t("drillIn.updatesToggleCalloutTitle")}>
        {t.rich("drillIn.updatesToggleCalloutBody", { strong, code })}
      </Callout>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("drillIn.updatesApplyTitle")}</h4>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("drillIn.updatesApplyBody", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.firewallTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("drillIn.firewallIntro")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {firewallItems.map((_, idx) => (
          <li key={idx}>
            {t.rich(`drillIn.firewallItems.${idx}`, {
              strong,
              em,
              code,
              green: greenText,
              orange: orangeText,
              red: redText,
            })}
          </li>
        ))}
      </ul>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.firewallRefresh", { em, code })}
      </p>

      <Callout variant="info" title={t("drillIn.firewallCalloutTitle")}>
        {t("drillIn.firewallCalloutBody")}
      </Callout>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("drillIn.actionBarTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("drillIn.actionBarIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        <li>{t.rich("drillIn.consoleItem", { strong, code, link })}</li>
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("drillIn.lifecycleIntro", { code })}
      </p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("drillIn.headerButton")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("drillIn.headerEnabled")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("drillIn.headerAction")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {lifecycleRows.map((row, idx) => (
              <tr key={row.button} className={idx < lifecycleRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">
                  <strong className={buttonColorClass(row.color)}>{row.button}</strong>
                </td>
                <td className="px-3 py-2 align-top">{row.enabled}</td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="warning" title={t("drillIn.forceStopTitle")}>
        {t.rich("drillIn.forceStopBody", { strong })}
      </Callout>

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

      <CopyableCode
        code={`${t("dataCollected.codeComment1")}
pvesh get /cluster/resources --type vm --output-format=json | jq

${t("dataCollected.codeComment2")}
qm config 100   ${t("dataCollected.codeComment3")}
pct config 100  ${t("dataCollected.codeComment4")}`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {whereNextItems.map((item, idx) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {t.rich(`whereNext.items.${idx}.tailRich`, { code })}
          </li>
        ))}
      </ul>
    </div>
  )
}
