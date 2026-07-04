import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import Image from "next/image"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.creatingBackups.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox interactive backup",
      "proxmenux backup menu",
      "backup profile default custom",
      "hb_prepare_staging",
      "proxmenux backup wizard",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/backup-restore/creating-backups" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/backup-restore/creating-backups",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type EntryRow = { entry: string; path: string; detail: string }
type MatrixRow = { combo: string; destination: string; profile: string; action: string }
type StepRow = { step: string; name: string; detail: string }
type WritingRow = { topic: string; detail: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function CreatingBackupsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.creatingBackups" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { backupRestore: { creatingBackups: {
      entryPoints: { rows: EntryRow[] }
      matrix: { rows: MatrixRow[] }
      commonPipeline: { steps: StepRow[] }
      included: {
        globalItems: string[]
        rootItems: string[]
        proxmenuxItems: string[]
        notInProfileItems: string[]
      }
      writing: { rows: WritingRow[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const cb = messages.docs.backupRestore.creatingBackups
  const entryRows = cb.entryPoints.rows
  const matrixRows = cb.matrix.rows
  const pipelineSteps = cb.commonPipeline.steps
  const globalItems = cb.included.globalItems
  const rootItems = cb.included.rootItems
  const proxmenuxItems = cb.included.proxmenuxItems
  const notInProfileItems = cb.included.notInProfileItems
  const writingRows = cb.writing.rows
  const whereNextItems = cb.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={9}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, em, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("entryPoints.heading")}
      </h2>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Entry point</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Path</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {entryRows.map((row, idx) => (
              <tr key={row.entry} className={idx < entryRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.entry}</strong></td>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap">{row.path}</td>
                <td className="px-3 py-2 align-top">{t.rich(`entryPoints.rows.${idx}.detail`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("modes.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("modes.body", { code, strong })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        <Link href="/docs/backup-restore/scheduled-jobs" className="text-blue-600 hover:underline font-medium">
          {t("modes.seeAlso")}
        </Link>
      </p>

      <figure className="my-6">
        <a
          href="/images/docs/backup-restore/scheduled-backup-monitor.png"
          target="_blank"
          rel="noopener noreferrer"
          className="block cursor-zoom-in group"
          aria-label={t("modes.monitorAlt")}
        >
          <Image
            src="/images/docs/backup-restore/scheduled-backup-monitor.png"
            alt={t("modes.monitorAlt")}
            width={1400}
            height={700}
            className="rounded-lg border border-gray-200 shadow-sm w-full h-auto transition group-hover:shadow-md"
          />
        </a>
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("modes.monitorCaption")}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("matrix.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("matrix.intro")}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">#</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Destination</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Profile</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">What it does</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {matrixRows.map((row, idx) => (
              <tr key={row.combo} className={idx < matrixRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.combo}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap">{row.destination}</td>
                <td className="px-3 py-2 align-top whitespace-nowrap">{row.profile}</td>
                <td className="px-3 py-2 align-top">{t.rich(`matrix.rows.${idx}.action`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("profiles.heading")}
      </h2>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("profiles.defaultTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("profiles.defaultBody", { code, em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("profiles.customTitle")}
      </h3>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("profiles.customBody", { code, em })}
      </p>

      <figure className="my-6">
        <a
          href="/images/docs/backup-restore/custom-picker.png"
          target="_blank"
          rel="noopener noreferrer"
          className="block cursor-zoom-in group"
          aria-label={t("profiles.customPickerAlt")}
        >
          <Image
            src="/images/docs/backup-restore/custom-picker.png"
            alt={t("profiles.customPickerAlt")}
            width={1400}
            height={700}
            className="rounded-lg border border-gray-200 shadow-sm w-full h-auto transition group-hover:shadow-md"
          />
        </a>
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("profiles.customPickerCaption")}
        </figcaption>
      </figure>

      <figure className="my-6">
        <a
          href="/images/docs/backup-restore/manage-custom-paths.png"
          target="_blank"
          rel="noopener noreferrer"
          className="block cursor-zoom-in group"
          aria-label={t("profiles.manageCustomAlt")}
        >
          <Image
            src="/images/docs/backup-restore/manage-custom-paths.png"
            alt={t("profiles.manageCustomAlt")}
            width={1400}
            height={700}
            className="rounded-lg border border-gray-200 shadow-sm w-full h-auto transition group-hover:shadow-md"
          />
        </a>
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("profiles.manageCustomCaption")}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("commonPipeline.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("commonPipeline.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">#</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Step</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {pipelineSteps.map((row, idx) => (
              <tr key={row.step} className={idx < pipelineSteps.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.step}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.name}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`commonPipeline.steps.${idx}.detail`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("included.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("included.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t.rich("included.globalTitle", { code })}
      </h3>

      <ul className="mb-6 space-y-1">
        {globalItems.map((_, idx) => (
          <li key={idx} className="text-gray-800 leading-relaxed pl-1">
            <span className="text-gray-400 mr-2">•</span>
            {t.rich(`included.globalItems.${idx}`, { code })}
          </li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t.rich("included.rootTitle", { code })}
      </h3>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("included.rootBody", { code })}
      </p>

      <ul className="mb-6 space-y-1">
        {rootItems.map((_, idx) => (
          <li key={idx} className="text-gray-800 leading-relaxed pl-1">
            <span className="text-gray-400 mr-2">•</span>
            {t.rich(`included.rootItems.${idx}`, { code })}
          </li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t.rich("included.proxmenuxTitle", { code })}
      </h3>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("included.proxmenuxBody", { code })}
      </p>

      <ul className="mb-6 space-y-1">
        {proxmenuxItems.map((_, idx) => (
          <li key={idx} className="text-gray-800 leading-relaxed pl-1">
            <span className="text-gray-400 mr-2">•</span>
            {t.rich(`included.proxmenuxItems.${idx}`, { code })}
          </li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("included.notInProfileTitle")}
      </h3>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("included.notInProfileBody", { code })}
      </p>

      <ul className="mb-6 space-y-2">
        {notInProfileItems.map((_, idx) => (
          <li key={idx} className="text-gray-800 leading-relaxed pl-1">
            <span className="text-gray-400 mr-2">•</span>
            {t.rich(`included.notInProfileItems.${idx}`, { code, strong })}
          </li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("included.customPathsTitle")}
      </h3>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("included.customPathsBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("archiveStructure.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("archiveStructure.intro", { code })}
      </p>

      <pre className="bg-gray-50 border border-gray-200 rounded-md p-4 text-sm font-mono text-gray-800 overflow-x-auto whitespace-pre leading-relaxed mb-6">
{t("archiveStructure.tree")}
      </pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("confirmation.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("confirmation.body", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("writing.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("writing.intro")}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Topic</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {writingRows.map((row, idx) => (
              <tr key={row.topic} className={idx < writingRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.topic}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`writing.rows.${idx}.detail`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("finishedScreens.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t("finishedScreens.intro")}
      </p>

      <figure className="my-6">
        <a
          href="/images/docs/backup-restore/backup-finished-scripts.png"
          target="_blank"
          rel="noopener noreferrer"
          className="block cursor-zoom-in group"
          aria-label={t("finishedScreens.scriptsAlt")}
        >
          <Image
            src="/images/docs/backup-restore/backup-finished-scripts.png"
            alt={t("finishedScreens.scriptsAlt")}
            width={1400}
            height={700}
            className="rounded-lg border border-gray-200 shadow-sm w-full h-auto transition group-hover:shadow-md"
          />
        </a>
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("finishedScreens.scriptsCaption")}
        </figcaption>
      </figure>

      <figure className="my-6">
        <a
          href="/images/docs/backup-restore/backup-finished-monitor.png"
          target="_blank"
          rel="noopener noreferrer"
          className="block cursor-zoom-in group"
          aria-label={t("finishedScreens.monitorAlt")}
        >
          <Image
            src="/images/docs/backup-restore/backup-finished-monitor.png"
            alt={t("finishedScreens.monitorAlt")}
            width={1400}
            height={700}
            className="rounded-lg border border-gray-200 shadow-sm w-full h-auto transition group-hover:shadow-md"
          />
        </a>
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("finishedScreens.monitorCaption")}
        </figcaption>
      </figure>

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
