import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"
import { routing } from "@/i18n/routing"

/**
 * Pilot page for the i18n migration. Pattern used here is the same one
 * contributors should follow for every other docs page:
 *
 *   - Translatable strings live under `messages/<locale>/docs/<section>/<page>.json`
 *     (or `index.json` when the file represents the section's index page,
 *     like this one).
 *   - The page is an async Server Component that calls
 *     `getTranslations({ namespace: '<namespace>' })` once and uses
 *     `t()` for plain text and `t.rich()` for paragraphs containing
 *     <code>, <strong>, <em> or <link> markers.
 *   - Arrays of structured items (table rows, lists, etc.) are pulled
 *     with `getMessages({ locale })` and iterated; that keeps the JSON readable
 *     for translators.
 *   - generateMetadata uses the same namespace so <title> and OG tags
 *     translate with the locale.
 */

export async function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }))
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox monitor",
      "proxmox dashboard",
      "proxmox ve dashboard",
      "proxmox web dashboard",
      "proxmox notifications",
      "proxmox health monitor",
      "proxmox smart monitoring",
      "proxmox prometheus",
      "proxmox homepage integration",
      "proxmenux monitor",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/monitor" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/monitor",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type CoverageSection = { name: string; description: string }
type NextStepItem = { label: string; description: string }

