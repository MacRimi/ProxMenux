import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { ArrowRight, Ban, ShieldCheck, ScanLine } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.security.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox fail2ban",
      "proxmox lynis",
      "proxmox security",
      "proxmox hardening",
      "proxmox intrusion prevention",
      "proxmox security audit",
      "proxmox ssh fail2ban",
      "proxmox web ui fail2ban",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/security" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/security",
    },
    twitter: {
      card: "summary",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type StringItem = string

interface OptionProps {
  title: string
  description: string
  Icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>
  href: string
}

function OptionCard({ title, description, Icon, href }: OptionProps) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-3 rounded-md border border-gray-200 bg-white p-3 transition-colors hover:border-blue-400 hover:bg-blue-50"
    >
      <span className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md bg-gray-100 text-gray-600 group-hover:bg-blue-100 group-hover:text-blue-700">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-sm font-medium text-gray-900 group-hover:text-blue-700">
          {title}
          <ArrowRight className="h-3.5 w-3.5 text-gray-400 group-hover:text-blue-600 transition-transform group-hover:translate-x-0.5" />
        </div>
        <div className="mt-0.5 text-xs text-gray-600 leading-snug">{description}</div>
      </div>
    </Link>
  )
}

export default async function SecurityOverviewPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.security" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { security: {
      cards: {
        fail2ban: { bullets: StringItem[] }
        lynis: { bullets: StringItem[] }
      }
    } }
  }
  const fail2banBullets = messages.docs.security.cards.fail2ban.bullets
  const lynisBullets = messages.docs.security.cards.lynis.bullets

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={4}
        scriptPath="menus/security_menu.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { strong, em })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("opening.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("opening.body", { strong })}</p>

      <Image
        src="/security/security-menu.png"
        alt={t("opening.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("pick.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("pick.body")}</p>

      <div className="grid gap-4 md:grid-cols-1 lg:grid-cols-2 mb-8 not-prose">
        <a
          href="#fail2ban"
          className="rounded-lg border-2 border-red-300 bg-red-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-red-100 text-red-700">
              <Ban className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("cards.fail2ban.title")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t("cards.fail2ban.body")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {fail2banBullets.map((_, idx) => (
              <li key={idx}>{t(`cards.fail2ban.bullets.${idx}`)}</li>
            ))}
          </ul>
        </a>

        <a
          href="#lynis"
          className="rounded-lg border-2 border-blue-300 bg-blue-50 p-5 flex flex-col transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 text-blue-700">
              <ScanLine className="h-5 w-5" aria-hidden />
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{t("cards.lynis.title")}</h3>
          </div>
          <p className="text-sm text-gray-800 mb-3">{t("cards.lynis.body")}</p>
          <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
            {lynisBullets.map((_, idx) => (
              <li key={idx}>{t(`cards.lynis.bullets.${idx}`)}</li>
            ))}
          </ul>
        </a>
      </div>

      <Callout variant="tip" title={t("workflowTip.title")}>
        {t.rich("workflowTip.body", { code })}
      </Callout>

      <h2 id="fail2ban" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">
        {t("fail2banSection.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("fail2banSection.body")}</p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        <OptionCard
          title={t("fail2banSection.optionTitle")}
          description={t("fail2banSection.optionDescription")}
          Icon={Ban}
          href="/docs/security/fail2ban"
        />
      </div>

      <h2 id="lynis" className="text-2xl font-semibold mt-10 mb-4 text-gray-900 scroll-mt-24">
        {t("lynisSection.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("lynisSection.body", { code })}</p>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        <OptionCard
          title={t("lynisSection.optionTitle")}
          description={t("lynisSection.optionDescription")}
          Icon={ScanLine}
          href="/docs/security/lynis"
        />
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        <ShieldCheck className="inline h-5 w-5 mr-1 -mt-1 text-emerald-600" aria-hidden />
        {t("componentStatus.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("componentStatus.body", { code })}</p>
    </div>
  )
}
