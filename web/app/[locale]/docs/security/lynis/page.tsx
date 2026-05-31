import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { DataFlowDiagram } from "@/components/ui/data-flow-diagram"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.security.lynis.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/security/lynis",
    },
  }
}

type WhyRow = { sourceRich: string; path: string; update: string; fresh: string }
type ReportRow = { markerRich: string; meaning: string; action: string }
type ReinstallRow = { actionRich: string; whatRich: string }
type RelatedItem = { href: string; label: string; tail?: string; tailRich?: string }

export default async function LynisPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.security.lynis" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { security: { lynis: {
      detection: { items: string[] }
      whyUpstream: { rows: WhyRow[] }
      report: { rows: ReportRow[] }
      reinstall: { rows: ReinstallRow[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const block = messages.docs.security.lynis
  const detectionItems = block.detection.items
  const whyRows = block.whyUpstream.rows
  const reportRows = block.report.rows
  const reinstallRows = block.reinstall.rows
  const relatedItems = block.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const ok = (chunks: React.ReactNode) => <code className="text-emerald-700">{chunks}</code>
  const warn = (chunks: React.ReactNode) => <code className="text-amber-700">{chunks}</code>
  const sugg = (chunks: React.ReactNode) => <code className="text-red-700">{chunks}</code>
  const linkFail2ban = (chunks: React.ReactNode) => (
    <Link href="/docs/security/fail2ban" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const linkSecurityTab = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/security" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={5}
        scriptPath="security/lynis_installer.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manageMenu.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("manageMenu.intro")}</p>

      <Image
        src="/security/lynis-menu.png"
        alt={t("manageMenu.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whyUpstream.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("whyUpstream.intro", { code })}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("whyUpstream.headerSource")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("whyUpstream.headerPath")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("whyUpstream.headerUpdate")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("whyUpstream.headerFresh")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {whyRows.map((row, idx) => (
              <tr key={idx} className={idx < whyRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">{t.rich(`whyUpstream.rows.${idx}.sourceRich`, { strong })}</td>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.path}</td>
                <td className="px-3 py-2 align-top">{row.update}</td>
                <td className="px-3 py-2 align-top">{row.fresh}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("install.heading")}</h2>

      <DataFlowDiagram
        nodes={[
          {
            label: t("install.node1Label"),
            detail: t("install.node1Detail"),
            variant: "source",
          },
          {
            label: t("install.node2Label"),
            detail: t("install.node2Detail"),
            variant: "bridge",
          },
          {
            label: t("install.node3Label"),
            detail: t("install.node3Detail"),
            variant: "target",
          },
        ]}
      />

      <p className="mt-6 mb-4 text-gray-800 leading-relaxed">{t.rich("install.outro", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("detection.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("detection.intro")}</p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {detectionItems.map((_, idx) => (
          <li key={idx}>{t.rich(`detection.items.${idx}`, { code })}</li>
        ))}
      </ol>
      <p className="mb-6 text-gray-800 leading-relaxed">{t.rich("detection.outro", { code, strong })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("audit.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("audit.intro", { strong })}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("audit.code") as string}</pre>
      <p className="mt-4 mb-4 text-gray-800 leading-relaxed">{t.rich("audit.outro", { code, ok, warn, sugg })}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("audit.summary") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("report.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("report.intro", { code, strong })}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("report.headerMarker")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("report.headerMeaning")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("report.headerAction")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {reportRows.map((row, idx) => (
              <tr key={idx} className={idx < reportRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">{t.rich(`report.rows.${idx}.markerRich`, { strong })}</td>
                <td className="px-3 py-2 align-top">{row.meaning}</td>
                <td className="px-3 py-2 align-top">{row.action}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-6 text-gray-800 leading-relaxed">{t.rich("report.outro", { code })}</p>

      <Callout variant="tip" title={t("pairFail2ban.title")}>
        {t.rich("pairFail2ban.body", { code, link: linkFail2ban })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("update.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("update.body", { code, strong })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("reinstall.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("reinstall.headerAction")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("reinstall.headerWhat")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {reinstallRows.map((_, idx) => (
              <tr key={idx} className={idx < reinstallRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">{t.rich(`reinstall.rows.${idx}.actionRich`, { strong })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`reinstall.rows.${idx}.whatRich`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("cli.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("cli.intro")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("cli.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.cloneTitle")}>
        {t.rich("troubleshoot.cloneBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.notFoundTitle")}>
        {t.rich("troubleshoot.notFoundIntro", { code })}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{t.raw("troubleshoot.notFoundCode") as string}</pre>
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.sshTitle")}>
        {t.rich("troubleshoot.sshIntro", { code, link: linkFail2ban })}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{t.raw("troubleshoot.sshCode") as string}</pre>
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.scoreTitle")}>
        {t.rich("troubleshoot.scoreBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("files.heading")}</h2>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("files.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("sample.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("sample.intro", { link: linkSecurityTab })}</p>

      <figure className="my-4">
        <Image
          src="/monitor/security/lynis-report-pdf.png"
          alt={t("sample.imageAlt")}
          width={1414}
          height={2000}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("sample.captionPrefix")}
          <a
            href="/monitor/security/lynis-sample-report.pdf"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline inline-flex items-center gap-1"
          >
            {t("sample.captionLink")}
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>
          {t("sample.captionSuffix")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed text-sm">{t.rich("sample.cli", { code })}</p>

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
