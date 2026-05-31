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
  const t = await getTranslations({ locale, namespace: "docs.postInstall.network.meta" })
  return { title: t("title"), description: t("description") }
}

type AreaRow = { area: string; settings: string }
type RelatedItem = { label: string; href: string; tail: string }

export default async function PostInstallNetworkPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.network" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { network: {
      sysctl: { rows: AreaRow[] }
      names: { whyItems: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const sysctlRows = messages.docs.postInstall.network.sysctl.rows
  const whyItems = messages.docs.postInstall.network.names.whyItems
  const relatedItems = messages.docs.postInstall.network.related.items

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
        {t.rich("intro.body", { strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("ipv4.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("ipv4.intro", { code })}
      </p>

      <Callout variant="tip" title={t("ipv4.tipTitle")}>
        {t("ipv4.tipBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("sysctl.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sysctl.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("sysctl.tunedTitle")}</h3>
      <div className="my-4 overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("sysctl.headerArea")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("sysctl.headerSettings")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {sysctlRows.map((row, idx) => (
              <tr key={row.area}>
                <td className="border border-gray-200 px-3 py-2">{row.area}</td>
                <td className="border border-gray-200 px-3 py-2">{t.rich(`sysctl.rows.${idx}.settings`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("sysctl.sourceOutro", { code })}
      </p>

      <Callout variant="warning" title={t("sysctl.rpFilterTitle")}>
        {t.rich("sysctl.rpFilterBody", { em, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("ovs.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("ovs.intro", { code, em })}
      </p>

      <Callout variant="tip" title={t("ovs.tipTitle")}>
        {t.rich("ovs.tipBody", { strong, code })}
      </Callout>

      <Callout variant="warning" title={t("ovs.revertTitle")}>
        {t("ovs.revertBody")}
      </Callout>

      <CopyableCode
        code={`# After moving bridges off OVS:
apt purge openvswitch-switch openvswitch-common
apt autoremove --purge`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("bbr.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("bbr.intro")}</p>

      <CopyableCode
        code={`# /etc/sysctl.d/99-kernel-bbr.conf
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# /etc/sysctl.d/99-tcp-fastopen.conf
net.ipv4.tcp_fastopen = 3        # enable TFO for both client and server sockets`}
        className="my-4"
      />

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("bbr.verifyTitle")}</h3>
      <CopyableCode
        code={`# BBR is active
sysctl net.ipv4.tcp_congestion_control
# Expected: net.ipv4.tcp_congestion_control = bbr

# Qdisc is fair queuing (required for BBR to work well)
tc qdisc show | head

# TFO enabled (value 3 = client + server)
sysctl net.ipv4.tcp_fastopen`}
        className="my-4"
      />

      <Callout variant="tip" title={t("bbr.impactTitle")}>
        {t("bbr.impactBody")}
      </Callout>

      <Callout variant="warning" title={t("bbr.revertTitle")}>
        {t("bbr.revertBody")}
      </Callout>

      <CopyableCode
        code={`rm /etc/sysctl.d/99-kernel-bbr.conf /etc/sysctl.d/99-tcp-fastopen.conf
sysctl --system`}
        className="my-4"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("names.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("names.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("names.whyTitle")}</h3>
      <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-4">
        {whyItems.map((_, idx) => (
          <li key={idx}>{t.rich(`names.whyItems.${idx}`, { code })}</li>
        ))}
      </ul>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("names.writtenTitle")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">
        {t.rich("names.writtenIntro", { code })}
      </p>
      <CopyableCode
        code={`[Match]
MACAddress=aa:bb:cc:dd:ee:ff

[Link]
Name=enp3s0`}
        className="my-4"
      />

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("names.writtenOutro", { code })}
      </p>

      <Callout variant="tip" title={t("names.pveTitle")}>
        {t.rich("names.pveBody", { code })}
      </Callout>

      <Callout variant="warning" title={t("names.reviewTitle")}>
        {t.rich("names.reviewBody", { code, em })}
      </Callout>

      <Callout variant="tip" title={t("names.revertTitle")}>
        {t.rich("names.revertBody", { code, link: uninstallLink })}
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
