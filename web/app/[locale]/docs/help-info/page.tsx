import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import {
  ArrowRight,
  Terminal,
  HardDrive,
  Network,
  Package,
  Cpu,
  Database,
  Archive,
  Wrench,
} from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.helpInfo.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox commands",
      "proxmox cli",
      "proxmox cheatsheet",
      "qm command",
      "pct command",
      "pveversion",
      "vzdump",
      "zpool",
      "proxmox reference",
      "proxmox commands list",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/help-info" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/help-info",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type Option = { icon: string; href: string; title: string; description: string }

const ICONS: Record<string, React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  Terminal,
  HardDrive,
  Network,
  Package,
  Cpu,
  Database,
  Archive,
  Wrench,
}

function OptionCard({ option }: { option: Option }) {
  const Icon = ICONS[option.icon] || Terminal
  return (
    <Link
      href={option.href}
      className="group flex items-start gap-3 rounded-md border border-gray-200 bg-white p-3 transition-colors hover:border-blue-400 hover:bg-blue-50"
    >
      <span className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md bg-gray-100 text-gray-600 group-hover:bg-blue-100 group-hover:text-blue-700">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-sm font-medium text-gray-900 group-hover:text-blue-700">
          {option.title}
          <ArrowRight className="h-3.5 w-3.5 text-gray-400 group-hover:text-blue-600 transition-transform group-hover:translate-x-0.5" />
        </div>
        <div className="mt-0.5 text-xs text-gray-600 leading-snug">{option.description}</div>
      </div>
    </Link>
  )
}

export default async function HelpAndInfoPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.helpInfo" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { helpInfo: { categories: { options: Option[] } } }
  }
  const options = messages.docs.helpInfo.categories.options

  const kbd = (chunks: React.ReactNode) => <kbd>{chunks}</kbd>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={2}
        scriptPath="help_info_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { kbd })}
      </p>

      <Image
        src="/help/help-info-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("categories.heading")}</h2>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {options.map((o) => (
          <OptionCard key={o.href} option={o} />
        ))}
      </div>

      <Callout variant="tip" title={t("tip.title")}>
        {t("tip.body")}
      </Callout>
    </div>
  )
}
