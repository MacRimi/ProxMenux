import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ExternalLink, Database, Server, HardDrive, MonitorIcon } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.createVm.systemNas.systemNasOthers.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/create-vm/system-nas/system-nas-others",
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

type DefaultRow = { param: string; valueRich: string }
type AdvancedRow = { param: string; optionsRich: string }
type RelatedItem = { href: string; label: string; tail: string }
type SystemEntry = {
  id: string
  title: string
  icon: string
  officialName: string
  officialUrl: string
  description: string
  specs: string[]
  shellImg?: string
  webImg?: string
  shellAlt?: string
  webAlt?: string
}

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  Database,
  Server,
  HardDrive,
  MonitorIcon,
}

export default async function OtherNASSystemsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.createVm.systemNas.systemNasOthers" })
  const messages = (await getMessages({ locale })) as unknown as {
    docs: {
      createVm: {
        systemNas: {
          systemNasOthers: {
            config: { defaultRowsRich: DefaultRow[]; advancedRowsRich: AdvancedRow[] }
            storagePlan: { virtualItemsRich: string[]; importItemsRich: string[]; pciItemsRich: string[] }
            endToEnd: { itemsRich: string[] }
            systems: Record<string, SystemEntry>
            related: { itemsRich: RelatedItem[] }
          }
        }
      }
    }
  }
  const o = messages.docs.createVm.systemNas.systemNasOthers
  const defaultRows = o.config.defaultRowsRich
  const advancedRows = o.config.advancedRowsRich
  const virtualItems = o.storagePlan.virtualItemsRich
  const importItems = o.storagePlan.importItemsRich
  const pciItems = o.storagePlan.pciItemsRich
  const endToEndItems = o.endToEnd.itemsRich
  const systemOrder = ["truenasScale", "truenasCore", "openmediavault", "xigmanas", "rockstor", "zimaos"]
  const relatedItems = o.related.itemsRich

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const note = (chunks: React.ReactNode) => <span className="text-xs text-gray-500">{chunks}</span>
  const gpuLink = (chunks: React.ReactNode) => (
    <a href="/docs/hardware/gpu-vm-passthrough" className="text-blue-600 hover:underline">
      {chunks}
    </a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={15}
        scriptPath="vm/select_nas_iso.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.bodyRich", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("config.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("config.intro")}</p>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("config.defaultHeading")}</h3>
      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("config.headerParam")}</th>
              <th className="px-4 py-2 font-semibold">{t("config.headerValue")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {defaultRows.map((row, idx) => (
              <tr key={row.param}>
                <td className="px-4 py-2">{row.param}</td>
                <td className="px-4 py-2">{t.rich(`config.defaultRowsRich.${idx}.valueRich`, { code, note })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("config.advancedHeading")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("config.advancedIntro")}</p>
      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("config.headerParam")}</th>
              <th className="px-4 py-2 font-semibold">{t("config.headerOptions")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {advancedRows.map((row, idx) => (
              <tr key={row.param}>
                <td className="px-4 py-2">{row.param}</td>
                <td className="px-4 py-2">{t.rich(`config.advancedRowsRich.${idx}.optionsRich`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("config.zfsCalloutTitle")}>
        {t("config.zfsCalloutBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("storagePlan.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("storagePlan.intro")}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 my-6">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("storagePlan.virtualHeading")}</h3>
          <ul className="list-disc pl-5 text-sm text-gray-700 leading-relaxed space-y-1">
            {virtualItems.map((_, idx) => (
              <li key={idx}>{t.rich(`storagePlan.virtualItemsRich.${idx}`, { code })}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("storagePlan.importHeading")}</h3>
          <ul className="list-disc pl-5 text-sm text-gray-700 leading-relaxed space-y-1">
            {importItems.map((_, idx) => (
              <li key={idx}>{t.rich(`storagePlan.importItemsRich.${idx}`, { code })}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4 md:col-span-2">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("storagePlan.pciHeading")}</h3>
          <ul className="list-disc pl-5 text-sm text-gray-700 leading-relaxed space-y-1">
            {pciItems.map((_, idx) => (
              <li key={idx}>{t.rich(`storagePlan.pciItemsRich.${idx}`, { code, em })}</li>
            ))}
          </ul>
        </div>
      </div>

      <Callout variant="info" title={t("storagePlan.resetCalloutTitle")}>
        {t.rich("storagePlan.resetCalloutBodyRich", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("gpu.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("gpu.bodyRich", { link: gpuLink })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("autoFeatures.heading")}</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 my-4">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("autoFeatures.efiTitle")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t("autoFeatures.efiBody")}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("autoFeatures.isoTitle")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t.rich("autoFeatures.isoBodyRich", { code })}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("autoFeatures.guestTitle")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t("autoFeatures.guestBody")}</p>
        </div>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("endToEnd.heading")}</h2>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {endToEndItems.map((_, idx) => (
          <li key={idx}>{t.rich(`endToEnd.itemsRich.${idx}`, { code })}</li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-12 mb-6 text-gray-900">{t("perSystem.heading")}</h2>

      {systemOrder.map((key) => {
        const sys = o.systems[key]
        const Icon = ICONS[sys.icon] ?? Database
        return (
          <NASSection
            key={sys.id}
            id={sys.id}
            title={sys.title}
            icon={<Icon className="h-6 w-6 text-blue-500" />}
            officialName={sys.officialName}
            officialUrl={sys.officialUrl}
            description={sys.description}
            specs={sys.specs}
            shellImg={sys.shellImg}
            webImg={sys.webImg}
            shellAlt={sys.shellAlt}
            webAlt={sys.webAlt}
            shellLabel={t("perSystem.shellLabel")}
            webLabel={t("perSystem.webLabel")}
          />
        )
      })}

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

interface NASSectionProps {
  id: string
  title: string
  icon: React.ReactNode
  officialName: string
  officialUrl: string
  description: string
  specs: string[]
  shellImg?: string
  webImg?: string
  shellAlt?: string
  webAlt?: string
  shellLabel: string
  webLabel: string
}

function NASSection({
  id,
  title,
  icon,
  officialName,
  officialUrl,
  description,
  specs,
  shellImg,
  webImg,
  shellAlt,
  webAlt,
  shellLabel,
  webLabel,
}: NASSectionProps) {
  return (
    <section id={id} className="mt-10 scroll-mt-24 border-b border-gray-200 pb-8">
      <h3 className="text-xl font-semibold mb-3 flex items-center flex-wrap gap-2 text-gray-900">
        {icon}
        <span>{title}</span>
        <a
          href={officialUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-2 text-sm font-normal text-blue-600 hover:underline inline-flex items-center gap-1"
        >
          {officialName} <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{description}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {specs.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
      {(shellImg || webImg) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
          {shellImg && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-2">{shellLabel}</h4>
              <div className="overflow-hidden rounded-md border border-gray-200">
                <Image src={shellImg} alt={shellAlt ?? `${title} shell interface`} width={600} height={400} className="w-full object-contain" />
              </div>
            </div>
          )}
          {webImg && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-2">{webLabel}</h4>
              <div className="overflow-hidden rounded-md border border-gray-200">
                <Image src={webImg} alt={webAlt ?? `${title} web interface`} width={600} height={400} className="w-full object-contain" />
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
