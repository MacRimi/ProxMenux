import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { DataFlowDiagram } from "@/components/ui/data-flow-diagram"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.network.bridgeAnalysis.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/network/bridge-analysis",
    },
  }
}

type Step = { title: string; body: string; tone: "blue" | "amber" | "emerald" }
type RelatedItem = { label: string; href: string; tail?: string; tailRich?: string }

const TONE_CLASSES: Record<string, string> = {
  blue: "border-blue-400 bg-blue-50",
  amber: "border-amber-400 bg-amber-50",
  emerald: "border-emerald-400 bg-emerald-50",
}

export default async function BridgeAnalysisPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.network.bridgeAnalysis" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { network: { bridgeAnalysis: {
      when: { items: string[] }
      step1: { items: string[] }
      step2: { steps: Step[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const whenItems = messages.docs.network.bridgeAnalysis.when.items
  const step1Items = messages.docs.network.bridgeAnalysis.step1.items
  const repairSteps = messages.docs.network.bridgeAnalysis.step2.steps
  const relatedItems = messages.docs.network.bridgeAnalysis.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const persistentLink = (chunks: React.ReactNode) => (
    <Link href="/docs/network/persistent-names" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const configLink = (chunks: React.ReactNode) => (
    <Link href="/docs/network/config-analysis" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={6}
        scriptPath="menus/network_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("when.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("when.intro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {whenItems.map((_, idx) => (
          <li key={idx}>{t.rich(`when.items.${idx}`, { code })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("when.outro", { link: persistentLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("bigPicture.heading")}</h2>

      <DataFlowDiagram
        nodes={[
          {
            label: t("bigPicture.diagram1.nodes.sourceLabel"),
            detail: t("bigPicture.diagram1.nodes.sourceDetail"),
            variant: "source",
          },
          {
            label: t("bigPicture.diagram1.nodes.bridgeLabel"),
            detail: t("bigPicture.diagram1.nodes.bridgeDetail"),
            variant: "bridge",
          },
          {
            label: t("bigPicture.diagram1.nodes.targetLabel"),
            detail: t("bigPicture.diagram1.nodes.targetDetail"),
            variant: "target",
          },
        ]}
        arrowLabel={t("bigPicture.diagram1.arrowLabel")}
      />

      <DataFlowDiagram
        nodes={[
          {
            label: t("bigPicture.diagram2.nodes.sourceLabel"),
            detail: t("bigPicture.diagram2.nodes.sourceDetail"),
            variant: "source",
          },
          {
            label: t("bigPicture.diagram2.nodes.targetLabel"),
            detail: t("bigPicture.diagram2.nodes.targetDetail"),
            variant: "target",
          },
        ]}
        arrowLabel={t("bigPicture.diagram2.arrowLabel")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("step1.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("step1.intro", { strong })}
      </p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {step1Items.map((_, idx) => (
          <li key={idx}>{t.rich(`step1.items.${idx}`, { code })}</li>
        ))}
      </ul>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`🔍 BRIDGE CONFIGURATION ANALYSIS
==================================================

🌉 Bridge: vmbr0
   📍 Status: DOWN
   🌐 IP: No IP assigned
   🔌 Configured Ports: enp3s0
   ❌ Port enp3s0: NOT FOUND

🔧 SUGGESTION FOR vmbr0:
   Replace invalid port(s) 'enp3s0' with: eno1
   Command: sed -i 's/bridge-ports.*/bridge-ports eno1/' /etc/network/interfaces

📊 ANALYSIS SUMMARY
=========================
Bridges analyzed: 1
Issues found: 1
Physical interfaces available: 2

⚠️  IMPORTANT: No changes have been made to your system
Use the Guided Repair option to fix issues safely`}</pre>

      <Callout variant="success" title={t("step1.readonlyTitle")}>
        {t.rich("step1.readonlyBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("step2.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("step2.intro")}</p>

      <div className="space-y-4 mb-6">
        {repairSteps.map((step, idx) => (
          <div key={idx} className={`border-l-4 ${TONE_CLASSES[step.tone]} p-4 rounded-r-md`}>
            <div className="font-semibold text-gray-900 mb-1">{step.title}</div>
            <p className="text-sm text-gray-800 m-0">{t.rich(`step2.steps.${idx}.body`, { code, em, strong })}</p>
          </div>
        ))}
      </div>

      <Callout variant="warning" title={t("step2.restartTitle")}>
        {t.rich("step2.restartBody", { code, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("edits.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("edits.body", { code, link: configLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.unsupportedTitle")}>
        {t.rich("troubleshoot.unsupportedBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.noSuggestTitle")}>
        {t.rich("troubleshoot.noSuggestBody", { code, em })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.stillDownTitle")}>
        {t.rich("troubleshoot.stillDownBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.lostSshTitle")}>
        {t("troubleshoot.lostSshIntro")}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{`cp /var/backups/proxmenux/interfaces_backup_<TIMESTAMP> /etc/network/interfaces
systemctl restart networking`}</pre>
        {t("troubleshoot.lostSshOutro")}
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
