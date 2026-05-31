import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.network.configAnalysis.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/network/config-analysis",
    },
  }
}

type DiffersRow = { aspect: string; bridge: string; config: string }
type Step = { title: string; body: string; tone: "blue" | "amber" | "emerald" }
type RelatedItem = { label: string; href: string; tail?: string; tailRich?: string }

const TONE_CLASSES: Record<string, string> = {
  blue: "border-blue-400 bg-blue-50",
  amber: "border-amber-400 bg-amber-50",
  emerald: "border-emerald-400 bg-emerald-50",
}

export default async function ConfigAnalysisPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.network.configAnalysis" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { network: { configAnalysis: {
      differs: { rows: DiffersRow[] }
      step2: { steps: Step[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const differsRows = messages.docs.network.configAnalysis.differs.rows
  const cleanupSteps = messages.docs.network.configAnalysis.step2.steps
  const relatedItems = messages.docs.network.configAnalysis.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const bridgeLink = (chunks: React.ReactNode) => (
    <Link href="/docs/network/bridge-analysis" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const persistentLink = (chunks: React.ReactNode) => (
    <Link href="/docs/network/persistent-names" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const link = bridgeLink

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={5}
        scriptPath="menus/network_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("differs.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("differs.headerAspect")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("differs.headerBridge")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("differs.headerConfig")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {differsRows.map((row, idx) => (
              <tr key={idx} className={idx < differsRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">
                  <strong>{t.rich(`differs.rows.${idx}.aspect`, { code })}</strong>
                </td>
                <td className="px-3 py-2 align-top">{t.rich(`differs.rows.${idx}.bridge`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`differs.rows.${idx}.config`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("differs.outro", { strong, link })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("step1.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("step1.intro")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`🔍 NETWORK CONFIGURATION ANALYSIS
==================================================

📋 CONFIGURED INTERFACES
==============================
🔌 Interface: enp3s0
   ❌ Status: NOT FOUND
   ⚠️  Issue: Configured but doesn't exist

🔌 Interface: eno1
   ✅ Status: EXISTS (UP)
   🌐 IP: 192.168.1.10/24
   ℹ️  Type: Physical interface

🔌 Interface: vmbr0
   ✅ Status: EXISTS (UP)
   🌐 IP: 192.168.1.10/24
   ℹ️  Type: Virtual interface (normal)

🔧 SUGGESTION FOR enp3s0:
   This interface is configured but doesn't exist physically
   Consider removing its configuration
   Command: sed -i '/iface enp3s0/,/^$/d' /etc/network/interfaces

📊 ANALYSIS SUMMARY
=========================
Interfaces configured: 3
Issues found: 1

⚠️  IMPORTANT: No changes have been made to your system
Use the Guided Cleanup option to fix issues safely`}</pre>

      <Callout variant="success" title={t("step1.virtTitle")}>
        {t.rich("step1.virtBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("step2.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("step2.intro")}</p>

      <div className="space-y-4 mb-6">
        {cleanupSteps.map((step, idx) => (
          <div key={idx} className={`border-l-4 ${TONE_CLASSES[step.tone]} p-4 rounded-r-md`}>
            <div className="font-semibold text-gray-900 mb-1">{step.title}</div>
            <p className="text-sm text-gray-800 m-0">{t.rich(`step2.steps.${idx}.body`, { code, em, strong })}</p>
          </div>
        ))}
      </div>

      <Callout variant="warning" title={t("step2.noRestartTitle")}>
        {t.rich("step2.noRestartBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("caveats.heading")}</h2>

      <Callout variant="warning" title={t("caveats.boundaryTitle")}>
        {t.rich("caveats.boundaryBody", { code, strong })}
      </Callout>

      <Callout variant="info" title={t("caveats.tandemTitle")}>
        {t.rich("caveats.tandemBody", { code, link: bridgeLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.notFoundTitle")}>
        {t.rich("troubleshoot.notFoundBody", { code, link: persistentLink })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.tooMuchTitle")}>
        {t("troubleshoot.tooMuchBody")}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{`cp /var/backups/proxmenux/interfaces_backup_<TIMESTAMP> /etc/network/interfaces`}</pre>
        {t("troubleshoot.tooMuchOutro")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.bridgeBreakTitle")}>
        {t.rich("troubleshoot.bridgeBreakBody", { code, link: bridgeLink })}
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
