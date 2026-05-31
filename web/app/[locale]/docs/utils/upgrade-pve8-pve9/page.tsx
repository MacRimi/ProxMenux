import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { Zap, MessageSquare, BookOpen, ExternalLink, Youtube } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { YouTubeEmbed } from "@/components/ui/youtube-embed"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.utils.upgradePve8Pve9.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/utils/upgrade-pve8-pve9",
    },
  }
}

type StringItem = string
type TableRow2 = { settingRich: string; effectRich: string }
type PreflightRow = { checkRich: string; whyRich: string }
type DpkgRow = { fileRich: string; answerRich: string; whyRich: string; fileFont: boolean }
type TroubleItem = { title: string; bodyRich: string }
type RefItem = { href: string; title: string; desc: string }
type RelatedItem = { href: string; label: string; tail: string }

export default async function UpgradePve8Pve9Page({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.utils.upgradePve8Pve9" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { utils: { upgradePve8Pve9: {
      dangerCallout: { items: StringItem[] }
      threeWays: {
        auto: { items: StringItem[] }
        interactive: { items: StringItem[] }
        manual: { items: StringItem[] }
      }
      auto: {
        behaviourTable: { rows: TableRow2[] }
        preflightTable: { rows: PreflightRow[] }
        postItems: StringItem[]
      }
      interactive: { whenItems: StringItem[] }
      manual: { dpkgTable: { rows: DpkgRow[] } }
      troubleshooting: { items: TroubleItem[] }
      references: { items: RefItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const block = messages.docs.utils.upgradePve8Pve9
  const dangerItems = block.dangerCallout.items
  const autoCardItems = block.threeWays.auto.items
  const interactiveCardItems = block.threeWays.interactive.items
  const manualCardItems = block.threeWays.manual.items
  const behaviourRows = block.auto.behaviourTable.rows
  const preflightRows = block.auto.preflightTable.rows
  const postItems = block.auto.postItems
  const whenItems = block.interactive.whenItems
  const dpkgRows = block.manual.dpkgTable.rows
  const troubleItems = block.troubleshooting.items
  const refItems = block.references.items
  const relatedItems = block.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const kbd = (chunks: React.ReactNode) => <kbd>{chunks}</kbd>

  const autolink = (chunks: React.ReactNode) => (
    <Link href="#auto" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const dpkglink = (chunks: React.ReactNode) => (
    <Link href="#dpkg-prompts" className="text-blue-700 hover:underline">
      {chunks}
    </Link>
  )
  const netlink = (chunks: React.ReactNode) => (
    <Link href="/docs/network/persistent-names" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const wikilink = (chunks: React.ReactNode) => (
    <a
      href="https://pve.proxmox.com/wiki/Upgrade_from_8_to_9"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const cephlink = (chunks: React.ReactNode) => (
    <a
      href="https://pve.proxmox.com/wiki/Ceph_Squid"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
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
        estimatedMinutes={20}
        scriptPath="utilities/upgrade_pve8_to_pve9.sh"
      />

      <Callout variant="danger" title={t("dangerCallout.title")}>
        {t.rich("dangerCallout.intro", { strong })}
        <ul className="list-disc pl-6 mt-2 mb-0 space-y-1">
          {dangerItems.map((_, idx) => (
            <li key={idx}>{t.rich(`dangerCallout.items.${idx}`, { strong })}</li>
          ))}
        </ul>
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("modeMenu.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("modeMenu.intro", { em })}
      </p>

      <Image
        src="/utils/upgrade-pve8-pve9-menu.png"
        alt={t("modeMenu.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("threeWays.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("threeWays.intro", { code })}
      </p>

      <div className="grid gap-4 md:grid-cols-1 lg:grid-cols-3 mb-8 not-prose">
        <a
          href="#auto"
          className="rounded-lg border-2 border-emerald-300 bg-emerald-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
              <Zap className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("threeWays.auto.title")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">
            {t.rich("threeWays.auto.summary", { code, strong })}
          </p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {autoCardItems.map((_, idx) => (
              <li key={idx}>{t.rich(`threeWays.auto.items.${idx}`, { code, strong })}</li>
            ))}
          </ul>
        </a>

        <a
          href="#interactive"
          className="rounded-lg border-2 border-amber-300 bg-amber-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-amber-100 text-amber-700">
              <MessageSquare className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("threeWays.interactive.title")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">
            {t("threeWays.interactive.summary")}
          </p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {interactiveCardItems.map((_, idx) => (
              <li key={idx}>{t.rich(`threeWays.interactive.items.${idx}`, { code })}</li>
            ))}
          </ul>
        </a>

        <a
          href="#manual"
          className="rounded-lg border-2 border-blue-300 bg-blue-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-blue-700">
              <BookOpen className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("threeWays.manual.title")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">
            {t("threeWays.manual.summary")}
          </p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {manualCardItems.map((_, idx) => (
              <li key={idx}>{t(`threeWays.manual.items.${idx}`)}</li>
            ))}
          </ul>
        </a>
      </div>

      <Callout variant="info" title={t("precheckCallout.title")}>
        {t.rich("precheckCallout.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("webTerminal.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("webTerminal.body", { code })}
      </p>
      <Callout variant="warning" title={t("webTerminal.warningTitle")}>
        {t.rich("webTerminal.warningBody", { code })}
      </Callout>

      <h2 id="auto" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">
        {t("auto.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("auto.intro")}
      </p>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("auto.behaviourHeading")}</h3>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("auto.behaviourTable.settingHeader")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("auto.behaviourTable.effectHeader")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {behaviourRows.map((_, idx) => (
              <tr key={idx} className={idx < behaviourRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">
                  {t.rich(`auto.behaviourTable.rows.${idx}.settingRich`, { code })}
                </td>
                <td className="px-3 py-2 align-top">
                  {t.rich(`auto.behaviourTable.rows.${idx}.effectRich`, { strong })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("auto.flowHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("auto.flowIntro", { code })}
      </p>

      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-900 leading-relaxed border border-gray-200 whitespace-pre">{t.raw("auto.flowDiagram") as string}</pre>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("auto.preflightHeading")}</h3>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("auto.preflightTable.checkHeader")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("auto.preflightTable.whyHeader")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {preflightRows.map((_, idx) => (
              <tr key={idx} className={idx < preflightRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">
                  {t.rich(`auto.preflightTable.rows.${idx}.checkRich`, { strong })}
                </td>
                <td className="px-3 py-2 align-top">
                  {t.rich(`auto.preflightTable.rows.${idx}.whyRich`, { code })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("auto.distUpgradeHeading")}</h3>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("auto.distUpgradeCode") as string}</pre>
      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">
        {t.rich("auto.distUpgradeOutro", { code })}
      </p>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("auto.postHeading")}</h3>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {postItems.map((_, idx) => (
          <li key={idx}>{t.rich(`auto.postItems.${idx}`, { code, strong })}</li>
        ))}
      </ol>

      <h2 id="interactive" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">
        {t("interactive.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("interactive.intro", { code, strong, autolink })}
      </p>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("interactive.distUpgradeHeading")}</h3>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("interactive.distUpgradeCode") as string}</pre>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("interactive.whenHeading")}</h3>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {whenItems.map((_, idx) => (
          <li key={idx}>{t.rich(`interactive.whenItems.${idx}`, { code })}</li>
        ))}
      </ul>

      <Callout variant="info" title={t("interactive.promptCalloutTitle")}>
        {t.rich("interactive.promptCalloutBody", { strong, dpkglink })}
      </Callout>

      <h2 id="manual" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">
        {t("manual.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("manual.intro", { strong, em, wikilink })}
      </p>

      <Callout variant="warning" title={t("manual.rootCalloutTitle")}>
        {t.rich("manual.rootCalloutBody", { code })}
      </Callout>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("manual.phase1Heading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("manual.phase1Intro")}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("manual.phase1Code") as string}</pre>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("manual.phase2Heading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("manual.phase2Intro", { strong })}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("manual.phase2Code") as string}</pre>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("manual.phase3Heading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("manual.phase3Intro")}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("manual.phase3Code") as string}</pre>

      <h4 id="dpkg-prompts" className="text-lg font-semibold mt-6 mb-3 text-gray-900 scroll-mt-24">
        {t("manual.dpkgHeading")}
      </h4>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("manual.dpkgIntro", { strong })}
      </p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("manual.dpkgTable.fileHeader")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("manual.dpkgTable.answerHeader")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("manual.dpkgTable.whyHeader")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {dpkgRows.map((row, idx) => (
              <tr key={idx} className={idx < dpkgRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className={`px-3 py-2 align-top whitespace-nowrap${row.fileFont ? " font-mono text-xs" : ""}`}>
                  {t.rich(`manual.dpkgTable.rows.${idx}.fileRich`, { code })}
                </td>
                <td className="px-3 py-2 align-top whitespace-nowrap">
                  {t.rich(`manual.dpkgTable.rows.${idx}.answerRich`, { strong, kbd })}
                </td>
                <td className="px-3 py-2 align-top">
                  {t(`manual.dpkgTable.rows.${idx}.whyRich`)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("manual.inspectCalloutTitle")}>
        {t.rich("manual.inspectCalloutBody", { strong })}
      </Callout>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("manual.phase4Heading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("manual.phase4Intro", { code })}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("manual.phase4Code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("clusterCeph.heading")}</h2>

      <Callout variant="warning" title={t("clusterCeph.clusterCalloutTitle")}>
        {t.rich("clusterCeph.clusterCalloutBody", { code, strong })}
      </Callout>

      <Callout variant="warning" title={t("clusterCeph.cephCalloutTitle")}>
        {t.rich("clusterCeph.cephCalloutBody", { code, cephlink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshooting.heading")}</h2>

      {troubleItems.map((item, idx) => (
        <Callout key={idx} variant="troubleshoot" title={item.title}>
          {t.rich(`troubleshooting.items.${idx}.bodyRich`, { code, netlink })}
        </Callout>
      ))}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("files.heading")}</h2>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("files.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        <ExternalLink className="inline h-5 w-5 mr-1 -mt-1 text-gray-700" aria-hidden />
        {t("references.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("references.intro")}
      </p>
      <div className="grid gap-3 md:grid-cols-2 mb-6 not-prose">
        {refItems.map((item, idx) => (
          <a
            key={idx}
            href={item.href}
            target="_blank"
            rel="noopener noreferrer"
            className="block rounded-md border border-gray-200 bg-white p-4 transition-colors hover:border-blue-400 hover:bg-blue-50"
          >
            <div className="font-semibold text-gray-900 mb-1 flex items-center gap-1.5">
              {t(`references.items.${idx}.title`)}
              <ExternalLink className="h-3.5 w-3.5 text-gray-400" aria-hidden />
            </div>
            <div className="text-xs text-gray-600">{t(`references.items.${idx}.desc`)}</div>
          </a>
        ))}
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        <Youtube className="inline h-5 w-5 mr-1 -mt-1 text-red-600" aria-hidden />
        {t("video.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("video.intro")}
      </p>

      <YouTubeEmbed
        videoId="AmpgWHePp18"
        title={t("video.title")}
        caption={t("video.caption")}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item, idx) => (
          <li key={idx}>
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
