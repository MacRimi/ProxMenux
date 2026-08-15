import type { Metadata } from "next"
import type React from "react"
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
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.vmsLxcsApp.meta" })
  return { title: t("title"), description: t("description") }
}

type TableRow = { method: string; when: string }
type BreakdownRow = { part: string; meaning: string }
type ExampleRow = { text: string; regex: string; result: string }

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
      whatYouGet: { items: string[] }
      registerSuggested: { steps: string[] }
      manual: { linksItems: string[] }
      multiple: { usefulItems: string[] }
      tracking: {
        ingredients: string[]
        methodsTable: { rows: TableRow[] }
        sourceItems: string[]
        regexTwoItems: string[]
        step2Items: string[]
        step2Breakdown: { rows: BreakdownRow[] }
        step3Examples: { rows: ExampleRow[] }
        step4Items: string[]
        step6CorrectItems: string[]
      }
      state: { items: string[] }
      manage: { items: string[] }
      options: { items: string[] }
      notDetected: { steps: string[] }
    } } } }
  }
  const v = messages.docs.monitor.dashboard.vmsLxcsApp
  const whatYouGetItems = v.whatYouGet.items
  const registerSteps = v.registerSuggested.steps
  const manualLinks = v.manual.linksItems
  const multipleUseful = v.multiple.usefulItems
  const ingredients = v.tracking.ingredients
  const methodsRows = v.tracking.methodsTable.rows
  const sourceItems = v.tracking.sourceItems
  const regexTwoItems = v.tracking.regexTwoItems
  const step2Items = v.tracking.step2Items
  const breakdownRows = v.tracking.step2Breakdown.rows
  const exampleRows = v.tracking.step3Examples.rows
  const step4Items = v.tracking.step4Items
  const step6CorrectItems = v.tracking.step6CorrectItems
  const stateItems = v.state.items
  const manageItems = v.manage.items
  const optionsItems = v.options.items
  const notDetectedSteps = v.notDetected.steps

  // Rich-text tag handlers
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const code = (chunks: React.ReactNode) => (
    <code className="text-sm bg-gray-100 px-1 rounded">{chunks}</code>
  )
  const linkUpdates = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/vms-lxcs/updates" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        estimatedMinutes={12}
      />

      <p className="text-gray-800 mt-6">{t.rich("intro.p1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t.rich("intro.p2", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t.rich("intro.p3", { strong, em, code, link: linkUpdates })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whatYouGet.heading")}</h2>
      <p className="text-gray-800">{t("whatYouGet.lead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {whatYouGetItems.map((_, idx) => (
          <li key={idx}>{t.rich(`whatYouGet.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t.rich("whatYouGet.trailing", { strong, em, code })}</p>
      <Callout variant="warning">{t.rich("whatYouGet.callout", { strong, em, code })}</Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("firstOpening.heading")}</h2>
      <p className="text-gray-800">{t.rich("firstOpening.p1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t.rich("firstOpening.p2", { strong, em, code })}</p>

      <Figure
        src="/monitor/vms-modal-app-01.png"
        alt={t("figures.f01.alt")}
        caption={t("figures.f01.caption")}
      />

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("registerSuggested.heading")}</h3>
      <ol className="list-decimal pl-6 space-y-1 text-gray-800">
        {registerSteps.map((_, idx) => (
          <li key={idx}>{t.rich(`registerSuggested.steps.${idx}`, { strong, em, code })}</li>
        ))}
      </ol>
      <p className="text-gray-800 mt-4">{t.rich("registerSuggested.trailing", { strong, em, code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("catalog.heading")}</h2>
      <p className="text-gray-800">{t.rich("catalog.p1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t.rich("catalog.p2", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t.rich("catalog.p3", { strong, em, code })}</p>

      <Figure
        src="/monitor/vms-modal-app-02.png"
        alt={t("figures.f02.alt")}
        caption={t("figures.f02.caption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="text-gray-800">{t.rich("manual.p1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t.rich("manual.p2", { strong, em, code })}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("manual.nameHeading")}</h3>
      <p className="text-gray-800">{t.rich("manual.nameBody", { strong, em, code })}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("manual.linksHeading")}</h3>
      <p className="text-gray-800">{t("manual.linksLead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {manualLinks.map((_, idx) => (
          <li key={idx}>{t.rich(`manual.linksItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t.rich("manual.linksTrailing", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t.rich("manual.linksConfirm", { strong, em, code })}</p>

      <Figure
        src="/monitor/vms-modal-app-03.png"
        alt={t("figures.f03.alt")}
        caption={t("figures.f03.caption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("multiple.heading")}</h2>
      <p className="text-gray-800">{t.rich("multiple.intro", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("multiple.usefulLead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {multipleUseful.map((_, idx) => (
          <li key={idx}>{t.rich(`multiple.usefulItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t.rich("multiple.dontGroup", { strong, em, code })}</p>

      <Figure
        src="/monitor/vms-modal-app-04.png"
        alt={t("figures.f04.alt")}
        caption={t("figures.f04.caption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("tracking.heading")}</h2>
      <p className="text-gray-800">{t("tracking.intro")}</p>
      <ol className="list-decimal pl-6 mt-2 space-y-1 text-gray-800">
        {ingredients.map((_, idx) => (
          <li key={idx}>{t.rich(`tracking.ingredients.${idx}`, { strong, em, code })}</li>
        ))}
      </ol>
      <p className="text-gray-800 mt-4">{t.rich("tracking.trailing", { strong, em, code })}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("tracking.methodsHeading")}</h3>
      <p className="text-gray-800">{t("tracking.methodsLead")}</p>
      <div className="overflow-x-auto my-4">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("tracking.methodsTable.colMethod")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("tracking.methodsTable.colWhen")}</th>
            </tr>
          </thead>
          <tbody>
            {methodsRows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-300 px-3 py-2 font-mono text-xs">{row.method}</td>
                <td className="border border-gray-300 px-3 py-2">{row.when}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-gray-800 mt-4">{t.rich("tracking.methodsTrailing", { strong, em, code })}</p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("tracking.commandHeading")}</h4>
      <p className="text-gray-800">{t.rich("tracking.commandP1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("tracking.commandP2")}</p>
      <CopyableCode code={t("tracking.commandExample1")} language="text" />
      <p className="text-gray-800 mt-4">{t("tracking.commandP3")}</p>
      <CopyableCode code={t("tracking.commandExample2")} language="text" />
      <p className="text-gray-800 mt-4">{t.rich("tracking.commandP4", { strong, em, code })}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("tracking.sourceHeading")}</h3>
      <p className="text-gray-800">{t("tracking.sourceLead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {sourceItems.map((_, idx) => (
          <li key={idx}>{t.rich(`tracking.sourceItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t.rich("tracking.sourceTrailing", { strong, em, code })}</p>

      <h3 className="text-lg font-semibold mt-8 mb-2 text-gray-900">{t("tracking.regexHeading")}</h3>
      <p className="text-gray-800">{t.rich("tracking.regexIntro", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t.rich("tracking.regexOptional", { strong, em, code })}</p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("tracking.regexTwoHeading")}</h4>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {regexTwoItems.map((_, idx) => (
          <li key={idx}>{t.rich(`tracking.regexTwoItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t.rich("tracking.regexTwoTrailing", { strong, em, code })}</p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("tracking.step1Heading")}</h4>
      <p className="text-gray-800">{t("tracking.step1P1")}</p>
      <p className="text-gray-800 mt-4">{t("tracking.step1P2")}</p>
      <p className="text-gray-800 mt-4">{t("tracking.step1P3")}</p>
      <CopyableCode code={t("tracking.step1Cmd")} language="sh" />
      <p className="text-gray-800 mt-4">{t("tracking.step1P4")}</p>
      <CopyableCode code={t("tracking.step1Output")} language="text" />
      <p className="text-gray-800 mt-4">{t("tracking.step1P5")}</p>
      <p className="text-gray-800 mt-4">{t("tracking.step1P6")}</p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("tracking.step2Heading")}</h4>
      <p className="text-gray-800">{t.rich("tracking.step2Lead", { strong, em, code })}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {step2Items.map((_, idx) => (
          <li key={idx}>{t.rich(`tracking.step2Items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t("tracking.step2Recommended")}</p>
      <CopyableCode code={t("tracking.step2Regex")} language="text" />
      <p className="text-gray-800 mt-4">{t("tracking.step2ReadLead")}</p>
      <div className="overflow-x-auto my-4">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("tracking.step2Breakdown.colPart")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("tracking.step2Breakdown.colMeaning")}</th>
            </tr>
          </thead>
          <tbody>
            {breakdownRows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-300 px-3 py-2 font-mono text-xs">{row.part}</td>
                <td className="border border-gray-300 px-3 py-2">{row.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-gray-800 mt-4">{t.rich("tracking.step2DotNote", { strong, em, code })}</p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("tracking.step3Heading")}</h4>
      <p className="text-gray-800">{t("tracking.step3Lead")}</p>
      <div className="overflow-x-auto my-4">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100">
              <th className="border border-gray-300 px-3 py-2 text-left">{t("tracking.step3Examples.colText")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("tracking.step3Examples.colRegex")}</th>
              <th className="border border-gray-300 px-3 py-2 text-left">{t("tracking.step3Examples.colResult")}</th>
            </tr>
          </thead>
          <tbody>
            {exampleRows.map((row, idx) => (
              <tr key={idx}>
                <td className="border border-gray-300 px-3 py-2 font-mono text-xs">{row.text}</td>
                <td className="border border-gray-300 px-3 py-2 font-mono text-xs">{row.regex}</td>
                <td className="border border-gray-300 px-3 py-2 font-mono text-xs">{row.result}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-gray-800 mt-4">{t.rich("tracking.step3Note1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t.rich("tracking.step3Note2", { strong, em, code })}</p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("tracking.step4Heading")}</h4>
      <p className="text-gray-800">{t("tracking.step4Intro")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {step4Items.map((_, idx) => (
          <li key={idx}>{t.rich(`tracking.step4Items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t.rich("tracking.step4Trailing", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4"><strong>{t("tracking.step4RecLabel")}</strong></p>
      <CopyableCode code={t.raw("tracking.step4RecRegex") as string} language="text" />
      <p className="text-gray-800 mt-4"><strong>{t("tracking.step4LessLabel")}</strong></p>
      <CopyableCode code={t("tracking.step4LessRegex")} language="text" />
      <p className="text-gray-800 mt-4">{t.rich("tracking.step4Note", { strong, em, code })}</p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("tracking.step5Heading")}</h4>
      <p className="text-gray-800">{t("tracking.step5Lead")}</p>
      <CopyableCode code={t("tracking.step5Regex")} language="text" />
      <p className="text-gray-800 mt-4">{t.rich("tracking.step5P1", { strong, em, code })}</p>
      <p className="text-gray-800 mt-4">{t("tracking.step5P2")}</p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("tracking.step6Heading")}</h4>
      <p className="text-gray-800">{t.rich("tracking.step6Lead", { strong, em, code })}</p>
      <CopyableCode code={t("tracking.step6Output")} language="text" />
      <p className="text-gray-800 mt-4">{t("tracking.step6CorrectLead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {step6CorrectItems.map((_, idx) => (
          <li key={idx}>{t.rich(`tracking.step6CorrectItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t.rich("tracking.step6ErrorNote", { strong, em, code })}</p>
      <Callout variant="tip">{t.rich("tracking.step6Callout", { strong, em, code })}</Callout>

      <Figure
        src="/monitor/vms-modal-app-05.png"
        alt={t("figures.f05.alt")}
        caption={t("figures.f05.caption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("state.heading")}</h2>

      <Figure
        src="/monitor/vms-modal-app-06.png"
        alt={t("figures.f06.alt")}
        caption={t("figures.f06.caption")}
      />

      <p className="text-gray-800">{t("state.lead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {stateItems.map((_, idx) => (
          <li key={idx}>{t.rich(`state.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t.rich("state.trailing", { strong, em, code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manage.heading")}</h2>
      <p className="text-gray-800">{t("manage.lead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {manageItems.map((_, idx) => (
          <li key={idx}>{t.rich(`manage.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t.rich("manage.trailing", { strong, em, code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("options.heading")}</h2>
      <p className="text-gray-800">{t("options.lead")}</p>
      <ul className="list-disc pl-6 mt-2 space-y-1 text-gray-800">
        {optionsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`options.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="text-gray-800 mt-4">{t.rich("options.trailing", { strong, em, code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("notDetected.heading")}</h2>
      <p className="text-gray-800">{t("notDetected.intro")}</p>
      <ol className="list-decimal pl-6 mt-2 space-y-1 text-gray-800">
        {notDetectedSteps.map((_, idx) => (
          <li key={idx}>{t.rich(`notDetected.steps.${idx}`, { strong, em, code, link: linkUpdates })}</li>
        ))}
      </ol>
      <p className="text-gray-800 mt-4">{t.rich("notDetected.trailing", { strong, em, code })}</p>

      <Figure
        src="/monitor/vms-modal-app-07.png"
        alt={t("figures.f07.alt")}
        caption={t("figures.f07.caption")}
      />
    </div>
  )
}
