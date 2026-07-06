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
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.restoring.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox restore",
      "proxmenux restore",
      "hb_compat_check",
      "apply_pending_restore",
      "apply_cluster_postboot",
      "path classification hot reboot dangerous",
      "destructive rollback",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/backup-restore/restoring" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/backup-restore/restoring",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type ActionRow = { action: string; detail: string }
type OutputRow = { output: string; detail: string }
type ModeRow = { mode: string; detail: string }
type ClassRow = { class: string; detail: string }
type FileRow = { file: string; content: string }
type TaskRow = { task: string; detail: string }
type TimeRow = { stage: string; time: string; detail: string }
type LogRow = { log: string; detail: string }
type FieldRow = { name: string; detail: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function RestoringPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.restoring" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { backupRestore: { restoring: {
      threeActions: { actionRows: ActionRow[] }
      compatibilityCheck: { outputRows: OutputRow[] }
      twoModes: { modeRows: ModeRow[] }
      pathClassification: { rows: ClassRow[] }
      pendingMachinery: { rows: FileRow[] }
      postbootDispatcher: { tasks: TaskRow[] }
      liveProgress: { fields: FieldRow[] }
      tenMinutes: { rows: TimeRow[] }
      logs: { rows: LogRow[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const rs = messages.docs.backupRestore.restoring
  const actionRows = rs.threeActions.actionRows
  const outputRows = rs.compatibilityCheck.outputRows
  const modeRows = rs.twoModes.modeRows
  const classRows = rs.pathClassification.rows
  const pendingRows = rs.pendingMachinery.rows
  const postbootTasks = rs.postbootDispatcher.tasks
  const liveFields = rs.liveProgress.fields
  const timeRows = rs.tenMinutes.rows
  const logRows = rs.logs.rows
  const whereNextItems = rs.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  const asciiDiagram = (text: string, caption: string) => (
    <figure className="my-6">
      <pre className="bg-gray-50 border border-gray-200 rounded-md p-4 text-xs sm:text-sm font-mono text-gray-800 overflow-x-auto whitespace-pre leading-relaxed">
        {text}
      </pre>
      {caption && (
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {caption}
        </figcaption>
      )}
    </figure>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={22}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("threeActions.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t("threeActions.intro")}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Action</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {actionRows.map((row, idx) => (
              <tr key={row.action} className={idx < actionRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.action}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`threeActions.actionRows.${idx}.detail`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("compatibilityCheck.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("compatibilityCheck.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Output</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">What it drives</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {outputRows.map((row, idx) => (
              <tr key={row.output} className={idx < outputRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.output}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`compatibilityCheck.outputRows.${idx}.detail`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("compatibilityCheck.reportBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("twoModes.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("twoModes.intro", { em })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Mode</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {modeRows.map((row, idx) => (
              <tr key={row.mode} className={idx < modeRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.mode}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`twoModes.modeRows.${idx}.detail`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("pathClassification.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pathClassification.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Class</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Behaviour</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {classRows.map((row, idx) => (
              <tr key={row.class} className={idx < classRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs"><strong>{row.class}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`pathClassification.rows.${idx}.detail`, { code, em, strong })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("fullFlow.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("fullFlow.intro")}
      </p>

      {asciiDiagram(t("fullFlow.diagram"), "")}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("pendingMachinery.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pendingMachinery.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">File</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Content</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {pendingRows.map((row, idx) => (
              <tr key={row.file} className={idx < pendingRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs"><strong>{row.file}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`pendingMachinery.rows.${idx}.content`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("pendingMachinery.unitBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("postbootDispatcher.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("postbootDispatcher.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Task</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {postbootTasks.map((row, idx) => (
              <tr key={row.task} className={idx < postbootTasks.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.task}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`postbootDispatcher.tasks.${idx}.detail`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("postbootExample.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("postbootExample.body", { code })}
      </p>

      <figure className="my-6">
        <a
          href="/images/docs/backup-restore/postboot-completion-console.png"
          target="_blank"
          rel="noopener noreferrer"
          className="block cursor-zoom-in group"
          aria-label={t("postbootExample.imageAlt")}
        >
          <Image
            src="/images/docs/backup-restore/postboot-completion-console.png"
            alt={t("postbootExample.imageAlt")}
            width={1600}
            height={800}
            className="rounded-lg border border-gray-200 shadow-sm w-full h-auto transition group-hover:shadow-md"
          />
        </a>
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("postbootExample.imageCaption")}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("liveProgress.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("liveProgress.body", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Card element</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {liveFields.map((row, idx) => (
              <tr key={row.name} className={idx < liveFields.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.name}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`liveProgress.fields.${idx}.detail`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("liveProgress.dismissBody", { code, em })}
      </p>

      {/* Two states of the Details modal side-by-side: the running run
          first (badge blue, current step, time remaining), then the
          completed run (badge green, filled bar, total duration).
          File names are historical — `-details.png` was captured while
          the run was in progress and `-card.png` after it finished. */}
      <figure className="my-6">
        <a
          href="/images/docs/backup-restore/monitor-restore-progress-details.png"
          target="_blank"
          rel="noopener noreferrer"
          className="block cursor-zoom-in group"
          aria-label={t("liveProgress.imageAlt")}
        >
          <Image
            src="/images/docs/backup-restore/monitor-restore-progress-details.png"
            alt={t("liveProgress.imageAlt")}
            width={1600}
            height={1200}
            className="rounded-lg border border-gray-200 shadow-sm w-full h-auto transition group-hover:shadow-md"
          />
        </a>
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("liveProgress.imageCaption")}
        </figcaption>
      </figure>

      <figure className="my-6">
        <a
          href="/images/docs/backup-restore/monitor-restore-progress-card.png"
          target="_blank"
          rel="noopener noreferrer"
          className="block cursor-zoom-in group"
          aria-label={t("liveProgress.detailsImageAlt")}
        >
          <Image
            src="/images/docs/backup-restore/monitor-restore-progress-card.png"
            alt={t("liveProgress.detailsImageAlt")}
            width={1600}
            height={1200}
            className="rounded-lg border border-gray-200 shadow-sm w-full h-auto transition group-hover:shadow-md"
          />
        </a>
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("liveProgress.detailsImageCaption")}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("tenMinutes.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("tenMinutes.intro")}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Stage</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Time</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {timeRows.map((row, idx) => (
              <tr key={row.stage} className={idx < timeRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top"><strong>{row.stage}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.time}</td>
                <td className="px-3 py-2 align-top">{t.rich(`tenMinutes.rows.${idx}.detail`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("tenMinutes.outroBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("destructiveRollback.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("destructiveRollback.body", { code, em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("logs.heading")}
      </h2>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Log path</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Content</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {logRows.map((row, idx) => (
              <tr key={row.log} className={idx < logRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.log}</td>
                <td className="px-3 py-2 align-top">{t.rich(`logs.rows.${idx}.detail`, { code })}</td>
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
