import type { Metadata } from "next"
import Image from "next/image"
import { ExternalLink } from "lucide-react"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.security.sslLetsencrypt.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/security/ssl-letsencrypt",
    },
    alternates: { canonical: "https://proxmenux.com/docs/security/ssl-letsencrypt" },
  }
}

type StringItem = string
type TableRow = {
  fileRich: string
  originRich?: string
  origin?: string
  when?: string
  whenRich?: string
}

export default async function SslLetsEncryptPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.security.sslLetsencrypt" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: {
      security: {
        sslLetsencrypt: {
          twoways: {
            proxmox: { items: StringItem[] }
            custom: { items: StringItem[] }
          }
          proxmoxCert: { table: { rows: TableRow[] } }
          letsencrypt: { prereqs: { items: StringItem[] } }
          custom: { items: StringItem[] }
          trustCa: { items: StringItem[] }
        }
      }
    }
  }

  const block = messages.docs.security.sslLetsencrypt
  const proxmoxItems = block.twoways.proxmox.items
  const customItems = block.twoways.custom.items
  const tableRows = block.proxmoxCert.table.rows
  const prereqItems = block.letsencrypt.prereqs.items
  const customListItems = block.custom.items
  const trustCaItems = block.trustCa.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const br = () => <br />
  const extlink1 = (chunks: React.ReactNode) => (
    <a
      href="https://pve.proxmox.com/wiki/Certificate_Management"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const extlink2 = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/acmesh-official/acme.sh/wiki/dnsapi"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={5}
        scriptPath="AppImage/scripts/auth_manager.py"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("wheresetting.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("wheresetting.body", { strong })}
      </p>

      <figure className="my-6">
        <Image
          src="/monitor/security/ssl-https-card.png"
          alt={t("wheresetting.imageAlt")}
          width={2000}
          height={1124}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("wheresetting.caption")}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("twoways.heading")}</h2>

      <div className="grid gap-4 md:grid-cols-2 mb-8 not-prose">
        <div className="rounded-lg border-2 border-green-300 bg-green-50 p-5">
          <h3 className="text-lg font-semibold text-gray-900 mb-2">{t("twoways.proxmox.title")}</h3>
          <p className="text-sm text-gray-800 mb-3">{t("twoways.proxmox.summary")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {proxmoxItems.map((_, idx) => (
              <li key={idx}>{t(`twoways.proxmox.items.${idx}`)}</li>
            ))}
          </ul>
        </div>

        <div className="rounded-lg border-2 border-blue-300 bg-blue-50 p-5">
          <h3 className="text-lg font-semibold text-gray-900 mb-2">{t("twoways.custom.title")}</h3>
          <p className="text-sm text-gray-800 mb-3">
            {t.rich("twoways.custom.summaryRich", { code })}
          </p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {customItems.map((_, idx) => (
              <li key={idx}>{t.rich(`twoways.custom.items.${idx}`, { code })}</li>
            ))}
          </ul>
        </div>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("proxmoxCert.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("proxmoxCert.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">
                {t("proxmoxCert.table.headers.file")}
              </th>
              <th className="text-left px-3 py-2 border-b border-gray-200">
                {t("proxmoxCert.table.headers.origin")}
              </th>
              <th className="text-left px-3 py-2 border-b border-gray-200">
                {t("proxmoxCert.table.headers.when")}
              </th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {tableRows.map((row, idx) => (
              <tr
                key={idx}
                className={idx < tableRows.length - 1 ? "border-b border-gray-100" : ""}
              >
                <td className="px-3 py-2 align-top whitespace-nowrap">
                  {t.rich(`proxmoxCert.table.rows.${idx}.fileRich`, { code, br })}
                </td>
                <td className="px-3 py-2 align-top">
                  {row.originRich
                    ? t.rich(`proxmoxCert.table.rows.${idx}.originRich`, { code, strong, em })
                    : t(`proxmoxCert.table.rows.${idx}.origin`)}
                </td>
                <td className="px-3 py-2 align-top">
                  {row.whenRich
                    ? t.rich(`proxmoxCert.table.rows.${idx}.whenRich`, { code })
                    : t(`proxmoxCert.table.rows.${idx}.when`)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("proxmoxCert.callout.title")}>
        {t.rich("proxmoxCert.callout.bodyRich", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("letsencrypt.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("letsencrypt.intro", { code, em, extlink1 })}
      </p>

      <Callout variant="info" title={t("letsencrypt.prereqs.title")}>
        <ul className="list-disc pl-5 space-y-1 mb-0">
          {prereqItems.map((_, idx) => (
            <li key={idx}>{t.rich(`letsencrypt.prereqs.items.${idx}`, { strong })}</li>
          ))}
        </ul>
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">
        {t("letsencrypt.step1.heading")}
      </h3>
      <p className="mb-2 text-gray-800 leading-relaxed">
        {t.rich("letsencrypt.step1.introRich", { code })}
      </p>
      <pre className="rounded-md bg-gray-900 text-gray-100 p-4 overflow-x-auto text-xs font-mono mb-4">
        {t("letsencrypt.step1.code")}
      </pre>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("letsencrypt.step1.afterRich", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">
        {t("letsencrypt.step2.heading")}
      </h3>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("letsencrypt.step2.http01Rich", { code, strong })}
      </p>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("letsencrypt.step2.dns01Rich", { strong })}
      </p>
      <pre className="rounded-md bg-gray-900 text-gray-100 p-4 overflow-x-auto text-xs font-mono mb-4">
        {t("letsencrypt.step2.code")}
      </pre>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("letsencrypt.step2.outroRich", { code, extlink2 })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">
        {t("letsencrypt.step3.heading")}
      </h3>
      <p className="mb-2 text-gray-800 leading-relaxed">
        {t.rich("letsencrypt.step3.http01Rich", { code })}
      </p>
      <pre className="rounded-md bg-gray-900 text-gray-100 p-4 overflow-x-auto text-xs font-mono mb-3">
        {t("letsencrypt.step3.code1")}
      </pre>
      <p className="mb-2 text-gray-800 leading-relaxed">{t("letsencrypt.step3.dns01")}</p>
      <pre className="rounded-md bg-gray-900 text-gray-100 p-4 overflow-x-auto text-xs font-mono mb-4">
        {t("letsencrypt.step3.code2")}
      </pre>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("letsencrypt.step3.wildcardRich", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">
        {t("letsencrypt.step4.heading")}
      </h3>
      <pre className="rounded-md bg-gray-900 text-gray-100 p-4 overflow-x-auto text-xs font-mono mb-3">
        {t("letsencrypt.step4.code")}
      </pre>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("letsencrypt.step4.afterRich", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">
        {t("letsencrypt.step5.heading")}
      </h3>
      <pre className="rounded-md bg-gray-900 text-gray-100 p-4 overflow-x-auto text-xs font-mono mb-3">
        {t("letsencrypt.step5.code")}
      </pre>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("letsencrypt.step5.afterRich", { code })}
      </p>

      <Callout variant="tip" title={t("letsencrypt.gui.title")}>
        {t.rich("letsencrypt.gui.bodyRich", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        {t("switchToHttps.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("switchToHttps.bodyRich", { code, strong, em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("custom.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("custom.intro", { strong })}
      </p>
      <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-4">
        {customListItems.map((_, idx) => (
          <li key={idx}>{t.rich(`custom.items.${idx}`, { code, strong })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("custom.outro")}</p>

      <pre className="rounded-md bg-gray-900 text-gray-100 p-4 overflow-x-auto text-xs font-mono mb-4">
        {t("custom.code")}
      </pre>

      <Callout variant="warning" title={t("custom.symlinkCallout.title")}>
        {t.rich("custom.symlinkCallout.bodyRich", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("afterHttps.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("afterHttps.bodyRich", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">
        {t("afterHttps.reverse.heading")}
      </h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("afterHttps.reverse.bodyRich", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("trustCa.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("trustCa.intro1Rich", { code })}
      </p>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("trustCa.intro2Rich", { code })}
      </p>
      <pre className="rounded-md bg-gray-900 text-gray-100 p-4 overflow-x-auto text-xs font-mono mb-4">
        {t("trustCa.code")}
      </pre>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("trustCa.thenImport")}</p>
      <ul className="list-disc pl-6 space-y-2 text-gray-800 mb-4">
        {trustCaItems.map((_, idx) => (
          <li key={idx}>{t.rich(`trustCa.items.${idx}`, { code, strong, em })}</li>
        ))}
      </ul>
      <Callout variant="info" title={t("trustCa.standalone.title")}>
        {t.rich("trustCa.standalone.bodyRich", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("disable.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("disable.bodyRich", { strong })}
      </p>

      <Callout variant="info" title={t("disable.stateCallout.title")}>
        {t.rich("disable.stateCallout.bodyRich", { code })}
      </Callout>
    </div>
  )
}
