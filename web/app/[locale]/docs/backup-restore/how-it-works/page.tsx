import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.howItWorks.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox backup internals",
      "proxmox manifest json",
      "proxmox backup collectors",
      "packages.manual.list",
      "components_status.json",
      "proxmenux rootfs",
      "proxmox rsync backup",
      "apply_cluster_postboot",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/backup-restore/how-it-works" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/backup-restore/how-it-works",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type CategoryRow = { category: string; paths: string; why: string }
type CollectorRow = { collector: string; produces: string; content: string }
type InstallerRow = { component: string; installer: string; action: string }
type StageRow = { stage: string; name: string; reads: string; action: string }

export default async function HowItWorksPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.howItWorks" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { backupRestore: { howItWorks: {
      rootfs: { categoryRows: CategoryRow[] }
      manifest: { collectorRows: CollectorRow[] }
      applications: { installerRows: InstallerRow[] }
      restoreFlow: { stageRows: StageRow[] }
    } } }
  }
  const hw = messages.docs.backupRestore.howItWorks
  const categoryRows = hw.rootfs.categoryRows
  const collectorRows = hw.manifest.collectorRows
  const installerRows = hw.applications.installerRows
  const stageRows = hw.restoreFlow.stageRows

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={14}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("layout.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("layout.intro", { code, strong })}
      </p>

      <figure className="my-6">
        <pre className="bg-gray-50 border border-gray-200 rounded-md p-4 text-sm font-mono text-gray-800 overflow-x-auto whitespace-pre leading-relaxed">
{t("layout.tree")}
        </pre>
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("layout.treeCaption")}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("rootfs.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("rootfs.intro", { code, strong, em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("rootfs.defaultProfileTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("rootfs.defaultProfileBody", { code, strong })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">{t("rootfs.categoriesTitle")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Paths</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Why</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {categoryRows.map((row, idx) => (
              <tr key={row.category} className={idx < categoryRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.category}</strong></td>
                <td className="px-3 py-2 align-top font-mono text-xs text-gray-700 leading-relaxed">{row.paths}</td>
                <td className="px-3 py-2 align-top">{t.rich(`rootfs.categoryRows.${idx}.why`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("rootfs.customTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("rootfs.customBody", { code, em, strong })}
      </p>

      <h4 className="text-base font-semibold mt-5 mb-2 text-gray-900">
        {t("rootfs.customExtrasTitle")}
      </h4>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("rootfs.customExtrasBody", { code, em, strong })}
      </p>

      <h4 className="text-base font-semibold mt-5 mb-2 text-gray-900">
        {t("rootfs.customModeTitle")}
      </h4>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("rootfs.customModeBody", { code, em, strong })}
      </p>

      <h4 className="text-base font-semibold mt-5 mb-2 text-gray-900">
        {t("rootfs.customMissingTitle")}
      </h4>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("rootfs.customMissingBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("manifest.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("manifest.intro", { code, strong })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Collector</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Produces</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Content</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {collectorRows.map((row, idx) => (
              <tr key={row.collector} className={idx < collectorRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.collector}</strong></td>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap">{row.produces}</td>
                <td className="px-3 py-2 align-top">{t.rich(`manifest.collectorRows.${idx}.content`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-sm text-gray-500 italic text-center mb-6">
        {t("manifest.orchestratorCaption")}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("manifest.schemaTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("manifest.schemaBody", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("applications.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("applications.intro", { code, strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("applications.packagesTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("applications.packagesBody", { code, em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("applications.componentsTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("applications.componentsBody", { code, em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("applications.componentInstallersTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("applications.componentInstallersBody", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Component</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Installer</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Action on <code>--auto-reinstall</code></th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {installerRows.map((row, idx) => (
              <tr key={row.component} className={idx < installerRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.component}</strong></td>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap">{row.installer}</td>
                <td className="px-3 py-2 align-top">{t.rich(`applications.installerRows.${idx}.action`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("restoreFlow.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("restoreFlow.intro", { code, strong })}
      </p>

      <div className="overflow-x-auto mb-2">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">#</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Stage</th>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">Reads</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Action</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {stageRows.map((row, idx) => (
              <tr key={row.stage} className={idx < stageRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs"><strong>{row.stage}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.name}</strong></td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.reads}</td>
                <td className="px-3 py-2 align-top">{t.rich(`restoreFlow.stageRows.${idx}.action`, { code, em })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-sm text-gray-500 italic text-center mb-6">
        {t("restoreFlow.stagesCaption")}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("whyItWorks.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("whyItWorks.body", { code, strong })}
      </p>
    </div>
  )
}
