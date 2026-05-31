import type { Metadata } from "next"
import Image from "next/image"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { Terminal, FileCode, ShieldCheck, ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.installation.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/installation",
    },
  }
}

type DuringRow = { package: string; purpose: string }

export default async function InstallationPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.installation" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: {
      installation: {
        during: { rows: DuringRow[] }
      }
    }
  }
  const duringRows = messages.docs.installation.during.rows

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  const internalLink = (href: string, className = "text-blue-600 hover:underline") =>
    (chunks: React.ReactNode) => (
      <Link href={href} className={className}>
        {chunks}
      </Link>
    )

  const extlink = (href: string, className = "text-blue-600 hover:underline inline-flex items-center gap-1") =>
    (chunks: React.ReactNode) => (
      <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
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
        estimatedMinutes={3}
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        <Terminal className="inline h-5 w-5 mr-1 -mt-1 text-blue-600" aria-hidden />
        {t("stable.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("stable.intro")}</p>
      <CopyableCode code={t.raw("stable.code") as string} />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("during.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("during.intro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("during.tablePackage")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("during.tablePurpose")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {duringRows.map((row, idx) => (
              <tr key={row.package} className={idx < duringRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap font-mono text-xs">{row.package}</td>
                <td className="px-3 py-2 align-top">{row.purpose}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("during.outro", { code, strong })}</p>

      <Image
        src="https://macrimi.github.io/ProxMenux/install/install.png"
        alt={t("during.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("first.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("first.intro")}</p>
      <CopyableCode code={t.raw("first.code") as string} />

      <p className="mt-4 mb-4 text-gray-800 leading-relaxed">
        {t.rich("first.outro", { postlink: internalLink("/docs/post-install") })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("beta.heading")}</h2>
      <Callout variant="info" title={t("beta.calloutTitle")}>
        {t.rich("beta.calloutBody", { code })}
      </Callout>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("beta.intro")}</p>
      <CopyableCode code={t.raw("beta.code") as string} />

      <p className="mt-4 mb-4 text-gray-800 leading-relaxed">
        {t.rich("beta.outro", { code, betalink: internalLink("/docs/settings/beta-program") })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("updating.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t.rich("updating.body", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("uninstall.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("uninstall.body", {
          strong,
          code,
          uninstalllink: internalLink("/docs/settings/uninstall-proxmenux"),
        })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.virustotalTitle")}>
        {t.rich("troubleshoot.virustotalBody", {
          code,
          em,
          issuelink: extlink("https://github.com/MacRimi/ProxMenux/issues/162"),
        })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.aptTitle")}>
        {t.rich("troubleshoot.aptBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.menuTitle")}>
        {t.rich("troubleshoot.menuBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.stuckTitle")}>
        {t.rich("troubleshoot.stuckBody", { code, strong })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.otherTitle")}>
        {t.rich("troubleshoot.otherBody", {
          code,
          issueslink: extlink("https://github.com/MacRimi/ProxMenux/issues"),
        })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("next.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        <li>{t.rich("next.postInstall", { postlink: internalLink("/docs/post-install") })}</li>
        <li>{t.rich("next.introduction", { introlink: internalLink("/docs/introduction") })}</li>
        <li>{t.rich("next.monitor", { monitorlink: internalLink("/docs/settings/proxmenux-monitor") })}</li>
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("requirements.heading")}</h2>

      <Callout variant="info" title={t("requirements.reqTitle")}>
        {t.rich("requirements.reqBody", { strong })}
      </Callout>

      <Callout variant="info" title={t("requirements.inspectTitle")}>
        <ul className="list-disc pl-6 mt-1 mb-0 space-y-1">
          <li>
            <FileCode className="inline h-4 w-4 mr-1 -mt-0.5 text-blue-600" aria-hidden />{" "}
            {t.rich("requirements.inspectReview", {
              sourcelink: extlink(
                "https://github.com/MacRimi/ProxMenux/blob/main/install_proxmenux.sh",
                "text-blue-700 hover:underline inline-flex items-center gap-1",
              ),
            })}
          </li>
          <li>
            <ShieldCheck className="inline h-4 w-4 mr-1 -mt-0.5 text-emerald-600" aria-hidden />{" "}
            {t.rich("requirements.inspectCoc", {
              coclink: extlink(
                "https://github.com/MacRimi/ProxMenux?tab=coc-ov-file#-2-security--code-responsibility",
                "text-blue-700 hover:underline inline-flex items-center gap-1",
              ),
            })}
          </li>
        </ul>
      </Callout>
    </div>
  )
}
