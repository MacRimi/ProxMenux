import type { Metadata } from "next"
import type React from "react"
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"
import { DocHeader } from "@/components/ui/doc-header"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.vmsLxcsApp.meta" })
  return { title: t("title"), description: t("description") }
}

type DetectorRow = { method: string; use: string }
type StateRow = { state: string; display: string; meaning: string }
type ProblemRow = { problem: string; resolution: string }

function Figure({ src, alt, caption }: { src: string; alt: string; caption: string }) {
  return (
    <figure className="my-6">
      <img src={src} alt={alt} className="w-full rounded-lg border border-gray-200 shadow-sm" />
      <figcaption className="mt-2 text-center text-sm italic text-gray-500">{caption}</figcaption>
    </figure>
  )
}

export default async function AppTabPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.vmsLxcsApp" })
  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { vmsLxcsApp: {
      overview: { items: string[] }
      discovery: { items: string[] }
      registration: { steps: string[] }
      catalog: { items: string[] }
      docker: { items: string[] }
      webLinks: { items: string[] }
      tracking: { detectorRows: DetectorRow[]; sources: string[]; regexRules: string[] }
      updater: { items: string[] }
      states: { rows: StateRow[] }
      management: { items: string[] }
      troubleshooting: { rows: ProblemRow[] }
    } } } }
  }
  const v = messages.docs.monitor.dashboard.vmsLxcsApp

  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const code = (chunks: React.ReactNode) => <code className="rounded bg-gray-100 px-1 text-sm">{chunks}</code>
  const linkUpdates = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/vms-lxcs/updates" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const richList = (base: string, items: string[]) => (
    <ul className="mt-2 list-disc space-y-2 pl-6 text-gray-800">
      {items.map((_, idx) => (
        <li key={idx}>{t.rich(`${base}.${idx}`, { strong, em, code, link: linkUpdates })}</li>
      ))}
    </ul>
  )

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <DocHeader title={t("header.title")} description={t("header.description")} estimatedMinutes={11} />

      <p className="mt-6 text-gray-800">{t.rich("intro.p1", { strong, em, code })}</p>
      <p className="mt-4 text-gray-800">{t.rich("intro.p2", { strong, em, code, link: linkUpdates })}</p>
      <Callout variant="info">{t.rich("intro.callout", { strong, em, code })}</Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("overview.heading")}</h2>
      <p className="text-gray-800">{t("overview.lead")}</p>
      {richList("overview.items", v.overview.items)}

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("discovery.heading")}</h2>
      <p className="text-gray-800">{t.rich("discovery.lead", { strong, em, code })}</p>
      {richList("discovery.items", v.discovery.items)}
      <Callout variant="tip">{t.rich("discovery.callout", { strong, em, code })}</Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("registration.heading")}</h2>
      <p className="text-gray-800">{t("registration.lead")}</p>
      <ol className="mt-2 list-decimal space-y-2 pl-6 text-gray-800">
        {v.registration.steps.map((_, idx) => (
          <li key={idx}>{t.rich(`registration.steps.${idx}`, { strong, em, code })}</li>
        ))}
      </ol>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("catalog.heading")}</h2>
      <p className="text-gray-800">{t.rich("catalog.lead", { strong, em, code })}</p>
      {richList("catalog.items", v.catalog.items)}
      <Figure
        src="/monitor/vms-modal-app-02.png"
        alt={t("figures.catalog.alt")}
        caption={t("figures.catalog.caption")}
      />

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("docker.heading")}</h2>
      <p className="text-gray-800">{t.rich("docker.lead", { strong, em, code })}</p>
      {richList("docker.items", v.docker.items)}
      <Callout variant="info">{t.rich("docker.callout", { strong, em, code })}</Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("webLinks.heading")}</h2>
      <p className="text-gray-800">{t("webLinks.lead")}</p>
      {richList("webLinks.items", v.webLinks.items)}
      <Figure
        src="/monitor/vms-modal-app-03.png"
        alt={t("figures.webLinks.alt")}
        caption={t("figures.webLinks.caption")}
      />

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("tracking.heading")}</h2>
      <p className="text-gray-800">{t.rich("tracking.lead", { strong, em, code })}</p>
      <div className="my-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("tracking.colMethod")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("tracking.colUse")}</th>
            </tr>
          </thead>
          <tbody>
            {v.tracking.detectorRows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-300 px-3 py-2 font-mono text-xs">{row.method}</td>
                <td className="border border-gray-300 px-3 py-2">{row.use}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="mt-8 mb-2 text-lg font-semibold text-gray-900">{t("tracking.sourcesHeading")}</h3>
      {richList("tracking.sources", v.tracking.sources)}

      <h3 className="mt-8 mb-2 text-lg font-semibold text-gray-900">{t("tracking.regexHeading")}</h3>
      <p className="text-gray-800">{t.rich("tracking.regexLead", { strong, em, code })}</p>
      {richList("tracking.regexRules", v.tracking.regexRules)}
      <p className="mt-4 text-gray-800">{t("tracking.regexExampleLead")}</p>
      <CopyableCode code={t.raw("tracking.regexExample") as string} language="text" />
      <Callout variant="warning">{t.rich("tracking.regexCallout", { strong, em, code })}</Callout>

      <Figure
        src="/monitor/vms-modal-app-05.png"
        alt={t("figures.tracking.alt")}
        caption={t("figures.tracking.caption")}
      />

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("updater.heading")}</h2>
      <p className="text-gray-800">{t.rich("updater.lead", { strong, em, code, link: linkUpdates })}</p>
      {richList("updater.items", v.updater.items)}

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("states.heading")}</h2>
      <div className="my-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("states.colState")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("states.colDisplay")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("states.colMeaning")}</th>
            </tr>
          </thead>
          <tbody>
            {v.states.rows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-300 px-3 py-2 font-medium">{row.state}</td>
                <td className="border border-gray-300 px-3 py-2">{row.display}</td>
                <td className="border border-gray-300 px-3 py-2">{row.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Figure
        src="/monitor/vms-modal-app-06.png"
        alt={t("figures.card.alt")}
        caption={t("figures.card.caption")}
      />

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("management.heading")}</h2>
      <p className="text-gray-800">{t("management.lead")}</p>
      {richList("management.items", v.management.items)}

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("troubleshooting.heading")}</h2>
      <div className="my-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("troubleshooting.colProblem")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("troubleshooting.colResolution")}</th>
            </tr>
          </thead>
          <tbody>
            {v.troubleshooting.rows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-300 px-3 py-2 font-medium">{row.problem}</td>
                <td className="border border-gray-300 px-3 py-2">{row.resolution}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
