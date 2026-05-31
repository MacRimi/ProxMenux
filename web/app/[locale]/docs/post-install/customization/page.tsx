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
  const t = await getTranslations({ locale, namespace: "docs.postInstall.customization.meta" })
  return { title: t("title"), description: t("description") }
}

type RelatedItem = { label: string; href: string; tail: string }

export default async function PostInstallCustomizationPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.customization" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { customization: {
      banner: { versionItems: string[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const versionItems = messages.docs.postInstall.customization.banner.versionItems
  const relatedItems = messages.docs.postInstall.customization.related.items

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
        description={t("header.description")}
        section={t("header.section")}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("bashrc.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("bashrc.intro", { code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("bashrc.writesTitle")}</h3>
      <CopyableCode
        code={`# BEGIN PMX_CORE_BASHRC
# ProxMenux core customizations
export HISTTIMEFORMAT="%d/%m/%y %T "
export PS1="\\[\\e[31m\\][\\[\\e[m\\]\\[\\e[38;5;172m\\]\\u\\[\\e[m\\]@\\[\\e[38;5;153m\\]\\h\\[\\e[m\\] \\[\\e[38;5;214m\\]\\W\\[\\e[m\\]\\[\\e[31m\\]]\\[\\e[m\\]\\$ "
alias l='ls -CF'
alias la='ls -A'
alias ll='ls -alF'
alias ls='ls --color=auto'
alias grep='grep --color=auto'
alias fgrep='fgrep --color=auto'
alias egrep='egrep --color=auto'
source /etc/profile.d/bash_completion.sh
# END PMX_CORE_BASHRC`}
        className="my-4"
      />

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("bashrc.writesOutro", { code })}
      </p>

      <Callout variant="tip" title={t("bashrc.rootTitle")}>
        {t("bashrc.rootBody")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("motd.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("motd.intro", { em, code })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("motd.writesTitle")}</h3>
      <CopyableCode
        code={`    This system is optimised by: ProxMenux

<original /etc/motd content follows here>`}
        className="my-4"
      />
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("motd.writesOutro", { code })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("banner.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("banner.intro", { em })}
      </p>

      <h3 className="text-lg font-semibold mt-6 mb-2 text-gray-900">{t("banner.versionTitle")}</h3>
      <ul className="list-disc pl-6 space-y-1 text-gray-800 mb-4">
        {versionItems.map((_, idx) => (
          <li key={idx}>{t.rich(`banner.versionItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("banner.versionOutro", { code })}
      </p>

      <Callout variant="warning" title={t("banner.breakTitle")}>
        {t.rich("banner.breakBody", { code, link: uninstallLink })}
      </Callout>

      <Callout variant="danger" title={t("banner.legalTitle")}>
        {t.rich("banner.legalBody", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verify.heading")}</h2>
      <p className="mb-3 text-gray-800 leading-relaxed">{t("verify.intro")}</p>
      <CopyableCode
        code={`# bashrc: the prompt becomes colored, ll / la aliases work
exec bash              # reload current shell
ll

# MOTD: log out and SSH back in — the ProxMenux banner shows above the default message
cat /etc/motd

# Subscription banner: log out of the web UI, then log back in — no popup`}
        className="my-4"
      />

      <Callout variant="tip" title={t("verify.reversibleTitle")}>
        {t.rich("verify.reversibleBody", { code, link: uninstallLink })}
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
