import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { DataFlowDiagram } from "@/components/ui/data-flow-diagram"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.notifications.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox notifications",
      "proxmox telegram",
      "proxmox discord",
      "proxmox email alerts",
      "proxmox gotify",
      "proxmox apprise",
      "proxmox ntfy",
      "proxmox matrix notifications",
      "proxmox alerts",
      "proxmox notification webhook",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/monitor/notifications" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/monitor/notifications",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type SourceRow = { collector: string; watches: string; events: string }
type DispatchRow = { stage: string; what: string; tunable: string }
type CatalogueRow = { group: string; events: string }
type ApiRow = { endpoint: string; method: string; use: string }
type WhereNextItem = { label: string; href: string; tail?: string; tailRich?: string }

export default async function NotificationsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.notifications" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { notifications: {
      enabling: { steps: string[] }
      sources: { rows: SourceRow[] }
      telegram: {
        step1Items: string[]
        privateItems: string[]
        groupItems: string[]
      }
      discord: { items: string[] }
      gotify: { items: string[] }
      email: { gmailItems: string[]; outlookItems: string[] }
      apprise: { listItems: string[]; steps: string[] }
      rich: { togglesItems: string[] }
      quiet: { purposeItems: string[]; howItems: string[] }
      digest: {
        purposeItems: string[]
        howItems: string[]
        neverDelayedSub: string[]
      }
      dispatch: { rows: DispatchRow[] }
      pveWebhook: {
        registeredItems: string[]
        securityItems: string[]
        actionsItems: string[]
      }
      catalogue: { rows: CatalogueRow[] }
      api: { rows: ApiRow[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const n = messages.docs.monitor.notifications
  const enablingSteps = n.enabling.steps
  const sourceRows = n.sources.rows
  const tgStep1 = n.telegram.step1Items
  const tgPriv = n.telegram.privateItems
  const tgGroup = n.telegram.groupItems
  const discordItems = n.discord.items
  const gotifyItems = n.gotify.items
  const gmailItems = n.email.gmailItems
  const outlookItems = n.email.outlookItems
  const appriseListItems = n.apprise.listItems
  const appriseSteps = n.apprise.steps
  const togglesItems = n.rich.togglesItems
  const quietPurpose = n.quiet.purposeItems
  const quietHow = n.quiet.howItems
  const digestPurpose = n.digest.purposeItems
  const digestHow = n.digest.howItems
  const digestNeverSub = n.digest.neverDelayedSub
  const dispatchRows = n.dispatch.rows
  const pveRegistered = n.pveWebhook.registeredItems
  const pveSecurity = n.pveWebhook.securityItems
  const pveActions = n.pveWebhook.actionsItems
  const catalogueRows = n.catalogue.rows
  const apiRows = n.api.rows
  const whereNextItems = n.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const hmLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/health-monitor" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const pveLink = (chunks: React.ReactNode) => (
    <a href="#pve-webhook-integration" className="text-blue-600 hover:underline">{chunks}</a>
  )
  const aiLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/ai-assistant#what-context-the-ai-receives" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const aiPageLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/ai-assistant" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const catalogueLink = (chunks: React.ReactNode) => (
    <Link href="#event-catalogue" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const quietLink = (chunks: React.ReactNode) => (
    <Link href="#quiet-hours" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const ext = (href: string) => (chunks: React.ReactNode) =>
    (
      <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
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
        estimatedMinutes={18}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { link: hmLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howItWorks.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("howItWorks.intro")}</p>

      <DataFlowDiagram
        nodes={[
          { variant: "source", label: t("howItWorks.nodes.sourcesLabel"), detail: t("howItWorks.nodes.sourcesDetail") },
          { variant: "bridge", label: t("howItWorks.nodes.dispatchLabel"), detail: t("howItWorks.nodes.dispatchDetail") },
          { variant: "bridge", label: t("howItWorks.nodes.aiLabel"), detail: t("howItWorks.nodes.aiDetail") },
          { variant: "target", label: t("howItWorks.nodes.channelsLabel"), detail: t("howItWorks.nodes.channelsDetail") },
        ]}
        arrowLabel={t("howItWorks.arrowLabel")}
        caption={t("howItWorks.caption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("enabling.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("enabling.intro", { em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/settings/notifications-disabled.png" alt={t("enabling.disabledAlt")} width={2000} height={552} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("enabling.disabledCaption")}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("enabling.stepsIntro")}</p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {enablingSteps.map((_, idx) => (
          <li key={idx}>{t.rich(`enabling.steps.${idx}`, { em, code, pvelink: pveLink })}</li>
        ))}
      </ol>

      <figure className="my-4">
        <Image src="/monitor/settings/notifications-active.png" alt={t("enabling.activeAlt")} width={2000} height={1142} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("enabling.activeCaption", { em })}</figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("sources.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sources.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("sources.headerCollector")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("sources.headerWatches")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("sources.headerEvents")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {sourceRows.map((row, idx) => (
              <tr key={row.collector} className={idx < sourceRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.collector}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`sources.rows.${idx}.watches`, { code, pvelink: pveLink })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`sources.rows.${idx}.events`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sources.after1", { code })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sources.after2", { code, ailink: aiLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("channels.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("channels.intro", { em })}
      </p>

      <Callout variant="warning" title={t("channels.credsTitle")}>
        {t.rich("channels.credsBody", { code })}
      </Callout>

      <h3 id="telegram" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("telegram.heading")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("telegram.intro", { strong, em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/settings/telegram-setup-guide.png" alt={t("telegram.guideAlt")} width={1923} height={2000} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("telegram.guideCaption", { em })}</figcaption>
      </figure>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("telegram.step1Title")}</h4>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {tgStep1.map((_, idx) => (
          <li key={idx}>{t.rich(`telegram.step1Items.${idx}`, { em, code, a: ext("https://t.me/BotFather") })}</li>
        ))}
      </ol>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("telegram.step2Title")}</h4>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("telegram.step2Intro", { em })}
      </p>

      <p className="mb-2 text-gray-800 leading-relaxed">
        <strong>{t("telegram.privateLabel")}</strong>
      </p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {tgPriv.map((_, idx) => (
          <li key={idx}>
            {t.rich(`telegram.privateItems.${idx}`, {
              code,
              a1: ext("https://t.me/userinfobot"),
              a2: ext("https://t.me/myidbot"),
              a: ext("https://t.me/userinfobot"),
            })}
          </li>
        ))}
      </ol>

      <figure className="my-4">
        <Image src="/monitor/settings/telegram-private-chat.png" alt={t("telegram.privateAlt")} width={2000} height={768} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("telegram.privateCaption")}</figcaption>
      </figure>

      <p className="mb-2 text-gray-800 leading-relaxed">
        <strong>{t("telegram.groupLabel")}</strong>
      </p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {tgGroup.map((_, idx) => (
          <li key={idx}>{t.rich(`telegram.groupItems.${idx}`, { code, em })}</li>
        ))}
      </ol>

      <figure className="my-4">
        <Image src="/monitor/settings/telegram-group-chat.png" alt={t("telegram.groupAlt")} width={2000} height={768} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("telegram.groupCaption", { code, em })}</figcaption>
      </figure>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("telegram.step3Title")}</h4>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("telegram.step3Body", { em })}
      </p>

      <h3 id="discord" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("discord.heading")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("discord.intro", { em })}
      </p>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {discordItems.map((_, idx) => (
          <li key={idx}>{t.rich(`discord.items.${idx}`, { em, code })}</li>
        ))}
      </ol>

      <figure className="my-4">
        <Image src="/monitor/settings/discord-channel.png" alt={t("discord.imageAlt")} width={2000} height={435} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("discord.imageCaption", { em })}</figcaption>
      </figure>

      <h3 id="gotify" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("gotify.heading")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("gotify.intro", { em })}
      </p>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {gotifyItems.map((_, idx) => (
          <li key={idx}>{t.rich(`gotify.items.${idx}`, { em, code, a: ext("https://gotify.net/docs/install") })}</li>
        ))}
      </ol>

      <figure className="my-4">
        <Image src="/monitor/settings/gotify-channel.png" alt={t("gotify.imageAlt")} width={2000} height={573} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("gotify.imageCaption")}</figcaption>
      </figure>

      <h3 id="email" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("email.heading")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("email.intro")}</p>

      <figure className="my-4">
        <Image src="/monitor/settings/email-channel.png" alt={t("email.imageAlt")} width={2000} height={1248} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("email.imageCaption")}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("email.appNote", { strong })}
      </p>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("email.gmailTitle")}</h4>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("email.gmailIntro", { strong, em })}
      </p>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {gmailItems.map((_, idx) => (
          <li key={idx}>
            {t.rich(`email.gmailItems.${idx}`, {
              em,
              code,
              a:
                idx === 0
                  ? ext("https://myaccount.google.com/security")
                  : ext("https://myaccount.google.com/apppasswords"),
            })}
          </li>
        ))}
      </ol>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("email.outlookTitle")}</h4>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("email.outlookIntro", { strong })}
      </p>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {outlookItems.map((_, idx) => (
          <li key={idx}>{t.rich(`email.outlookItems.${idx}`, { em, code, a: ext("https://account.microsoft.com/security") })}</li>
        ))}
      </ol>

      <Callout variant="tip" title={t("email.relayTitle")}>
        {t("email.relayBody")}
      </Callout>

      <h3 id="apprise" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("apprise.heading")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("apprise.intro")}</p>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("apprise.listIntro")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {appriseListItems.map((_, idx) => (
          <li key={idx}>
            {t.rich(`apprise.listItems.${idx}`, {
              a: idx === 0 ? ext("https://github.com/caronc/apprise/wiki") : ext("https://github.com/caronc/apprise/wiki/URLBasics"),
            })}
          </li>
        ))}
      </ul>

      <h4 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("apprise.stepsTitle")}</h4>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {appriseSteps.map((_, idx) => (
          <li key={idx}>{t.rich(`apprise.steps.${idx}`, { em, code, a: ext("https://github.com/caronc/apprise/wiki") })}</li>
        ))}
      </ol>

      <Callout variant="info" title={t("apprise.deliveredTitle")}>
        {t("apprise.deliveredBody")}
      </Callout>

      <Callout variant="tip" title={t("apprise.fanoutTitle")}>
        {t.rich("apprise.fanoutBody", { a: ext("https://github.com/caronc/apprise-api") })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("rich.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("rich.intro", { em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/settings/notification-categories.png" alt={t("rich.imageAlt")} width={2000} height={1668} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("rich.imageCaption", { em })}</figcaption>
      </figure>

      <h3 id="rich-messages" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("rich.richTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("rich.richIntro", { em })}
      </p>

      <div className="grid md:grid-cols-2 gap-4 mb-6 not-prose">
        <div className="rounded-lg border-2 border-gray-200 bg-gray-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-gray-700 mb-2">
            {t("rich.plainHeader")}
          </div>
          <pre className="text-sm font-mono text-gray-800 whitespace-pre-wrap leading-relaxed m-0">
{`[INFO] vm_start
VM 101 (homeassistant) started
on node pve-01
host: home-lab`}
          </pre>
        </div>
        <div className="rounded-lg border-2 border-blue-300 bg-blue-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-800 mb-2">
            {t("rich.richHeader")}
          </div>
          <pre className="text-sm font-mono text-gray-800 whitespace-pre-wrap leading-relaxed m-0">
{`🟢 VM started
VM 101 (homeassistant) is now
running on node pve-01
🏠 home-lab`}
          </pre>
        </div>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("rich.richOutro")}</p>

      <h3 id="event-toggles" className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("rich.togglesTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("rich.togglesIntro")}</p>

      <ol className="list-decimal pl-6 text-gray-800 leading-relaxed space-y-2 mb-4">
        {togglesItems.map((_, idx) => (
          <li key={idx}>{t.rich(`rich.togglesItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ol>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("rich.togglesOutro", { em, code })}
      </p>

      <h2 id="quiet-hours" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("quiet.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("quiet.intro", { strong })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/settings/quiet-hours-and-digest-config.png" alt={t("quiet.imageAlt")} width={1600} height={1200} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("quiet.imageCaption")}</figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("quiet.purposeTitle")}</h3>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {quietPurpose.map((_, idx) => (
          <li key={idx}>{t.rich(`quiet.purposeItems.${idx}`, { strong })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("quiet.howTitle")}</h3>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {quietHow.map((_, idx) => (
          <li key={idx}>{t.rich(`quiet.howItems.${idx}`, { strong, code })}</li>
        ))}
      </ol>

      <Callout variant="info" title={t("quiet.criticalTitle")}>
        {t.rich("quiet.criticalBody", { link: catalogueLink })}
      </Callout>

      <h2 id="daily-digest" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("digest.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("digest.intro1", { strong })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("digest.intro2", { link: quietLink })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("digest.purposeTitle")}</h3>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {digestPurpose.map((_, idx) => (
          <li key={idx}>{t.rich(`digest.purposeItems.${idx}`, { strong })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("digest.howTitle")}</h3>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {digestHow.map((_, idx) => (
          <li key={idx}>
            {t.rich(`digest.howItems.${idx}`, { strong, em, code })}
            {idx === 3 && (
              <ul className="list-disc pl-6 mt-1">
                {digestNeverSub.map((_, sIdx) => (
                  <li key={sIdx}>{t.rich(`digest.neverDelayedSub.${sIdx}`, { strong })}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>

      <Callout variant="tip" title={t("digest.comboTitle")}>
        {t.rich("digest.comboBody", { em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("displayName.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("displayName.intro", { em, code })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/settings/display-name.png" alt={t("displayName.imageAlt")} width={2000} height={256} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("displayName.imageCaption")}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("displayName.outro", { em, code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("dispatch.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("dispatch.intro")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dispatch.headerStage")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dispatch.headerWhat")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dispatch.headerTunable")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {dispatchRows.map((row, idx) => (
              <tr key={row.stage} className={idx < dispatchRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.stage}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`dispatch.rows.${idx}.what`, { code })}</td>
                <td className="px-3 py-2 align-top">{row.tunable}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("dispatch.calloutTitle")}>
        {t("dispatch.calloutBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("aiRewrite.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("aiRewrite.body1")}</p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("aiRewrite.body2", { code, link: aiPageLink })}
      </p>

      <Callout variant="warning" title={t("aiRewrite.privacyTitle")}>
        {t("aiRewrite.privacyBody")}
      </Callout>

      <h2 id="pve-webhook-integration" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("pveWebhook.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pveWebhook.intro1", { em, code })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pveWebhook.intro2", { em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/settings/pve-webhook-target.png" alt={t("pveWebhook.imageAlt")} width={1452} height={1360} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto mx-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("pveWebhook.imageCaption")}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("pveWebhook.registeredIntro")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {pveRegistered.map((_, idx) => (
          <li key={idx}>
            {t.rich(`pveWebhook.registeredItems.${idx}`, { strong, em, code })}
            {idx === 1 && (
              <code className="block mt-2 bg-gray-50 border border-gray-200 rounded p-2 text-xs whitespace-pre-wrap">{`{ "title": "{{ escape title }}",
  "message": "{{ escape message }}",
  "severity": "{{ severity }}",
  "timestamp": "{{ timestamp }}",
  "fields": {{ json fields }} }`}</code>
            )}
          </li>
        ))}
      </ul>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("pveWebhook.securityTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pveWebhook.securityIntro", { code })}
      </p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {pveSecurity.map((_, idx) => (
          <li key={idx}>{t.rich(`pveWebhook.securityItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <Callout variant="info" title={t("pveWebhook.practiceTitle")}>
        {t.rich("pveWebhook.practiceBody", { code })}
      </Callout>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("pveWebhook.actionsIntro")}</p>

      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {pveActions.map((_, idx) => (
          <li key={idx}>{t.rich(`pveWebhook.actionsItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <Callout variant="info" title={t("pveWebhook.clusterTitle")}>
        {t.rich("pveWebhook.clusterBody", { code, em })}
      </Callout>

      <h2 id="event-catalogue" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("catalogue.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("catalogue.intro")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("catalogue.headerGroup")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("catalogue.headerEvents")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {catalogueRows.map((row, idx) => (
              <tr key={row.group} className={idx < catalogueRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.group}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`catalogue.rows.${idx}.events`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("catalogue.burstNote", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("history.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("history.body1", { em, code })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("history.body2", { em })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("history.body3", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("api.heading")}</h2>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("api.headerEndpoint")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("api.headerMethod")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("api.headerUse")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {apiRows.map((row, idx) => (
              <tr key={row.endpoint} className={idx < apiRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.endpoint}</td>
                <td className="px-3 py-2 align-top">{row.method}</td>
                <td className="px-3 py-2 align-top">{t.rich(`api.rows.${idx}.use`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CopyableCode
        code={`# Send a test notification to Discord
curl -X POST http://<host>:8008/api/notifications/test \\
  -H "Authorization: Bearer <api-token>" \\
  -H "Content-Type: application/json" \\
  -d '{"channel":"discord"}'

# Emit a custom event from a script
curl -X POST http://<host>:8008/api/notifications/send \\
  -H "Authorization: Bearer <api-token>" \\
  -H "Content-Type: application/json" \\
  -d '{"event_type":"custom","severity":"warning","data":{"message":"Cron job took >10 min"}}'

# Pull the last 50 history entries for one channel
curl -H "Authorization: Bearer <api-token>" \\
  'http://<host>:8008/api/notifications/history?channel=telegram&limit=50' | jq

# Test an AI provider connection (verifies the API key and model)
curl -X POST http://<host>:8008/api/notifications/test-ai \\
  -H "Authorization: Bearer <api-token>" \\
  -H "Content-Type: application/json" \\
  -d '{"provider":"openai","api_key":"sk-...","model":"gpt-4o-mini"}'`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {whereNextItems.map((item, idx) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tailRich ? t.rich(`whereNext.items.${idx}.tailRich`, { code }) : item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
