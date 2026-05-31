import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.postInstall.virtualization.meta" })
  return { title: t("title"), description: t("description") }
}

type GuestRow = { detected: string; package: string }
type BootRow = { boot: string; file: string; post: string }
type RelatedItem = { label: string; href: string; tail: string }

export default async function PostInstallVirtualizationPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.virtualization" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { virtualization: {
      guestAgent: { rows: GuestRow[] }
      vfio: {
        whoItems: string[]
        bootRows: BootRow[]
        pathItems: string[]
      }
      related: { items: RelatedItem[] }
    } } }
  }
  const v = messages.docs.postInstall.virtualization
  const guestRows = v.guestAgent.rows
  const whoItems = v.vfio.whoItems
  const bootRows = v.vfio.bootRows
  const pathItems = v.vfio.pathItems
  const relatedItems = v.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const nvidiaHostLink = (chunks: React.ReactNode) => (
    <Link href="/docs/hardware/nvidia-host" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const uninstallLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/uninstall" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        section={t("header.section")}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("guestAgent.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("guestAgent.intro", { code })}
      </p>

      <div className="my-4 overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("guestAgent.headerDetected")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("guestAgent.headerPackage")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {guestRows.map((row) => (
              <tr key={row.detected}>
                <td className="border border-gray-200 px-3 py-2">{row.detected}</td>
                <td className="border border-gray-200 px-3 py-2"><code>{row.package}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("guestAgent.skipTitle")}>
        {t.rich("guestAgent.skipBody", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("vfio.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("vfio.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("vfio.whoTitle")}</h3>
      <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-4">
        {whoItems.map((_, idx) => (
          <li key={idx}>{t.rich(`vfio.whoItems.${idx}`, { em })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("vfio.whoOutro", { strong, em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("vfio.doesTitle")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("vfio.doesIntro")}</p>

      <div className="my-4 overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("vfio.headerBoot")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("vfio.headerFile")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("vfio.headerPost")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {bootRows.map((row) => (
              <tr key={row.boot}>
                <td className="border border-gray-200 px-3 py-2">{row.boot}</td>
                <td className="border border-gray-200 px-3 py-2"><code>{row.file}</code></td>
                <td className="border border-gray-200 px-3 py-2"><code>{row.post}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-3 text-gray-800 leading-relaxed">{t("vfio.kernelIntro")}</p>
      <CopyableCode
        code={`# Intel CPU → intel_iommu=on
# AMD CPU   → amd_iommu=on
# Plus these in both cases:
iommu=pt
pcie_acs_override=downstream,multifunction`}
        className="my-4"
      />

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("vfio.modulesIntro", { code })}
      </p>
      <CopyableCode
        code={`vfio
vfio_iommu_type1
vfio_pci
vfio_virqfd   # only on kernels < 6.2 (merged into vfio in 6.2+)`}
        className="my-4"
      />

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("vfio.blacklistIntro", { code })}
      </p>
      <CopyableCode
        code={`nouveau
lbm-nouveau
radeon
nvidia
nvidiafb
options nouveau modeset=0`}
        className="my-4"
      />

      <Callout variant="warning" title={t("vfio.blacklistTitle")}>
        {t.rich("vfio.blacklistBody", { em, strong, link: nvidiaHostLink })}
      </Callout>

      <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-4">
        {pathItems.map((_, idx) => (
          <li key={idx}>{t.rich(`vfio.pathItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <Callout variant="warning" title={t("vfio.rebootTitle")}>
        {t.rich("vfio.rebootBody", { code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("vfio.verifyTitle")}</h3>
      <CopyableCode
        code={`# IOMMU is actually on
dmesg | grep -E "DMAR|IOMMU" | head
# Expect lines like "IOMMU enabled" / "DMAR: IOMMU enabled"

# VFIO modules loaded
lsmod | grep vfio

# See your IOMMU groups — each "Group N" can be passed independently
for d in /sys/kernel/iommu_groups/*/devices/*; do
  n=${"${d#*/iommu_groups/*}"}; n=${"${n%%/*}"}
  printf 'Group %s  ' "$n"; lspci -nns "${"${d##*/}"}"
done | sort -V`}
        className="my-4"
      />

      <Callout variant="tip" title={t("vfio.revertTitle")}>
        {t.rich("vfio.revertBody", { code, link: uninstallLink })}
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
