import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { Server, HardDrive } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.createVm.systemLinux.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/create-vm/system-linux",
      images: [
        {
          url: "/vm/menu_linux.png",
          width: 1200,
          height: 630,
          alt: t("ogImageAlt"),
        },
      ],
    },
  }
}

type ConfigRow = { param: string; value?: string; valueRich?: string; options?: string; optionsRich?: string }
type Distro = { name: string; variants: string[] }
type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string }

export default async function SystemLinuxPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.createVm.systemLinux" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { createVm: { systemLinux: {
      config: { defaultRows: ConfigRow[]; advancedRows: ConfigRow[] }
      storagePlan: { virtualDiskItems: StringItem[]; importDiskItems: StringItem[]; pciItems: StringItem[] }
      installOptions: { distros: Distro[] }
      endToEnd: { items: StringItem[] }
      postInstall: { trimItems: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const defaultRows = messages.docs.createVm.systemLinux.config.defaultRows
  const advancedRows = messages.docs.createVm.systemLinux.config.advancedRows
  const virtualDiskItems = messages.docs.createVm.systemLinux.storagePlan.virtualDiskItems
  const importDiskItems = messages.docs.createVm.systemLinux.storagePlan.importDiskItems
  const pciItems = messages.docs.createVm.systemLinux.storagePlan.pciItems
  const distros = messages.docs.createVm.systemLinux.installOptions.distros
  const endToEndItems = messages.docs.createVm.systemLinux.endToEnd.items
  const trimItems = messages.docs.createVm.systemLinux.postInstall.trimItems
  const relatedItems = messages.docs.createVm.systemLinux.related.items

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
        estimatedMinutes={15}
        scriptPath="vm/select_linux_iso.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <div className="flex flex-col items-center my-6">
        <div className="w-full max-w-[768px] overflow-hidden rounded-md border border-gray-200">
          <Image
            src="/vm/menu_linux.png"
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
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 my-4">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("autoFeatures.efiTitle")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t("autoFeatures.efiBody")}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("autoFeatures.isoTitle")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t.rich("autoFeatures.isoBody", { code })}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="text-base font-semibold text-gray-900 mb-2">{t("autoFeatures.guestTitle")}</h3>
          <p className="text-sm text-gray-700 leading-relaxed">{t("autoFeatures.guestBody")}</p>
        </div>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("installOptions.heading")}</h2>

      <section className="mt-6">
        <div className="flex items-center gap-3 mb-3">
          <Server className="h-8 w-8 text-blue-500" />
          <h3 className="text-xl font-semibold text-gray-900 m-0">{t("installOptions.officialHeading")}</h3>
        </div>
        <p className="mb-4 text-gray-800 leading-relaxed">
          {t.rich("installOptions.officialBody", { code })}
        </p>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 my-4">
          {distros.map((d) => (
            <div key={d.name} className="rounded-md border border-gray-200 bg-white p-3">
              <div className="text-sm font-semibold text-gray-900">{d.name}</div>
              <ul className="mt-1 text-xs text-gray-600 space-y-0.5">
                {d.variants.map((v) => (
                  <li key={v}>{v}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-4">
          <div className="flex flex-col items-center">
            <div className="w-full max-w-[768px] overflow-hidden rounded-md border border-gray-200">
              <Image src="/vm/distro_linux.png" alt={t("installOptions.officialImageAlt")} width={768} height={0} style={{ height: "auto" }} className="w-full object-contain" sizes="(max-width: 768px) 100vw, 768px" />
            </div>
            <span className="mt-2 text-sm text-gray-600">{t("installOptions.officialImageCaption")}</span>
          </div>
        </div>
      </section>

      <section className="mt-10">
        <div className="flex items-center gap-3 mb-3">
          <HardDrive className="h-8 w-8 text-blue-500" />
          <h3 className="text-xl font-semibold text-gray-900 m-0">{t("installOptions.localHeading")}</h3>
        </div>
        <p className="mb-4 text-gray-800 leading-relaxed">
          {t.rich("installOptions.localBody", { code })}
        </p>
        <div className="flex flex-col items-center">
          <div className="w-full max-w-[768px] overflow-hidden rounded-md border border-gray-200">
            <Image src="/vm/local-store.png" alt={t("installOptions.localImageAlt")} width={768} height={0} style={{ height: "auto" }} className="w-full object-contain" sizes="(max-width: 768px) 100vw, 768px" />
          </div>
          <span className="mt-2 text-sm text-gray-600">{t("installOptions.localImageCaption")}</span>
        </div>
      </section>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("endToEnd.heading")}</h2>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {endToEndItems.map((_, idx) => (
          <li key={idx}>{t.rich(`endToEnd.items.${idx}`, { code })}</li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("postInstall.heading")}</h2>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("postInstall.guestAgentHeading")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("postInstall.guestAgentBody")}</p>

      <div className="space-y-4 mb-6">
        <div>
          <p className="text-sm font-semibold text-gray-900 mb-1">{t("postInstall.debian")}</p>
          <CopyableCode code={`sudo apt update && sudo apt install qemu-guest-agent -y
sudo systemctl enable --now qemu-guest-agent`} />
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-900 mb-1">{t("postInstall.fedora")}</p>
          <CopyableCode code={`sudo dnf install qemu-guest-agent -y
sudo systemctl enable --now qemu-guest-agent`} />
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-900 mb-1">{t("postInstall.arch")}</p>
          <CopyableCode code={`sudo pacman -S qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent`} />
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-900 mb-1">{t("postInstall.opensuse")}</p>
          <CopyableCode code={`sudo zypper install qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent`} />
        </div>
      </div>

      <h3 className="text-lg font-semibold mt-8 mb-3 text-gray-900">{t("postInstall.virtioHeading")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("postInstall.virtioBody", { code })}
      </p>
      <Callout variant="warning" title={t("postInstall.virtioWarnTitle")}>
        {t("postInstall.virtioWarnBody")}
      </Callout>

      <h3 className="text-lg font-semibold mt-8 mb-3 text-gray-900">{t("postInstall.trimHeading")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("postInstall.trimBody", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {trimItems.map((_, idx) => (
          <li key={idx}>{t.rich(`postInstall.trimItems.${idx}`, { code })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-8 mb-3 text-gray-900">{t("postInstall.balloonHeading")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("postInstall.balloonBody", { code })}
      </p>

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
