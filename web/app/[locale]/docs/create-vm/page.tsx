import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ExternalLink, HardDrive, MonitorCog, Laptop } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.createVm.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox create vm",
      "proxmox synology vm",
      "proxmox windows vm",
      "proxmox truenas vm",
      "proxmox unraid vm",
      "proxmox openmediavault",
      "proxmox vm wizard",
      "proxmox nas vm",
      "proxmox dsm",
      "proxmenux create vm",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/create-vm" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/create-vm",
      images: [
        {
          url: "/vm/vm-creation-menu.png",
          width: 1200,
          height: 630,
          alt: t("ogImageAlt"),
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type Route = {
  key: string
  title: string
  icon: string
  href: string
  accent: string
  iconBg: string
  description: string
  bullets: string[]
}
type StringItem = string
type ScriptRowData = { path: string; role: string }
type RelatedItem = { href: string; label: string; tail?: string }

const ICONS: Record<string, React.ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>> = {
  HardDrive,
  MonitorCog,
  Laptop,
}

function ScriptRow({ path, role }: { path: string; role: string }) {
  return (
    <tr>
      <td className="px-4 py-2">
        <a
          className="inline-flex items-center gap-1.5 text-blue-600 hover:underline"
          href={`https://github.com/MacRimi/ProxMenux/blob/main/scripts/${path}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          <span className="font-mono">{path}</span>
          <ExternalLink className="h-3.5 w-3.5 shrink-0 opacity-70" />
        </a>
      </td>
      <td className="px-4 py-2 text-gray-700">{role}</td>
    </tr>
  )
}

export default async function CreateVMOverviewPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.createVm" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { createVm: {
      families: { routes: Route[] }
      afterPick: { items: StringItem[] }
      scripts: { rows: ScriptRowData[] }
      related: { items: RelatedItem[] }
    } }
  }
  const routes = messages.docs.createVm.families.routes
  const afterPickItems = messages.docs.createVm.afterPick.items
  const scriptRows = messages.docs.createVm.scripts.rows
  const relatedItems = messages.docs.createVm.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const osxLink = (chunks: React.ReactNode) => (
    <a
      href="https://osx-proxmox.com"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={2}
        scriptPath="menus/create_vm_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.body", { strong })}
      </p>

      <Image
        src="/vm/vm-creation-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("families.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("families.intro")}</p>

      <div className="grid gap-4 md:grid-cols-1 lg:grid-cols-3 mb-8 not-prose">
        {routes.map((route) => {
          const Icon = ICONS[route.icon] || HardDrive
          return (
            <Link
              key={route.key}
              href={route.href}
              className={`rounded-lg border-2 p-5 ${route.accent} flex flex-col transition-shadow hover:shadow-md`}
            >
              <div className="flex items-center gap-3 mb-3">
                <span className={`inline-flex h-9 w-9 items-center justify-center rounded-full ${route.iconBg}`}>
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </span>
                <h3 className="text-lg font-semibold text-gray-900 m-0">{route.title}</h3>
              </div>
              <p className="text-sm text-gray-800 mb-3">{route.description}</p>
              <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
                {route.bullets.map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
            </Link>
          )
        })}
      </div>

      <Callout variant="info" title={t("community.title")}>
        {t.rich("community.intro", { em, strong })}
        <ul className="mt-3 list-disc list-inside space-y-1">
          <li>{t.rich("community.macosRich", { strong, osxLink })}</li>
          <li>{t.rich("community.othersRich", { strong })}</li>
        </ul>
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("afterPick.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("afterPick.intro")}</p>
      <ol className="list-decimal list-inside mb-4 text-gray-800 leading-relaxed space-y-2">
        {afterPickItems.map((_, idx) => (
          <li key={idx}>{t.rich(`afterPick.items.${idx}`, { strong, code })}</li>
        ))}
      </ol>

      <Callout variant="tip" title={t("afterPick.tipTitle")}>
        {t.rich("afterPick.tipBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("scripts.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("scripts.intro")}</p>
      <div className="overflow-x-auto rounded-md border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("scripts.headerScript")}</th>
              <th className="px-4 py-2 font-semibold">{t("scripts.headerRole")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {scriptRows.map((row) => (
              <ScriptRow key={row.path} path={row.path} role={row.role} />
            ))}
          </tbody>
        </table>
      </div>

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
