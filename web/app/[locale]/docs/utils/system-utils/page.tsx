import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.utils.systemUtils.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/utils/system-utils",
    },
  }
}

type ActionRow = { option: string; behaviourRich: string }
type PackageRow = { package: string; verify: string; description: string }
type RelatedItem = { href: string; label: string; tailRich?: string }

export default async function SystemUtilsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.utils.systemUtils" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { utils: { systemUtils: {
      actions: { rows: ActionRow[] }
      packages: { rows: PackageRow[] }
      howItWorks: { items: string[]; verifyOutcomes: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const block = messages.docs.utils.systemUtils
  const actionRows = block.actions.rows
  const packageRows = block.packages.rows
  const howItems = block.howItWorks.items
  const verifyOutcomes = block.howItWorks.verifyOutcomes
  const relatedItems = block.related.items

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
        scriptPath="utilities/system_utils.sh"
      />

      <Callout variant="info" title={t("info.title")}>
        {t.rich("info.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("opening.intro", { strong })}
      </p>

      <Image
        src="/utils/system-utils-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("actions.heading")}</h2>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("actions.headerOption")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("actions.headerBehaviour")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {actionRows.map((row, idx) => (
              <tr key={idx} className={idx < actionRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.option}</strong></td>
                <td className="px-3 py-2 align-top">{t.rich(`actions.rows.${idx}.behaviourRich`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("packages.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("packages.intro", { code })}
      </p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("packages.headerPackage")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("packages.headerVerify")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("packages.headerDescription")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800 [&>tr>td]:px-3 [&>tr>td]:py-2 [&>tr>td]:align-top [&>tr>td:nth-child(-n+2)]:whitespace-nowrap [&>tr>td:nth-child(-n+2)]:font-mono [&>tr>td:nth-child(-n+2)]:text-xs">
            {packageRows.map((row, idx) => (
              <tr key={idx} className={idx < packageRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td>{row.package}</td>
                <td>{row.verify}</td>
                <td>{row.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("howItWorks.heading")}</h2>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {howItems.map((_, idx) => (
          <li key={idx}>{t.rich(`howItWorks.items.${idx}`, { code })}</li>
        ))}
        <li>
          {t.rich("howItWorks.verifyIntro", { code })}
          <ul className="list-disc pl-6 mt-1 space-y-1">
            {verifyOutcomes.map((_, idx) => (
              <li key={idx}>{t.rich(`howItWorks.verifyOutcomes.${idx}`, { strong, em })}</li>
            ))}
          </ul>
        </li>
        <li>{t.rich("howItWorks.summary", { em })}</li>
      </ol>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verify.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("verify.intro", { code })}
      </p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("verify.code") as string}</pre>
      <p className="mt-4 mb-6 text-gray-800 leading-relaxed">
        {t.rich("verify.outro", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.reposTitle")}>
        {t.rich("troubleshoot.reposBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.warningsTitle")}>
        {t.rich("troubleshoot.warningsBody", { code })}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.hangsTitle")}>
        {t.rich("troubleshoot.hangsBody", { code, kbd })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("files.heading")}</h2>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{t.raw("files.code") as string}</pre>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item, idx) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tailRich ? t.rich(`related.items.${idx}.tailRich`, { code }) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}
