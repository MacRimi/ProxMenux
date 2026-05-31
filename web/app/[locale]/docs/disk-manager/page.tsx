import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ArrowRight, HardDrive, FileDown, Cpu, Boxes, Eraser, Activity, Server, Wrench } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.diskManager.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox disk passthrough",
      "proxmox attach disk to vm",
      "proxmox import disk",
      "proxmox qm importdisk",
      "proxmox lxc bind mount disk",
      "proxmox smart test",
      "proxmox wipe disk",
      "proxmox hba passthrough",
      "proxmox nvme passthrough",
      "qm set scsi",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/disk-manager" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/disk-manager",
    },
    twitter: {
      card: "summary",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type DiskOption = { icon: string; href: string; title: string; description: string }
type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string }

const ICONS: Record<string, React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  HardDrive,
  FileDown,
  Cpu,
  Boxes,
  Eraser,
  Activity,
}

function DiskOptionCard({ option }: { option: DiskOption }) {
  const Icon = ICONS[option.icon] || HardDrive
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

export default async function DiskManagerOverviewPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.diskManager" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { diskManager: {
      groups: { vmItems: StringItem[]; lxcItems: StringItem[]; utilitiesItems: StringItem[] }
      vm: { options: DiskOption[] }
      lxc: { options: DiskOption[] }
      utilities: { options: DiskOption[] }
      safety: { items: StringItem[] }
      related: { items: RelatedItem[] }
    } }
  }
  const vmItems = messages.docs.diskManager.groups.vmItems
  const lxcItems = messages.docs.diskManager.groups.lxcItems
  const utilitiesItems = messages.docs.diskManager.groups.utilitiesItems
  const vmOptions = messages.docs.diskManager.vm.options
  const lxcOptions = messages.docs.diskManager.lxc.options
  const utilityOptions = messages.docs.diskManager.utilities.options
  const safetyItems = messages.docs.diskManager.safety.items
  const relatedItems = messages.docs.diskManager.related.items

  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={3}
        scriptPath="menus/storage_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { strong })}
      </p>

      <Image
        src="/disk/disk-manager-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("groups.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("groups.intro", { strong })}
      </p>

      <div className="grid gap-4 md:grid-cols-1 lg:grid-cols-3 mb-8 not-prose">
        <a
          href="#vm"
          className="rounded-lg border-2 border-blue-300 bg-blue-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-blue-700">
              <Server className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("groups.vmTitle")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t("groups.vmBody")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {vmItems.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </a>

        <a
          href="#lxc"
          className="rounded-lg border-2 border-emerald-300 bg-emerald-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
              <Boxes className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("groups.lxcTitle")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t("groups.lxcBody")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {lxcItems.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </a>

        <a
          href="#utilities"
          className="rounded-lg border-2 border-amber-300 bg-amber-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-amber-100 text-amber-700">
              <Wrench className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("groups.utilitiesTitle")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t("groups.utilitiesBody")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {utilitiesItems.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        </a>
      </div>

      <h2 id="vm" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">{t("vm.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("vm.intro")}</p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {vmOptions.map((o) => <DiskOptionCard key={o.href} option={o} />)}
      </div>

      <h2 id="lxc" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">{t("lxc.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("lxc.intro")}</p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {lxcOptions.map((o) => <DiskOptionCard key={o.href} option={o} />)}
      </div>

      <h2 id="utilities" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">{t("utilities.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("utilities.intro")}</p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {utilityOptions.map((o) => <DiskOptionCard key={o.href} option={o} />)}
      </div>

      <Callout variant="warning" title={t("safety.title")}>
        {t("safety.intro")}
        <ul className="mt-3 list-disc list-inside space-y-1">
          {safetyItems.map((_, idx) => (
            <li key={idx}>{t.rich(`safety.items.${idx}`, { strong })}</li>
          ))}
        </ul>
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
