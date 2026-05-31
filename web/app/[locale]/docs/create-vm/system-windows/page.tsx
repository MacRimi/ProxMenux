import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ExternalLink, Server } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.createVm.systemWindows.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/create-vm/system-windows",
      images: [
        {
          url: "/vm/menu_windows.png",
          width: 1200,
          height: 630,
          alt: t("ogImageAlt"),
        },
      ],
    },
  }
}

type ConfigRow = { param: string; value?: string; valueRich?: string; options?: string; optionsRich?: string }
type StringItem = string
type VirtioStep = { title: string; body?: string; bodyRich?: string; img: string; caption: string }
type RelatedItem = { href: string; label: string; tail?: string }

export default async function SystemWindowsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.createVm.systemWindows" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { createVm: { systemWindows: {
      config: { defaultRows: ConfigRow[]; advancedRows: ConfigRow[] }
      storagePlan: { virtualDiskItems: StringItem[]; importDiskItems: StringItem[]; pciItems: StringItem[] }
      installOptions: { uupItems: StringItem[] }
      endToEnd: { items: StringItem[] }
      virtio: { steps: VirtioStep[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const defaultRows = messages.docs.createVm.systemWindows.config.defaultRows
  const advancedRows = messages.docs.createVm.systemWindows.config.advancedRows
  const virtualDiskItems = messages.docs.createVm.systemWindows.storagePlan.virtualDiskItems
  const importDiskItems = messages.docs.createVm.systemWindows.storagePlan.importDiskItems
  const pciItems = messages.docs.createVm.systemWindows.storagePlan.pciItems
  const uupItems = messages.docs.createVm.systemWindows.installOptions.uupItems
  const endToEndItems = messages.docs.createVm.systemWindows.endToEnd.items
  const virtioSteps = messages.docs.createVm.systemWindows.virtio.steps
  const relatedItems = messages.docs.createVm.systemWindows.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const gpuLink = (chunks: React.ReactNode) => (
    <a href="/docs/hardware/gpu-vm-passthrough" className="text-blue-600 hover:underline">{chunks}</a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={20}
        scriptPath="vm/select_windows_iso.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <div className="flex flex-col items-center my-6">
        <div className="w-full max-w-[768px] overflow-hidden rounded-md border border-gray-200">
          <Image
            src="/vm/menu_windows.png"
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
                <td className="px-4 py-2">
                  {row.valueRich ? t.rich(`config.defaultRows.${idx}.valueRich`, { code }) : row.value}
                </td>
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
                <td className="px-4 py-2">
                  {row.optionsRich ? t.rich(`config.advancedRows.${idx}.optionsRich`, { code }) : row.options}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="warning" title={t("config.tpmWarnTitle")}>
        {t("config.tpmWarnBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("storagePlan.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("storagePlan.body", { strong })}
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 my-6">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("storagePlan.virtualDiskTitle")}</h3>
          <ul className="list-disc pl-5 text-sm text-gray-700 leading-relaxed space-y-1">
            {virtualDiskItems.map((_, idx) => (
              <li key={idx}>{t.rich(`storagePlan.virtualDiskItems.${idx}`, { code })}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("storagePlan.importDiskTitle")}</h3>
          <ul className="list-disc pl-5 text-sm text-gray-700 leading-relaxed space-y-1">
            {importDiskItems.map((_, idx) => (
              <li key={idx}>{t.rich(`storagePlan.importDiskItems.${idx}`, { code })}</li>
            ))}
          </ul>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4 md:col-span-2">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("storagePlan.pciTitle")}</h3>
          <ul className="list-disc pl-5 text-sm text-gray-700 leading-relaxed space-y-1">
            {pciItems.map((_, idx) => (
              <li key={idx}>{t.rich(`storagePlan.pciItems.${idx}`, { em, code })}</li>
            ))}
          </ul>
        </div>
      </div>

      <Callout variant="info" title={t("storagePlan.resetTitle")}>
        {t.rich("storagePlan.resetBody", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("gpu.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("gpu.body", { gpuLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("autoFeatures.heading")}</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 my-4">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("autoFeatures.efiTitle")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t("autoFeatures.efiBody")}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("autoFeatures.tpmTitle")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t("autoFeatures.tpmBody")}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("autoFeatures.isoTitle")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t.rich("autoFeatures.isoBody", { code, em })}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("autoFeatures.guestTitle")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t.rich("autoFeatures.guestBody", { code })}</p>
        </div>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("installOptions.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("installOptions.intro")}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 my-6">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-12 h-12 flex items-center justify-center rounded-md bg-blue-50">
              <Image src="https://uupdump.net/static/uupdump/1.1.0/img/logo.svg" alt={t("installOptions.uupLogoAlt")} width={40} height={40} className="object-contain" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("installOptions.uupTitle")}</h3>
          </div>
          <p className="text-sm text-gray-700 leading-relaxed mb-4">
            {t.rich("installOptions.uupBody", { strong })}
          </p>
          <ul className="list-disc pl-5 text-sm text-gray-700 leading-relaxed space-y-1 mb-4">
            {uupItems.map((_, idx) => (
              <li key={idx}>{t(`installOptions.uupItems.${idx}`)}</li>
            ))}
          </ul>
          <Link href="/docs/utils/UUp-Dump-ISO-Creator" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline">
            {t("installOptions.uupLearnMore")}
            <ExternalLink className="h-3.5 w-3.5" />
          </Link>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-12 h-12 flex items-center justify-center rounded-md bg-blue-50 text-blue-600">
              <Server className="h-7 w-7" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("installOptions.localTitle")}</h3>
          </div>
          <p className="text-sm text-gray-700 leading-relaxed mb-4">
            {t.rich("installOptions.localBody", { code })}
          </p>
          <div className="mt-4 overflow-hidden rounded-md border border-gray-200">
            <Image src="/vm/local-store-windows.png" alt={t("installOptions.localImageAlt")} width={600} height={400} className="w-full object-contain" />
          </div>
          <p className="mt-2 text-xs text-gray-600">{t("installOptions.localImageCaption")}</p>
        </div>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("endToEnd.heading")}</h2>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {endToEndItems.map((_, idx) => (
          <li key={idx}>{t.rich(`endToEnd.items.${idx}`, { code })}</li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("virtio.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("virtio.body", { code })}
      </p>

      <Callout variant="warning" title={t("virtio.warnTitle")}>
        {t.rich("virtio.warnBody", { code })}
      </Callout>

      {virtioSteps.map((step, idx) => (
        <section key={idx} className="mt-8 border-b border-gray-200 pb-8">
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-800">
              {t("virtio.stepLabel")} {idx + 1}
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{step.title}</h3>
          </div>
          <p className="mb-4 text-gray-800 leading-relaxed">
            {step.bodyRich ? t.rich(`virtio.steps.${idx}.bodyRich`, { strong, code }) : step.body}
          </p>
          <div className="flex flex-col items-center">
            <div className="w-full max-w-[768px] overflow-hidden rounded-md border border-gray-200">
              <Image src={step.img} alt={step.caption} width={768} height={0} style={{ height: "auto" }} className="w-full object-contain" sizes="(max-width: 768px) 100vw, 768px" />
            </div>
            <span className="mt-2 text-sm text-gray-600">{step.caption}</span>
          </div>
        </section>
      ))}

      <Callout variant="tip" title={t("virtio.tipTitle")}>
        {t.rich("virtio.tipBody", { code })}
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
