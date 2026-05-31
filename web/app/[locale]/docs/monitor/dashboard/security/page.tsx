import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
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
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.security.meta" })
  return { title: t("title"), description: t("description") }
}

type DataRow = { card: string; endpoint: string; source: string }
type WhereNextItem = { label: string; href: string; tail?: string; tailRich?: string }

export default async function SecurityTabPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.security" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { security: {
      auth: { items: string[] }
      ssl: { items: string[] }
      gateway: { step3Items: string[]; step4Items: string[] }
      firewall: { items: string[] }
      lynis: { scoreItems: string[] }
      dataCollected: { rows: DataRow[] }
      whereNext: { items: WhereNextItem[] }
    } } } }
  }
  const sec = messages.docs.monitor.dashboard.security
  const authItems = sec.auth.items
  const sslItems = sec.ssl.items
  const step3Items = sec.gateway.step3Items
  const step4Items = sec.gateway.step4Items
  const firewallItems = sec.firewall.items
  const lynisScoreItems = sec.lynis.scoreItems
  const dataRows = sec.dataCollected.rows
  const whereNextItems = sec.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const authLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/access-auth" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const sslPageLink = (chunks: React.ReactNode) => (
    <Link href="/docs/security/ssl-letsencrypt" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const integrationsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/integrations" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const tailscaleHomeAnchor = (chunks: React.ReactNode) => (
    <a href="https://tailscale.com" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
      {chunks}
      <ExternalLink className="h-3 w-3" aria-hidden="true" />
    </a>
  )
  const tailscaleKeysAnchor = (chunks: React.ReactNode) => (
    <a href="https://login.tailscale.com/admin/settings/keys" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
      {chunks}
      <ExternalLink className="h-3 w-3" aria-hidden="true" />
    </a>
  )
  const tailscaleMachinesAnchor = (chunks: React.ReactNode) => (
    <a href="https://login.tailscale.com/admin/machines" target="_blank" rel="noopener noreferrer" className="text-amber-700 hover:underline inline-flex items-center gap-1">
      {chunks}
      <ExternalLink className="h-3 w-3" aria-hidden="true" />
    </a>
  )
  const fail2banLink = (chunks: React.ReactNode) => (
    <Link href="/docs/security/fail2ban" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const lynisLink = (chunks: React.ReactNode) => (
    <Link href="/docs/security/lynis" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const lynisSampleAnchor = (chunks: React.ReactNode) => (
    <a href="/monitor/security/lynis-sample-report.pdf" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
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
        estimatedMinutes={18}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("monitor.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("monitor.intro")}</p>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("auth.heading")}</h3>

      <figure className="my-4">
        <Image src="/monitor/security/auth-card.png" alt={t("auth.imageAlt")} width={2000} height={956} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("auth.imageCaption")}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("auth.intro", { link: authLink })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {authItems.map((_, idx) => (
          <li key={idx}>{t.rich(`auth.items.${idx}`, { strong, em })}</li>
        ))}
      </ul>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("ssl.heading")}</h3>

      <figure className="my-4">
        <Image src="/monitor/security/ssl-https-card.png" alt={t("ssl.imageAlt")} width={2000} height={1124} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("ssl.imageCaption", { em })}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("ssl.intro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {sslItems.map((_, idx) => (
          <li key={idx}>{t.rich(`ssl.items.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <figure className="my-4">
        <Image src="/monitor/security/ssl-https-enabled.png" alt={t("ssl.enabledAlt")} width={2000} height={889} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("ssl.enabledCaption", { em })}</figcaption>
      </figure>

      <Callout variant="info" title={t("ssl.acmeTitle")}>
        {t.rich("ssl.acmeBody", { em })}
      </Callout>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("ssl.walkthroughLink", { code, link: sslPageLink })}
      </p>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("apiTokens.heading")}</h3>

      <figure className="my-4">
        <Image src="/monitor/security/api-tokens-empty.png" alt={t("apiTokens.emptyAlt")} width={2000} height={855} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("apiTokens.emptyCaption", { em, code })}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("apiTokens.intro")}</p>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("apiTokens.generateBody", { strong, em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/api-tokens-generate.png" alt={t("apiTokens.generateAlt")} width={2000} height={1124} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("apiTokens.generateCaption")}</figcaption>
      </figure>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("apiTokens.saveBody", { strong })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/api-tokens-generated.png" alt={t("apiTokens.generatedAlt")} width={2000} height={1468} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("apiTokens.generatedCaption", { code })}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("apiTokens.outro", { em, link: integrationsLink })}
      </p>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("gateway.heading")}</h3>

      <figure className="my-4">
        <Image src="/monitor/security/secure-gateway-card.png" alt={t("gateway.cardAlt")} width={2000} height={434} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("gateway.cardCaption")}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("gateway.intro", { code, a: tailscaleHomeAnchor })}
      </p>

      <h4 className="text-lg font-semibold mt-6 mb-3 text-gray-900">{t("gateway.wizardTitle")}</h4>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("gateway.wizardIntro", { em })}
      </p>

      <h5 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("gateway.step0Title")}</h5>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("gateway.step0Body", { em, a: tailscaleKeysAnchor })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/tailscale-auth-key-page.png" alt={t("gateway.step0Alt")} width={2000} height={1115} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("gateway.step0Caption", { em })}</figcaption>
      </figure>

      <h5 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("gateway.step1Title")}</h5>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("gateway.step1Body", { em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/gateway-step-1-intro.png" alt={t("gateway.step1Alt")} width={1589} height={2000} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("gateway.step1Caption")}</figcaption>
      </figure>

      <h5 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("gateway.step2Title")}</h5>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("gateway.step2Body", { code })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/gateway-step-3-auth.png" alt={t("gateway.step2Alt")} width={1985} height={2000} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("gateway.step2Caption")}</figcaption>
      </figure>

      <h5 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("gateway.step3Title")}</h5>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("gateway.step3Intro")}</p>
      <ul className="list-disc pl-6 mb-3 text-gray-800 leading-relaxed space-y-1">
        {step3Items.map((_, idx) => (
          <li key={idx}>{t.rich(`gateway.step3Items.${idx}`, { strong })}</li>
        ))}
      </ul>

      <figure className="my-4">
        <Image src="/monitor/security/gateway-step-2-scope.png" alt={t("gateway.step3Alt")} width={1934} height={2000} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("gateway.step3Caption", { em })}</figcaption>
      </figure>

      <h5 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("gateway.step4Title")}</h5>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("gateway.step4Intro", { strong })}
      </p>
      <ul className="list-disc pl-6 mb-3 text-gray-800 leading-relaxed space-y-1">
        {step4Items.map((_, idx) => (
          <li key={idx}>{t.rich(`gateway.step4Items.${idx}`, { strong, em })}</li>
        ))}
      </ul>

      <figure className="my-4">
        <Image src="/monitor/security/gateway-step-4-advanced.png" alt={t("gateway.step4Alt")} width={1847} height={2000} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("gateway.step4Caption")}</figcaption>
      </figure>

      <h5 className="text-base font-semibold mt-6 mb-2 text-gray-900">{t("gateway.step5Title")}</h5>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("gateway.step5Body", { strong })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/gateway-step-5-review.png" alt={t("gateway.step5Alt")} width={1860} height={2000} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("gateway.step5Caption")}</figcaption>
      </figure>

      <Callout variant="warning" title={t("gateway.approvalTitle")}>
        {t.rich("gateway.approvalBody", { em, a: tailscaleMachinesAnchor })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("pve.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("pve.intro")}</p>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("firewall.heading")}</h3>

      <figure className="my-4">
        <Image src="/monitor/security/firewall-card.png" alt={t("firewall.imageAlt")} width={2000} height={1256} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("firewall.imageCaption", { em })}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("firewall.intro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {firewallItems.map((_, idx) => (
          <li key={idx}>{t.rich(`firewall.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">
        {t("fail2ban.heading")} <em>{t("fail2ban.subHeading")}</em>
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("fail2ban.whatIs", { strong })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("fail2ban.notBundled", { strong })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/fail2ban-not-installed.png" alt={t("fail2ban.notInstalledAlt")} width={2000} height={968} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("fail2ban.notInstalledCaption")}</figcaption>
      </figure>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("fail2ban.clickBody", { em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/fail2ban-install-confirm.png" alt={t("fail2ban.confirmAlt")} width={1808} height={1678} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("fail2ban.confirmCaption", { code })}</figcaption>
      </figure>

      <p className="mb-3 text-gray-800 leading-relaxed">{t("fail2ban.confirmIntro")}</p>

      <figure className="my-4">
        <Image src="/monitor/security/fail2ban-install-progress.png" alt={t("fail2ban.progressAlt")} width={2000} height={1512} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("fail2ban.progressCaption")}</figcaption>
      </figure>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("fail2ban.afterInstall", { em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/fail2ban-active.png" alt={t("fail2ban.activeAlt")} width={2000} height={1614} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("fail2ban.activeCaption", { code })}</figcaption>
      </figure>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("fail2ban.tuneBody", { strong, em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/fail2ban-sshd-config.png" alt={t("fail2ban.configAlt")} width={2000} height={919} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("fail2ban.configCaption", { em })}</figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("fail2ban.outro", { em, code, link: fail2banLink })}
      </p>

      <Callout variant="info" title={t("fail2ban.calloutTitle")}>
        {t.rich("fail2ban.calloutBody", { em, code })}
      </Callout>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">
        {t("lynis.heading")} <em>{t("lynis.subHeading")}</em>
      </h3>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("lynis.whatIs", { strong })}
      </p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("lynis.whyUseful", { strong, code })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/lynis-not-installed.png" alt={t("lynis.notInstalledAlt")} width={2000} height={919} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("lynis.notInstalledCaption")}</figcaption>
      </figure>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("lynis.notBundled", { strong })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/lynis-install-confirm.png" alt={t("lynis.confirmAlt")} width={1985} height={2000} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("lynis.confirmCaption")}</figcaption>
      </figure>

      <figure className="my-4">
        <Image src="/monitor/security/lynis-install-progress.png" alt={t("lynis.progressAlt")} width={1856} height={972} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("lynis.progressCaption")}</figcaption>
      </figure>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("lynis.afterInstall", { em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/lynis-installed-empty.png" alt={t("lynis.installedAlt")} width={2000} height={1131} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("lynis.installedCaption")}</figcaption>
      </figure>

      <figure className="my-4">
        <Image src="/monitor/security/lynis-audit-running.png" alt={t("lynis.runningAlt")} width={2000} height={1131} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t("lynis.runningCaption")}</figcaption>
      </figure>

      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("lynis.finishedBody", { em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/lynis-audit-results.png" alt={t("lynis.resultsAlt")} width={2000} height={1183} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">{t.rich("lynis.resultsCaption", { strong })}</figcaption>
      </figure>

      <Callout variant="info" title={t("lynis.scoreTitle")}>
        {t.rich("lynis.scoreIntro", { em, code })}
        <ul className="list-disc pl-6 mt-2 mb-0 space-y-1">
          {lynisScoreItems.map((_, idx) => (
            <li key={idx}>{t.rich(`lynis.scoreItems.${idx}`, { em })}</li>
          ))}
        </ul>
      </Callout>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("lynis.reportBody", { strong, em })}
      </p>

      <figure className="my-4">
        <Image src="/monitor/security/lynis-report-pdf.png" alt={t("lynis.reportAlt")} width={1414} height={2000} className="rounded-lg border border-gray-200 shadow-sm w-full h-auto" />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("lynis.reportCaption", { a: lynisSampleAnchor })}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("lynis.runPeriodically")}</p>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("lynis.outro", { em, link: lynisLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("dataCollected.heading")}</h2>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerCard")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerEndpoint")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("dataCollected.headerSource")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {dataRows.map((row, idx) => (
              <tr key={row.card} className={idx < dataRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top">{row.card}</td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.endpoint}</td>
                <td className="px-3 py-2 align-top">{t.rich(`dataCollected.rows.${idx}.source`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CopyableCode
        code={`# Confirm the auth log on the host (used by Fail2Ban + audit)
journalctl -t proxmenux-auth --since '7 days ago' | tail

# Cross-check the firewall rules the dashboard sees
pve-firewall status
cat /etc/pve/firewall/host.fw

# Verify Fail2Ban (only if installed)
fail2ban-client status
fail2ban-client status sshd

# Verify Lynis (only if installed)
lynis show version
ls -lh /var/log/lynis-report.dat`}
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
