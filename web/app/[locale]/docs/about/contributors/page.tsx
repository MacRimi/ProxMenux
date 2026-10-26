import type { Metadata } from "next"
import type { ReactNode } from "react"
import Image from "next/image"
import { getTranslations, setRequestLocale } from "next-intl/server"
import { BookOpen, Code2, ExternalLink, FlaskRound, GitPullRequest, Heart, Languages, Youtube } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

const REPOSITORY = "https://github.com/MacRimi/ProxMenux"
const activeContributors = ["Vaso73", "f3rs3n", "jcastro"] as const

// Human authors of merged PRs and code contributions, checked on 2026-10-26.
// Alphabetical, without commit rankings. Ongoing contributors are credited above.
const codeContributors = [
  "byGarcia", "cod378", "detlefs", "fklnc94", "MaEscalanteHe",
  "MrCaringi", "pbr85", "pespinel", "phyrexia", "riri-314", "yeager",
]
const earlyContributors = [
  { name: "MALOW", avatar: "malow.png" },
  { name: "Segarra", avatar: "segarra.png" },
  { name: "Aprilia", avatar: "aprilia.png" },
  { name: "Jonatan Castro", avatar: "jonatancastro.png", github: "jcastro", youtube: "https://www.youtube.com/@JonatanCastro" },
  { name: "Kamunhas", avatar: "Kamunhas.png" },
  { name: "heriberto", avatar: "heriberto.png" },
  { name: "JF_Car", avatar: "JF_Car.png" },
  { name: "rafapuerta", avatar: "rafapuerta.png" },
  { name: "JcMinarro", avatar: "JcMinarro.png" },
]

function contributionsUrl(login: string) {
  return REPOSITORY + "/pulls?q=" + encodeURIComponent("is:pr is:merged author:" + login)
}

function External({ href, children, className = "" }: { href: string; children: ReactNode; className?: string }) {
  return <a href={href} target="_blank" rel="noopener noreferrer" className={"rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-blue-600 " + className}>{children}</a>
}

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.about.contributors.meta" })
  return {
    title: t("title"), description: t("description"),
    openGraph: {
      title: t("ogTitle"), description: t("ogDescription"), type: "article",
      url: "https://proxmenux.com/" + locale + "/docs/about/contributors/",
    },
  }
}

