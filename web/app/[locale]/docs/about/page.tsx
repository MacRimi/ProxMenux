import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { ArrowRight, Users, HelpCircle, ScrollText, Heart, Star, ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.about.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/about",
    },
  }
}

type SectionOption = {
  icon: string
  href: string
  title: string
  description: string
}

type InvolvedCard = {
  href: string
  title: string
  description: string
}

const ICONS: Record<string, React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  HelpCircle,
  Users,
  ScrollText,
}

function OptionCard({ option }: { option: SectionOption }) {
  const Icon = ICONS[option.icon] || HelpCircle
  return (
    <Link
      href={option.href}
      className="group flex items-start gap-3 rounded-md border border-gray-200 bg-white p-3 transition-colors hover:border-blue-400 hover:bg-blue-50"
    >
      <span className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md bg-gray-100 text-gray-600 group-hover:bg-blue-100 group-hover:text-blue-700">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-sm font-medium text-gray-900 group-hover:text-blue-700">
          {option.title}
          <ArrowRight className="h-3.5 w-3.5 text-gray-400 group-hover:text-blue-600 transition-transform group-hover:translate-x-0.5" />
        </div>
        <div className="mt-0.5 text-xs text-gray-600 leading-snug">{option.description}</div>
      </div>
    </Link>
  )
}

export default async function AboutOverviewPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.about" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: {
      about: {
        section: { options: SectionOption[] }
        involved: { cards: InvolvedCard[] }
      }
    }
  }
  const options = messages.docs.about.section.options
  const involvedCards = messages.docs.about.involved.cards

  const starlink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/MacRimi/ProxMenux"
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
        estimatedMinutes={2}
      />

      <Callout variant="info" title={t("callout.title")}>
        {t("callout.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("section.heading")}</h2>
      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {options.map((o) => (
          <OptionCard key={o.href} option={o} />
        ))}
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("involved.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t("involved.intro")}
      </p>
      <div className="grid gap-3 md:grid-cols-3 mb-6 not-prose">
        {involvedCards.map((card) => (
          <a
            key={card.href}
            href={card.href}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-start justify-between gap-3 rounded-md border border-gray-200 bg-white p-4 transition-colors hover:border-blue-400 hover:bg-blue-50"
          >
            <div>
              <div className="font-semibold text-gray-900 mb-1">{card.title}</div>
              <div className="text-xs text-gray-600">{card.description}</div>
            </div>
            <ExternalLink className="w-3.5 h-3.5 text-gray-400 mt-0.5 flex-shrink-0" aria-hidden />
          </a>
        ))}
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">
        <Star className="inline h-5 w-5 mr-1 -mt-1 text-amber-500" aria-hidden />
        {t("support.heading")}
      </h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("support.introRich", { starlink })}
      </p>
      <p className="mb-4 text-gray-800 leading-relaxed">
        <a
          href="https://ko-fi.com/G2G313ECAN"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-pink-600 hover:underline"
        >
          <Heart className="h-4 w-4" aria-hidden /> {t("support.kofiLabel")}
        </a>
        {t("support.kofiOutro")}
      </p>
    </div>
  )
}
