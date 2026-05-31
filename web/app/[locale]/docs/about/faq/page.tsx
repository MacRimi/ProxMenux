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
  const t = await getTranslations({ locale, namespace: "docs.about.faq.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/about/faq",
    },
  }
}

interface QAProps {
  q: string
  children: React.ReactNode
}

function QA({ q, children }: QAProps) {
  return (
    <div className="mb-8">
      <h2 className="text-xl font-semibold mb-3 text-gray-900">{q}</h2>
      <div className="text-gray-800 leading-relaxed space-y-3">{children}</div>
    </div>
  )
}

export default async function FaqPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.about.faq" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: {
      about: {
        faq: {
          q1: { items: string[] }
        }
      }
    }
  }
  const q1Items = messages.docs.about.faq.q1.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  const installlink = (chunks: React.ReactNode) => (
    <Link href="/docs/installation" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const upgradelink = (chunks: React.ReactNode) => (
    <Link href="/docs/utils/upgrade-pve8-pve9" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const betalink = (chunks: React.ReactNode) => (
    <Link href="/docs/settings/beta-program" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const uninstalllink = (chunks: React.ReactNode) => (
    <Link href="/docs/settings/uninstall-proxmenux" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const contriblink = (chunks: React.ReactNode) => (
    <Link href="/docs/about/contributors" className="text-blue-600 hover:underline">
      {chunks}
    </Link>
  )
  const issueslink = (chunks: React.ReactNode) => (
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
  const coclink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/MacRimi/ProxMenux/blob/main/CODE_OF_CONDUCT.md"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const discusslink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/MacRimi/ProxMenux/discussions"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const scriptlink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/MacRimi/ProxMenux/blob/main/install_proxmenux.sh"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const issuelink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/MacRimi/ProxMenux/issues/162"
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
        estimatedMinutes={5}
      />

      <Callout variant="info" title={t("quickLinks.title")}>
        <ul className="list-disc pl-6 mb-0 space-y-1">
          <li>
            <Link href="/docs/installation" className="text-blue-700 hover:underline">
              {t("quickLinks.installationLabel")}
            </Link>
            {t("quickLinks.installationSuffix")}
          </li>
          <li>
            <Link href="/docs/introduction" className="text-blue-700 hover:underline">
              {t("quickLinks.introductionLabel")}
            </Link>
            {t("quickLinks.introductionSuffix")}
          </li>
          <li>
            <Link href="/docs/settings/uninstall-proxmenux" className="text-blue-700 hover:underline">
              {t("quickLinks.uninstallLabel")}
            </Link>
            {t("quickLinks.uninstallSuffix")}
          </li>
          <li>
            <a
              href="https://github.com/MacRimi/ProxMenux/issues"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-700 hover:underline inline-flex items-center gap-1"
            >
              {t("quickLinks.issuesLabel")}
              <ExternalLink className="w-3 h-3" />
            </a>{" "}
            ·{" "}
            <a
              href="https://github.com/MacRimi/ProxMenux/discussions"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-700 hover:underline inline-flex items-center gap-1"
            >
              {t("quickLinks.discussionsLabel")}
              <ExternalLink className="w-3 h-3" />
            </a>
          </li>
        </ul>
      </Callout>

      <QA q={t("q1.question")}>
        <p>{t.rich("q1.p1Rich", { strong })}</p>
        <p>{t("q1.p2")}</p>
        <p className="mb-0">{t("q1.p3")}</p>
        <ul className="list-disc pl-6 mb-0 space-y-1">
          {q1Items.map((_, idx) => (
            <li key={idx}>{t(`q1.items.${idx}`)}</li>
          ))}
        </ul>
      </QA>

      <QA q={t("q2.question")}>
        <p>{t.rich("q2.p1Rich", { installlink })}</p>
        <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 border border-gray-200">
          {t("q2.stableInstall")}
        </pre>
        <p>{t("q2.p2")}</p>
        <pre className="rounded-md bg-gray-100 p-4 overflow-x-auto text-xs font-mono text-gray-800 border border-gray-200">
          {t("q2.menuCmd")}
        </pre>
      </QA>

      <QA q={t("q3.question")}>
        <p>{t.rich("q3.bodyRich", { strong, upgradelink })}</p>
      </QA>

      <QA q={t("q5.question")}>
        <p>{t.rich("q5.p1Rich", { code })}</p>
        <p className="mb-0">{t.rich("q5.p2Rich", { betalink })}</p>
      </QA>

      <QA q={t("q6.question")}>
        <p>{t.rich("q6.p1Rich", { issueslink, code })}</p>
        <p className="mb-0">{t.rich("q6.p2Rich", { strong, coclink })}</p>
      </QA>

      <QA q={t("q7.question")}>
        <p>{t.rich("q7.p1Rich", { strong })}</p>
        <ul className="list-disc pl-6 mb-0 space-y-1">
          <li>{t.rich("q7.item1Rich", { discusslink })}</li>
          <li>{t.rich("q7.item2Rich", { coclink })}</li>
          <li>{t.rich("q7.item3Rich", { contriblink })}</li>
        </ul>
      </QA>

      <QA q={t("q10.question")}>
        <p>{t.rich("q10.p1Rich", { strong, code })}</p>
        <p className="mb-0">{t.rich("q10.p2Rich", { uninstalllink })}</p>
      </QA>

      <QA q={t("q11.question")}>
        <p>{t.rich("q11.p1Rich", { em, code })}</p>
        <p className="mb-0">{t.rich("q11.p2Rich", { scriptlink, issuelink })}</p>
      </QA>
    </div>
  )
}
