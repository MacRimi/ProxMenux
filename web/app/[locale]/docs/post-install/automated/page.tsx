import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import CopyableCode from "@/components/CopyableCode"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.postInstall.automated.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/post-install/automated",
    },
  }
}

type OptimizationRow = { tool: string; what: string; category: string; categorySlug: string }
type RelatedItem = { label: string; href: string; tail: string }

export default async function AutomatedPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.automated" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { automated: {
      optimizations: OptimizationRow[]
      upgrade: { items: string[] }
      notDoes: { items: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const optimizations = messages.docs.postInstall.automated.optimizations
  const upgradeItems = messages.docs.postInstall.automated.upgrade.items
  const notDoesItems = messages.docs.postInstall.automated.notDoes.items
  const relatedItems = messages.docs.postInstall.automated.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const customLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/customizable" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const upgradeLink = (chunks: React.ReactNode) => (
    <Link href="/docs/utils/system-update" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const secLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/security" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const virtLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/virtualization" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const optLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/optional" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const perfLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/performance" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const storLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/storage" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const overviewLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const uninstallLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/uninstall" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={10}
        scriptPath="post_install/auto_post_install.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong, link: customLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("applies.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("applies.intro", {
          em: (chunks) => <em>{chunks}</em>,
        })}
      </p>

      <div className="overflow-x-auto rounded-md border border-gray-200 mb-6">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("applies.headerNum")}</th>
              <th className="px-4 py-2 font-semibold">{t("applies.headerTool")}</th>
              <th className="px-4 py-2 font-semibold">{t("applies.headerWhat")}</th>
              <th className="px-4 py-2 font-semibold">{t("applies.headerCategory")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {optimizations.map((o, i) => (
              <tr key={i}>
                <td className="px-4 py-2 text-gray-500 font-mono">{i + 1}</td>
                <td className="px-4 py-2 font-semibold">{o.tool}</td>
                <td className="px-4 py-2 text-gray-700 leading-relaxed">{o.what}</td>
                <td className="px-4 py-2">
                  <Link
                    href={`/docs/post-install/${o.categorySlug}`}
                    className="text-blue-600 hover:underline whitespace-nowrap"
                  >
                    {o.category}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="tip" title={t("hardwareTitle")}>
        {t.rich("hardwareBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("upgrade.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("upgrade.intro")}</p>
      <CopyableCode
        code={`apt update && apt full-upgrade -y`}
        language="bash"
      />
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("upgrade.after", { strong, link: upgradeLink })}
      </p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {upgradeItems.map((_, idx) => (
          <li key={idx}>{t.rich(`upgrade.items.${idx}`, { code })}</li>
        ))}
      </ul>
      <Callout variant="info" title={t("upgrade.sameTitle")}>
        {t.rich("upgrade.sameBody", { code, link: upgradeLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("endResult.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("endResult.body")}</p>

      <Image
        src="/post-install/automated-result.png"
        alt={t("endResult.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("notDoes.heading")}</h2>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {notDoesItems.map((_, idx) => (
          <li key={idx}>{t.rich(`notDoes.items.${idx}`, { secLink, virtLink, optLink, perfLink, storLink })}</li>
        ))}
      </ul>

      <Callout variant="warning" title={t("xshokTitle")}>
        {t.rich("xshokBody", { code, link: overviewLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("revert.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("revert.body", { code, link: uninstallLink })}
      </p>

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
