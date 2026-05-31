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
  const t = await getTranslations({ locale, namespace: "docs.network.monitoring.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/network/monitoring",
    },
  }
}

type WhenRow = { question: string; use: string }
type IptrafRow = { mode: string; useFor: string }
type IperfRow = { mode: string; behaviour: string; cli: string }
type RelatedItem = { label: string; href: string; tail?: string; tailRich?: string }

export default async function NetworkMonitoringPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.network.monitoring" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { network: { monitoring: {
      when: { rows: WhenRow[] }
      iptraf: { rows: IptrafRow[] }
      iperf3: { rows: IperfRow[]; workflow: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const whenRows = messages.docs.network.monitoring.when.rows
  const iptrafRows = messages.docs.network.monitoring.iptraf.rows
  const iperfRows = messages.docs.network.monitoring.iperf3.rows
  const workflow = messages.docs.network.monitoring.iperf3.workflow
  const relatedItems = messages.docs.network.monitoring.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const kbd = (chunks: React.ReactNode) => <kbd>{chunks}</kbd>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={4}
        scriptPath="menus/network_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("when.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("when.headerQuestion")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("when.headerUse")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {whenRows.map((row, idx) => (
              <tr key={idx} className={idx < whenRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top">{t.rich(`when.rows.${idx}.question`, { em })}</td>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.use}</strong></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("iftop.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("iftop.body", { code, em })}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`12.5Kb        25.0Kb        37.5Kb        50.0Kb         62.5Kb
└─────────────┴─────────────┴─────────────┴──────────────┴──────────
proxmox.lan         => 192.168.1.50          14.2Kb  9.8Kb   7.1Kb
                    <=                        2.3Kb  1.7Kb   1.4Kb
proxmox.lan         => 1.1.1.1                0b     145b     38b
                    <=                       128b    96b      24b
─────────────────────────────────────────────────────────────────
TX:          14.2Kb       9.9Kb       7.1Kb
RX:           2.4Kb       1.8Kb       1.4Kb
TOTAL:       16.6Kb      11.7Kb       8.5Kb`}</pre>
      <p className="mt-4 mb-4 text-gray-800 leading-relaxed">
        {t.rich("iftop.exit", { strong, kbd })}
      </p>
      <Callout variant="tip" title={t("iftop.keysTitle")}>
        {t.rich("iftop.keysBody", { code, kbd })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("iptraf.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("iptraf.intro", { em })}
      </p>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("iptraf.menuIntro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("iptraf.headerMode")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("iptraf.headerUseFor")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {iptrafRows.map((row, idx) => (
              <tr key={idx} className={idx < iptrafRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.mode}</strong></td>
                <td className="px-3 py-2 align-top">{row.useFor}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("iptraf.exit", { strong, kbd })}
      </p>
      <Callout variant="tip" title={t("iptraf.logTitle")}>
        {t.rich("iptraf.logBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("iperf3.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("iperf3.intro1", { em })}
      </p>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("iperf3.intro2", { strong })}
      </p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("iperf3.headerMode")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("iperf3.headerBehaviour")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("iperf3.headerCli")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {iperfRows.map((row, idx) => (
              <tr key={idx} className={idx < iperfRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.mode}</strong></td>
                <td className="px-3 py-2 align-top">{row.behaviour}</td>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.cli}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("iperf3.workflowIntro")}</p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {workflow.map((_, idx) => (
          <li key={idx}>{t.rich(`iperf3.workflow.${idx}`, { em, strong })}</li>
        ))}
      </ol>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("iperf3.sample")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`Connecting to host 10.0.0.10, port 5201
[  5] local 10.0.0.20 port 53994 connected to 10.0.0.10 port 5201
[ ID] Interval           Transfer     Bitrate         Retr  Cwnd
[  5]   0.00-1.00   sec  1.10 GBytes  9.45 Gbits/sec    0    1.55 MBytes
[  5]   1.00-2.00   sec  1.10 GBytes  9.45 Gbits/sec    0    1.55 MBytes
[  5]   2.00-3.00   sec  1.10 GBytes  9.45 Gbits/sec    0    1.55 MBytes
...
- - - - - - - - - - - - - - - - - - - - - - - - -
[ ID] Interval           Transfer     Bitrate         Retr
[  5]   0.00-10.00  sec  11.0 GBytes  9.45 Gbits/sec    0    sender
[  5]   0.00-10.00  sec  11.0 GBytes  9.44 Gbits/sec         receiver

iperf Done.`}</pre>

      <Callout variant="tip" title={t("iperf3.flagsTitle")}>
        {t.rich("iperf3.flagsBody", { code })}
      </Callout>

      <Callout variant="warning" title={t("iperf3.firewallTitle")}>
        {t.rich("iperf3.firewallBody", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("install.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("install.body", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.hangTitle")}>
        {t.rich("troubleshoot.hangBody", { code, kbd })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.refusedTitle")}>
        {t.rich("troubleshoot.refusedBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.slowTitle")}>
        {t.rich("troubleshoot.slowBody", { code, em })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.noTrafficTitle")}>
        {t.rich("troubleshoot.noTrafficBody", { code })}
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
