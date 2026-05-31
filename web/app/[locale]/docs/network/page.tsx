import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import {
  ArrowRight,
  Activity,
  LineChart,
  Wrench,
  ListChecks,
  Tag,
  Archive,
  ShieldCheck,
  ShieldAlert,
  Eye,
} from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.network.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox network management",
      "proxmox bridge configuration",
      "proxmox bond",
      "proxmox vlan",
      "proxmox network repair",
      "proxmox /etc/network/interfaces",
      "proxmox network diagnostics",
      "proxmox persistent interface names",
      "proxmox network backup",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/network" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/network",
    },
    twitter: {
      card: "summary",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type SectionOption = { title: string; description: string }

const READ_ONLY_CONFIG = [
  { Icon: Activity, href: "/docs/network/diagnostics" },
  { Icon: LineChart, href: "/docs/network/monitoring" },
]
const ANALYZE_CONFIG = [
  { Icon: Wrench, href: "/docs/network/bridge-analysis" },
  { Icon: ListChecks, href: "/docs/network/config-analysis" },
]
const APPLY_CONFIG = [
  { Icon: Tag, href: "/docs/network/persistent-names" },
  { Icon: Archive, href: "/docs/network/backup-restore" },
]

function OptionCard({
  title,
  description,
  Icon,
  href,
}: SectionOption & {
  Icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>
  href: string
}) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-3 rounded-md border border-gray-200 bg-white p-3 transition-colors hover:border-blue-400 hover:bg-blue-50"
    >
      <span className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md bg-gray-100 text-gray-600 group-hover:bg-blue-100 group-hover:text-blue-700">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-sm font-medium text-gray-900 group-hover:text-blue-700">
          {title}
          <ArrowRight className="h-3.5 w-3.5 text-gray-400 group-hover:text-blue-600 transition-transform group-hover:translate-x-0.5" />
        </div>
        <div className="mt-0.5 text-xs text-gray-600 leading-snug">{description}</div>
      </div>
    </Link>
  )
}

export default async function NetworkOverviewPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.network" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { network: {
      tiers: {
        readOnly: { items: string[] }
        analyze: { items: string[] }
        apply: { items: string[] }
      }
      readOnlySection: { options: SectionOption[] }
      analyzeSection: { options: SectionOption[] }
      applySection: { options: SectionOption[] }
    } }
  }
  const readOnlyTierItems = messages.docs.network.tiers.readOnly.items
  const analyzeTierItems = messages.docs.network.tiers.analyze.items
  const applyTierItems = messages.docs.network.tiers.apply.items
  const readOnlyOptions = messages.docs.network.readOnlySection.options
  const analyzeOptions = messages.docs.network.analyzeSection.options
  const applyOptions = messages.docs.network.applySection.options

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={5}
        scriptPath="menus/network_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("openingMenu.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("openingMenu.intro", { strong })}
      </p>

      <Image
        src="/network/network-menu.png"
        alt={t("openingMenu.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("safety.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("safety.body")}</p>

      <div className="grid gap-4 md:grid-cols-1 lg:grid-cols-3 mb-8 not-prose">
        <a
          href="#read-only"
          className="rounded-lg border-2 border-emerald-300 bg-emerald-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
              <Eye className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("tiers.readOnly.title")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t("tiers.readOnly.body")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {readOnlyTierItems.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </a>

        <a
          href="#analyze"
          className="rounded-lg border-2 border-amber-300 bg-amber-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-amber-100 text-amber-700">
              <ShieldAlert className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("tiers.analyze.title")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t("tiers.analyze.body")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {analyzeTierItems.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </a>

        <a
          href="#apply"
          className="rounded-lg border-2 border-red-300 bg-red-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-red-100 text-red-700">
              <ShieldCheck className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("tiers.apply.title")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t("tiers.apply.body")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {applyTierItems.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </a>
      </div>

      <Callout variant="warning" title={t("classicTitle")}>
        {t.rich("classicBody", { strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("backups.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("backups.intro", { code })}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`/var/backups/proxmenux/
├── interfaces_backup_2026-04-26_14-30-12
├── interfaces_backup_2026-04-26_15-08-44
└── interfaces_backup_2026-04-26_18-22-09`}</pre>
      <p className="mt-4 mb-4 text-gray-800 leading-relaxed">{t("backups.rollbackIntro")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`cp /var/backups/proxmenux/interfaces_backup_<TIMESTAMP> /etc/network/interfaces
systemctl restart networking`}</pre>

      <h2 id="read-only" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">
        {t("readOnlySection.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("readOnlySection.body", { code })}
      </p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {readOnlyOptions.map((o, idx) => (
          <OptionCard
            key={READ_ONLY_CONFIG[idx].href}
            title={o.title}
            description={o.description}
            Icon={READ_ONLY_CONFIG[idx].Icon}
            href={READ_ONLY_CONFIG[idx].href}
          />
        ))}
      </div>

      <h2 id="analyze" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">
        {t("analyzeSection.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("analyzeSection.body", { code, strong })}
      </p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {analyzeOptions.map((o, idx) => (
          <OptionCard
            key={ANALYZE_CONFIG[idx].href}
            title={o.title}
            description={o.description}
            Icon={ANALYZE_CONFIG[idx].Icon}
            href={ANALYZE_CONFIG[idx].href}
          />
        ))}
      </div>

      <h2 id="apply" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">
        {t("applySection.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("applySection.body", { em })}
      </p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {applyOptions.map((o, idx) => (
          <OptionCard
            key={APPLY_CONFIG[idx].href}
            title={o.title}
            description={o.description}
            Icon={APPLY_CONFIG[idx].Icon}
            href={APPLY_CONFIG[idx].href}
          />
        ))}
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("consoleTitle")}</h2>
      <Callout variant="danger" title={t("consoleSubTitle")}>
        {t("consoleBody")}
      </Callout>
    </div>
  )
}
