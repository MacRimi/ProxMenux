import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import {
  ArrowRight,
  HardDrive,
  Server,
  Network,
  FolderOpen,
  Database,
  Share2,
  Download,
  Upload,
  Link2,
} from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.storageShare.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox nfs",
      "proxmox samba",
      "proxmox cifs",
      "proxmox iscsi",
      "proxmox lxc mount points",
      "proxmox bind mount",
      "proxmox shared storage",
      "proxmox storage share",
      "proxmox nfs server lxc",
      "proxmox samba server lxc",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/storage-share" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/storage-share",
    },
    twitter: {
      card: "summary",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type OptionData = { href: string; icon: string; title: string; description: string }
type StringItem = string

const ICONS: Record<string, React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  Network,
  Share2,
  Database,
  HardDrive,
  FolderOpen,
  Download,
  Upload,
  Link2,
}

function OptionCard({ option }: { option: OptionData }) {
  const Icon = ICONS[option.icon] || Network
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

export default async function StorageShareOverviewPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.storageShare" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { storageShare: {
      groups: { hostItems: StringItem[]; lxcMountItems: StringItem[]; lxcNetItems: StringItem[] }
      host: { options: OptionData[] }
      lxcNet: { options: OptionData[] }
    } }
  }
  const hostItems = messages.docs.storageShare.groups.hostItems
  const lxcMountItems = messages.docs.storageShare.groups.lxcMountItems
  const lxcNetItems = messages.docs.storageShare.groups.lxcNetItems
  const hostOptions = messages.docs.storageShare.host.options
  const lxcNetOptions = messages.docs.storageShare.lxcNet.options

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const mountLink = (chunks: React.ReactNode) => (
    <Link href="/docs/storage-share/lxc-mount-points" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={5}
        scriptPath="menus/share_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { em, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { strong })}
      </p>

      <Image
        src="/share/storage-share-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("groups.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("groups.intro", { strong, em })}
      </p>

      <div className="grid gap-4 md:grid-cols-1 lg:grid-cols-3 mb-8 not-prose">
        <a
          href="#host"
          className="rounded-lg border-2 border-blue-300 bg-blue-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-blue-700">
              <Server className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("groups.hostTitle")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t.rich("groups.hostBody", { code })}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {hostItems.map((_, idx) => (
              <li key={idx}>{t(`groups.hostItems.${idx}`)}</li>
            ))}
          </ul>
        </a>

        <a
          href="#lxc-mount"
          className="rounded-lg border-2 border-emerald-300 bg-emerald-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
              <Link2 className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("groups.lxcMountTitle")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t.rich("groups.lxcMountBody", { code })}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {lxcMountItems.map((_, idx) => (
              <li key={idx}>{t.rich(`groups.lxcMountItems.${idx}`, { code })}</li>
            ))}
          </ul>
        </a>

        <a
          href="#lxc-net"
          className="rounded-lg border-2 border-amber-300 bg-amber-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-amber-100 text-amber-700">
              <Network className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("groups.lxcNetTitle")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t.rich("groups.lxcNetBody", { strong })}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {lxcNetItems.map((_, idx) => (
              <li key={idx}>{t.rich(`groups.lxcNetItems.${idx}`, { strong })}</li>
            ))}
          </ul>
        </a>
      </div>

      <h2 id="host" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">{t("host.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("host.intro", { code, strong })}
      </p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {hostOptions.map((o) => (
          <OptionCard key={o.href} option={o} />
        ))}
      </div>

      <h2 id="lxc-mount" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">{t("lxcMount.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("lxcMount.intro", { code })}
      </p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        <OptionCard
          option={{
            title: t("lxcMount.card.title"),
            description: t("lxcMount.card.description"),
            icon: "Link2",
            href: "/docs/storage-share/lxc-mount-points",
          }}
        />
      </div>

      <h2 id="lxc-net" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">{t("lxcNet.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("lxcNet.intro", { em, mountLink })}
      </p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {lxcNetOptions.map((o) => (
          <OptionCard key={o.href} option={o} />
        ))}
      </div>

      <Callout variant="warning" title={t("privReq.title")}>
        {t.rich("privReq.body", { strong, code, mountLink })}
      </Callout>

      <Callout variant="info" title={t("unprivExplain.title")}>
        {t.rich("unprivExplain.body", { strong, em, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("scripts.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("scripts.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        <li>
          <a
            href="https://github.com/MacRimi/ProxMenux/blob/main/scripts/global/share-common.func"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline font-mono"
          >
            global/share-common.func
          </a>
          {t("scripts.itemTail")}
        </li>
      </ul>
    </div>
  )
}
