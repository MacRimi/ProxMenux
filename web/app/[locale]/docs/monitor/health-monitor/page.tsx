import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { DataFlowDiagram } from "@/components/ui/data-flow-diagram"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.healthMonitor.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox health monitor",
      "proxmox health check",
      "proxmox smart monitoring",
      "proxmox zfs monitoring",
      "proxmox alerts",
      "proxmox proactive monitoring",
      "proxmox disk monitoring",
      "proxmox memory monitor",
      "proxmox cpu monitor",
      "proxmenux health monitor",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/monitor/health-monitor" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/monitor/health-monitor",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type CategoryRow = { category: string; checks: string; events: string }
type SeverityRow = { status: string; colour: string; meaning: string; notification: string }
type DismissRow = { finding: string; why: string }
type AutoresolveRow = { trigger: string; action: string }
type ObservationsRow = { property: string; errors: string; obs: string }
type RestRow = { endpoint: string; method: string; use: string }
type WhereNextItem = { label: string; href: string; tail?: string; tailRich?: string }

export default async function HealthMonitorPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.healthMonitor" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { healthMonitor: {
      categories: { rows: CategoryRow[] }
      severity: { rows: SeverityRow[] }
      dashboardView: { items: string[] }
      dismiss: { rows: DismissRow[] }
      autoresolve: { rows: AutoresolveRow[] }
      observations: { rows: ObservationsRow[] }
      notification: { items: string[] }
      rest: { rows: RestRow[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const hm = messages.docs.monitor.healthMonitor
  const categoryRows = hm.categories.rows
  const severityRows = hm.severity.rows
  const dashboardItems = hm.dashboardView.items
  const dismissRows = hm.dismiss.rows
  const autoresolveRows = hm.autoresolve.rows
  const observationsRows = hm.observations.rows
  const notificationItems = hm.notification.items
  const restRows = hm.rest.rows
  const whereNextItems = hm.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const notifLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/notifications" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const aiLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/ai-assistant" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={18}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howItWorks.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("howItWorks.intro", { strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("howItWorks.scannerTitle")}</h3>

      <DataFlowDiagram
        nodes={[
          { variant: "source", label: t("howItWorks.scannerNodes.samplerLabel"), detail: t("howItWorks.scannerNodes.samplerDetail") },
          { variant: "bridge", label: t("howItWorks.scannerNodes.cycleLabel"), detail: t("howItWorks.scannerNodes.cycleDetail") },
          { variant: "bridge", label: t("howItWorks.scannerNodes.checksLabel"), detail: t("howItWorks.scannerNodes.checksDetail") },
          { variant: "target", label: t("howItWorks.scannerNodes.sqliteLabel"), detail: t("howItWorks.scannerNodes.sqliteDetail") },
        ]}
        arrowLabel={t("howItWorks.scannerArrowLabel")}
        caption={t("howItWorks.scannerCaption")}
      />

      <h3 className="text-lg font-semibold mt-8 mb-3 text-gray-900">{t("howItWorks.notifTitle")}</h3>

      <DataFlowDiagram
        nodes={[
          { variant: "source", label: t("howItWorks.notifNodes.errorsLabel"), detail: t("howItWorks.notifNodes.errorsDetail") },
          { variant: "bridge", label: t("howItWorks.notifNodes.dispatcherLabel"), detail: t("howItWorks.notifNodes.dispatcherDetail") },
          { variant: "bridge", label: t("howItWorks.notifNodes.templatesLabel"), detail: t("howItWorks.notifNodes.templatesDetail") },
          { variant: "target", label: t("howItWorks.notifNodes.channelsLabel"), detail: t("howItWorks.notifNodes.channelsDetail") },
        ]}
        arrowLabel={t("howItWorks.notifArrowLabel")}
        caption={t("howItWorks.notifCaption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("categories.heading")}</h2>

      <figure className="my-6">
        <Image
          src="/monitor/health-monitor.png"
          alt={t("categories.imageAlt")}
          width={1608}
          height={1752}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto mx-auto max-w-2xl"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("categories.imageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("categories.intro", { strong })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("categories.headerCategory")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("categories.headerChecks")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("categories.headerEvents")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {categoryRows.map((row, idx) => (
              <tr key={row.category} className={idx < categoryRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.category}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`categories.rows.${idx}.checks`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`categories.rows.${idx}.events`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("severity.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("severity.headerStatus")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("severity.headerColour")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("severity.headerMeaning")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("severity.headerNotification")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {severityRows.map((row, idx) => (
              <tr key={row.status} className={idx < severityRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.status}</strong></td>
                <td className="px-3 py-2 align-top">{row.colour}</td>
                <td className="px-3 py-2 align-top">{t.rich(`severity.rows.${idx}.meaning`, { em })}</td>
                <td className="px-3 py-2 align-top">{row.notification}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("severity.infoNote", { strong })}
      </p>

      <Callout variant="info" title={t("severity.unknownTitle")}>
        {t.rich("severity.unknownBody", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("dashboardView.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("dashboardView.intro", { strong })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {dashboardItems.map((_, idx) => (
          <li key={idx}>{t.rich(`dashboardView.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <Callout variant="tip" title={t("dashboardView.pillTitle")}>
        {t("dashboardView.pillBody")}
      </Callout>

      <h2 id="dismissing-alerts-and-the-suppression-duration" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">{t("dismiss.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("dismiss.intro", { em })}
      </p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        <li>{t.rich("dismiss.step1", { strong, code })}</li>
        <li>
          {t.rich("dismiss.step2", { strong, code })}
          <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{`24 hours       (default)
72 hours
168 hours      (one week)
720 hours      (one month)
8760 hours     (one year)
-1             (permanent — never re-fires)
<custom>       (any positive integer of hours)`}</pre>
        </li>
      </ol>

      <figure className="my-6">
        <Image
          src="/monitor/dismiss-duration-dropdown.png"
          alt={t("dismiss.dropdownImageAlt")}
          width={1540}
          height={1072}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("dismiss.dropdownImageCaption", { em })}
        </figcaption>
      </figure>

      <figure className="my-6">
        <Image
          src="/monitor/health-suppression-settings.png"
          alt={t("dismiss.imageAlt")}
          width={2010}
          height={1816}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("dismiss.imageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("dismiss.outro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("dismiss.activeSuppressionsTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("dismiss.activeSuppressionsBody", { strong, em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("dismiss.autoTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("dismiss.autoBody", { strong })}
      </p>

      <Callout variant="warning" title={t("dismiss.tempTitle")}>
        {t.rich("dismiss.tempBody", { strong })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("dismiss.nonDismissableTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("dismiss.nonDismissableBody")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dismiss.headerFinding")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dismiss.headerWhy")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {dismissRows.map((row, idx) => (
              <tr key={row.finding} className={idx < dismissRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.finding}</strong></td>
                <td className="px-3 py-2 align-top">{row.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("dismiss.principle")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("autoresolve.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("autoresolve.intro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("autoresolve.headerTrigger")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("autoresolve.headerAction")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {autoresolveRows.map((row, idx) => (
              <tr key={idx} className={idx < autoresolveRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top">{t.rich(`autoresolve.rows.${idx}.trigger`, { code })}</td>
                <td className="px-3 py-2 align-top">{row.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Callout variant="tip" title={t("autoresolve.permanentTitle")}>
        {t.rich("autoresolve.permanentBody", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("observations.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("observations.intro", { code, strong })}
      </p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("observations.headerProperty")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t.rich("observations.headerErrors", { code })}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t.rich("observations.headerObs", { code })}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {observationsRows.map((row, idx) => (
              <tr key={row.property} className={idx < observationsRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.property}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`observations.rows.${idx}.errors`, { em, code, strong })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`observations.rows.${idx}.obs`, { em, code, strong })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("observations.outro")}</p>

      <Callout variant="warning" title={t("observations.renameTitle")}>
        {t.rich("observations.renameBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("notification.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("notification.intro")}</p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {notificationItems.map((_, idx) => (
          <li key={idx}>{t.rich(`notification.items.${idx}`, { strong, code })}</li>
        ))}
      </ol>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("notification.outro", { notifLink, aiLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("rest.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("rest.intro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("rest.headerEndpoint")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("rest.headerMethod")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("rest.headerUse")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {restRows.map((row, idx) => (
              <tr key={row.endpoint} className={idx < restRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.endpoint}</td>
                <td className="px-3 py-2 align-top">{row.method}</td>
                <td className="px-3 py-2 align-top">{t.rich(`rest.rows.${idx}.use`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CopyableCode
        code={`${t("rest.codeComment1")}
curl -H "Authorization: Bearer <api-token>" \\
  http://<host>:8008/api/health/full | jq '.health.overall'

${t("rest.codeComment2")}
curl -X POST http://<host>:8008/api/health/acknowledge \\
  -H "Authorization: Bearer <api-token>" \\
  -H "Content-Type: application/json" \\
  -d '{"error_key":"smart_sdh"}'

${t("rest.codeComment3")}
curl -X POST http://<host>:8008/api/health/settings \\
  -H "Authorization: Bearer <api-token>" \\
  -H "Content-Type: application/json" \\
  -d '{"suppress_disks":"168"}'`}
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
