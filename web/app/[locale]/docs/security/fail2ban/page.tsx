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
  const t = await getTranslations({ locale, namespace: "docs.security.fail2ban.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/security/fail2ban",
    },
  }
}

type JailRow = { jail: string; protects: string; retries: string; ban: string }
type LoggerRow = { service: string; source: string; output: string }
type ManageRow = { action: string; what: string }

export default async function Fail2BanPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.security.fail2ban" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { security: { fail2ban: {
      jails: { rows: JailRow[] }
      loggers: { rows: LoggerRow[] }
      manage: { rows: ManageRow[] }
      hardening: { items: string[] }
    } } }
  }
  const block = messages.docs.security.fail2ban
  const jailRows = block.jails.rows
  const loggerRows = block.loggers.rows
  const manageRows = block.manage.rows
  const hardeningItems = block.hardening.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const codeNw = (chunks: React.ReactNode) => <code className="whitespace-nowrap">{chunks}</code>
  const codeXs = (chunks: React.ReactNode) => <code className="text-xs">{chunks}</code>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={8}
        scriptPath="security/fail2ban_installer.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("firstLaunch.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("firstLaunch.body")}
      </p>

      <Image
        src="/security/fail2ban-install.png"
        alt={t("firstLaunch.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("jails.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("jails.headerJail")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("jails.headerProtects")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("jails.headerRetries")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("jails.headerBan")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {jailRows.map((row, idx) => (
              <tr key={row.jail} className={idx < jailRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.jail}</strong></td>
                <td className="px-3 py-2 align-top">{row.protects}</td>
                <td className="px-3 py-2 align-top whitespace-nowrap">{row.retries}</td>
                <td className="px-3 py-2 align-top whitespace-nowrap">{row.ban}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("jails.outro", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("journald.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("journald.intro", { code, codeNw, em })}
      </p>

      <DataFlowDiagram
        nodes={[
          {
            label: t("journald.diagram.sshLabel"),
            detail: t("journald.diagram.sshDetail"),
            variant: "source",
          },
          {
            label: t("journald.diagram.journaldLabel"),
            detail: t("journald.diagram.journaldDetail"),
            variant: "bridge",
          },
          {
            label: t("journald.diagram.fail2banLabel"),
            detail: t("journald.diagram.fail2banDetail"),
            variant: "target",
          },
        ]}
        arrowLabel={t("journald.diagram.arrowLabel")}
      />

      <p className="mt-6 mb-4 text-gray-800 leading-relaxed">
        {t.rich("journald.afterDiagram", { code, codeXs })}
      </p>

      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("journald.code") as string}</pre>

      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">
        {t.rich("journald.outro", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("loggers.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("loggers.intro1", { code })}
      </p>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("loggers.intro2", { code })}
      </p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("loggers.headerService")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("loggers.headerSource")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("loggers.headerOutput")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {loggerRows.map((row, idx) => (
              <tr key={row.service} className={idx < loggerRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs"><strong>{row.service}</strong></td>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.source}</td>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.output}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("loggers.outro", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("backend.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("backend.intro", { code })}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("backend.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("hardening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("hardening.intro", { code, strong })}
      </p>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("hardening.installerIntro")}
      </p>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {hardeningItems.map((_, idx) => (
          <li key={idx}>{t.rich(`hardening.items.${idx}`, { code, strong })}</li>
        ))}
      </ol>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("hardening.outro", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manage.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("manage.intro")}
      </p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("manage.headerAction")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("manage.headerWhat")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {manageRows.map((row, idx) => (
              <tr key={row.action} className={idx < manageRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.action}</strong></td>
                <td className="px-3 py-2 align-top">{row.what}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verify.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("verify.intro")}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("verify.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.neverBansTitle")}>
        {t.rich("troubleshoot.neverBansBody", { code, em })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.monitorEmptyTitle")}>
        {t.rich("troubleshoot.monitorEmptyBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.selfBanTitle")}>
        {t("troubleshoot.selfBanIntro")}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{t.raw("troubleshoot.selfBanCode") as string}</pre>
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.aptFailTitle")}>
        {t.rich("troubleshoot.aptFailBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.lockoutTitle")}>
        {t.rich("troubleshoot.lockoutBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("files.heading")}</h2>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("files.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        <li>
          <Link href="/docs/monitor/dashboard/security" className="text-blue-600 hover:underline">
            {t("related.monitorLabel")}
          </Link>
          {t("related.monitorTail")}
        </li>
        <li>
          <Link href="/docs/security/lynis" className="text-blue-600 hover:underline">
            {t("related.lynisLabel")}
          </Link>
          {t("related.lynisTail")}
        </li>
        <li>
          <Link href="/docs/security" className="text-blue-600 hover:underline">
            {t("related.securityLabel")}
          </Link>
          {t("related.securityTail")}
        </li>
      </ul>
    </div>
  )
}
