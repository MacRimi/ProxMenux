import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.apiReference.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox api",
      "proxmox rest api",
      "proxmox monitor api",
      "proxmox integration",
      "proxmox home assistant",
      "proxmox homepage",
      "proxmox grafana",
      "proxmox prometheus endpoint",
      "proxmox n8n",
      "proxmox bearer token",
      "proxmox curl example",
      "proxmenux api",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/monitor/api" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/monitor/api",
    },
    twitter: {
      card: "summary",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type EndpointRow = { endpoint: string; method: string; use: string }
type WhereNextItem = { label: string; href: string; tail?: string; tailRich?: string }
type MetricRow = { metric: string; desc: string }
type MetricGroup = { group: string; metrics: MetricRow[] }

export default async function MonitorApiPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.apiReference" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { apiReference: {
      auth: { rows: EndpointRow[]; items: string[] }
      conventions: { items: string[] }
      system: { rows: EndpointRow[] }
      health: { rows: EndpointRow[] }
      storage: { rows: EndpointRow[] }
      network: { rows: EndpointRow[] }
      vms: { rows: EndpointRow[] }
      backups: { rows: EndpointRow[] }
      logs: { rows: EndpointRow[] }
      notifications: { rows: EndpointRow[] }
      security: { rows: EndpointRow[] }
      proxmenuxIntegration: { rows: EndpointRow[] }
      prometheus: { groups: MetricGroup[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const api = messages.docs.monitor.apiReference
  const authRows = api.auth.rows
  const authItems = api.auth.items
  const conventionsItems = api.conventions.items
  const systemRows = api.system.rows
  const healthRows = api.health.rows
  const storageRows = api.storage.rows
  const networkRows = api.network.rows
  const vmsRows = api.vms.rows
  const backupsRows = api.backups.rows
  const logsRows = api.logs.rows
  const notifRows = api.notifications.rows
  const securityRows = api.security.rows
  const proxmenuxRows = api.proxmenuxIntegration.rows
  const metricGroups = api.prometheus.groups
  const whereNextItems = api.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const accessLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/access-auth" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const healthLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/health-monitor" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const notifLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/notifications" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const aiLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/ai-assistant" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const integrationsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/integrations" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  const endpointTable = (rows: EndpointRow[], pathPrefix: string) => (
    <div className="overflow-x-auto mb-6">
      <table className="w-full text-sm border border-gray-200 rounded-md">
        <thead className="bg-gray-50 text-gray-900">
          <tr>
            <th className="text-left px-3 py-2 border-b border-gray-200">{t("headerEndpoint")}</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">{t("headerMethod")}</th>
            <th className="text-left px-3 py-2 border-b border-gray-200">{t("headerUse")}</th>
          </tr>
        </thead>
        <tbody className="text-gray-800">
          {rows.map((row, idx) => (
            <tr key={`${row.endpoint}-${row.method}-${idx}`} className={idx < rows.length - 1 ? "border-b border-gray-100" : ""}>
              <td className="px-3 py-2 align-top font-mono text-xs">{row.endpoint}</td>
              <td className="px-3 py-2 align-top">{row.method}</td>
              <td className="px-3 py-2 align-top">{t.rich(`${pathPrefix}.${idx}.use`, { code })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={22}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong, link: accessLink })}
      </Callout>

      <h2 id="authentication" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("auth.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("auth.intro")}</p>

      <CopyableCode
        code={`curl -H "Authorization: Bearer <token>" http://<host>:8008/api/system | jq`}
        className="my-4"
      />

      <p className="mb-4 text-gray-800 leading-relaxed">{t("auth.tokensIntro")}</p>

      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1 mb-4">
        {authItems.map((_, idx) => (
          <li key={idx}>{t.rich(`auth.items.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("auth.flowLink", { link: accessLink })}
      </p>

      {endpointTable(authRows, "auth.rows")}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("conventions.heading")}</h2>

      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1 mb-6">
        {conventionsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`conventions.items.${idx}`, { code })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("system.heading")}</h2>
      {endpointTable(systemRows, "system.rows")}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("health.heading")}</h2>
      {endpointTable(healthRows, "health.rows")}
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("health.outro", { link: healthLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("storage.heading")}</h2>
      {endpointTable(storageRows, "storage.rows")}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("network.heading")}</h2>
      {endpointTable(networkRows, "network.rows")}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("vms.heading")}</h2>
      {endpointTable(vmsRows, "vms.rows")}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("backups.heading")}</h2>
      {endpointTable(backupsRows, "backups.rows")}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("logs.heading")}</h2>
      {endpointTable(logsRows, "logs.rows")}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("notifications.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("notifications.intro", { notifLink, aiLink })}
      </p>
      {endpointTable(notifRows, "notifications.rows")}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("security.heading")}</h2>
      {endpointTable(securityRows, "security.rows")}

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("proxmenuxIntegration.heading")}</h2>
      {endpointTable(proxmenuxRows, "proxmenuxIntegration.rows")}

      <h2 id="prometheus" className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("prometheus.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("prometheus.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("prometheus.exportedTitle")}</h3>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("prometheus.headerGroup")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("prometheus.headerMetric")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("prometheus.headerDesc")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {metricGroups.flatMap((group, gIdx) =>
              group.metrics.map((m, mIdx) => (
                <tr key={`${group.group}-${m.metric}`} className="border-b border-gray-100">
                  {mIdx === 0 && (
                    <td className="px-3 py-2 align-top whitespace-nowrap" rowSpan={group.metrics.length}>
                      <strong>{group.group}</strong>
                    </td>
                  )}
                  <td className="px-3 py-2 align-top font-mono text-xs">{m.metric}</td>
                  <td className="px-3 py-2 align-top">
                    {t.rich(`prometheus.groups.${gIdx}.metrics.${mIdx}.desc`, { code })}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <h3 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("prometheus.scrapeTitle")}</h3>

      <p className="mb-3 text-gray-800 leading-relaxed">{t("prometheus.scrapeIntro")}</p>

      <CopyableCode
        code={`# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'proxmenux'
    metrics_path: /api/prometheus
    scheme: https              # or http if TLS isn't enabled in ProxMenux
    scrape_interval: 30s
    authorization:
      type: Bearer
      credentials: '<your-api-token>'
    static_configs:
      - targets:
          - 'pve01.lan:8008'
          - 'pve02.lan:8008'
          - 'pve03.lan:8008'`}
        className="my-4"
      />

      <Callout variant="tip" title={t("prometheus.perHostTitle")}>
        {t.rich("prometheus.perHostBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("puttingItTogether.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("puttingItTogether.body", { link: integrationsLink })}
      </p>

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
