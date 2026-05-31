import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import {
  ArrowRight,
  Server,
  Cpu,
  HardDrive,
  Network,
  Shield,
  Activity,
  Wrench,
  Boxes,
  BookOpen,
  Bell,
  Sparkles,
  Terminal,
  Code2,
  Plug,
  ExternalLink,
} from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.introduction.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmenux",
      "proxmox menu script",
      "proxmox management tool",
      "proxmox tui",
      "proxmox cli",
      "proxmox dashboard",
      "proxmox open source",
      "proxmox automation",
      "proxmox helper script",
      "proxmox post install",
      "proxmox community tool",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/introduction" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/introduction",
      siteName: "ProxMenux",
      images: [
        {
          url: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public/main.png",
          width: 1363,
          height: 735,
          alt: "ProxMenux — Menu-Driven Tool for Proxmox VE",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
      images: [
        "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public/main.png",
      ],
    },
  }
}

const iconMap: Record<string, React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  Server,
  Cpu,
  HardDrive,
  Network,
  Shield,
  Activity,
  Wrench,
  Boxes,
  BookOpen,
  Bell,
  Sparkles,
  Terminal,
  Code2,
  Plug,
}

type FeatureItem = {
  title: string
  description: string
  icon: string
  href: string
}

type InstallRow = { pathRich: string; bundles: string; when: string }

type NextItem = {
  lead: string
  linkHref: string
  linkLabel: string
  tail?: string
  tailRich?: string
}

function FeatureCard({
  title,
  description,
  Icon,
  href,
}: {
  title: string
  description: string
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

export default async function IntroductionPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.introduction" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: {
      introduction: {
        twoProducts: { layers: string[] }
        scriptsSection: { items: FeatureItem[] }
        monitorSection: { items: FeatureItem[] }
        installPaths: { rows: InstallRow[] }
        next: { items: NextItem[] }
      }
    }
  }
  const block = messages.docs.introduction
  const layers = block.twoProducts.layers
  const scriptItems = block.scriptsSection.items
  const monitorItems = block.monitorSection.items
  const installRows = block.installPaths.rows
  const nextItems = block.next.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const github = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/MacRimi/ProxMenux"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const monitorOverviewLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const installationLink = (chunks: React.ReactNode) => (
    <Link href="/docs/installation" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={5}
      />

      <div className="my-6 not-prose flex flex-col items-center gap-4 rounded-lg border border-gray-200 bg-gradient-to-br from-blue-50 to-white p-6 sm:flex-row sm:items-start">
        <Image
          src="https://macrimi.github.io/ProxMenux/logo.png"
          alt="ProxMenux Logo"
          width={96}
          height={96}
          className="flex-shrink-0"
        />
        <div className="text-center sm:text-left">
          <p className="text-base text-gray-800 leading-relaxed mb-3">
            {t.rich("hero.tagline", { strong })}
          </p>
          <p className="text-sm text-gray-700 m-0">
            {t.rich("hero.audience", { em, github })}
          </p>
        </div>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("twoProducts.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("twoProducts.intro")}</p>

      <div className="grid gap-4 md:grid-cols-2 mb-6 not-prose">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center gap-2 mb-2">
            <Terminal className="h-5 w-5 text-blue-600" aria-hidden />
            <h3 className="text-base font-semibold text-gray-900 m-0">{t("twoProducts.scripts.title")}</h3>
          </div>
          <p className="text-sm text-gray-700 leading-relaxed m-0">
            {t.rich("twoProducts.scripts.body", { code })}
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="h-5 w-5 text-blue-600" aria-hidden />
            <h3 className="text-base font-semibold text-gray-900 m-0">{t("twoProducts.monitor.title")}</h3>
          </div>
          <p className="text-sm text-gray-700 leading-relaxed m-0">
            {t("twoProducts.monitor.body")}
          </p>
        </div>
      </div>

      <Callout variant="info" title={t("twoProducts.calloutTitle")}>
        {t("twoProducts.calloutIntro")}
        <ul className="list-disc pl-6 mt-2 mb-0 space-y-1">
          {layers.map((_, idx) => (
            <li key={idx}>{t.rich(`twoProducts.layers.${idx}`, { strong })}</li>
          ))}
        </ul>
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("scriptsSection.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("scriptsSection.intro", { code })}
      </p>

      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {scriptItems.map((f) => {
          const Icon = iconMap[f.icon] ?? Server
          return <FeatureCard key={f.href} title={f.title} description={f.description} Icon={Icon} href={f.href} />
        })}
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("monitorSection.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("monitorSection.intro", { link: monitorOverviewLink })}
      </p>

      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {monitorItems.map((f) => {
          const Icon = iconMap[f.icon] ?? Activity
          return <FeatureCard key={f.href} title={f.title} description={f.description} Icon={Icon} href={f.href} />
        })}
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("installPaths.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("installPaths.intro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("installPaths.headerPath")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("installPaths.headerBundles")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {installRows.map((row, idx) => (
              <tr key={idx} className={idx < installRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">
                  {t.rich(`installPaths.rows.${idx}.pathRich`, { strong })}
                </td>
                <td className="px-3 py-2 align-top">{row.bundles}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("installPaths.outro", { link: installationLink })}
      </p>

      <Callout variant="warning" title={t("warnSource.title")}>
        {t("warnSource.body")}{" "}
        <a
          href="https://github.com/MacRimi/ProxMenux/tree/main/scripts"
          target="_blank"
          rel="noopener noreferrer"
          className="text-amber-700 hover:underline inline-flex items-center gap-1"
        >
          {t("warnSource.sourceLabel")}
          <ExternalLink className="w-3 h-3" />
        </a>
        {" "}·{" "}
        <a
          href="https://github.com/MacRimi/ProxMenux?tab=coc-ov-file#-2-security--code-responsibility"
          target="_blank"
          rel="noopener noreferrer"
          className="text-amber-700 hover:underline inline-flex items-center gap-1"
        >
          {t("warnSource.cocLabel")}
          <ExternalLink className="w-3 h-3" />
        </a>
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("next.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {nextItems.map((item, idx) => (
          <li key={idx}>
            {t.rich(`next.items.${idx}.lead`, { strong })}
            <Link href={item.linkHref} className="text-blue-600 hover:underline">
              {item.linkLabel}
            </Link>
            {item.tailRich ? t.rich(`next.items.${idx}.tailRich`, { code }) : item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
