import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import Image from "next/image"
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
  const t = await getTranslations({ locale, namespace: "docs.postInstall.basicSettings.meta" })
  return { title: t("title"), description: t("description") }
}

type UpgradeRow = { version: string; script: string; codename: string }
type UtilityItem = { pkg: string; desc: string }
type UtilityGroup = { group: string; items: UtilityItem[] }
type RelatedItem = { label: string; href: string; tail: string }

const SCREENSHOTS = [
  { pkg: "htop", alt: "htop interactive process viewer", src: "/basic/htop.png" },
  { pkg: "btop", alt: "btop resource monitor", src: "/basic/btop.png" },
  { pkg: "iftop", alt: "iftop bandwidth per connection", src: "/basic/iftop.png" },
  { pkg: "iotop", alt: "iotop disk I/O per process", src: "/basic/iotop.png" },
  { pkg: "iptraf-ng", alt: "iptraf-ng IP LAN monitor", src: "/basic/iptraf-ng.png" },
  { pkg: "tmux", alt: "tmux terminal multiplexer", src: "/basic/tmux.png" },
]

export default async function PostInstallBasicSettingsPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.basicSettings" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { basicSettings: {
      upgrade: { rows: UpgradeRow[]; doesItems: string[] }
      utilities: { groups: UtilityGroup[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const upgradeRows = messages.docs.postInstall.basicSettings.upgrade.rows
  const doesItems = messages.docs.postInstall.basicSettings.upgrade.doesItems
  const utilityGroups = messages.docs.postInstall.basicSettings.utilities.groups
  const relatedItems = messages.docs.postInstall.basicSettings.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const updateLink = (chunks: React.ReactNode) => (
    <Link href="/docs/utils/system-update" className="text-blue-600 hover:underline">{chunks}</Link>
  )
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
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("upgrade.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("upgrade.intro", { em })}
      </p>

      <div className="my-4 overflow-x-auto">
        <table className="min-w-full border border-gray-200 text-sm">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("upgrade.headerVersion")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("upgrade.headerScript")}</th>
              <th className="border border-gray-200 px-3 py-2 text-left text-gray-900">{t("upgrade.headerCodename")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {upgradeRows.map((row) => (
              <tr key={row.version}>
                <td className="border border-gray-200 px-3 py-2">{row.version}</td>
                <td className="border border-gray-200 px-3 py-2"><code>{row.script}</code></td>
                <td className="border border-gray-200 px-3 py-2">{row.codename}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("upgrade.officialTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("upgrade.officialBody")}</p>
      <CopyableCode
        code={`apt update && apt full-upgrade -y`}
        language="bash"
      />
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("upgrade.officialOutro", { em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("upgrade.doesTitle")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("upgrade.doesIntro", { link: updateLink })}
      </p>
      <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-4">
        {doesItems.map((_, idx) => (
          <li key={idx}>{t.rich(`upgrade.doesItems.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <Callout variant="info" title={t("upgrade.shortTitle")}>
        {t.rich("upgrade.shortBody", { code, link: updateLink })}
      </Callout>

      <Callout variant="warning" title={t("upgrade.subTitle")}>
        {t("upgrade.subBody")}
      </Callout>

      <Callout variant="tip" title={t("upgrade.safetyTitle")}>
        {t.rich("upgrade.safetyBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("time.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("time.intro", { code })}
      </p>

      <Callout variant="warning" title={t("time.depTitle")}>
        {t.rich("time.depBody", { code })}
      </Callout>

      <CopyableCode
        code={`# Manual alternative — pick your IANA zone
timedatectl list-timezones | grep -i europe   # e.g. Europe/Madrid
timedatectl set-timezone Europe/Madrid
timedatectl set-ntp true
timedatectl                                   # verify`}
        className="my-4"
      />

      <Callout variant="tip" title={t("time.revertTitle")}>
        {t.rich("time.revertBody", { link: uninstallLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("languages.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("languages.intro", { code, strong })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("languages.writtenTitle")}</h3>
      <CopyableCode
        code={`# /etc/apt/apt.conf.d/99-disable-translations
Acquire::Languages "none";`}
        className="my-4"
      />

      <Callout variant="tip" title={t("languages.revertTitle")}>
        {t.rich("languages.revertBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("utilities.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("utilities.intro", { strong, code })}
      </p>

      <Image
        src="/basic/menu_utilities.png"
        alt={t("utilities.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <Callout variant="tip" title={t("utilities.reuseTitle")}>
        {t.rich("utilities.reuseBody", { code, em })}
      </Callout>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("utilities.listTitle")}</h3>

      {utilityGroups.map((group) => (
        <div key={group.group} className="mb-6">
          <h4 className="text-base font-semibold text-gray-900 mb-2">{group.group}</h4>
          <dl className="divide-y divide-gray-200 border border-gray-200 rounded-md overflow-hidden">
            {group.items.map((item) => (
              <div key={item.pkg} className="grid grid-cols-1 sm:grid-cols-[150px_1fr] gap-2 px-4 py-3 bg-white">
                <dt className="font-mono text-sm text-gray-900">{item.pkg}</dt>
                <dd className="text-sm text-gray-700 m-0 leading-relaxed">{item.desc}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}

      <h3 className="text-lg font-semibold mt-8 mb-3 text-gray-900">{t("utilities.actionTitle")}</h3>

      <div className="grid gap-4 sm:grid-cols-2 my-4">
        {SCREENSHOTS.map((s) => (
          <figure key={s.pkg} className="m-0">
            <Image
              src={s.src}
              alt={s.alt}
              width={450}
              height={280}
              className="rounded shadow border border-gray-200 w-full h-auto"
            />
            <figcaption className="text-xs text-gray-600 mt-1 text-center">
              <code>{s.pkg}</code>
            </figcaption>
          </figure>
        ))}
      </div>

      <Callout variant="warning" title={t("utilities.noBulkTitle")}>
        {t.rich("utilities.noBulkBody", { strong })}
      </Callout>

      <CopyableCode
        code={`# Remove a utility you no longer want
apt purge htop
apt autoremove --purge`}
        className="my-4"
      />

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
