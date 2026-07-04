import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { AlertTriangle } from "lucide-react"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.crossKernel.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox cross-kernel restore",
      "bk_older bk_newer safe subset",
      "IOMMU VFIO hydration",
      "kernel-agnostic restore",
      "hb_unsafe_paths_cross_version",
      "HB_HYDRATION_APPLIED",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/backup-restore/cross-kernel" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/backup-restore/cross-kernel",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type DirectionRow = { direction: string; condition: string; behavior: string }
type CategoryRow = { category: string; paths: string; reason: string }
type PhaseRow = { phase: string; detail: string }
type ScenarioRow = { scenario: string; detail: string }
type CodeRefRow = { component: string; location: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function CrossKernelPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.crossKernel" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { backupRestore: { crossKernel: {
      directionCheck: { rows: DirectionRow[] }
      safeSubsetFilter: { categoryRows: CategoryRow[] }
      hydration: { phaseRows: PhaseRow[] }
      concreteExamples: { rows: ScenarioRow[] }
      codeReference: { rows: CodeRefRow[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const ck = messages.docs.backupRestore.crossKernel
  const directionRows = ck.directionCheck.rows
  const categoryRows = ck.safeSubsetFilter.categoryRows
  const phaseRows = ck.hydration.phaseRows
  const scenarioRows = ck.concreteExamples.rows
  const codeRefRows = ck.codeReference.rows
  const whereNextItems = ck.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={16}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, strong, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("directionCheck.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("directionCheck.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Direction</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Condition</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Behaviour</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {directionRows.map((row, idx) => (
              <tr key={row.direction} className={idx < directionRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.direction}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`directionCheck.rows.${idx}.condition`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`directionCheck.rows.${idx}.behavior`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("whyBkNewerIsSafe.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("whyBkNewerIsSafe.body", { code, em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("safeSubsetFilter.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("safeSubsetFilter.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Category</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Paths</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Why they are skipped</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {categoryRows.map((row, idx) => (
              <tr key={row.category} className={idx < categoryRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.category}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`safeSubsetFilter.categoryRows.${idx}.paths`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`safeSubsetFilter.categoryRows.${idx}.reason`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("safeSubsetFilter.outroBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("hydration.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("hydration.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Phase</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {phaseRows.map((row, idx) => (
              <tr key={row.phase} className={idx < phaseRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.phase}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`hydration.phaseRows.${idx}.detail`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("planCommit.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("planCommit.body", { code, em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("flowDiagram.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("flowDiagram.intro")}
      </p>

      <pre className="bg-gray-50 border border-gray-200 rounded-md p-4 text-xs sm:text-sm font-mono text-gray-800 overflow-x-auto whitespace-pre leading-relaxed mb-6">
        {t("flowDiagram.diagram")}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("concreteExamples.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("concreteExamples.intro")}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Scenario</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">What hydration does</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {scenarioRows.map((row, idx) => (
              <tr key={row.scenario} className={idx < scenarioRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.scenario}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`concreteExamples.rows.${idx}.detail`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="my-8 rounded-lg border border-amber-200 bg-amber-50 p-5">
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" aria-hidden="true" />
          <div>
            <h3 className="text-base font-semibold text-amber-900 mb-1">
              {t("callout.warningTitle")}
            </h3>
            <p className="text-sm text-amber-900/90 leading-relaxed">
              {t.rich("callout.warningBody", { code })}
            </p>
          </div>
        </div>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("codeReference.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("codeReference.intro")}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Component</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Location</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {codeRefRows.map((row, idx) => (
              <tr key={row.component} className={idx < codeRefRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.component}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`codeReference.rows.${idx}.location`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("whereNext.heading")}
      </h2>

      <ul className="mb-6 space-y-2">
        {whereNextItems.map((item) => (
          <li key={item.href} className="text-gray-800 leading-relaxed">
            <Link href={item.href} className="text-blue-600 hover:underline font-medium">
              {item.label}
            </Link>
            <span>{item.tail}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
