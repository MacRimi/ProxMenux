import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.terminal.meta" })
  return { title: t("title"), description: t("description") }
}

type KeyboardRow = { button: string; sends: string; use?: string; useRich?: boolean }
type DisconnectRow = { cause: string; fix: string }
type WhereNextItem = { label: string; href: string; tail: string }

export default async function TerminalTabPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.monitor.dashboard.terminal" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { monitor: { dashboard: { terminal: {
      keyboard: { rows: KeyboardRow[]; ctrlItems: string[] }
      auth: { items: string[] }
      clipboard: { items: string[] }
      disconnect: { rows: DisconnectRow[] }
      fourTerminals: { items: string[] }
      whereNext: { items: WhereNextItem[] }
    } } } }
  }
  const term = messages.docs.monitor.dashboard.terminal
  const kbRows = term.keyboard.rows
  const ctrlItems = term.keyboard.ctrlItems
  const authItems = term.auth.items
  const clipboardItems = term.clipboard.items
  const disconnectRows = term.disconnect.rows
  const fourTerminalsItems = term.fourTerminals.items
  const whereNextItems = term.whereNext.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const green = (chunks: React.ReactNode) => <span className="text-green-600 font-semibold">{chunks}</span>
  const red = (chunks: React.ReactNode) => <span className="text-red-600 font-semibold">{chunks}</span>
  const vmsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/vms-lxcs" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const vmsLinkAmber = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/vms-lxcs" className="text-blue-700 hover:underline">
      {chunks}
    </Link>
  )
  const authLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/access-auth" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const authLinkWarn = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/access-auth" className="text-amber-700 hover:underline">
      {chunks}
    </Link>
  )
  const gatewayLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/integrations" className="text-amber-700 hover:underline">
      {chunks}
    </Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={7}
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <figure className="my-6">
        <Image
          src="/monitor/terminal/single-terminal.png"
          alt={t("singleAlt")}
          width={1600}
          height={1000}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("singleCaption", { em })}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("target.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("target.body1", { strong })}
      </p>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("target.body2", { strong, em, code, link: vmsLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("fourTerminals.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("fourTerminals.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {fourTerminalsItems.map((_, idx) => (
          <li key={idx}>{t.rich(`fourTerminals.items.${idx}`, { strong, em, code })}</li>
        ))}
      </ul>
      <p className="mb-6 text-gray-800 leading-relaxed">
        {t.rich("fourTerminals.outro", { strong, em, code })}
      </p>

      <figure className="my-6">
        <Image
          src="/monitor/terminal/grid-4-terminals.png"
          alt={t("gridAlt")}
          width={1600}
          height={1000}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("gridCaption", { code })}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("keyboard.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("keyboard.intro", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("keyboard.headerButton")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("keyboard.headerSends")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("keyboard.headerUse")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {kbRows.map((row, idx) => (
              <tr key={row.button} className={idx < kbRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{row.button}</strong></td>
                <td className="px-3 py-2 align-top font-mono text-xs">{row.sends}</td>
                <td className="px-3 py-2 align-top">
                  {row.useRich ? (
                    <>
                      {t("keyboard.ctrlIntro")}
                      <ul className="list-disc pl-5 mt-1 space-y-0.5">
                        {ctrlItems.map((_, cidx) => (
                          <li key={cidx}>{t.rich(`keyboard.ctrlItems.${cidx}`, { code })}</li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    t.rich(`keyboard.rows.${idx}.use`, { code })
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("keyboard.modalTitle")}>
        {t.rich("keyboard.modalBody", { code, link: vmsLinkAmber })}
      </Callout>

      <figure className="my-6">
        <Image
          src="/monitor/terminal/lxc-console-modal.png"
          alt={t("lxcAlt")}
          width={1600}
          height={1200}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("lxcCaption", { em })}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("search.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("search.intro", { code, strong, em })}
      </p>

      <figure className="my-6">
        <Image
          src="/monitor/terminal/search-commands.png"
          alt={t("search.modalAlt")}
          width={1600}
          height={1200}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("search.modalCaption", { code, em })}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        <strong>{t("search.aboutLabel")}</strong>{" "}
        <a
          href="https://cheat.sh"
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 hover:underline inline-flex items-center gap-1"
        >
          cheat.sh
          <ExternalLink className="w-3 h-3" />
        </a>{" "}
        {t.rich("search.aboutBody", { code })}
      </p>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("search.headerSource")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("search.headerWhen")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("search.headerWhat")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            <tr className="border-b border-gray-100">
              <td className="px-3 py-2 align-top whitespace-nowrap">
                <a
                  href="https://cheat.sh"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline inline-flex items-center gap-1 font-semibold"
                >
                  cheat.sh
                  <ExternalLink className="w-3 h-3" />
                </a>{" "}
                {t("search.onlineLabel")}
              </td>
              <td className="px-3 py-2 align-top">{t("search.onlineWhen")}</td>
              <td className="px-3 py-2 align-top">{t.rich("search.onlineWhat", { green })}</td>
            </tr>
            <tr>
              <td className="px-3 py-2 align-top whitespace-nowrap"><strong>{t("search.fallbackLabel")}</strong></td>
              <td className="px-3 py-2 align-top">{t("search.fallbackWhen")}</td>
              <td className="px-3 py-2 align-top">{t.rich("search.fallbackWhat", { red })}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <p className="mb-6 text-gray-800 leading-relaxed text-sm">
        {t.rich("search.sendingNote", { strong })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("auth.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {authItems.map((_, idx) => (
          <li key={idx}>{t.rich(`auth.items.${idx}`, { code, link: authLink })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("clipboard.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {clipboardItems.map((_, idx) => (
          <li key={idx}>{t.rich(`clipboard.items.${idx}`, { strong, code })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("disconnect.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("disconnect.intro")}</p>
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("disconnect.headerCause")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("disconnect.headerFix")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {disconnectRows.map((row, idx) => (
              <tr key={row.cause} className={idx < disconnectRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top">{row.cause}</td>
                <td className="px-3 py-2 align-top">{t.rich(`disconnect.rows.${idx}.fix`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="warning" title={t("warning.title")}>
        {t.rich("warning.body", { code, authLink: authLinkWarn, gatewayLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("whereNext.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {whereNextItems.map((item) => (
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
