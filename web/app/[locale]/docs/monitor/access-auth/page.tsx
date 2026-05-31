import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.accessAuth.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox 2fa",
      "proxmox totp",
      "proxmox dashboard authentication",
      "proxmox user profile",
      "proxmox dashboard avatar",
      "proxmox api tokens",
      "proxmox reverse proxy",
      "proxmox nginx",
      "proxmox caddy",
      "proxmox traefik",
      "proxmox fail2ban dashboard",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/monitor/access-auth" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/monitor/access-auth",
    },
    twitter: {
      card: "summary",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type Row2 = { button: string; what: string; api: string }
type FieldRow = { field: string; required: string; notes: string }
type EndpointRow = { endpoint: string; what: string }
type CryptoRow = { asset: string; algorithm: string; where: string }
type AppRow = { name: string; href: string; platforms: string; notes: string }
type WhereNextItem = { label: string; href: string; tail?: string; tailRich?: string }

export default async function MonitorAccessAuthPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.accessAuth" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { accessAuth: {
      firstLaunch: {
        rows: Row2[]
        fieldRows: FieldRow[]
        endpointRows: EndpointRow[]
      }
      password: {
        items: string[]
        publicItems: string[]
        cryptoRows: CryptoRow[]
      }
      twofa: {
        apps: AppRow[]
        setupSteps: string[]
        setupStep4Sub: string[]
        lostItems: string[]
        rejectedItems: string[]
      }
      apiTokens: { generateSteps: string[]; cheatItems: string[] }
      https: { items: string[] }
      fail2ban: { items: string[] }
      whereNext: { items: WhereNextItem[] }
    } } }
  }
  const aa = messages.docs.monitor.accessAuth
  const firstLaunchRows = aa.firstLaunch.rows
  const fieldRows = aa.firstLaunch.fieldRows
  const endpointRows = aa.firstLaunch.endpointRows
  const passwordItems = aa.password.items
  const publicItems = aa.password.publicItems
  const cryptoRows = aa.password.cryptoRows
  const apps = aa.twofa.apps
  const setupSteps = aa.twofa.setupSteps
  const setupStep4Sub = aa.twofa.setupStep4Sub
  const lostItems = aa.twofa.lostItems
  const rejectedItems = aa.twofa.rejectedItems
  const generateSteps = aa.apiTokens.generateSteps
  const cheatItems = aa.apiTokens.cheatItems
  const httpsItems = aa.https.items
  const fail2banItems = aa.fail2ban.items
  const whereNextItems = aa.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const apiLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const intLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const gatewayLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const fail2banLink = (chunks: React.ReactNode) => (
    <Link href="/docs/security/fail2ban" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const tailscaleAnchor = (chunks: React.ReactNode) => (
    <a href="https://tailscale.com" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
      {chunks}
      <ExternalLink className="h-3 w-3" aria-hidden="true" />
    </a>
  )
  const tsKeysAnchor = (chunks: React.ReactNode) => (
    <a href="https://login.tailscale.com/admin/settings/keys" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
      {chunks}
      <ExternalLink className="h-3 w-3" aria-hidden="true" />
    </a>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={15}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { em, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("reaching.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("reaching.intro", { code })}
      </p>
      <CopyableCode
        code={`# 1) Direct on the LAN
http://<proxmox-ip>:8008

# 2) Behind a reverse proxy with a dedicated host name (recommended off-LAN)
https://monitor.example.com

# 3) Through Secure Gateway (Tailscale) — same LAN URL, from anywhere
http://<proxmox-lan-ip>:8008      # works from any device on your tailnet`}
        className="my-4"
      />
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("reaching.outro", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("firstLaunch.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("firstLaunch.intro", { code, em })}
      </p>

      <figure className="my-6">
        <img src="/monitor/auth-setup.png" alt={t("firstLaunch.imageAlt")} className="rounded-lg border border-gray-200 shadow-sm w-full" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("firstLaunch.imageCaption")}</figcaption>
      </figure>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("firstLaunch.headerButton")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("firstLaunch.headerWhat")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("firstLaunch.headerApi")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {firstLaunchRows.map((row, idx) => (
              <tr key={row.button} className={idx < firstLaunchRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.button}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`firstLaunch.rows.${idx}.what`, { em, code })}</td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.api}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("firstLaunch.twofaCalloutTitle")}>
        {t.rich("firstLaunch.twofaCalloutBody", { strong })}
      </Callout>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("firstLaunch.createTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("firstLaunch.createIntro", { em })}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("firstLaunch.headerField")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("firstLaunch.headerRequired")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("firstLaunch.headerNotes")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {fieldRows.map((row, idx) => (
              <tr key={row.field} className={idx < fieldRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.field}</strong></td>
                <td className="px-3 py-2 align-top">{row.required}</td>
                <td className="px-3 py-2 align-top">{t.rich(`firstLaunch.fieldRows.${idx}.notes`, { code, strong })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <figure className="my-6">
        <img src="/monitor/security/create-user-form.png" alt={t("firstLaunch.createImageAlt")} className="rounded-lg border border-gray-200 shadow-sm w-full" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("firstLaunch.createImageCaption")}</figcaption>
      </figure>

      <Callout variant="info" title={t("firstLaunch.saveCalloutTitle")}>
        {t.rich("firstLaunch.saveCalloutBody", { code })}
      </Callout>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("firstLaunch.avatarTitle")}</h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("firstLaunch.avatarBody1", { strong })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("firstLaunch.avatarBody2")}</p>

      <figure className="my-6">
        <img src="/monitor/security/profile-page.png" alt={t("firstLaunch.profileImageAlt")} className="rounded-lg border border-gray-200 shadow-sm w-full" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("firstLaunch.profileImageCaption")}</figcaption>
      </figure>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("firstLaunch.headerEndpoint")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("firstLaunch.headerEpWhat")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {endpointRows.map((row, idx) => (
              <tr key={row.endpoint} className={idx < endpointRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.endpoint}</td>
                <td className="px-3 py-2 align-top">{t.rich(`firstLaunch.endpointRows.${idx}.what`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="warning" title={t("firstLaunch.reversibleTitle")}>
        {t.rich("firstLaunch.reversibleBody", { em, strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("password.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("password.intro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {passwordItems.map((_, idx) => (
          <li key={idx}>{t.rich(`password.items.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <figure className="my-6">
        <img src="/monitor/login-screen.png" alt={t("password.loginImageAlt")} className="rounded-lg border border-gray-200 shadow-sm w-full" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("password.loginImageCaption")}</figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("password.loginFlowTitle")}</h3>
      <CopyableCode
        code={`# Without 2FA
curl -X POST http://<host>:8008/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username":"<user>","password":"<password>"}'

# Response
{
  "success": true,
  "token": "eyJhbGciOiJIUzI1NiIs..."
}`}
        className="my-4"
      />
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("password.twofaIntro", { code })}
      </p>
      <CopyableCode
        code={`curl -X POST http://<host>:8008/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username":"<user>","password":"<password>","totp_token":"123456"}'`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("password.publicTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("password.publicIntro")}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {publicItems.map((_, idx) => (
          <li key={idx}>{t.rich(`password.publicItems.${idx}`, { code })}</li>
        ))}
      </ul>

      <h3 id="security-model" className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("password.cryptoTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("password.cryptoIntro", { code })}
      </p>

      <div className="overflow-x-auto mb-4">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("password.headerAsset")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("password.headerAlgo")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("password.headerWhere")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {cryptoRows.map((row, idx) => (
              <tr key={row.asset} className={idx < cryptoRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top"><strong>{row.asset}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`password.cryptoRows.${idx}.algorithm`, { code })}</td>
                <td className="px-3 py-2 align-top">{t.rich(`password.cryptoRows.${idx}.where`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("password.authJsonTitle")}>
        {t.rich("password.authJsonBody", { code, em })}
      </Callout>

      <Callout variant="warning" title={t("password.rotateTitle")}>
        {t.rich("password.rotateBody", { code, strong })}
      </Callout>

      <h3 id="recovering-password" className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("password.recoverTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("password.recoverIntro", { code })}
      </p>

      <CopyableCode
        code={`# 1. Run the ProxMenux menu as root
menu

# 2. Settings → Reset ProxMenux Monitor Password
#    The menu will:
#     - Back up auth.json to auth.json.bak-<UTC timestamp>
#     - Stop the proxmenux-monitor service
#     - Clear username / password_hash / TOTP secret / backup codes
#     - Keep jwt_secret and api_tokens intact
#     - Restart the service

# 3. Open the dashboard at http://<host>:8008
#    The setup wizard appears — create a new admin account.`}
        className="my-4"
      />

      <Callout variant="info" title={t("password.survivesTitle")}>
        {t.rich("password.survivesBody", { code })}
      </Callout>

      <Callout variant="warning" title={t("password.physicalTitle")}>
        {t.rich("password.physicalBody", { strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("twofa.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("twofa.intro", { strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("twofa.pickTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("twofa.pickIntro")}</p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("twofa.headerApp")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("twofa.headerPlatforms")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("twofa.headerAppNotes")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {apps.map((row, idx) => (
              <tr key={row.name} className={idx < apps.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap">
                  <a
                    href={row.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-semibold text-blue-600 hover:underline inline-flex items-center gap-1"
                  >
                    {row.name}
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </a>
                </td>
                <td className="px-3 py-2 align-top">{row.platforms}</td>
                <td className="px-3 py-2 align-top">{row.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("twofa.backupTitle")}>
        {t("twofa.backupBody")}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("twofa.setupTitle")}</h3>

      <figure className="my-6">
        <img src="/monitor/2fa-setup.png" alt={t("twofa.setupImageAlt")} className="rounded-lg border border-gray-200 shadow-sm w-full" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("twofa.setupImageCaption")}</figcaption>
      </figure>

      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-3">
        {setupSteps.map((_, idx) => (
          <li key={idx}>
            {t.rich(`twofa.setupSteps.${idx}`, { strong, em, code })}
            {idx === 3 && (
              <ul className="list-disc pl-6 mt-2 space-y-1">
                {setupStep4Sub.map((_, sIdx) => (
                  <li key={sIdx}>{t.rich(`twofa.setupStep4Sub.${sIdx}`, { em, code })}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>

      <Callout variant="warning" title={t("twofa.testTitle")}>
        {t.rich("twofa.testBody", { em, code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("twofa.lostTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("twofa.lostIntro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {lostItems.map((_, idx) => (
          <li key={idx}>
            {t.rich(`twofa.lostItems.${idx}`, { strong, code })}
            {idx === 2 && (
              <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{`systemctl restart proxmenux-monitor.service`}</pre>
            )}
          </li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("twofa.lostShellOutro")}</p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("twofa.disableTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("twofa.disableBody", { strong, code })}
      </p>

      <Callout variant="troubleshoot" title={t("twofa.rejectedTitle")}>
        {t("twofa.rejectedIntro")}
        <ul className="list-disc pl-5 mt-2 space-y-1">
          {rejectedItems.map((_, idx) => (
            <li key={idx}>{t.rich(`twofa.rejectedItems.${idx}`, { strong, code })}</li>
          ))}
        </ul>
        {t("twofa.rejectedOutro")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("apiTokens.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("apiTokens.intro", { strong, code })}
      </p>

      <figure className="my-6">
        <img src="/monitor/api-tokens.png" alt={t("apiTokens.imageAlt")} className="rounded-lg border border-gray-200 shadow-sm w-full" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("apiTokens.imageCaption")}</figcaption>
      </figure>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("apiTokens.generateTitle")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("apiTokens.generateIntro")}</p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {generateSteps.map((_, idx) => (
          <li key={idx}>{t.rich(`apiTokens.generateSteps.${idx}`, { strong, em })}</li>
        ))}
      </ol>

      <p className="mb-3 text-gray-800 leading-relaxed">{t("apiTokens.generateCli")}</p>
      <CopyableCode
        code={`curl -X POST http://<host>:8008/api/auth/generate-api-token \\
  -H "Authorization: Bearer <session-token>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "password": "<your-password>",
    "totp_token": "123456",
    "token_name": "Home Assistant"
  }'

# Response — the "token" field is the only place the token appears.
{
  "success": true,
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_name": "Home Assistant",
  "expires_in": "365 days"
}`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("apiTokens.useTitle")}</h3>
      <CopyableCode
        code={`curl -H "Authorization: Bearer <api-token>" \\
  http://<host>:8008/api/system`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("apiTokens.revokeTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("apiTokens.revokeBody", { strong, code })}
      </p>
      <CopyableCode
        code={`# Same operation via API
curl -X DELETE http://<host>:8008/api/auth/api-tokens/<token-id> \\
  -H "Authorization: Bearer <session-token>"`}
        className="my-4"
      />

      <Callout variant="tip" title={t("apiTokens.cheatTitle")}>
        <ul className="list-disc pl-5 mt-2 space-y-1">
          {cheatItems.map((_, idx) => (
            <li key={idx}>{t.rich(`apiTokens.cheatItems.${idx}`, { code })}</li>
          ))}
        </ul>
      </Callout>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("apiTokens.outro", { apiLink, intLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("https.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("https.intro")}</p>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {httpsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`https.items.${idx}`, { strong, code })}</li>
        ))}
      </ol>
      <Callout variant="warning" title={t("https.calloutTitle")}>
        {t("https.calloutBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("gateway.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("gateway.intro", { strong, a: tailscaleAnchor })}
      </p>
      <Callout variant="tip" title={t("gateway.calloutTitle")}>
        {t.rich("gateway.calloutBody", { code })}
      </Callout>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("gateway.deployBody", { a: tsKeysAnchor })}
      </p>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("gateway.outro", { link: gatewayLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("proxy.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("proxy.intro", { strong, code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("proxy.nginxTitle")}</h3>
      <CopyableCode
        code={`# /etc/nginx/sites-available/proxmenux-monitor.conf
server {
    listen 443 ssl http2;
    server_name monitor.example.com;

    ssl_certificate     /etc/letsencrypt/live/monitor.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/monitor.example.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8008;
        proxy_http_version 1.1;

        # WebSocket upgrade (terminal tab)
        proxy_set_header   Upgrade           $http_upgrade;
        proxy_set_header   Connection        "upgrade";

        # Real client IP — required for the auth log + Fail2Ban hook
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   X-Forwarded-Host  $host;

        # Long-running terminal sessions
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("proxy.caddyTitle")}</h3>
      <CopyableCode
        code={`# Caddyfile
monitor.example.com {
    reverse_proxy 127.0.0.1:8008 {
        # Caddy auto-handles WebSocket upgrades and forwards X-Forwarded-* by default.
        header_up Host {host}
        header_up X-Real-IP {remote}
    }
}`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("proxy.traefikTitle")}</h3>
      <CopyableCode
        code={`# docker-compose snippet, or equivalent IngressRoute on Kubernetes
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.proxmenux.rule=Host(\`monitor.example.com\`)"
  - "traefik.http.routers.proxmenux.tls=true"
  - "traefik.http.routers.proxmenux.tls.certresolver=letsencrypt"
  - "traefik.http.services.proxmenux.loadbalancer.server.port=8008"
  # WebSocket and forwarded headers are on by default in Traefik.`}
        className="my-4"
      />

      <Callout variant="tip" title={t("proxy.subPathTitle")}>
        {t.rich("proxy.subPathBody", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("audit.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("audit.intro", { code })}
      </p>
      <CopyableCode
        code={`# Failed login from 192.0.2.10 (real IP recovered from X-Forwarded-For)
2026-04-24 14:32:11 WARNING proxmenux.auth: authentication failure; rhost=192.0.2.10 user=admin

# Successful login
2026-04-24 14:32:18 INFO    proxmenux.auth: authentication success;  rhost=192.0.2.10 user=admin`}
        className="my-4"
      />
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("audit.outro", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("fail2ban.heading")}</h2>
      <Callout variant="info" title={t("fail2ban.calloutTitle")}>
        {t.rich("fail2ban.calloutBody", { strong, link: fail2banLink })}
      </Callout>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("fail2ban.intro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {fail2banItems.map((_, idx) => (
          <li key={idx}>{t.rich(`fail2ban.items.${idx}`, { code })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("fail2ban.outro", { link: fail2banLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.noScreenTitle")}>
        {t.rich("troubleshoot.noScreenBody", { code })}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{`rm /root/.config/proxmenux-monitor/auth.json
systemctl restart proxmenux-monitor.service`}</pre>
        {t.rich("troubleshoot.noScreenOutro", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.tokenTitle")}>
        {t.rich("troubleshoot.tokenBody", { code })}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{`curl -H "Authorization: Bearer <token>" \\
  http://<host>:8008/api/system | jq .`}</pre>
        {t.rich("troubleshoot.tokenOutro", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.no2faTitle")}>
        {t.rich("troubleshoot.no2faBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.wsTitle")}>
        {t.rich("troubleshoot.wsBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {whereNextItems.map((item, idx) => (
          <li key={item.href + idx}>
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
