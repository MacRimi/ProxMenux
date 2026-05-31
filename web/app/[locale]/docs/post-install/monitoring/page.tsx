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
  const t = await getTranslations({ locale, namespace: "docs.postInstall.monitoring.meta" })
  return { title: t("title"), description: t("description") }
}

type RelatedItem = { label: string; href: string; tail: string }

export default async function PostInstallMonitoringPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.monitoring" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { monitoring: {
      ovh: { decisionsItems: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const decisionsItems = messages.docs.postInstall.monitoring.ovh.decisionsItems
  const relatedItems = messages.docs.postInstall.monitoring.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const ovhAnchor = (chunks: React.ReactNode) => (
    <a href="https://www.ovhcloud.com" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const rtmAnchor = (chunks: React.ReactNode) => (
    <a href="https://www.ovhcloud.com/en/bare-metal/monitoring/" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
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
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("ovh.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("ovh.intro", { a: ovhAnchor })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("ovh.decisionsTitle")}</h3>
      <ol className="list-decimal pl-6 space-y-1 text-gray-800 mb-4">
        {decisionsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`ovh.decisionsItems.${idx}`, { code, em })}</li>
        ))}
      </ol>

      <Callout variant="danger" title={t("ovh.remoteTitle")}>
        {t.rich("ovh.remoteBody", { code })}
      </Callout>

      <Callout variant="warning" title={t("ovh.noOpTitle")}>
        {t.rich("ovh.noOpBody", { em })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("ovh.runsTitle")}</h3>
      <CopyableCode
        code={`# Detect + conditionally install
public_ip=$(curl -s ipinfo.io/ip)
is_ovh=$(whois -h v4.whois.cymru.com " -t $public_ip" | tail -n 1 | cut -d'|' -f3 | grep -i "ovh")

if [ -n "$is_ovh" ]; then
  wget -qO - https://last-public-ovh-infra-yak.snap.mirrors.ovh.net/yak/archives/apply.sh \\
    | OVH_PUPPET_MANIFEST=distribyak/catalog/master/puppet/manifests/common/rtmv2.pp bash
fi`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("ovh.verifyTitle")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("ovh.verifyBody", { a: rtmAnchor })}
      </p>
      <CopyableCode
        code={`systemctl status ovh-rtm      # or grep the unit name from your install log
journalctl -u ovh-rtm --since "10 min ago"`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("ovh.troubleTitle")}</h3>

      <Callout variant="tip" title={t("ovh.spuriousTitle")}>
        {t.rich("ovh.spuriousBody", { em, code })}
      </Callout>

      <Callout variant="tip" title={t("ovh.revertTitle")}>
        {t.rich("ovh.revertBody", { code })}
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
