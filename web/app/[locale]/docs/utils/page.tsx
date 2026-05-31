import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import {
  ArrowRight,
  Disc,
  Package,
  RefreshCw,
  ArrowUpCircle,
  Upload,
  Download,
  Wrench,
  Boxes,
  ArrowLeftRight,
} from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.utils.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox utilities",
      "proxmox update",
      "pve 8 to 9 upgrade",
      "pve9 upgrade",
      "proxmox ova export",
      "proxmox ovf import",
      "uup dump proxmox",
      "windows iso proxmox",
      "vmware to proxmox",
      "virtualbox to proxmox",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/utils" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/utils",
    },
    twitter: {
      card: "summary",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type StringItem = string
type OptionItem = { title: string; description: string; href: string }

interface OptionProps {
  title: string
  description: string
  Icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>
  href: string
}

function OptionCard({ title, description, Icon, href }: OptionProps) {
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

export default async function UtilitiesOverviewPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.utils" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { utils: {
      groups: {
        iso: { bullets: StringItem[] }
        maintenance: { bullets: StringItem[] }
        portability: { bullets: StringItem[] }
      }
      isoSection: { options: OptionItem[] }
      maintenanceSection: { options: OptionItem[] }
      portabilitySection: { options: OptionItem[] }
    } }
  }
  const block = messages.docs.utils
  const isoBullets = block.groups.iso.bullets
  const maintBullets = block.groups.maintenance.bullets
  const portBullets = block.groups.portability.bullets
  const isoOptions = block.isoSection.options
  const maintOptions = block.maintenanceSection.options
  const portOptions = block.portabilitySection.options

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  const isoIcons: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>[] = [Disc]
  const maintIcons: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>[] = [Package, RefreshCw, ArrowUpCircle]
  const portIcons: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>[] = [Upload, Download]

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={5}
        scriptPath="menus/utilities_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("opening.body", { strong })}</p>

      <Image
        src="/utils/utilities-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("groups.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("groups.intro")}</p>

      <div className="grid gap-4 md:grid-cols-1 lg:grid-cols-3 mb-8 not-prose">
        <a
          href="#iso"
          className="rounded-lg border-2 border-blue-300 bg-blue-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-blue-700">
              <Disc className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("groups.iso.title")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t("groups.iso.body")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {isoBullets.map((_, idx) => (
              <li key={idx}>{t(`groups.iso.bullets.${idx}`)}</li>
            ))}
          </ul>
        </a>

        <a
          href="#maintenance"
          className="rounded-lg border-2 border-emerald-300 bg-emerald-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
              <Wrench className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("groups.maintenance.title")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t("groups.maintenance.body")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {maintBullets.map((_, idx) => (
              <li key={idx}>{t(`groups.maintenance.bullets.${idx}`)}</li>
            ))}
          </ul>
        </a>

        <a
          href="#portability"
          className="rounded-lg border-2 border-amber-300 bg-amber-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-amber-100 text-amber-700">
              <ArrowLeftRight className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("groups.portability.title")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t("groups.portability.body")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {portBullets.map((_, idx) => (
              <li key={idx}>{t(`groups.portability.bullets.${idx}`)}</li>
            ))}
          </ul>
        </a>
      </div>

      <Callout variant="warning" title={t("upgradeWarn.title")}>
        {t.rich("upgradeWarn.body", { strong })}
      </Callout>

      <h2 id="iso" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">
        {t("isoSection.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("isoSection.body", { code })}</p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {isoOptions.map((o, idx) => (
          <OptionCard key={o.href} {...o} Icon={isoIcons[idx]} />
        ))}
      </div>

      <h2 id="maintenance" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">
        {t("maintenanceSection.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("maintenanceSection.body", { strong })}</p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {maintOptions.map((o, idx) => (
          <OptionCard key={o.href} {...o} Icon={maintIcons[idx]} />
        ))}
      </div>

      <h2 id="portability" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">
        {t("portabilitySection.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("portabilitySection.body")}</p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {portOptions.map((o, idx) => (
          <OptionCard key={o.href} {...o} Icon={portIcons[idx]} />
        ))}
      </div>

      <Callout variant="info" title={t("diskSpaceCallout.title")}>
        {t.rich("diskSpaceCallout.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        <Boxes className="inline h-5 w-5 mr-1 -mt-1 text-gray-700" aria-hidden />
        {t("fitsTogether.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("fitsTogether.body", { code, em })}</p>
    </div>
  )
}
