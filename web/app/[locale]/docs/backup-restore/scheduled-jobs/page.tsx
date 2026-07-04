import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Info } from "lucide-react"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.scheduledJobs.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox scheduled backup",
      "proxmenux backup job",
      "systemd timer backup",
      "vzdump attach hook",
      "keep-last keep-daily",
      "backup retention proxmox",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/backup-restore/scheduled-jobs" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/backup-restore/scheduled-jobs",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type ModeRow = { mode: string; backends: string; schedule: string; retention: string }
type StepRow = { step: string; detail: string }
type LayoutRow = { path: string; content: string }
type MgmtRow = { action: string; detail: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function ScheduledJobsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.scheduledJobs" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { backupRestore: { scheduledJobs: {
      intro: { modelsList: string[] }
      modes: { rows: ModeRow[] }
      attachDetail: { steps: StepRow[] }
      storageLayout: { rows: LayoutRow[] }
      runner: { steps: string[] }
      management: { rows: MgmtRow[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const sj = messages.docs.backupRestore.scheduledJobs
  const modelsList = sj.intro.modelsList
  const modeRows = sj.modes.rows
  const attachSteps = sj.attachDetail.steps
  const layoutRows = sj.storageLayout.rows
  const runnerSteps = sj.runner.steps
  const mgmtRows = sj.management.rows
  const whereNextItems = sj.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={11}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("intro.title")}
      </h2>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t("intro.body")}
      </p>

      <ul className="mb-6 space-y-3">
        {modelsList.map((_, idx) => (
          <li key={idx} className="text-gray-800 leading-relaxed pl-1">
            <span className="text-gray-400 mr-2">•</span>
            {t.rich(`intro.modelsList.${idx}`, { code, strong })}
          </li>
        ))}
      </ul>

      <div className="my-8 rounded-lg border border-blue-200 bg-blue-50 p-5">
        <div className="flex items-start gap-3">
          <Info className="h-5 w-5 text-blue-600 shrink-0 mt-0.5" aria-hidden="true" />
          <div>
            <h3 className="text-base font-semibold text-blue-900 mb-1">
              {t("attachBadge.title")}
            </h3>
            <p className="text-sm text-blue-900/90 leading-relaxed">
              {t.rich("attachBadge.body", { code, strong })}
            </p>
          </div>
        </div>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("modes.heading")}
      </h2>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Mode</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Backends</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Schedule</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Retention</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {modeRows.map((row, idx) => (
              <tr key={row.mode} className={idx < modeRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.mode}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap text-xs">{row.backends}</td>
                <td className="px-3 py-2 align-top">{t.rich(`modes.rows.${idx}.schedule`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`modes.rows.${idx}.retention`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("attachDetail.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("attachDetail.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">#</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {attachSteps.map((row, idx) => (
              <tr key={row.step} className={idx < attachSteps.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.step}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`attachDetail.steps.${idx}.detail`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("attachDetail.outroBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("storageLayout.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("storageLayout.intro")}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Path</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Content</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {layoutRows.map((row, idx) => (
              <tr key={row.path} className={idx < layoutRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.path}</td>
                <td className="px-3 py-2 align-top">{t.rich(`storageLayout.rows.${idx}.content`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t.rich("runner.heading", { code })}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("runner.intro")}
      </p>

      <ol className="mb-6 space-y-3 list-decimal pl-6">
        {runnerSteps.map((_, idx) => (
          <li key={idx} className="text-gray-800 leading-relaxed">
            {t.rich(`runner.steps.${idx}`, { code, strong })}
          </li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("management.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("management.intro")}
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
            {mgmtRows.map((row, idx) => (
              <tr key={row.action} className={idx < mgmtRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.action}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`management.rows.${idx}.detail`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("notifications.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("notifications.body", { code })}
      </p>

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
