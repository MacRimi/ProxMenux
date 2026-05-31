import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
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
  const t = await getTranslations({ locale, namespace: "docs.monitor.architecture.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmenux architecture",
      "proxmox monitor flask",
      "proxmox dashboard sqlite",
      "proxmox appimage dashboard",
      "proxmox websocket terminal",
      "proxmox monitor blueprints",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/monitor/architecture" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/monitor/architecture",
    },
    twitter: {
      card: "summary",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type ThreadRow = { thread: string; cadence: string; job: string }
type BlueprintRow = { blueprint: string; prefix: string[]; owns: string }
type DataRow = { source: string; usedFor: string }
type PersistenceRow = { path: string; owner: string; contents: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function MonitorArchitecturePage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.architecture" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { architecture: {
      requestFlow: { rows: ThreadRow[] }
      systemd: { items: string[] }
      appimage: { consequences: string[] }
      flask: { rows: BlueprintRow[] }
      dataSources: { rows: DataRow[] }
      persistence: { rows: PersistenceRow[] }
      health: { items: string[] }
      notifications: { items: string[] }
      websocket: { items: string[] }
      proxy: { items: string[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const arch = messages.docs.monitor.architecture
  const threadRows = arch.requestFlow.rows
  const systemdItems = arch.systemd.items
  const consequences = arch.appimage.consequences
  const blueprintRows = arch.flask.rows
  const dataRows = arch.dataSources.rows
  const persistenceRows = arch.persistence.rows
  const healthItems = arch.health.items
  const notificationItems = arch.notifications.items
  const websocketItems = arch.websocket.items
  const proxyItems = arch.proxy.items
  const whereNextItems = arch.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const link = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const notifLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/notifications" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const aiLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/ai-assistant" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const accessLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/access-auth" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const fail2banLink = (chunks: React.ReactNode) => (
    <Link href="/docs/security/fail2ban" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const fail2banWarnLink = (chunks: React.ReactNode) => (
    <Link href="/docs/security/fail2ban" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={10}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("requestFlow.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("requestFlow.intro")}</p>

      <DataFlowDiagram
        nodes={[
          { variant: "source", label: t("requestFlow.nodes.clientLabel"), detail: t("requestFlow.nodes.clientDetail") },
          { variant: "bridge", label: t("requestFlow.nodes.flaskLabel"), detail: t("requestFlow.nodes.flaskDetail") },
          { variant: "bridge", label: t("requestFlow.nodes.hostLabel"), detail: t("requestFlow.nodes.hostDetail") },
          { variant: "target", label: t("requestFlow.nodes.stateLabel"), detail: t("requestFlow.nodes.stateDetail") },
        ]}
        arrowLabel={t("requestFlow.diagramArrowLabel")}
        caption={t("requestFlow.diagramCaption")}
      />

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("requestFlow.threadsIntro", { strong })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("requestFlow.headerThread")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("requestFlow.headerCadence")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("requestFlow.headerJob")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {threadRows.map((row, idx) => (
              <tr key={row.thread} className={idx < threadRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.thread}</td>
                <td className="px-3 py-2 align-top whitespace-nowrap">{row.cadence}</td>
                <td className="px-3 py-2 align-top">
                  {t.rich(`requestFlow.rows.${idx}.job`, { code })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("systemd.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("systemd.intro", { code })}
      </p>
      <CopyableCode
        code={`[Unit]
Description=ProxMenux Monitor - Web Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/proxmenux-monitor
ExecStart=/opt/proxmenux-monitor/ProxMenux-Monitor.AppImage
Restart=on-failure
RestartSec=10
Environment="PORT=8008"

[Install]
WantedBy=multi-user.target`}
        className="my-4"
      />
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {systemdItems.map((_, idx) => (
          <li key={idx}>{t.rich(`systemd.items.${idx}`, { strong, code })}</li>
        ))}
      </ul>
      <Callout variant="tip" title={t("systemd.inspectTitle")}>
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{`systemctl cat proxmenux-monitor.service       # show the unit content
systemctl status proxmenux-monitor.service    # state + recent log
journalctl -u proxmenux-monitor.service -f    # follow live`}</pre>
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("appimage.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("appimage.intro", { code })}
      </p>
      <CopyableCode
        code={`AppDir/
├── AppRun                              # entrypoint: sets PATH/LD_LIBRARY_PATH, exec flask_server
├── usr/
│   ├── bin/
│   │   ├── flask_server.py             # main process
│   │   ├── flask_*_routes.py           # Flask blueprints (auth, health, terminal, …)
│   │   ├── auth_manager.py             # JWT + TOTP + API tokens
│   │   ├── health_monitor.py           # 10-category checker
│   │   ├── health_persistence.py       # SQLite layer
│   │   ├── notification_manager.py     # orchestrator
│   │   ├── notification_channels.py    # Telegram, Discord, Email, …
│   │   ├── notification_templates.py   # message rendering + AI hook
│   │   ├── notification_events.py      # JournalWatcher, TaskWatcher, …
│   │   ├── ai_providers/               # OpenAI · Anthropic · Gemini · Groq · Ollama · OpenRouter
│   │   ├── proxmox_storage_monitor.py  # storage pool inspection
│   │   ├── hardware_monitor.py         # CPU/PCIe/GPU enumeration
│   │   ├── ipmitool, sensors, upsc     # vendored hardware tools
│   │   └── …
│   ├── lib/python3/                    # vendored Python deps (Flask, JWT, psutil, …)
│   └── share/                          # icons + .desktop file
└── web/                                # Next.js static export
    ├── index.html
    ├── _next/                          # JS / CSS chunks
    └── manifest.json                   # PWA manifest`}
        className="my-4"
      />
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("appimage.consequencesIntro")}
      </p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {consequences.map((_, idx) => (
          <li key={idx}>{t.rich(`appimage.consequences.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("flask.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("flask.intro", { code })}
      </p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("flask.headerBlueprint")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("flask.headerPrefix")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("flask.headerOwns")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {blueprintRows.map((row, idx) => (
              <tr key={row.blueprint} className={idx < blueprintRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.blueprint}</td>
                <td className="px-3 py-2 align-top font-mono text-xs leading-6">
                  {row.prefix.map((p, pidx) => (
                    <span key={pidx}>
                      {p}
                      {pidx < row.prefix.length - 1 && <br />}
                    </span>
                  ))}
                </td>
                <td className="px-3 py-2 align-top">
                  {t.rich(`flask.rows.${idx}.owns`, { code })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("flask.endpointsLink", { link })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("dataSources.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("dataSources.intro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataSources.headerSource")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataSources.headerUsedFor")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {dataRows.map((row, idx) => (
              <tr key={row.source} className={idx < dataRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.source}</td>
                <td className="px-3 py-2 align-top">{row.usedFor}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("dataSources.cacheTitle")}>
        {t.rich("dataSources.cacheBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("persistence.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("persistence.intro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("persistence.headerPath")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("persistence.headerOwner")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("persistence.headerContents")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {persistenceRows.map((row, idx) => (
              <tr key={row.path} className={idx < persistenceRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.path}</td>
                <td className="px-3 py-2 align-top">{t.rich(`persistence.rows.${idx}.owner`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`persistence.rows.${idx}.contents`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="warning" title={t("persistence.backupTitle")}>
        {t.rich("persistence.backupBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("health.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("health.intro", { code })}
      </p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {healthItems.map((_, idx) => (
          <li key={idx}>{t.rich(`health.items.${idx}`, { code })}</li>
        ))}
      </ol>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("health.afterIntro", { code })}
      </p>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("health.cycleEnd", { em, code, link })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("notifications.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("notifications.intro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {notificationItems.map((_, idx) => (
          <li key={idx}>{t.rich(`notifications.items.${idx}`, { strong, code })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("notifications.linksFooter", { notifLink, aiLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("websocket.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("websocket.intro", { em, code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {websocketItems.map((_, idx) => (
          <li key={idx}>{t.rich(`websocket.items.${idx}`, { strong, code })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("websocket.outro", { code })}
      </p>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("websocket.proxyNote", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("proxy.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("proxy.intro")}</p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {proxyItems.map((_, idx) => (
          <li key={idx}>{t.rich(`proxy.items.${idx}`, { strong, code })}</li>
        ))}
      </ol>
      <Callout variant="info" title={t("proxy.calloutTitle")}>
        {t.rich("proxy.calloutBody", { strong, code, link: fail2banWarnLink })}
      </Callout>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("proxy.outro", { accessLink, fail2banLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {whereNextItems.map((item) => (
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
