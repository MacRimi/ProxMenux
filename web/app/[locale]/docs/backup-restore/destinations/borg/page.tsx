import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
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
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.destinations.borg.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "borg backup proxmox",
      "borg repository",
      "borg ssh",
      "borg repokey",
      "borg serve restrict-to-path",
      "borg-linux64",
      "borgbackup deduplication",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/backup-restore/destinations/borg" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/backup-restore/destinations/borg",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type PriorityRow = { priority: string; source: string; detail: string }
type RepoTypeRow = { type: string; url: string; detail: string }
type StrategyRow = { mode: string; label: string; detail: string }
type FileRow = { file: string; content: string }
type EnvRow = { var: string; value: string; purpose: string }
type ReferenceItem = { label: string; href: string; tail: string }
type RequirementRow = { requirement: string; detail: string }

export default async function BorgDestinationPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.destinations.borg" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { backupRestore: { destinations: { borg: {
      binarySourcing: { rows: PriorityRow[] }
      repoTypes: { rows: RepoTypeRow[] }
      serverSetup: { hostChoicesItems: string[]; requirementsRows: RequirementRow[] }
      sshAuth: { strategyRows: StrategyRow[] }
      savedTargets: { rows: FileRow[] }
      runtimeEnv: { rows: EnvRow[] }
      references: { items: ReferenceItem[] }
    } } } }
  }
  const borg = messages.docs.backupRestore.destinations.borg
  const binaryRows = borg.binarySourcing.rows
  const repoTypeRows = borg.repoTypes.rows
  const hostChoicesItems = borg.serverSetup.hostChoicesItems
  const requirementsRows = borg.serverSetup.requirementsRows
  const strategyRows = borg.sshAuth.strategyRows
  const savedTargetRows = borg.savedTargets.rows
  const envRows = borg.runtimeEnv.rows
  const references = borg.references.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={13}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("aboutBorg.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("aboutBorg.body", { code })}
      </p>

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("binarySourcing.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("binarySourcing.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">#</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Source</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {binaryRows.map((row, idx) => (
              <tr key={row.priority} className={idx < binaryRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.priority}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap">{t.rich(`binarySourcing.rows.${idx}.source`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`binarySourcing.rows.${idx}.detail`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("repoTypes.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("repoTypes.intro")}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Type</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Repository URL</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {repoTypeRows.map((row, idx) => (
              <tr key={row.type} className={idx < repoTypeRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.type}</strong></td>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap">{row.url}</td>
                <td className="px-3 py-2 align-top">{t.rich(`repoTypes.rows.${idx}.detail`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("serverSetup.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("serverSetup.intro", { code, em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("serverSetup.hostChoicesTitle")}
      </h3>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t("serverSetup.hostChoicesBody")}
      </p>

      <ul className="mb-4 space-y-2">
        {hostChoicesItems.map((_, idx) => (
          <li key={idx} className="text-gray-800 leading-relaxed pl-1">
            <span className="text-gray-400 mr-2">•</span>
            {t.rich(`serverSetup.hostChoicesItems.${idx}`, { code, em })}
          </li>
        ))}
      </ul>

      <Callout variant="warning" title={t("serverSetup.lxcWarningTitle")}>
        {t("serverSetup.lxcWarningBody")}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("serverSetup.requirementsTitle")}
      </h3>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Requirement</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Detail</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {requirementsRows.map((row, idx) => (
              <tr key={idx} className={idx < requirementsRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top">{t.rich(`serverSetup.requirementsRows.${idx}.requirement`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`serverSetup.requirementsRows.${idx}.detail`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("serverSetup.minimalSetupTitle")}
      </h3>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t("serverSetup.minimalSetupBody")}
      </p>

      <CopyableCode code={t("serverSetup.minimalSetupCmd")} language="bash" />

      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">
        {t.rich("serverSetup.minimalSetupNote", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("sshAuth.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sshAuth.intro", { code, strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("sshAuth.strategiesTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("sshAuth.strategiesIntro")}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Mode</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Best for</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">What it does</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {strategyRows.map((row, idx) => (
              <tr key={row.mode} className={idx < strategyRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.mode}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap">{row.label}</td>
                <td className="px-3 py-2 align-top">{t.rich(`sshAuth.strategyRows.${idx}.detail`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("sshAuth.restrictTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sshAuth.restrictBody", { code })}
      </p>

      <CopyableCode code={t("sshAuth.restrictLine")} language="text" />

      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">
        {t.rich("sshAuth.restrictNote", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("savedTargets.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("savedTargets.intro")}
      </p>

      <div className="overflow-x-auto mb-4">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">File</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Content</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {savedTargetRows.map((row, idx) => (
              <tr key={row.file} className={idx < savedTargetRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.file}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`savedTargets.rows.${idx}.content`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t("savedTargets.outro")}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("encryption.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("encryption.body", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("runtimeEnv.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("runtimeEnv.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Variable</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Value</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Purpose</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {envRows.map((row, idx) => (
              <tr key={row.var} className={idx < envRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.var}</strong></td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.value}</td>
                <td className="px-3 py-2 align-top">{t.rich(`runtimeEnv.rows.${idx}.purpose`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("archiveFormat.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("archiveFormat.intro")}
      </p>

      <CopyableCode code={t("archiveFormat.namePattern")} language="text" />

      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">
        {t.rich("archiveFormat.retentionBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("restoreAccess.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("restoreAccess.body", { code, em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("references.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("references.intro")}
      </p>

      <ul className="mb-6 space-y-2">
        {references.map((item) => (
          <li key={item.href} className="text-gray-800 leading-relaxed">
            <a
              href={item.href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline font-medium inline-flex items-center gap-1"
            >
              {item.label}
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </a>
            <span>{item.tail}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