export default async function MonitorOverviewPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)

  const t = await getTranslations({ locale, namespace: "docs.monitor" })

  // Arrays of objects can't be expressed via t(), so pull them straight
  // from the message tree. This is the recommended pattern in the
  // next-intl docs for repeating structured items like table rows.
  const messages = (await getMessages({ locale })) as unknown as {
    docs: {
      monitor: {
        coverage: { sections: CoverageSection[] }
        nextSteps: { items: NextStepItem[] }
        howItRuns: { bullets: string[] }
      }
    }
  }
  const coverageSections = messages.docs.monitor.coverage.sections
  const nextStepsItems = messages.docs.monitor.nextSteps.items
  const howItRunsBullets = messages.docs.monitor.howItRuns.bullets

  // Inline tag renderers shared across every t.rich() call on this page.
  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  // <link>...</link> defaults to "/docs/monitor" — the section index.
  // Individual t.rich() calls override this to point elsewhere when
  // the source string demands it (api section, etc.).
  const link = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={6}
      />

      <Callout variant="info" title={t("atGlance.title")}>
        {t.rich("atGlance.body", { code })}
      </Callout>

      {/* Hero screenshot */}
      <figure className="my-8">
        <img
          src="/monitor/dashboard-home.png"
          alt={t("hero.alt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("hero.caption")}
        </figcaption>
      </figure>

      {/* ─────────────────────────── What it covers ─────────────────────────── */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("coverage.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("coverage.intro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("coverage.tableSection")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("coverage.tableWhat")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {coverageSections.map((row, idx) => (
              <tr
                key={row.name}
                className={idx < coverageSections.length - 1 ? "border-b border-gray-100" : ""}
              >
                <td className="px-3 py-2 align-top whitespace-nowrap">
                  <strong>{row.name}</strong>
                </td>
                <td className="px-3 py-2 align-top">
                  {t.rich(`coverage.sections.${idx}.description`, { code })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("coverage.footer", { link })}
      </p>

      {/* ─────────────────────────── How it runs ─────────────────────────── */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howItRuns.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("howItRuns.intro", { code })}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {howItRunsBullets.map((_, idx) => (
          <li key={idx}>{t.rich(`howItRuns.bullets.${idx}`, { code, strong })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("howItRuns.footer", { link })}
      </p>

      <Callout variant="tip" title={t("noAgent.title")}>
        {t("noAgent.body")}
      </Callout>

      {/* ─────────────────────────── Access ─────────────────────────── */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("access.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("access.intro")}</p>
      <CopyableCode
        code={`${t("access.codeComment1")}
http://<your-proxmox-ip>:8008

${t("access.codeComment2")}
https://<your-domain>/proxmenux-monitor/`}
        className="my-4"
      />
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("access.afterCode", { code })}
      </p>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("access.footer", { link })}
      </p>

      {/* ─────────────────────────── Mobile / PWA ─────────────────────────── */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("mobile.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("mobile.intro", { code })}</p>
      <div className="grid md:grid-cols-2 gap-6 my-6 items-start">
        <figure>
          <img
            src="/monitor/mobile-home.png"
            alt={t("mobile.phoneAlt")}
            className="rounded-lg border border-gray-200 shadow-sm w-full"
          />
          <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
            {t("mobile.phoneCaption")}
          </figcaption>
        </figure>
        <div>
          <h3 className="text-lg font-semibold mb-2 text-gray-900">{t("mobile.addHeading")}</h3>
          <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
            <li>
              <strong>{t("mobile.iosLabel")}</strong> {t.rich("mobile.iosBody", { code, em })}
            </li>
            <li>
              <strong>{t("mobile.androidLabel")}</strong>{" "}
              {t.rich("mobile.androidBody", { em })}
            </li>
            <li>{t("mobile.afterInstall")}</li>
          </ul>
          <Callout variant="warning" title={t("mobile.onlineOnlyTitle")} className="mt-4">
            {t.rich("mobile.onlineOnlyBody", { strong })}
          </Callout>
        </div>
      </div>

      {/* ─────────────────────────── Health Monitor ─────────────────────────── */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("health.heading")}</h2>

      <figure className="my-6">
        <img
          src="/monitor/health-monitor.png"
          alt={t("health.alt")}
          className="rounded-lg border border-gray-200 shadow-sm w-full"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("health.caption")}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("health.body1", { code, strong })}
      </p>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("health.feedsIntro")}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        <li>{t.rich("health.feedsHealth", { strong })}</li>
        <li>{t.rich("health.feedsChannels", { strong })}</li>
        <li>{t.rich("health.feedsAI", { strong })}</li>
      </ul>
      <Callout variant="tip" title={t("health.suppressionTitle")}>
        {t.rich("health.suppressionBody", { em })}
      </Callout>

      {/* ─────────────────────────── API & integrations ─────────────────────────── */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("api.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("api.intro", { code })}
      </p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        <li>{t.rich("api.tokens", { code, strong })}</li>
        <li>{t.rich("api.bearer", { code })}</li>
        <li>
          {t.rich("api.catalog", {
            linkApi: (chunks) => (
              <Link href="/docs/monitor" className="text-blue-600 hover:underline">
                {chunks}
              </Link>
            ),
            linkIntegrations: (chunks) => (
              <Link href="/docs/monitor" className="text-blue-600 hover:underline">
                {chunks}
              </Link>
            ),
          })}
        </li>
      </ul>

      {/* ─────────────────────────── Service control ─────────────────────────── */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("serviceControl.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("serviceControl.intro", { em })}
      </p>
      <CopyableCode
        code={`${t("serviceControl.codeComment")}
systemctl status proxmenux-monitor.service
systemctl is-active proxmenux-monitor.service
systemctl enable --now proxmenux-monitor.service
systemctl disable --now proxmenux-monitor.service
journalctl -u proxmenux-monitor.service -f`}
        className="my-4"
      />
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("serviceControl.footer", {
          link: (chunks) => (
            <Link href="/docs/settings/proxmenux-monitor" className="text-blue-600 hover:underline">
              {chunks}
            </Link>
          ),
        })}
      </p>

      {/* ─────────────────────────── Where to next ─────────────────────────── */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("nextSteps.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {nextStepsItems.map((item) => (
          <li key={item.label}>
            <Link href="/docs/monitor" className="text-blue-600 hover:underline">
              {item.label}
            </Link>{" "}
            {item.description}
          </li>
        ))}
      </ul>
    </div>
  )
}
