import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { DataFlowDiagram } from "@/components/ui/data-flow-diagram"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.utils.importVm.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/utils/import-vm",
    },
  }
}

type StringItem = string
type FlowNode = { label: string; detail: string; variant: "source" | "bridge" | "target" }
type OvfRow = { field: string; source: string; default: string }
type PostRow = { setting: string; default: string; recommended?: string; recommendedRich?: string }
type RelatedItem = { href: string; label: string; tail?: string; tailRich?: string }

export default async function ImportVmPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.utils.importVm" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { utils: { importVm: {
      picker: { items: StringItem[] }
      flow: { nodes: FlowNode[] }
      ovf: { rows: OvfRow[] }
      dialog: { items: StringItem[] }
      diskLoop: { items: StringItem[] }
      postImport: { rows: PostRow[] }
      notImported: { items: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const block = messages.docs.utils.importVm
  const pickerItems = block.picker.items
  const flowNodes = block.flow.nodes
  const ovfRows = block.ovf.rows
  const dialogItems = block.dialog.items
  const diskLoopItems = block.diskLoop.items
  const postRows = block.postImport.rows
  const notImportedItems = block.notImported.items
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
        scriptPath="utilities/import_vm_ova_ovf.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("picker.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("picker.intro")}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {pickerItems.map((_, idx) => (
          <li key={idx}>{t.rich(`picker.items.${idx}`, { code })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">{t.rich("picker.outro", { code })}</p>

      <Image
        src="/utils/import-vm-picker.png"
        alt={t("picker.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("flow.heading")}</h2>

      <DataFlowDiagram
        nodes={flowNodes.map((n) => ({ label: n.label, detail: n.detail, variant: n.variant }))}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("ovf.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("ovf.intro", { code, strong })}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("ovf.headerField")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("ovf.headerSource")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("ovf.headerDefault")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {ovfRows.map((row, idx) => (
              <tr key={idx} className={idx < ovfRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.field}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.source}</td>
                <td className="px-3 py-2 align-top">{row.default}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="warning" title={t("memWarn.title")}>
        {t.rich("memWarn.body", { code, strong, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("dialog.heading")}</h2>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-2">
        {dialogItems.map((_, idx) => (
          <li key={idx}>{t.rich(`dialog.items.${idx}`, { code, strong })}</li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("create.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("create.intro")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("create.code") as string}</pre>
      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">{t.rich("create.outro", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("diskLoop.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("diskLoop.intro")}</p>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {diskLoopItems.map((_, idx) => (
          <li key={idx}>{t.rich(`diskLoop.items.${idx}`, { code })}</li>
        ))}
      </ol>
      <p className="mb-6 text-gray-800 leading-relaxed">{t.rich("diskLoop.outro", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("postImport.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("postImport.intro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("postImport.headerSetting")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("postImport.headerDefault")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("postImport.headerRecommended")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {postRows.map((row, idx) => (
              <tr key={idx} className={idx < postRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.setting}</strong></td>
                <td className="px-3 py-2 align-top">{row.default}</td>
                <td className="px-3 py-2 align-top">
                  {row.recommendedRich
                    ? t.rich(`postImport.rows.${idx}.recommendedRich`, { code })
                    : row.recommended}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="warning" title={t("fwWarn.title")}>
        {t.rich("fwWarn.body", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("notImported.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {notImportedItems.map((_, idx) => (
          <li key={idx}>{t.rich(`notImported.items.${idx}`, { strong })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.orphanTitle")}>
        {t("troubleshoot.orphanIntro")}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{t.raw("troubleshoot.orphanCode") as string}</pre>
        {t("troubleshoot.orphanOutro")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.memTitle")}>
        {t("troubleshoot.memIntro")}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{t.raw("troubleshoot.memCode") as string}</pre>
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.bootTitle")}>
        {t("troubleshoot.bootIntro")}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{t.raw("troubleshoot.bootCode") as string}</pre>
        {t("troubleshoot.bootOutro")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.bsodTitle")}>
        {t.rich("troubleshoot.bsodBody", { code, em })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.zeroTitle")}>
        {t.rich("troubleshoot.zeroBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.awkTitle")}>
        {t.rich("troubleshoot.awkIntro", { code })}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{t.raw("troubleshoot.awkCode") as string}</pre>
        {t("troubleshoot.awkOutro")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.netTitle")}>
        {t.rich("troubleshoot.netBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("files.heading")}</h2>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("files.code") as string}</pre>

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
