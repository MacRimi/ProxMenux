import type { Metadata } from "next"
import type React from "react"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.vmsLxcsUpdates.meta" })
  return { title: t("title"), description: t("description") }
}

type DecisionRow = { situation: string; action: string }
type DifferenceRow = { field: string; location: string; role: string }

function Figure({ src, alt, caption }: { src: string; alt: string; caption: string }) {
  return (
    <figure className="my-6">
      <img
        src={src}
        alt={alt}
        className="rounded-lg border border-gray-200 shadow-sm w-full"
      />
      <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
        {caption}
      </figcaption>
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
      decision: { table: { rows: DecisionRow[] } }
      figureOut: {
        step3Items: string[]
        step4Items: string[]
      }
      requirements: { items: string[] }
      difference: { table: { rows: DifferenceRow[] } }
      apply: {
        steps: string[]
        systemItems: string[]
        appItems: string[]
      }
      scheduled: { createSteps: string[] }
    } } } }
  }
  const v = messages.docs.monitor.dashboard.vmsLxcsUpdates
  const decisionRows = v.decision.table.rows
  const step3Items = v.figureOut.step3Items
  const step4Items = v.figureOut.step4Items
  const reqItems = v.requirements.items
  const diffRows = v.difference.table.rows
  const applySteps = v.apply.steps
  const applySystem = v.apply.systemItems
  const applyApp = v.apply.appItems
  const schedSteps = v.scheduled.createSteps

  // Rich-text tag handlers
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const code = (chunks: React.ReactNode) => (
    <code className="text-sm bg-gray-100 px-1 rounded">{chunks}</code>
  )
  const linkApp = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/vms-lxcs/app" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const linkHelperHome = (chunks: React.ReactNode) => (
    <a
      href="https://community-scripts.org"
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-blue-600 hover:underline"
    >
      {chunks}
      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
    </a>
  )
  const linkHelperDocs = (chunks: React.ReactNode) => (
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

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        estimatedMinutes={12}
      />

      <p className="text-gray-800 mt-6">{t.rich("intro.p1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t.rich("intro.p2", { strong, em, code, link: linkApp })}</p>
      <Callout variant="info">{t.rich("intro.callout", { strong, em, code })}</Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("mechanisms.heading")}</h2>
      <p className="text-gray-800">{t("mechanisms.intro")}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("mechanisms.osHeading")}</h3>
      <p className="text-gray-800">{t("mechanisms.osP1")}</p>
      <p className="text-gray-800 mt-4">{t.rich("mechanisms.osP2", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("mechanisms.osP3")}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("mechanisms.helperHeading")}</h3>
      <p className="text-gray-800">{t.rich("mechanisms.helperP1", { strong, em, code, linkHelperHome })}</p>
      <p className="text-gray-800 mt-4">{t.rich("mechanisms.helperP2", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">
        {t.rich("mechanisms.helperP3", { strong, em, code, linkHelperHome, linkHelperDocs })}
      </p>
      <p className="text-gray-800 mt-4">{t.rich("mechanisms.helperP4", { strong, em, code })}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("mechanisms.customHeading")}</h3>
      <p className="text-gray-800">{t.rich("mechanisms.customP1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("mechanisms.customP2")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("decision.heading")}</h2>
      <div className="overflow-x-auto my-4">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("decision.table.colSituation")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("decision.table.colAction")}</th>
            </tr>
          </thead>
          <tbody>
            {decisionRows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-300 px-3 py-2">{row.situation}</td>
                <td className="border border-gray-300 px-3 py-2 font-mono text-xs">{row.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-gray-800 mt-4">{t("decision.trailing")}</p>

      <Figure
        src="/monitor/vms-modal-updates-01.png"
        alt={t("figures.f01.alt")}
        caption={t("figures.f01.caption")}
      />
      <Figure
        src="/monitor/vms-modal-updates-02.png"
        alt={t("figures.f02.alt")}
        caption={t("figures.f02.caption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("custom.heading")}</h2>
      <p className="text-gray-800">{t.rich("custom.p1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("custom.p2")}</p>

      <Figure
        src="/monitor/vms-modal-updates-03.png"
        alt={t("figures.f03.alt")}
        caption={t("figures.f03.caption")}
      />
      <Figure
        src="/monitor/vms-modal-updates-04.png"
        alt={t("figures.f04.alt")}
        caption={t("figures.f04.caption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("figureOut.heading")}</h2>
      <p className="text-gray-800">{t("figureOut.intro")}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("figureOut.step1Heading")}</h3>
      <p className="text-gray-800">{t.rich("figureOut.step1P1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("figureOut.step1P2")}</p>
      <CopyableCode code={t("figureOut.step1Cmd1")} language="sh" />
      <p className="text-gray-800 mt-4">{t("figureOut.step1P3")}</p>
      <CopyableCode code={t("figureOut.step1Cmd2")} language="sh" />
      <p className="text-gray-800 mt-4">{t.rich("figureOut.step1P4", { strong, em, code })}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("figureOut.step2Heading")}</h3>
      <p className="text-gray-800">{t.rich("figureOut.step2P1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("figureOut.step2P2")}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("figureOut.step3Heading")}</h3>
      <p className="text-gray-800">{t("figureOut.step3Lead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {step3Items.map((_, idx) => (
          <li key={idx}>{t.rich(`figureOut.step3Items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t("figureOut.step3P1")}</p>
      <CopyableCode code={t("figureOut.step3Cmd")} language="sh" />
      <p className="text-gray-800 mt-4">{t.rich("figureOut.step3P2", { strong, em, code })}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("figureOut.step4Heading")}</h3>
      <p className="text-gray-800">{t("figureOut.step4Lead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {step4Items.map((_, idx) => (
          <li key={idx}>{t.rich(`figureOut.step4Items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t("figureOut.step4Note")}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("figureOut.step5Heading")}</h3>
      <p className="text-gray-800">{t("figureOut.step5P1")}</p>
      <CopyableCode code={t.raw("figureOut.step5Cmd1") as string} language="text" />
      <p className="text-gray-800 mt-4">{t.rich("figureOut.step5P2", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("figureOut.step5P3")}</p>
      <CopyableCode code={t("figureOut.step5Cmd2")} language="sh" />
      <p className="text-gray-800 mt-4">{t("figureOut.step5P4")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("requirements.heading")}</h2>
      <p className="text-gray-800">{t("requirements.lead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {reqItems.map((_, idx) => (
          <li key={idx}>{t.rich(`requirements.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t.rich("requirements.trailing", { strong, em, code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("difference.heading")}</h2>
      <p className="text-gray-800">{t("difference.lead")}</p>
      <div className="overflow-x-auto my-4">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("difference.table.colField")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("difference.table.colLocation")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("difference.table.colRole")}</th>
            </tr>
          </thead>
          <tbody>
            {diffRows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-300 px-3 py-2 font-medium">{row.field}</td>
                <td className="border border-gray-300 px-3 py-2 text-xs">{row.location}</td>
                <td className="border border-gray-300 px-3 py-2 text-xs">{row.role}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-gray-800 mt-4">{t.rich("difference.trailing", { strong, em, code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("apply.heading")}</h2>
      <p className="text-gray-800">{t("apply.lead")}</p>
      <ol className="list-decimal pl-6 mt-2 space-y-1 text-gray-800">
        {applySteps.map((_, idx) => (
          <li key={idx}>{t.rich(`apply.steps.${idx}`, { strong, em, code })}</li>
        ))}
      </ol>
      <p className="text-gray-800 mt-4">{t("apply.trailing1")}</p>
      <p className="text-gray-800 mt-4">{t("apply.systemLead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {applySystem.map((_, idx) => (
          <li key={idx}>{t.rich(`apply.systemItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t("apply.appLead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {applyApp.map((_, idx) => (
          <li key={idx}>{t.rich(`apply.appItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t("apply.trailing2")}</p>

      <Figure
        src="/monitor/vms-modal-updates-05.png"
        alt={t("figures.f05.alt")}
        caption={t("figures.f05.caption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("backup.heading")}</h2>
      <p className="text-gray-800">{t.rich("backup.p1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("backup.p2")}</p>
      <p className="text-gray-800 mt-4">{t("backup.p3")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("restart.heading")}</h2>
      <p className="text-gray-800">{t.rich("restart.p1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("restart.p2")}</p>
      <p className="text-gray-800 mt-4">{t("restart.p3")}</p>

      <Figure
        src="/monitor/vms-modal-updates-06.png"
        alt={t("figures.f06.alt")}
        caption={t("figures.f06.caption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("scheduled.heading")}</h2>
      <p className="text-gray-800">{t.rich("scheduled.p1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("scheduled.createLead")}</p>
      <ol className="list-decimal pl-6 mt-2 space-y-1 text-gray-800">
        {schedSteps.map((_, idx) => (
          <li key={idx}>{t.rich(`scheduled.createSteps.${idx}`, { strong, em, code })}</li>
        ))}
      </ol>
      <p className="text-gray-800 mt-4">{t("scheduled.p2")}</p>
      <p className="text-gray-800 mt-4">{t("scheduled.p3")}</p>
      <Callout variant="tip">{t("scheduled.callout")}</Callout>

      <Figure
        src="/monitor/vms-modal-updates-07.png"
        alt={t("figures.f07.alt")}
        caption={t("figures.f07.caption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verify.heading")}</h2>
      <p className="text-gray-800">{t("verify.p1")}</p>
      <p className="text-gray-800 mt-4">{t.rich("verify.p2", { strong, em, code, link: linkApp })}</p>
      <p className="text-gray-800 mt-4">{t("verify.p3")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("troubleshoot.noButtonHeading")}</h3>
      <Callout variant="troubleshoot">{t.rich("troubleshoot.noButtonBody", { strong, em, code })}</Callout>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("troubleshoot.aptHeading")}</h3>
      <Callout variant="troubleshoot">{t.rich("troubleshoot.aptBody", { strong, em, code })}</Callout>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("troubleshoot.noUpdaterHeading")}</h3>
      <Callout variant="troubleshoot">{t.rich("troubleshoot.noUpdaterBody", { strong, em, code })}</Callout>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("troubleshoot.helperDetectedHeading")}</h3>
      <Callout variant="troubleshoot">{t.rich("troubleshoot.helperDetectedBody", { strong, em, code })}</Callout>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("troubleshoot.customFailsHeading")}</h3>
      <Callout variant="troubleshoot">{t.rich("troubleshoot.customFailsBody", { strong, em, code })}</Callout>
    </div>
  )
}
