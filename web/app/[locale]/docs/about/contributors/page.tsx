import type { Metadata } from "next"
import Image from "next/image"
import { getTranslations, setRequestLocale } from "next-intl/server"
import { Youtube, FlaskRound, ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.about.contributors.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/about/contributors",
    },
  }
}

interface Contributor {
  name: string
  roleKey: "testing" | "testingReviewer"
  avatar: string
  youtubeUrl?: string
}

const contributors: Contributor[] = [
  {
    name: "MALOW",
    roleKey: "testing",
    avatar: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/avatars/malow.png",
  },
  {
    name: "Segarra",
    roleKey: "testing",
    avatar: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/avatars/segarra.png",
  },
  {
    name: "Aprilia",
    roleKey: "testing",
    avatar: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/avatars/aprilia.png",
  },
  {
    name: "Jonatan Castro",
    roleKey: "testingReviewer",
    avatar: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/avatars/jonatancastro.png",
    youtubeUrl: "https://www.youtube.com/@JonatanCastro",
  },
  {
    name: "Kamunhas",
    roleKey: "testing",
    avatar: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/avatars/Kamunhas.png",
  },
  // Added 2026-05-31 after the v1.2.2 release.
  {
    name: "heriberto",
    roleKey: "testing",
    avatar: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/avatars/heriberto.png",
  },
  {
    name: "JF_Carr",
    roleKey: "testing",
    avatar: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/avatars/JF_Carr.png",
  },
  {
    name: "rafapuerta",
    roleKey: "testing",
    avatar: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/avatars/rafapuerta.png",
  },
  {
    name: "JcMinarro",
    roleKey: "testing",
    avatar: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/avatars/JcMinarro.png",
  },
]

export default async function ContributorsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.about.contributors" })

  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const extlink = (href: string) => (chunks: React.ReactNode) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const extlinkBlue = (href: string) => (chunks: React.ReactNode) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const extlinkEmerald = (href: string) => (chunks: React.ReactNode) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-emerald-700 hover:underline inline-flex items-center gap-1"
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
        estimatedMinutes={1}
      />

      <Callout variant="info" title={t("beyond.title")}>
        {t.rich("beyond.body", {
          extlink: extlink("https://github.com/MacRimi/ProxMenux/graphs/contributors"),
        })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("testers.heading")}</h2>

      <p className="mb-6 text-gray-800 leading-relaxed">{t("testers.intro")}</p>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-6 mt-6 mb-8 not-prose">
        {contributors.map((c) => (
          <div key={c.name} className="text-center">
            <div className="relative inline-block">
              <Image
                src={c.avatar}
                alt={c.name}
                width={80}
                height={80}
                className="w-20 h-20 rounded-full border-2 border-gray-300 object-cover"
                unoptimized
              />
              <div className="absolute -bottom-1 -right-1 bg-orange-500 rounded-full p-1">
                <FlaskRound className="h-4 w-4 text-white" aria-hidden />
              </div>
            </div>
            <h3 className="text-base font-semibold text-gray-900 mt-2 mb-0">{c.name}</h3>
            <p className="text-xs text-gray-600 mt-0.5">{t(`testers.roles.${c.roleKey}`)}</p>
            {c.youtubeUrl && (
              <a
                href={c.youtubeUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 mt-1 text-xs text-red-600 hover:text-red-700"
              >
                <Youtube className="h-3.5 w-3.5" aria-hidden /> {t("testers.youtube")}
              </a>
            )}
          </div>
        ))}
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("contribute.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("contribute.intro")}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        <li>
          {t.rich("contribute.tester", {
            strong,
            beta: extlinkBlue("https://github.com/MacRimi/ProxMenux/blob/develop/install_proxmenux_beta.sh"),
          })}
        </li>
        <li>
          {t.rich("contribute.developer", {
            strong,
            gh: extlinkBlue("https://github.com/MacRimi/ProxMenux/pulls"),
          })}
        </li>
        <li>{t.rich("contribute.designer", { strong })}</li>
        <li>
          {t.rich("contribute.ideas", {
            strong,
            disc: extlinkBlue("https://github.com/MacRimi/ProxMenux/discussions"),
          })}
        </li>
      </ul>

      <Callout variant="tip" title={t("coc.title")}>
        {t.rich("coc.body", {
          coclink: extlinkEmerald("https://github.com/MacRimi/ProxMenux/blob/main/CODE_OF_CONDUCT.md"),
        })}
      </Callout>
    </div>
  )
}
