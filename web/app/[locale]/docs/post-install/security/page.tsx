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
  const t = await getTranslations({ locale, namespace: "docs.postInstall.security.meta" })
  return { title: t("title"), description: t("description") }
}

type RelatedItem = { label: string; href: string; tail: string }

export default async function PostInstallSecurityPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.security" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { security: {
      rpcbind: { whyItems: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const whyItems = messages.docs.postInstall.security.rpcbind.whyItems
  const relatedItems = messages.docs.postInstall.security.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const uninstallLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/uninstall" className="text-blue-700 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        section={t("header.section")}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("rpcbind.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("rpcbind.intro", { code, strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("rpcbind.whyTitle")}</h3>
      <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-4">
        {whyItems.map((_, idx) => (
          <li key={idx}>{t.rich(`rpcbind.whyItems.${idx}`, { code })}</li>
        ))}
      </ul>

      <Callout variant="warning" title={t("rpcbind.nfsTitle")}>
        {t.rich("rpcbind.nfsBody", { strong, em, code })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("rpcbind.runsTitle")}</h3>
      <CopyableCode
        code={`# Stop and disable the rpcbind service
systemctl stop rpcbind
systemctl disable rpcbind`}
        className="my-4"
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("rpcbind.runsOutro")}</p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("rpcbind.verifyTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("rpcbind.verifyBody", { code })}
      </p>
      <CopyableCode
        code={`systemctl is-active rpcbind       # should report: inactive
systemctl is-enabled rpcbind      # should report: disabled
ss -tulpn | grep ':111 '          # should return nothing`}
        className="my-4"
      />

      <Callout variant="tip" title={t("rpcbind.reversibleTitle")}>
        {t.rich("rpcbind.reversibleBody", { em, link: uninstallLink })}
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
