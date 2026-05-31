import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { CommandTable, type CommandGroup } from "@/components/ui/command-table"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.helpInfo.updateCommands.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox apt update",
      "proxmox apt upgrade",
      "pveupgrade",
      "proxmox dist-upgrade",
      "dpkg proxmox",
      "proxmox repository",
      "proxmox package commands",
      "apt pveversion",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/help-info/update-commands" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/help-info/update-commands",
    },
    twitter: {
      card: "summary",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type RelatedItem = { href: string; label: string; tail?: string }

export default async function UpdateCommandsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.helpInfo.updateCommands" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { helpInfo: { updateCommands: {
      commandGroups: CommandGroup[]
      related: { items: RelatedItem[] }
    } } }
  }
  const commandGroups = messages.docs.helpInfo.updateCommands.commandGroups
  const relatedItems = messages.docs.helpInfo.updateCommands.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const upgradeLink = (chunks: React.ReactNode) => (
    <Link href="/docs/utils/upgrade-pve8-pve9" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={3}
        scriptPath="help_info_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <CommandTable groups={commandGroups} />

      <Callout variant="warning" title={t("backupWarn.title")}>
        {t.rich("backupWarn.bodyRich", { code, strong, upgradeLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
