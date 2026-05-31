import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import {
  ArrowRight,
  Activity,
  TestTube,
  Languages,
  Info,
  Trash2,
} from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.settings.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmenux settings",
      "proxmenux monitor activation",
      "proxmenux beta program",
      "proxmenux language",
      "proxmenux uninstall",
      "proxmenux version",
      "proxmenux configuration",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/settings" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/settings",
    },
    twitter: {
      card: "summary",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type Option = {
  icon: string
  href: string
  title: string
  description: string
  badge?: string
}
type InstallRow = { type: string; bundles: string; menu?: string; menuRich?: string }

const ICONS: Record<string, React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  Activity,
  TestTube,
  Languages,
  Info,
  Trash2,
}

function OptionCard({ option }: { option: Option }) {
  const Icon = ICONS[option.icon] || Activity
  return (
    <Link
      href={option.href}
      className="group flex items-start gap-3 rounded-md border border-gray-200 bg-white p-3 transition-colors hover:border-blue-400 hover:bg-blue-50"
    >
      <span className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md bg-gray-100 text-gray-600 group-hover:bg-blue-100 group-hover:text-blue-700">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm font-medium text-gray-900 group-hover:text-blue-700">
          <span className="flex items-center gap-1">
            {option.title}
            <ArrowRight className="h-3.5 w-3.5 text-gray-400 group-hover:text-blue-600 transition-transform group-hover:translate-x-0.5" />
          </span>
          {option.badge && (
            <span className="inline-flex items-center rounded-full border border-gray-300 bg-gray-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-600">
              {option.badge}
            </span>
          )}
        </div>
        <div className="mt-0.5 text-xs text-gray-600 leading-snug">{option.description}</div>
      </div>
    </Link>
  )
}

export default async function SettingsOverviewPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.settings" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { settings: {
      installTypes: { rows: InstallRow[] }
      options: { list: Option[] }
    } }
  }
  const installRows = messages.docs.settings.installTypes.rows
  const optionsList = messages.docs.settings.options.list

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const kbd = (chunks: React.ReactNode) => <kbd>{chunks}</kbd>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={3}
        scriptPath="menus/config_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { kbd })}
      </p>

      <Image
        src="/settings/settings-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("installTypes.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("installTypes.intro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("installTypes.headerType")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("installTypes.headerBundles")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("installTypes.headerMenu")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {installRows.map((row, idx) => (
              <tr key={row.type} className={idx < installRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.type}</strong></td>
                <td className="px-3 py-2 align-top">{row.bundles}</td>
                <td className="px-3 py-2 align-top">
                  {row.menuRich ? t.rich(`installTypes.rows.${idx}.menuRich`, { strong }) : row.menu}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("installTypes.detectionTitle")}>
        {t.rich("installTypes.detectionBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("options.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("options.intro", { em })}
      </p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {optionsList.map((o) => (
          <OptionCard key={o.href} option={o} />
        ))}
      </div>

      <Callout variant="tip" title={t("configTip.title")}>
        {t.rich("configTip.bodyRich", { code })}
      </Callout>
    </div>
  )
}
