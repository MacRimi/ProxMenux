import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.settings.meta" })
  return { title: t("title"), description: t("description") }
}

type ColourRow = { colour: string; range: string; meaning: string }
type ThresholdRow = { section: string; warning: string; critical: string; gates: string }
type DataRow = { card: string; endpoint: string; source: string }
type WhereNextItem = { label: string; href: string; tail?: string; tailRich?: string }

export default async function SettingsTabPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.settings" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { settings: {
      health: { items: string[]; activeItems: string[] }
      thresholds: {
        whatForItems: string[]
        colourRows: ColourRow[]
        thresholdRows: ThresholdRow[]
      }
      lxcDetection: { whatRunsItems: string[] }
      storageExclusions: { items: string[] }
      interfaceExclusions: { items: string[] }
      notifications: { items: string[] }
      optimizations: { dotsItems: string[] }
      dataCollected: { rows: DataRow[] }
      whereNext: { items: WhereNextItem[] }
    } } } }
  }
  const s = messages.docs.monitor.dashboard.settings
  const healthItems = s.health.items
  const activeSuppressionItems = s.health.activeItems
  const whatForItems = s.thresholds.whatForItems
  const colourRows = s.thresholds.colourRows
  const thresholdRows = s.thresholds.thresholdRows
  const whatRunsItems = s.lxcDetection.whatRunsItems
  const storageItems = s.storageExclusions.items
  const interfaceItems = s.interfaceExclusions.items
  const notificationItems = s.notifications.items
  const dotsItems = s.optimizations.dotsItems
  const dataRows = s.dataCollected.rows
  const whereNextItems = s.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const green = () => <span className="inline-block w-2 h-2 rounded-full bg-green-500 align-middle mr-1" />
  const amber = () => <span className="inline-block w-2 h-2 rounded-full bg-amber-500 align-middle mr-1" />
  const healthLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/health-monitor#dismissing-alerts-and-the-suppression-duration" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const storageTabLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/storage" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const networkTabLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/network" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const notifLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/notifications" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const aiLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/ai-assistant" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const autoLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/automated" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const customLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/customizable" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const updatesLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/updates" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const uninstallLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/uninstall" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={9}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("networkUnits.heading")}</h2>

      <figure className="my-4">
        <Image
          src="/monitor/settings/network-units.png"
          alt={t("networkUnits.imageAlt")}
          width={2000}
          height={374}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("networkUnits.imageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("networkUnits.body", { strong })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("health.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("health.intro", { strong })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {healthItems.map((_, idx) => (
          <li key={idx}>{t.rich(`health.items.${idx}`, { strong })}</li>
        ))}
      </ul>

      <figure className="my-6">
        <Image
          src="/monitor/health-suppression-settings.png"
          alt={t("health.imageAlt")}
          width={2010}
          height={1816}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("health.imageCaption")}
        </figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("health.editTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("health.editBody", { strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("health.activeTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("health.activeIntro", { strong, em })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {activeSuppressionItems.map((_, idx) => (
          <li key={idx}>{t.rich(`health.activeItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("health.activeReenableTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("health.activeReenableBody", { strong, code })}
      </p>

      <Callout variant="info" title={t("health.activeAutoRefreshTitle")}>
        {t("health.activeAutoRefreshBody")}
      </Callout>

      <p className="mt-4 mb-4 text-gray-800 leading-relaxed">
        {t.rich("health.activePermanentNote", { strong, em, code })}
      </p>

      <Callout variant="info" title={t("health.calloutTitle")}>
        {t.rich("health.calloutBody", { link: healthLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("thresholds.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("thresholds.intro", { em, strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("thresholds.whatForTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("thresholds.whatForIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {whatForItems.map((_, idx) => (
          <li key={idx}>{t(`thresholds.whatForItems.${idx}`)}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("thresholds.whatForOutro", { strong, code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900" id="status-colours">{t("thresholds.coloursTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("thresholds.coloursIntro")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("thresholds.headerColour")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("thresholds.headerRange")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("thresholds.headerMeaning")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {colourRows.map((row, idx) => {
              // Color tier is identified positionally so the dot stays
              // correct in any locale (Spanish: Verde / Ámbar / Rojo).
              const dotClass = ["bg-green-500", "bg-amber-500", "bg-red-500"][idx] ?? "bg-red-500"
              return (
                <tr key={row.colour} className={idx < colourRows.length - 1 ? "border-b border-gray-100" : ""}>
                  <td className="px-3 py-2 align-top whitespace-nowrap">
                    <span className={`inline-block w-3 h-3 rounded-full ${dotClass} align-middle mr-2`} />
                    <strong>{row.colour}</strong>
                  </td>
                  <td className="px-3 py-2 align-top">{row.range}</td>
                  <td className="px-3 py-2 align-top">{row.meaning}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("thresholds.sectionsTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("thresholds.sectionsIntro", { em })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("thresholds.headerSection")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap bg-amber-100/60">{t("thresholds.headerWarning")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap bg-red-100/60">{t("thresholds.headerCritical")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("thresholds.headerGates")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {thresholdRows.map((row, idx) => (
              <tr key={row.section} className={idx < thresholdRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top"><strong>{row.section}</strong></td>
                <td className={`px-3 py-2 align-top font-mono whitespace-nowrap ${row.warning === "—" ? "text-gray-400" : ""} bg-amber-100/40`}>{row.warning}</td>
                <td className="px-3 py-2 align-top font-mono whitespace-nowrap bg-red-100/40">{row.critical}</td>
                <td className="px-3 py-2 align-top">{t.rich(`thresholds.thresholdRows.${idx}.gates`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("thresholds.defaultsTitle")}>
        {t.rich("thresholds.defaultsBody", { em, strong })}
      </Callout>

      <Callout variant="tip" title={t("thresholds.validationTitle")}>
        {t("thresholds.validationBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("lxcDetection.heading")}</h2>

      <figure className="my-4">
        <Image
          src="/monitor/settings/lxc-update-detection.png"
          alt={t("lxcDetection.imageAlt")}
          width={2000}
          height={620}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("lxcDetection.imageCaption", { code })}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("lxcDetection.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("lxcDetection.whatRunsTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("lxcDetection.whatRunsIntro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {whatRunsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`lxcDetection.whatRunsItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <Callout variant="info" title={t("lxcDetection.selfUpdateTitle")}>
        {t.rich("lxcDetection.selfUpdateBody", { code })}
      </Callout>

      <Callout variant="tip" title={t("lxcDetection.refreshTitle")}>
        {t.rich("lxcDetection.refreshBody", { code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("lxcDetection.toggleTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("lxcDetection.toggleBody", { code, strong })}
      </p>

      <Callout variant="warning" title={t("lxcDetection.purgeTitle")}>
        {t.rich("lxcDetection.purgeBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("storageExclusions.heading")}</h2>

      <figure className="my-4">
        <Image
          src="/monitor/settings/storage-exclusions.png"
          alt={t("storageExclusions.imageAlt")}
          width={2000}
          height={1120}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("storageExclusions.imageCaption", { em })}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("storageExclusions.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {storageItems.map((_, idx) => (
          <li key={idx}>{t.rich(`storageExclusions.items.${idx}`, { strong })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("storageExclusions.outro", { em, code, link: storageTabLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("interfaceExclusions.heading")}</h2>

      <figure className="my-4">
        <Image
          src="/monitor/settings/interface-exclusions.png"
          alt={t("interfaceExclusions.imageAlt")}
          width={2000}
          height={1142}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("interfaceExclusions.imageCaption", { em })}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("interfaceExclusions.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {interfaceItems.map((_, idx) => (
          <li key={idx}>{t.rich(`interfaceExclusions.items.${idx}`, { code })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("interfaceExclusions.outro", { code, em, link: networkTabLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("notifications.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("notifications.body1", { em })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("notifications.body2")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {notificationItems.map((_, idx) => (
          <li key={idx}>{t.rich(`notifications.items.${idx}`, { notifLink, aiLink })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("optimizations.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("optimizations.intro", { code, autoLink, customLink })}
      </p>

      <figure className="my-4">
        <Image
          src="/monitor/settings/proxmenux-optimizations.png"
          alt={t("optimizations.imageAlt")}
          width={2000}
          height={1146}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("optimizations.imageCaption", { em })}
        </figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("optimizations.dotsTitle")}</h3>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {dotsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`optimizations.dotsItems.${idx}`, { strong, em, green, amber })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("optimizations.clickTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("optimizations.clickBody", { code })}
      </p>

      <figure className="my-4">
        <Image
          src="/monitor/settings/optimization-detail.png"
          alt={t("optimizations.detailAlt")}
          width={2000}
          height={1040}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("optimizations.detailCaption", { em, code })}
        </figcaption>
      </figure>

      <Callout variant="info" title={t("optimizations.whyTitle")}>
        {t("optimizations.whyBody")}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("optimizations.updatesTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("optimizations.updatesBody", { strong, em })}
      </p>

      <figure className="my-4">
        <Image
          src="/monitor/settings/proxmenux-optimizations-update-banner.png"
          alt={t("optimizations.updatesAlt")}
          width={2000}
          height={1146}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("optimizations.updatesCaption", { link: updatesLink })}
        </figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("optimizations.revertTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("optimizations.revertBody", { code, link: uninstallLink })}
      </p>

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
                <td className="px-3 py-2 align-top">{t.rich(`dataCollected.rows.${idx}.source`, { code, notifLink, aiLink })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {whereNextItems.map((item, idx) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tailRich ? t.rich(`whereNext.items.${idx}.tailRich`, { customLink }) : item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
