import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { DataFlowDiagram } from "@/components/ui/data-flow-diagram"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox backup",
      "proxmox host backup",
      "proxmox restore",
      "proxmox backup server",
      "borg backup proxmox",
      "cross-kernel restore",
      "proxmox host restore",
      "vzdump alternative",
      "proxmenux backup",
      "proxmox migration",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/backup-restore" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/backup-restore",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type WhatItIsNotItem = string
type WhereNextItem = { label: string; href: string; tail: string }

export default async function BackupRestoreOverviewPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.backupRestore" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { backupRestore: {
      whatItIsNot: { items: WhatItIsNotItem[] }
      whereNext: { items: WhereNextItem[] }
    } }
  }
  const br = messages.docs.backupRestore
  const whatItIsNotItems = br.whatItIsNot.items
  const whereNextItems = br.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={8}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("whatItIsNot.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("whatItIsNot.intro", { strong })}
      </p>

      <ul className="mb-6 space-y-3">
        {whatItIsNotItems.map((_, idx) => (
          <li key={idx} className="text-gray-800 leading-relaxed pl-1">
            <span className="text-gray-400 mr-2">•</span>
            {t.rich(`whatItIsNot.items.${idx}`, { code, strong })}
          </li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("threePillars.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("threePillars.intro", { strong })}
      </p>

      <DataFlowDiagram
        nodes={[
          { variant: "source", label: t("threePillars.pillar1Label"), detail: t("threePillars.pillar1Detail") },
          { variant: "source", label: t("threePillars.pillar2Label"), detail: t("threePillars.pillar2Detail") },
          { variant: "source", label: t("threePillars.pillar3Label"), detail: t("threePillars.pillar3Detail") },
        ]}
        caption={t("threePillars.diagramCaption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("restoreIsUniversal.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("restoreIsUniversal.body", { strong })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("twoInterfaces.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("twoInterfaces.intro", { strong })}
      </p>

      <DataFlowDiagram
        nodes={[
          { variant: "bridge", label: t("twoInterfaces.cliLabel"), detail: t("twoInterfaces.cliDetail") },
          { variant: "bridge", label: t("twoInterfaces.webLabel"), detail: t("twoInterfaces.webDetail") },
        ]}
        bidirectional
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("whereNext.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("whereNext.intro", { em })}
      </p>

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
