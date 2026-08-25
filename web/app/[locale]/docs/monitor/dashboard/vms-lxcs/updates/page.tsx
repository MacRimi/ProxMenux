import type { Metadata } from "next"
import type React from "react"
import { getMessages, getTranslations, setRequestLocale } from "next-intl/server"
import { ExternalLink } from "lucide-react"
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
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.vmsLxcsUpdates.meta" })
  return { title: t("title"), description: t("description") }
}

type MechanismRow = { source: string; action: string; notes: string }
type StatusRow = { state: string; appearance: string; meaning: string }
type ProblemRow = { problem: string; resolution: string }

function Figure({ src, alt, caption }: { src: string; alt: string; caption: string }) {
  return (
    <figure className="my-6">
      <img src={src} alt={alt} className="w-full rounded-lg border border-gray-200 shadow-sm" />
      <figcaption className="mt-2 text-center text-sm italic text-gray-500">{caption}</figcaption>
    </figure>
  )
}

export default async function UpdatesTabPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.vmsLxcsUpdates" })
  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { vmsLxcsUpdates: {
      overview: { items: string[] }
      mechanisms: { rows: MechanismRow[] }
      docker: { items: string[] }
      actions: { items: string[]; statusRows: StatusRow[] }
      custom: { items: string[] }
      bulk: { items: string[] }
      options: { items: string[] }
      scheduled: { items: string[] }
      completion: { items: string[] }
      troubleshooting: { rows: ProblemRow[] }
    } } } }
  }
  const v = messages.docs.monitor.dashboard.vmsLxcsUpdates

  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const code = (chunks: React.ReactNode) => <code className="rounded bg-gray-100 px-1 text-sm">{chunks}</code>
  const linkApp = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/vms-lxcs/app" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const linkHelper = (chunks: React.ReactNode) => (
    <a
      href="https://community-scripts.org/docs/tools/pve/update-apps"
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-blue-600 hover:underline"
    >
      {chunks}
      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
    </a>
  )

  const richList = (base: string, items: string[]) => (
    <ul className="mt-2 list-disc space-y-2 pl-6 text-gray-800">
      {items.map((_, idx) => (
        <li key={idx}>{t.rich(`${base}.${idx}`, { strong, em, code, link: linkApp, helper: linkHelper })}</li>
      ))}
    </ul>
  )

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <DocHeader title={t("header.title")} description={t("header.description")} estimatedMinutes={10} />

      <p className="mt-6 text-gray-800">{t.rich("intro.p1", { strong, em, code, link: linkApp })}</p>
      <p className="mt-4 text-gray-800">{t.rich("intro.p2", { strong, em, code })}</p>
      <Callout variant="info">{t.rich("intro.callout", { strong, em, code })}</Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("overview.heading")}</h2>
      <p className="text-gray-800">{t("overview.lead")}</p>
      {richList("overview.items", v.overview.items)}

      <Figure
        src="/monitor/vms-modal-updates-01.png"
        alt={t("figures.osPending.alt")}
        caption={t("figures.osPending.caption")}
      />

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("mechanisms.heading")}</h2>
      <p className="text-gray-800">{t.rich("mechanisms.lead", { strong, em, code, helper: linkHelper })}</p>
      <div className="my-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("mechanisms.colSource")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("mechanisms.colAction")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("mechanisms.colNotes")}</th>
            </tr>
          </thead>
          <tbody>
            {v.mechanisms.rows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-300 px-3 py-2 font-medium">{row.source}</td>
                <td className="border border-gray-300 px-3 py-2">{row.action}</td>
                <td className="border border-gray-300 px-3 py-2">{row.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Callout variant="warning">{t.rich("mechanisms.callout", { strong, em, code })}</Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("docker.heading")}</h2>
      <p className="text-gray-800">{t.rich("docker.lead", { strong, em, code })}</p>
      {richList("docker.items", v.docker.items)}
      <Callout variant="info">{t.rich("docker.callout", { strong, em, code })}</Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("actions.heading")}</h2>
      <p className="text-gray-800">{t("actions.lead")}</p>
      {richList("actions.items", v.actions.items)}
      <div className="my-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("actions.statusColState")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("actions.statusColAppearance")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("actions.statusColMeaning")}</th>
            </tr>
          </thead>
          <tbody>
            {v.actions.statusRows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-300 px-3 py-2 font-medium">{row.state}</td>
                <td className="border border-gray-300 px-3 py-2">{row.appearance}</td>
                <td className="border border-gray-300 px-3 py-2">{row.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("custom.heading")}</h2>
      <p className="text-gray-800">{t.rich("custom.lead", { strong, em, code })}</p>
      {richList("custom.items", v.custom.items)}
      <p className="mt-4 text-gray-800">{t("custom.exampleLead")}</p>
      <CopyableCode code={t("custom.example")} language="sh" />
      <Callout variant="warning">{t.rich("custom.callout", { strong, em, code })}</Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("bulk.heading")}</h2>
      <p className="text-gray-800">{t.rich("bulk.lead", { strong, em, code })}</p>
      {richList("bulk.items", v.bulk.items)}
      <Callout variant="info">{t.rich("bulk.callout", { strong, em, code })}</Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("options.heading")}</h2>
      <p className="text-gray-800">{t("options.lead")}</p>
      {richList("options.items", v.options.items)}
      <Figure
        src="/monitor/vms-modal-updates-06.png"
        alt={t("figures.options.alt")}
        caption={t("figures.options.caption")}
      />

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("scheduled.heading")}</h2>
      <p className="text-gray-800">{t.rich("scheduled.lead", { strong, em, code })}</p>
      {richList("scheduled.items", v.scheduled.items)}
      <Callout variant="tip">{t.rich("scheduled.callout", { strong, em, code })}</Callout>

      <h2 className="mt-10 mb-4 text-2xl font-semibold text-gray-900">{t("completion.heading")}</h2>
      <p className="text-gray-800">{t("completion.lead")}</p>
      {richList("completion.items", v.completion.items)}

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
