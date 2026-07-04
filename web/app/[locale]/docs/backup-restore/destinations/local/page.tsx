import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.destinations.local.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox local backup",
      "tar.zst archive",
      "proxmox backup usb",
      "proxmenux local destination",
      "proxmox backup to usb drive",
      "vzdump directory",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/backup-restore/destinations/local" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/backup-restore/destinations/local",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type OptionItem = string
type StateRow = { state: string; shown: string; action: string }

export default async function LocalDestinationPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.backupRestore.destinations.local" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { backupRestore: { destinations: { local: {
      targetConfig: { options: OptionItem[] }
      usbFlow: { stateRows: StateRow[] }
    } } } }
  }
  const loc = messages.docs.backupRestore.destinations.local
  const options = loc.targetConfig.options
  const stateRows = loc.usbFlow.stateRows

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={7}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("targetConfig.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("targetConfig.intro", { code, strong, em })}
      </p>

      <ul className="mb-6 space-y-3">
        {options.map((_, idx) => (
          <li key={idx} className="text-gray-800 leading-relaxed pl-1">
            <span className="text-gray-400 mr-2">•</span>
            {t.rich(`targetConfig.options.${idx}`, { code, strong })}
          </li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("usbFlow.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("usbFlow.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("usbFlow.statesTitle")}
      </h3>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200 whitespace-nowrap">State</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Menu entry</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">Action</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {stateRows.map((row, idx) => (
              <tr key={row.state} className={idx < stateRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs whitespace-nowrap"><strong>{row.state}</strong></td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.shown}</td>
                <td className="px-3 py-2 align-top">{t.rich(`usbFlow.stateRows.${idx}.action`, { code, strong })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-sm text-gray-700 mb-6 leading-relaxed">
        {t.rich("usbFlow.notMountedFallback", { code, em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("safetyCheck.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("safetyCheck.body", { code, strong })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("archiveFormat.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("archiveFormat.intro", { code, strong })}
      </p>

      <CopyableCode code={t("archiveFormat.namePattern")} language="text" />

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("archiveFormat.compressionTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("archiveFormat.compressionBody", { code, strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("archiveFormat.sourceTitle")}
      </h3>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("archiveFormat.sourceBody", { code, strong })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("sidecar.heading")}
      </h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sidecar.intro", { code, strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">
        {t("sidecar.contentTitle")}
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sidecar.contentBody", { code })}
      </p>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("sidecar.whyBody", { code, strong })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("restoreAccess.heading")}
      </h2>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("restoreAccess.body", { code, strong })}
      </p>
    </div>
  )
}
