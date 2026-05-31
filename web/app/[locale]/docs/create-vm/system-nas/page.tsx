import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ArrowRight, ExternalLink, HardDrive, Database, Server, MonitorIcon, Github } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.createVm.systemNas.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/create-vm/system-nas",
      images: [
        {
          url: "/vm/system-nas-menu.png",
          width: 1200,
          height: 630,
          alt: t("ogImageAlt"),
        },
      ],
    },
  }
}

type NASCard = {
  name: string
  tagline: string
  icon: string
  base: string
  fileSystem: string
  href: string
  flow: "loader" | "auto-iso" | "dedicated"
  external?: boolean
}
type RelatedItem = { href: string; label: string; tail?: string }

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  HardDrive,
  Database,
  Server,
  MonitorIcon,
}

const FLOW_CLS: Record<string, string> = {
  loader: "bg-purple-100 text-purple-800 border-purple-200",
  "auto-iso": "bg-blue-100 text-blue-800 border-blue-200",
  dedicated: "bg-indigo-100 text-indigo-800 border-indigo-200",
}

export default async function SystemNASPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.createVm.systemNas" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { createVm: { systemNas: {
      supported: { cards: NASCard[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const cards = messages.docs.createVm.systemNas.supported.cards
  const relatedItems = messages.docs.createVm.systemNas.related.items

  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const umbrelLink = (chunks: React.ReactNode) => (
    <a
      href="https://community-scripts.github.io/ProxmoxVE/scripts?id=umbrel-os-vm"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1 ml-1"
    >
      <Github className="h-3.5 w-3.5" /> {chunks}
    </a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={3}
        scriptPath="vm/select_nas_iso.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <div className="flex flex-col items-center my-6">
        <div className="w-full max-w-[768px] overflow-hidden rounded-md border border-gray-200">
          <Image
            src="/vm/system-nas-menu.png"
            alt={t("image.alt")}
            width={768}
            height={0}
            style={{ height: "auto" }}
            className="w-full object-contain"
            sizes="(max-width: 768px) 100vw, 768px"
          />
        </div>
        <span className="mt-2 text-sm text-gray-600">{t("image.caption")}</span>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("supported.heading")}</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
        {cards.map((card) => {
          const Icon = ICONS[card.icon] || HardDrive
          const flowLabel = t(`flowBadges.${card.flow}`)
          const cls = "group block rounded-lg border border-gray-200 bg-white p-5 transition-all hover:border-blue-300 hover:shadow-md"
          const inner = (
            <div className="flex items-start gap-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-600">
                <Icon className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-base font-semibold text-gray-900">{card.name}</h3>
                <p className="mt-1 text-sm text-gray-600 leading-relaxed">{card.tagline}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${FLOW_CLS[card.flow]}`}>
                    {flowLabel}
                  </span>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-600">
                  <div>
                    <dt className="font-semibold text-gray-700">{t("labels.base")}</dt>
                    <dd>{card.base}</dd>
                  </div>
                  <div>
                    <dt className="font-semibold text-gray-700">{t("labels.fileSystem")}</dt>
                    <dd>{card.fileSystem}</dd>
                  </div>
                </dl>
                <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-blue-600 group-hover:text-blue-700">
                  {t("labels.viewDetails")}
                  {card.external ? (
                    <ExternalLink className="h-3.5 w-3.5" />
                  ) : (
                    <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                  )}
                </span>
              </div>
            </div>
          )
          return card.external ? (
            <a key={card.name} href={card.href} target="_blank" rel="noopener noreferrer" className={cls}>
              {inner}
            </a>
          ) : (
            <Link key={card.name} href={card.href} className={cls}>
              {inner}
            </Link>
          )
        })}
      </div>

      <Callout variant="info" title={t("umbrel.title")}>
        {t.rich("umbrel.bodyRich", { strong, umbrelLink })}
      </Callout>

      <Callout variant="tip" title={t("zfsMem.title")}>
        {t.rich("zfsMem.bodyRich", { strong })}
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
