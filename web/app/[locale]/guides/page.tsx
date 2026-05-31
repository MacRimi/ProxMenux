import type { Metadata } from "next"
import { Link } from "@/i18n/navigation"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import {
  Play,
  MessageCircle,
  Users,
  Book,
  Database,
  Code,
  BookOpen,
  Library,
  Star,
  Sparkles,
  ExternalLink,
} from "lucide-react"
import Footer from "@/components/footer"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "guides.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox guides",
      "proxmox tutorials",
      "proxmox kodi lxc",
      "proxmox nvidia driver",
      "proxmox samba lxc",
      "proxmox cloud backup",
      "proxmox vzdump rclone",
      "proxmox coral tpu",
      "proxmox gpu lxc",
      "proxmox ve 9 guides",
    ],
    alternates: { canonical: "https://proxmenux.com/guides" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "website",
      url: "https://proxmenux.com/guides",
      siteName: "ProxMenux",
      images: [
        {
          url: "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public/main.png",
          width: 1363,
          height: 735,
          alt: t("ogImageAlt"),
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
      images: [
        "https://raw.githubusercontent.com/MacRimi/ProxMenux/main/web/public/main.png",
      ],
    },
  }
}

interface Guide {
  title: string
  description: string
  slug: string
}

interface ExternalCardProps {
  href: string
  title: string
  description: string
  Icon: React.ComponentType<{ className?: string }>
  color: string // tailwind bg + hover classes
  external?: boolean
}

function CardLink({ href, title, description, Icon, color, external = true }: ExternalCardProps) {
  const Inner = (
    <div className={`block p-6 rounded-lg shadow-md transition-colors h-full ${color}`}>
      <div className="flex items-center gap-3 mb-2">
        <Icon className="h-6 w-6 text-white flex-shrink-0" />
        <h3 className="text-xl font-semibold text-white m-0">{title}</h3>
      </div>
      <p className="text-gray-200 text-sm m-0">{description}</p>
    </div>
  )

  if (external) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className="block h-full">
        {Inner}
      </a>
    )
  }
  return (
    <Link href={href} className="block h-full">
      {Inner}
    </Link>
  )
}

