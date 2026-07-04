import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Star, ExternalLink } from "lucide-react"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.destinations.pbs.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox backup server",
      "pbs encryption keyfile",
      "pbs recovery passphrase",
      "proxmox-backup-client",
      "pxar snapshot",
      "pbs chunk deduplication",
      "proxmenux pbs",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/backup-restore/destinations/pbs" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/backup-restore/destinations/pbs",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type SourceRow = { source: string; path: string; content: string }
type ReferenceItem = { label: string; href: string; tail: string }

export default async function PbsDestinationPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.destinations.pbs" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { backupRestore: { destinations: { pbs: {
      repoSelection: { sourceRows: SourceRow[] }
      references: { items: ReferenceItem[] }
    } } } }
  }
  const sourceRows = messages.docs.backupRestore.destinations.pbs.repoSelection.sourceRows
  const references = messages.docs.backupRestore.destinations.pbs.references.items

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

      <div className="mb-6 -mt-3">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-emerald-800">
          <Star className="h-3.5 w-3.5 fill-current" aria-hidden="true" />
          {t("recommendedBadge")}
        </span>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("aboutPbs.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("aboutPbs.body", { code })}
      </p>

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("repoSelection.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("repoSelection.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Source</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">On-disk state</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Content</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {sourceRows.map((row, idx) => (
              <tr key={row.source} className={idx < sourceRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.source}</strong></td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.path}</td>
                <td className="px-3 py-2 align-top">{t.rich(`repoSelection.sourceRows.${idx}.content`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("repoSelection.menuTitle")}
      </h3>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("repoSelection.menuBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("backupCommand.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("backupCommand.intro", { code })}
      </p>

      <CopyableCode code={t("backupCommand.cmd")} language="bash" />

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("backupCommand.backupIdTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("backupCommand.backupIdBody", { code, em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("backupCommand.pxarTitle")}
      </h3>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("backupCommand.pxarBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("encryption.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("encryption.intro", { code, strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("encryption.keyfileTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("encryption.keyfileBody", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("encryption.recoveryTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("encryption.recoveryBody", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("encryption.blobUploadTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("encryption.blobUploadBody1", { code })}
      </p>

      <figure className="my-6">
        <a
          href="/images/docs/backup-restore/pbs-paired-backup-groups.png"
          target="_blank"
          rel="noopener noreferrer"
          className="block cursor-zoom-in group"
          aria-label={t("encryption.blobUploadImageAlt")}
        >
          <Image
            src="/images/docs/backup-restore/pbs-paired-backup-groups.png"
            alt={t("encryption.blobUploadImageAlt")}
            width={1400}
            height={700}
            className="rounded-lg border border-gray-200 shadow-sm w-full h-auto transition group-hover:shadow-md"
          />
        </a>
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("encryption.blobUploadImageCaption")}
        </figcaption>
      </figure>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">
        {t("encryption.blobUploadConstraintTitle")}
      </h4>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("encryption.blobUploadConstraintBody", { code, strong, em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("encryption.recoverTitle")}
      </h3>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("encryption.recoverBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("restoreAccess.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("restoreAccess.body", { code })}
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
