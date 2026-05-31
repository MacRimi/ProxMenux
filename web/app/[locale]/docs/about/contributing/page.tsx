import type { Metadata } from "next"
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
  const t = await getTranslations({ locale, namespace: "docs.about.contributing.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmenux contributing",
      "proxmenux pull request",
      "proxmenux branch model",
      "proxmenux develop branch",
      "proxmenux script template",
      "proxmenux script header",
      "proxmox bash contribution",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/about/contributing" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/about/contributing",
    },
    twitter: {
      card: "summary",
      title: t("title"),
      description: "How to contribute scripts, dialogs and improvements to the ProxMenux project.",
    },
  }
}

type BranchingRow = { branch: string; purposeRich: string }
type PhaseRow = { phaseRich: string; purposeRich: string; screenRich: string }
type DialogRow = { toolRich: string; whenRich: string; effectRich: string }
type MsgRow = { function: string; whenRich: string; spinner: string }
type WhereNextItem =
  | { kind: "external"; url: string; label: string; tail: string }
  | { kind: "internal"; href: string; label: string; tail: string }

export default async function ContributingPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.about.contributing" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { about: { contributing: {
      branching: { rows: BranchingRow[] }
      scriptHeader: { bullets: string[] }
      twoPhase: { rows: PhaseRow[]; phase1Rules: string[] }
      dialogVsWhiptail: { rows: DialogRow[] }
      messageFunctions: { rows: MsgRow[] }
      dialogConventions: { bullets: string[] }
      translation: { bullets: string[] }
      variableStyle: { bullets: string[] }
      dosAndDonts: { doBullets: string[]; dontBullets: string[] }
      submitting: { steps: string[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const block = messages.docs.about.contributing
  const branchingRows = block.branching.rows
  const scriptHeaderBullets = block.scriptHeader.bullets
  const twoPhaseRows = block.twoPhase.rows
  const phase1Rules = block.twoPhase.phase1Rules
  const dialogRows = block.dialogVsWhiptail.rows
  const msgRows = block.messageFunctions.rows
  const dialogBullets = block.dialogConventions.bullets
  const translationBullets = block.translation.bullets
  const variableStyleBullets = block.variableStyle.bullets
  const doBullets = block.dosAndDonts.doBullets
  const dontBullets = block.dosAndDonts.dontBullets
  const submittingSteps = block.submitting.steps
  const whereNextItems = block.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const contributorsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/about/contributors" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const cocLink = (chunks: React.ReactNode) => (
    <Link href="/docs/about/code-of-conduct" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const licenseLink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/MacRimi/ProxMenux/blob/main/LICENSE"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const securityLink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/MacRimi/ProxMenux/blob/main/SECURITY.md"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={15}
      />

      <Callout variant="info" title={t("twoPagesCallout.title")}>
        {t.rich("twoPagesCallout.body", { contributorsLink, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("branching.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("branching.intro")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("branching.headerBranch")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("branching.headerPurpose")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {branchingRows.map((row, idx) => (
              <tr key={row.branch} className={idx < branchingRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong><code>{row.branch}</code></strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`branching.rows.${idx}.purposeRich`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("branching.calloutTitle")}>
        {t.rich("branching.calloutBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("workflow.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("workflow.intro")}</p>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        <li>
          {t.rich("workflow.step1Lead", { code, strong })}
          <CopyableCode code={t.raw("workflow.step1Code") as string} className="my-3" />
          {t.rich("workflow.step1Trail", { code })}
        </li>
        <li>
          {t.rich("workflow.step2Lead", { strong })}
          <CopyableCode code={t.raw("workflow.step2Code") as string} className="my-3" />
        </li>
        <li>{t.rich("workflow.step3", { code, strong })}</li>
        <li>{t.rich("workflow.step4", { code, strong })}</li>
        <li>{t.rich("workflow.step5", { code, strong })}</li>
      </ol>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("scriptHeader.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("scriptHeader.intro", { strong })}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        {scriptHeaderBullets.map((_, idx) => (
          <li key={idx}>{t.rich(`scriptHeader.bullets.${idx}`, { strong, em })}</li>
        ))}
      </ul>

      <Callout variant="info" title={t("scriptHeader.licenseCalloutTitle")}>
        {t.rich("scriptHeader.licenseCalloutBody", { strong, code, licenseLink })}
      </Callout>

      <CopyableCode code={t.raw("scriptHeader.templateCode") as string} className="my-4" />

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("scriptHeader.optionalNote", { code })}</p>

      <Callout variant="tip" title={t("scriptHeader.whyCalloutTitle")}>
        {t("scriptHeader.whyCalloutBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("structure.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("structure.intro")}</p>

      <CopyableCode code={t.raw("structure.treeCode") as string} className="my-4" />

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("structure.outro", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("twoPhase.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("twoPhase.intro", { strong })}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("twoPhase.headerPhase")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("twoPhase.headerPurpose")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("twoPhase.headerScreen")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {twoPhaseRows.map((_, idx) => (
              <tr key={idx} className={idx < twoPhaseRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">{t.rich(`twoPhase.rows.${idx}.phaseRich`, { strong })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`twoPhase.rows.${idx}.purposeRich`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`twoPhase.rows.${idx}.screenRich`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("twoPhase.principle", { strong })}</p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("twoPhase.phase1Heading")}</h3>

      <CopyableCode code={t.raw("twoPhase.phase1Code") as string} className="my-4" />

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("twoPhase.phase1RulesIntro", { strong })}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {phase1Rules.map((_, idx) => (
          <li key={idx}>{t.rich(`twoPhase.phase1Rules.${idx}`, { code })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("twoPhase.phase2Heading")}</h3>

      <CopyableCode code={t.raw("twoPhase.phase2Code") as string} className="my-4" />

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("twoPhase.phase2Rules", { strong, code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t.rich("dialogVsWhiptail.headingRich", { code })}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("dialogVsWhiptail.intro")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dialogVsWhiptail.headerTool")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dialogVsWhiptail.headerWhen")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dialogVsWhiptail.headerEffect")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {dialogRows.map((_, idx) => (
              <tr key={idx} className={idx < dialogRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">{t.rich(`dialogVsWhiptail.rows.${idx}.toolRich`, { strong, code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`dialogVsWhiptail.rows.${idx}.whenRich`, { strong, code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`dialogVsWhiptail.rows.${idx}.effectRich`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("dialogVsWhiptail.calloutTitle")}>
        {t.rich("dialogVsWhiptail.calloutBody", { code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("dialogVsWhiptail.rebootHeading")}</h3>

      <p className="mb-3 text-gray-800 leading-relaxed">{t.rich("dialogVsWhiptail.rebootIntro", { code })}</p>

      <CopyableCode code={t.raw("dialogVsWhiptail.rebootCode") as string} className="my-4" />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("messageFunctions.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("messageFunctions.intro", { code })}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("messageFunctions.headerFunction")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("messageFunctions.headerWhen")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("messageFunctions.headerSpinner")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {msgRows.map((row, idx) => (
              <tr key={idx} className={idx < msgRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.function}</td>
                <td className="px-3 py-2 align-top">{t.rich(`messageFunctions.rows.${idx}.whenRich`, { em })}</td>
                <td className="px-3 py-2 align-top">{row.spinner}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("dialogConventions.heading")}</h2>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {dialogBullets.map((_, idx) => (
          <li key={idx}>{t.rich(`dialogConventions.bullets.${idx}`, { code })}</li>
        ))}
      </ul>

      <p className="mb-3 text-gray-800 leading-relaxed">{t("dialogConventions.exampleIntro")}</p>

      <CopyableCode code={t.raw("dialogConventions.exampleCode") as string} className="my-4" />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("translation.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("translation.intro", { code })}</p>

      <CopyableCode code={t.raw("translation.code") as string} className="my-4" />

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {translationBullets.map((_, idx) => (
          <li key={idx}>{t.rich(`translation.bullets.${idx}`, { strong })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("variableStyle.heading")}</h2>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {variableStyleBullets.map((_, idx) => (
          <li key={idx}>{t.rich(`variableStyle.bullets.${idx}`, { code })}</li>
        ))}
      </ul>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("variableStyle.standardNamesIntro")}</p>

      <CopyableCode code={t.raw("variableStyle.standardNamesCode") as string} className="my-4" />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("variableStyle.redirectHeading")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("variableStyle.redirectIntro", { code })}</p>

      <p className="mb-3 text-gray-800 leading-relaxed">{t.rich("variableStyle.withoutRedirectIntro", { strong })}</p>

      <CopyableCode code={t.raw("variableStyle.withoutRedirectCode") as string} className="my-4" />

      <p className="mb-3 text-gray-800 leading-relaxed">{t.rich("variableStyle.withRedirectIntro", { strong })}</p>

      <CopyableCode code={t.raw("variableStyle.withRedirectCode") as string} className="my-4" />

      <p className="mb-4 text-gray-800 leading-relaxed">{t("variableStyle.twoPatternsIntro")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        <li>
          {t.rich("variableStyle.discardLead", { strong })}
          <CopyableCode code={t.raw("variableStyle.discardCode") as string} className="my-3" />
        </li>
        <li>
          {t.rich("variableStyle.logLead", { strong })}
          <CopyableCode code={t.raw("variableStyle.logCode") as string} className="my-3" />
        </li>
      </ul>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("variableStyle.referenceOutro", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("dosAndDonts.heading")}</h2>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900 text-green-700">{t("dosAndDonts.doHeading")}</h3>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {doBullets.map((_, idx) => (
          <li key={idx}>{t.rich(`dosAndDonts.doBullets.${idx}`, { code })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900 text-red-700">{t("dosAndDonts.dontHeading")}</h3>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {dontBullets.map((_, idx) => (
          <li key={idx}>{t.rich(`dosAndDonts.dontBullets.${idx}`, { code })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("submitting.heading")}</h2>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-2">
        {submittingSteps.map((_, idx) => (
          <li key={idx}>{t.rich(`submitting.steps.${idx}`, { code, em, strong, cocLink })}</li>
        ))}
      </ol>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("submitting.securityOutro", { securityLink })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {whereNextItems.map((item, idx) => (
          <li key={idx}>
            {item.kind === "external" ? (
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline inline-flex items-center gap-1"
              >
                {item.label}
                <ExternalLink className="w-3 h-3" />
              </a>
            ) : (
              <Link href={item.href} className="text-blue-600 hover:underline">
                {item.label}
              </Link>
            )}
            {item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
