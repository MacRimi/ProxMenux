import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.utils.exportVm.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/utils/export-vm",
    },
  }
}

type StringItem = string
type FormatRow = { format: string; output: string; pros: string; cons: string }
type ImportItem = { href?: string; preRich?: string; linkLabel?: string; tailRich?: string }
type RelatedItem = { href: string; label: string; tail?: string; tailRich?: string }

export default async function ExportVmPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.utils.exportVm" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { utils: { exportVm: {
      stopped: { items: StringItem[] }
      format: { rows: FormatRow[] }
      exported: { items: StringItem[]; notItems: StringItem[] }
      import: { items: ImportItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const block = messages.docs.utils.exportVm
  const stoppedItems = block.stopped.items
  const formatRows = block.format.rows
  const exportedItems = block.exported.items
  const notExportedItems = block.exported.notItems
  const importItems = block.import.items
  const relatedItems = block.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={6}
        scriptPath="utilities/export_vm_ova_ovf.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("picker.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("picker.body", { code })}
      </p>

      <Image
        src="/utils/export-vm-picker.png"
        alt={t("picker.imgAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("stopped.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("stopped.intro")}</p>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {stoppedItems.map((_, idx) => (
          <li key={idx}>{t.rich(`stopped.items.${idx}`, { code })}</li>
        ))}
      </ol>
      <Callout variant="warning" title={t("stopped.warnTitle")}>
        {t.rich("stopped.warnBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("format.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("format.headerFormat")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("format.headerOutput")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("format.headerPros")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("format.headerCons")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {formatRows.map((row, idx) => (
              <tr key={row.format} className={idx < formatRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.format}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.output}</td>
                <td className="px-3 py-2 align-top">{row.pros}</td>
                <td className="px-3 py-2 align-top">{row.cons}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("destination.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("destination.body", { code })}
      </p>
      <Callout variant="info" title={t("destination.calloutTitle")}>
        {t("destination.calloutBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("package.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("package.intro", { code })}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("package.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("exported.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {exportedItems.map((_, idx) => (
          <li key={idx}>{t.rich(`exported.items.${idx}`, { code, strong })}</li>
        ))}
      </ul>
      <Callout variant="warning" title={t("exported.notTitle")}>
        <ul className="list-disc pl-6 mb-0 space-y-1">
          {notExportedItems.map((_, idx) => (
            <li key={idx}>{t.rich(`exported.notItems.${idx}`, { code, strong })}</li>
          ))}
        </ul>
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("conversion.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("conversion.intro")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("conversion.code") as string}</pre>
      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">
        {t.rich("conversion.outro", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manifest.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("manifest.intro", { code })}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("manifest.code") as string}</pre>
      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">
        {t.rich("manifest.outro", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("import.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("import.intro")}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {importItems.map((item, idx) => (
          <li key={idx}>
            {item.href && item.linkLabel ? (
              <>
                {t.rich(`import.items.${idx}.preRich`, { strong })}
                <Link href={item.href} className="text-blue-600 hover:underline">
                  {item.linkLabel}
                </Link>
                {t.rich(`import.items.${idx}.tailRich`, { strong })}
              </>
            ) : (
              t.rich(`import.items.${idx}.tailRich`, { strong })
            )}
          </li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.noSpaceTitle")}>
        {t("troubleshoot.noSpaceBody")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.unsupportedHwTitle")}>
        {t.rich("troubleshoot.unsupportedHwBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.nicTitle")}>
        {t.rich("troubleshoot.nicBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.runningTitle")}>
        {t.rich("troubleshoot.runningBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.slowTitle")}>
        {t.rich("troubleshoot.slowBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item, idx) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tailRich ? t.rich(`related.items.${idx}.tailRich`, { code }) : item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