export default async function ContributorsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.about.contributors" })
  const ways = [
    { key: "code", Icon: Code2 }, { key: "testing", Icon: FlaskRound },
    { key: "translations", Icon: Languages }, { key: "docs", Icon: BookOpen },
  ] as const
  const heading = "mb-3 text-2xl font-semibold text-gray-900"
  const paragraph = "mb-6 leading-relaxed text-gray-700"

  return (
    <div>
      <DocHeader title={t("header.title")} description={t("header.description")} section={t("header.section")} estimatedMinutes={3} />

      <section aria-labelledby="ongoing-contributors" className="mt-10">
        <h2 id="ongoing-contributors" className={heading}>{t("active.heading")}</h2>
        <p className={paragraph}>{t("active.intro")}</p>
        <div className="grid gap-4 md:grid-cols-3">
          {activeContributors.map((login) => (
            <article key={login} className="flex min-w-0 flex-col rounded-xl border border-blue-100 bg-gradient-to-b from-blue-50/70 to-white p-5">
              <External href={"https://github.com/" + login} className="group flex items-center gap-3">
                <Image src={"/avatars/contributors/" + login + ".png"} alt="" width={64} height={64} className="h-16 w-16 shrink-0 rounded-full border border-white object-cover shadow-sm" />
                <h3 className="min-w-0 break-words text-lg font-semibold text-gray-900 group-hover:text-blue-700">{login}<ExternalLink className="ml-1.5 inline h-3.5 w-3.5 text-gray-400" aria-hidden="true" /></h3>
              </External>
              <p className="mb-5 mt-4 flex-1 text-sm leading-6 text-gray-700">{t("active.people." + login)}</p>
              <External href={contributionsUrl(login)} className="inline-flex items-center gap-2 self-start text-sm font-medium text-blue-700 hover:underline">
                <GitPullRequest className="h-4 w-4 shrink-0" aria-hidden="true" />{t("code.viewWork")}<span className="sr-only">: {login}</span>
              </External>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="code-contributors" className="mt-12">
        <h2 id="code-contributors" className={heading}>{t("code.heading")}</h2>
        <p className={paragraph}>{t("code.intro")}</p>
        <ul className="grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-3">
          {codeContributors.map((login) => (
            <li key={login} className="flex min-w-0 items-center gap-3 rounded-lg border border-gray-200 p-3">
              <Image src={"/avatars/contributors/" + login + ".png"} alt="" width={40} height={40} className="h-10 w-10 shrink-0 rounded-full object-cover" />
              <div className="min-w-0">
                <External href={"https://github.com/" + login} className="break-words text-sm font-semibold text-gray-900 hover:text-blue-700 hover:underline">{login}</External>
                <External href={contributionsUrl(login)} className="block text-xs leading-5 text-blue-700 hover:underline">{t("code.viewWork")}<span className="sr-only">: {login}</span></External>
              </div>
            </li>
          ))}
        </ul>
        <div className="mt-5 flex flex-wrap gap-x-6 gap-y-3 text-sm font-medium">
          <External href={REPOSITORY + "/graphs/contributors"} className="inline-flex items-center gap-1.5 text-blue-700 hover:underline">{t("code.history")}<ExternalLink className="h-3.5 w-3.5" aria-hidden="true" /></External>
          <External href={REPOSITORY + "/pulls?q=is%3Apr+is%3Amerged"} className="inline-flex items-center gap-1.5 text-blue-700 hover:underline">{t("code.merged")}<ExternalLink className="h-3.5 w-3.5" aria-hidden="true" /></External>
        </div>
      </section>

      <section aria-labelledby="community-contributors" className="mt-12 rounded-xl border border-gray-200 bg-gray-50 p-5 sm:p-6">
        <h2 id="community-contributors" className={heading}>{t("community.heading")}</h2>
        <p className="mb-3 leading-relaxed text-gray-700">{t("community.body")}</p>
        <p className="m-0 leading-relaxed text-gray-700">{t("community.languages")}</p>
      </section>

      <section aria-labelledby="early-contributors" className="mt-12">
        <h2 id="early-contributors" className={heading}>{t("testers.heading")}</h2>
        <p className={paragraph}>{t("testers.intro")}</p>
        <ul className="grid list-none grid-cols-2 gap-x-4 gap-y-6 p-0 sm:grid-cols-3 lg:grid-cols-5">
          {earlyContributors.map((person) => (
            <li key={person.name} className="min-w-0 text-center">
              <Image src={"/avatars/" + person.avatar} alt="" width={64} height={64} className="mx-auto h-16 w-16 rounded-full border border-gray-200 object-cover" />
              <h3 className="mb-0 mt-2 break-words text-sm font-semibold text-gray-900">
                {person.github ? <External href={"https://github.com/" + person.github} className="hover:text-blue-700 hover:underline">{person.name}</External> : person.name}
              </h3>
              {person.youtube && <External href={person.youtube} className="mt-1 inline-flex items-center gap-1 text-xs text-red-700 hover:underline"><Youtube className="h-3.5 w-3.5" aria-hidden="true" />{t("testers.youtube")}</External>}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="join-contributors" className="mt-12 border-t border-gray-200 pt-8">
        <h2 id="join-contributors" className={heading}>{t("contribute.heading")}</h2>
        <p className={paragraph}>{t("contribute.intro")}</p>
        <ul className="grid list-none gap-4 p-0 sm:grid-cols-2">
          {ways.map(({ key, Icon }) => (
            <li key={key} className="flex gap-3">
              <Icon className="mt-1 h-5 w-5 shrink-0 text-blue-700" aria-hidden="true" />
              <div><h3 className="m-0 text-base font-semibold text-gray-900">{t("contribute.ways." + key + ".title")}</h3><p className="mb-0 mt-1 text-sm leading-6 text-gray-700">{t("contribute.ways." + key + ".body")}</p></div>
            </li>
          ))}
        </ul>
        <div className="mt-6 flex flex-wrap gap-3">
          <External href={REPOSITORY + "/blob/main/CONTRIBUTING.md"} className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800">{t("contribute.guide")}<ExternalLink className="h-4 w-4" aria-hidden="true" /></External>
          <External href={REPOSITORY + "/discussions"} className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-semibold text-gray-800 hover:bg-gray-50">{t("contribute.discuss")}<ExternalLink className="h-4 w-4" aria-hidden="true" /></External>
        </div>
      </section>

      <Callout variant="tip" title={t("thanks.title")} className="mt-8">
        <p className="flex items-start gap-2"><Heart className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /><span>{t("thanks.body")}</span></p>
      </Callout>
    </div>
  )
}
