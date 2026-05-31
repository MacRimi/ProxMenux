import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.settings.betaProgram.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/settings/beta-program",
    },
  }
}

type StringItem = string
type RelatedItem = { href: string; label: string; tail?: string }

export default async function BetaProgramPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.settings.betaProgram" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { settings: { betaProgram: {
      why: { items: StringItem[] }
      dialog: { options: StringItem[]; directions: StringItem[] }
      confirm: { items: StringItem[] }
      switching: { items: StringItem[] }
      feedback: { items: StringItem[] }
      related: { items: RelatedItem[] }
    } } }
  }
  const block = messages.docs.settings.betaProgram
  const whyItems = block.why.items
  const dialogOptions = block.dialog.options
  const dialogDirections = block.dialog.directions
  const confirmItems = block.confirm.items
  const switchingItems = block.switching.items
  const feedbackItems = block.feedback.items
  const relatedItems = block.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const ul = (chunks: React.ReactNode) => <ul className="list-disc pl-6 mt-1">{chunks}</ul>
  const li = (chunks: React.ReactNode) => <li>{chunks}</li>
  const link = (chunks: React.ReactNode) => (
    <Link href="/docs/settings/show-version-information" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const ghlink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/MacRimi/ProxMenux/issues"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
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
        scriptPath="menus/config_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code, strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("why.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("why.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {whyItems.map((_, idx) => (
          <li key={idx}>{t.rich(`why.items.${idx}`, { code, strong })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">{t.rich("why.outro", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("dialog.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("dialog.intro", { strong })}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {dialogOptions.map((_, idx) => (
          <li key={idx}>{t.rich(`dialog.options.${idx}`, { code })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("dialog.behaviour")}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {dialogDirections.map((_, idx) => (
          <li key={idx}>{t.rich(`dialog.directions.${idx}`, { strong })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("confirm.heading")}</h2>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {confirmItems.map((_, idx) => (
          <li key={idx}>{t.rich(`confirm.items.${idx}`, { code, strong, em, ul, li })}</li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("switching.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("switching.intro", { strong })}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {switchingItems.map((_, idx) => (
          <li key={idx}>{t.rich(`switching.items.${idx}`, { code })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("feedback.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("feedback.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {feedbackItems.map((_, idx) => (
          <li key={idx}>{t(`feedback.items.${idx}`)}</li>
        ))}
        <li>
          <pre className="mt-2 rounded-md bg-gray-100 p-3 overflow-x-auto text-xs font-mono text-gray-800 border border-gray-200">{t.raw("feedback.logsCommand") as string}</pre>
        </li>
        <li>{t.rich("feedback.versionLine", { link })}</li>
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">{t.rich("feedback.issueLine", { ghlink })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("manual.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("manual.intro")}</p>
      <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 leading-relaxed border border-gray-200">{`# Check current channel (returns "beta" or "stable")
jq -r '.beta_program.status // "stable"' /usr/local/share/proxmenux/config.json

# Switch to Stable
bash -c "$(wget -qLO - https://raw.githubusercontent.com/MacRimi/ProxMenux/main/install_proxmenux.sh)"

# Switch to Beta
bash -c "$(wget -qLO - https://raw.githubusercontent.com/MacRimi/ProxMenux/develop/install_proxmenux_beta.sh)"`}</pre>

      <Callout variant="info" title={t("unifiedCallout.title")}>
        {t.rich("unifiedCallout.body", { code, strong, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>

      <Callout variant="troubleshoot" title={t("troubleshoot.downloadTitle")}>
        {t.rich("troubleshoot.downloadBody", { code })}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{t.raw("troubleshoot.downloadCmd") as string}</pre>
        {t("troubleshoot.downloadOutro")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.errorsTitle")}>
        {t("troubleshoot.errorsBody")}
      </Callout>

      <Callout variant="troubleshoot" title={t("troubleshoot.configTitle")}>
        {t.rich("troubleshoot.configBody", { code })}
        <pre className="mt-2 rounded-md bg-white border border-slate-200 p-3 overflow-x-auto text-xs font-mono text-gray-800">{t.raw("troubleshoot.configCmd") as string}</pre>
        {t("troubleshoot.configOutro")}
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
