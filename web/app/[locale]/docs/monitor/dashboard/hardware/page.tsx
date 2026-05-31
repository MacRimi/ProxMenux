import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.hardware.meta" })
  return { title: t("title"), description: t("description") }
}

type GpuTool = { vendor: string; tool: string; projectLabel: string; projectHref?: string }
type DataRow = { section: string; endpoint: string; source: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function HardwareTabPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.hardware" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { hardware: {
      thresholds: { items: string[] }
      sections: { systemInfoItems: string[]; thermalItems: string[] }
      graphics: { tools: GpuTool[]; whereGoItems: string[] }
      coral: { pathsItems: string[] }
      power: { items: string[] }
      dataCollected: { rows: DataRow[] }
      whereNext: { items: WhereNextItem[] }
    } } } }
  }
  const hw = messages.docs.monitor.dashboard.hardware
  const thresholdsItems = hw.thresholds.items
  const systemInfoItems = hw.sections.systemInfoItems
  const thermalItems = hw.sections.thermalItems
  const gpuTools = hw.graphics.tools
  const whereGoItems = hw.graphics.whereGoItems
  const coralPathsItems = hw.coral.pathsItems
  const powerItems = hw.power.items
  const dataRows = hw.dataCollected.rows
  const whereNextItems = hw.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const green = () => <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500 align-middle mr-1" />
  const amber = () => <span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-500 align-middle mr-1" />
  const red = () => <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-500 align-middle mr-1" />
  const thresholdsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/settings#status-colours" className="text-blue-700 hover:underline">
      {chunks}
    </Link>
  )
  const switchModeLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/switch-gpu-mode" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const nvidiaHostLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/nvidia-host" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const nvidiaAnchor = (chunks: React.ReactNode) => (
    <a
      href="https://www.nvidia.com/Download/index.aspx"
      target="_blank"
      rel="noopener noreferrer"
      className="text-amber-900 underline hover:no-underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
    </a>
  )
  const link1 = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/nvidia-host" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const link2 = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/switch-gpu-mode" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const link3 = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/gpu-vm-passthrough" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const link4 = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/igpu-acceleration-lxc" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const installLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/install-coral-tpu-host" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const lxcLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/coral-tpu-lxc" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const coralAnchor = (chunks: React.ReactNode) => (
    <a
      href="https://coral.ai/docs/m2/get-started/"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
    </a>
  )
  const storageLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/storage" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const smartLink = (chunks: React.ReactNode) => (
    <Link href="/docs/disk-manager/smart-disk-test" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const pciSwitchLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/switch-gpu-mode" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={14}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <Callout variant="tip" title={t("thresholds.title")}>
        {t.rich("thresholds.intro", { strong, green, amber, red })}
        <ul className="list-disc pl-6 mt-2 space-y-0.5">
          {thresholdsItems.map((_, idx) => (
            <li key={idx}>{t.rich(`thresholds.items.${idx}`, { strong })}</li>
          ))}
        </ul>
        {t.rich("thresholds.outro", { link: thresholdsLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("sections.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sections.intro", { em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("sections.systemInfoTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("sections.systemInfoIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {systemInfoItems.map((_, idx) => (
          <li key={idx}>{t.rich(`sections.systemInfoItems.${idx}`, { strong })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("sections.memoryTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sections.memoryBody", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("sections.thermalTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sections.thermalIntro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {thermalItems.map((_, idx) => (
          <li key={idx}>{t.rich(`sections.thermalItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("graphics.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("graphics.intro", { em, strong, code, link: switchModeLink })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-graphics-cards-vfio.png"
          alt={t("graphics.vfioImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("graphics.vfioImageCaption", { code })}
        </figcaption>
      </figure>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-graphics-cards-lxc.png"
          alt={t("graphics.lxcImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("graphics.lxcImageCaption")}
        </figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("graphics.realtimeTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("graphics.realtimeBody", { code })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("graphics.toolsIntro")}</p>

      <div className="overflow-x-auto mb-6 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("graphics.headerVendor")}</th>
              <th className="px-4 py-2 font-semibold">{t("graphics.headerTool")}</th>
              <th className="px-4 py-2 font-semibold">{t("graphics.headerProject")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {gpuTools.map((row) => (
              <tr key={row.vendor}>
                <td className="px-4 py-2 align-top whitespace-nowrap"><strong>{row.vendor}</strong></td>
                <td className="px-4 py-2 align-top"><code>{row.tool}</code></td>
                <td className="px-4 py-2 align-top">
                  {row.projectHref ? (
                    <a
                      href={row.projectHref}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline inline-flex items-center gap-1"
                    >
                      {row.projectLabel}
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    </a>
                  ) : (
                    row.projectLabel
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-gpu-nvidia-modal.png"
          alt={t("graphics.nvidiaImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("graphics.nvidiaImageCaption")}
        </figcaption>
      </figure>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-gpu-intel-modal.png"
          alt={t("graphics.intelImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("graphics.intelImageCaption", { code })}
        </figcaption>
      </figure>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-gpu-amd-modal.png"
          alt={t("graphics.amdImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("graphics.amdImageCaption", { code })}
        </figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("graphics.installTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("graphics.installBody", { code, strong, link: nvidiaHostLink })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-gpu-nvidia-no-driver.png"
          alt={t("graphics.noDriverAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("graphics.noDriverCaption")}
        </figcaption>
      </figure>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-gpu-nvidia-install-prompt.png"
          alt={t("graphics.promptAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("graphics.promptCaption")}
        </figcaption>
      </figure>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-gpu-nvidia-install-success.png"
          alt={t("graphics.successAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("graphics.successCaption", { code })}
        </figcaption>
      </figure>

      <Callout variant="warning" title={t("graphics.warningTitle")}>
        {t.rich("graphics.warningBody", { code, em, a: nvidiaAnchor })}
      </Callout>

      <p className="mt-4 mb-2 text-gray-800 leading-relaxed">{t("graphics.whereGoIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {whereGoItems.map((_, idx) => (
          <li key={idx}>{t.rich(`graphics.whereGoItems.${idx}`, { em, link1, link2, link3, link4 })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("coral.heading")} <em>{t("coral.subHeading")}</em>
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("coral.intro", { code })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-coral-tpu-modal.png"
          alt={t("coral.imageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("coral.imageCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("coral.pathsIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {coralPathsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`coral.pathsItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("coral.outro", { installLink, lxcLink, a: coralAnchor })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("storage.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("storage.intro", { code, em })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-storage-summary.png"
          alt={t("storage.imageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("storage.imageCaption", { em })}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("storage.nvmeBody", { strong })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-storage-modal-nvme.png"
          alt={t("storage.nvmeModalAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("storage.nvmeModalCaption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("storage.outro", { em, storageLink, smartLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("pci.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pci.intro", { strong, em, code })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-pci-devices.png"
          alt={t("pci.imageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("pci.imageCaption", { code })}
        </figcaption>
      </figure>

      <Callout variant="tip" title={t("pci.bdfTitle")}>
        {t.rich("pci.bdfBody", { code, link: pciSwitchLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("usb.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("usb.intro", { code, em })}
      </p>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-usb-devices.png"
          alt={t("usb.imageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("usb.imageCaption", { code })}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("power.heading")} <em>{t("power.subHeading")}</em>
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("power.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {powerItems.map((_, idx) => (
          <li key={idx}>{t.rich(`power.items.${idx}`, { strong })}</li>
        ))}
      </ul>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-power-supplies.png"
          alt={t("power.supplyImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("power.supplyImageCaption")}
        </figcaption>
      </figure>

      <figure className="my-6">
        <img
          src="/monitor/hardware/hw-cpu-power.png"
          alt={t("power.cpuImageAlt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("power.cpuImageCaption")}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("psu.heading")} <em>{t("psu.subHeading")}</em>
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("psu.body")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("fans.heading")} <em>{t("fans.subHeading")}</em>
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("fans.body")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("ups.heading")} <em>{t("ups.subHeading")}</em>
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("ups.body", { em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("dataCollected.heading")}</h2>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerSection")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerEndpoint")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerSource")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {dataRows.map((row, idx) => (
              <tr key={row.section} className={idx < dataRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top">{row.section}</td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.endpoint}</td>
                <td className="px-3 py-2 align-top">{t.rich(`dataCollected.rows.${idx}.source`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CopyableCode
        code={`${t("dataCollected.codeComment1")}
lspci -nnk | grep -A2 -E 'VGA|Audio|Network|3D'
sensors

${t("dataCollected.codeComment2")}
curl -H "Authorization: Bearer <token>" \\
  http://<host>:8008/api/hardware | jq '.gpus'`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {whereNextItems.map((item) => (
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