export default async function GuidesPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "guides" })

  const messages = (await getMessages({ locale })) as unknown as {
    guides: { inDepth: { items: Guide[] } }
  }
  const guides = messages.guides.inDepth.items

  const link = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/MacRimi/ProxMenux/issues"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-400 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-900 to-gray-800 text-white pt-16 flex flex-col">
      <div className="flex-grow container mx-auto px-4 pt-6 pb-16">
        <div className="mb-10">
          <h1 className="text-4xl font-bold mb-3">{t("header.title")}</h1>
          <p className="text-xl text-gray-200 max-w-3xl">{t("header.tagline")}</p>
        </div>

        {/* ─────────────────────────── In-depth guides ─────────────────────────── */}
        <section className="mb-16">
          <div className="flex items-center gap-2 mb-6">
            <BookOpen className="h-7 w-7 text-blue-400" />
            <h2 className="text-3xl font-bold m-0">{t("inDepth.heading")}</h2>
          </div>
          <p className="text-gray-300 mb-6 max-w-3xl">{t("inDepth.intro")}</p>
          <div className="grid md:grid-cols-2 gap-6">
            {guides.map((guide) => (
              <Link
                key={guide.slug}
                href={`/guides/${guide.slug}`}
                className="block p-6 bg-white rounded-lg shadow-md hover:shadow-lg transition-shadow"
              >
                <h3 className="text-xl font-semibold mb-2 text-gray-900 m-0">{guide.title}</h3>
                <p className="text-sm text-gray-600 mt-2 mb-0">{guide.description}</p>
              </Link>
            ))}
          </div>
        </section>

        {/* ─────────────────────────── ProxMenux references ─────────────────────────── */}
        <section className="mb-16">
          <div className="flex items-center gap-2 mb-6">
            <Library className="h-7 w-7 text-emerald-400" />
            <h2 className="text-3xl font-bold m-0">{t("references.heading")}</h2>
          </div>
          <p className="text-gray-300 mb-6 max-w-3xl">{t("references.intro")}</p>
          <div className="grid md:grid-cols-2 gap-6">
            <CardLink
              href="/docs/glossary"
              title={t("references.cards.glossary.title")}
              description={t("references.cards.glossary.description")}
              Icon={Sparkles}
              color="bg-emerald-600 hover:bg-emerald-700"
              external={false}
            />
            <CardLink
              href="/docs/help-info"
              title={t("references.cards.helpInfo.title")}
              description={t("references.cards.helpInfo.description")}
              Icon={Code}
              color="bg-teal-600 hover:bg-teal-700"
              external={false}
            />
            <CardLink
              href="/guides/linux-resources"
              title={t("references.cards.linuxResources.title")}
              description={t("references.cards.linuxResources.description")}
              Icon={BookOpen}
              color="bg-cyan-600 hover:bg-cyan-700"
              external={false}
            />
            <CardLink
              href="/docs/external-repositories"
              title={t("references.cards.externalRepos.title")}
              description={t("references.cards.externalRepos.description")}
              Icon={Code}
              color="bg-slate-600 hover:bg-slate-700"
              external={false}
            />
          </div>
        </section>

        {/* ─────────────────────────── Official Proxmox resources ─────────────────────────── */}
        <section className="mb-16">
          <div className="flex items-center gap-2 mb-6">
            <Book className="h-7 w-7 text-amber-400" />
            <h2 className="text-3xl font-bold m-0">{t("official.heading")}</h2>
          </div>
          <p className="text-gray-300 mb-6 max-w-3xl">{t("official.intro")}</p>
          <div className="grid md:grid-cols-2 gap-6">
            <CardLink
              href="https://pve.proxmox.com/pve-docs/index.html"
              title={t("official.cards.pveDocs.title")}
              description={t("official.cards.pveDocs.description")}
              Icon={Book}
              color="bg-green-600 hover:bg-green-700"
            />
            <CardLink
              href="https://pbs.proxmox.com/docs/index.html"
              title={t("official.cards.pbsDocs.title")}
              description={t("official.cards.pbsDocs.description")}
              Icon={Database}
              color="bg-yellow-600 hover:bg-yellow-700"
            />
            <CardLink
              href="https://www.proxmox.com/en/services/training-courses/videos"
              title={t("official.cards.videoTraining.title")}
              description={t("official.cards.videoTraining.description")}
              Icon={Play}
              color="bg-red-600 hover:bg-red-700"
            />
            <CardLink
              href="https://forum.proxmox.com/"
              title={t("official.cards.forum.title")}
              description={t("official.cards.forum.description")}
              Icon={MessageCircle}
              color="bg-purple-600 hover:bg-purple-700"
            />
          </div>
        </section>

        {/* ─────────────────────────── Community projects & resources ─────────────────────────── */}
        <section className="mb-16">
          <div className="flex items-center gap-2 mb-6">
            <Star className="h-7 w-7 text-pink-400" />
            <h2 className="text-3xl font-bold m-0">{t("community.heading")}</h2>
          </div>
          <p className="text-gray-300 mb-6 max-w-3xl">{t("community.intro")}</p>
          <div className="grid md:grid-cols-2 gap-6">
            <CardLink
              href="https://community-scripts.github.io/ProxmoxVE/"
              title={t("community.cards.helperScripts.title")}
              description={t("community.cards.helperScripts.description")}
              Icon={Code}
              color="bg-indigo-600 hover:bg-indigo-700"
            />
            <CardLink
              href="https://github.com/Corsinvest/awesome-proxmox-ve"
              title={t("community.cards.awesome.title")}
              description={t("community.cards.awesome.description")}
              Icon={Star}
              color="bg-pink-600 hover:bg-pink-700"
            />
          </div>

          <p className="text-sm text-gray-400 mt-6 italic">
            {t.rich("community.suggestRich", { link })}
          </p>
        </section>

        {/* ─────────────────────────── Discussion ─────────────────────────── */}
        <section className="mb-8">
          <div className="flex items-center gap-2 mb-6">
            <Users className="h-7 w-7 text-orange-400" />
            <h2 className="text-3xl font-bold m-0">{t("discussion.heading")}</h2>
          </div>
          <p className="text-gray-300 mb-6 max-w-3xl">{t("discussion.intro")}</p>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            <CardLink
              href="https://github.com/MacRimi/ProxMenux/discussions"
              title={t("discussion.cards.proxmenuxDiscussions.title")}
              description={t("discussion.cards.proxmenuxDiscussions.description")}
              Icon={MessageCircle}
              color="bg-blue-600 hover:bg-blue-700"
            />
            <CardLink
              href="https://forum.proxmox.com/"
              title={t("discussion.cards.proxmoxForum.title")}
              description={t("discussion.cards.proxmoxForum.description")}
              Icon={MessageCircle}
              color="bg-purple-600 hover:bg-purple-700"
            />
            <CardLink
              href="https://www.reddit.com/r/Proxmox/"
              title={t("discussion.cards.reddit.title")}
              description={t("discussion.cards.reddit.description")}
              Icon={Users}
              color="bg-orange-600 hover:bg-orange-700"
            />
          </div>
        </section>
      </div>
      <Footer />
    </div>
  )
}
