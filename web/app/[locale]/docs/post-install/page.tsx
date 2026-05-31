import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { Zap, SlidersHorizontal, Undo2, ExternalLink, RefreshCw } from "lucide-react"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.postInstall.meta" })
  return {
    title: t("title"),
    description: t("description"),
    keywords: [
      "proxmox post install",
      "proxmox post-install script",
      "proxmox optimizations",
      "proxmox tweaks",
      "proxmox automated setup",
      "proxmox customization",
      "proxmox no subscription repository",
      "proxmox tuning",
      "proxmenux post install",
    ],
    alternates: { canonical: "https://proxmenux.com/docs/post-install" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/post-install",
    },
    twitter: {
      card: "summary_large_image",
      title: t("twitterTitle"),
      description: t("twitterDescription"),
    },
  }
}

type Route = { title: string; description: string; bullets: string[] }
type RelatedItem = { label: string; href: string; tail: string }

const ROUTE_CONFIG = [
  {
    key: "automated",
    href: "/docs/post-install/automated",
    Icon: Zap,
    accent: "border-emerald-300 bg-emerald-50",
    iconBg: "bg-emerald-100 text-emerald-700",
  },
  {
    key: "customizable",
    href: "/docs/post-install/customizable",
    Icon: SlidersHorizontal,
    accent: "border-amber-300 bg-amber-50",
    iconBg: "bg-amber-100 text-amber-700",
  },
  {
    key: "updates",
    href: "/docs/post-install/updates",
    Icon: RefreshCw,
    accent: "border-violet-300 bg-violet-50",
    iconBg: "bg-violet-100 text-violet-700",
  },
  {
    key: "uninstall",
    href: "/docs/post-install/uninstall",
    Icon: Undo2,
    accent: "border-blue-300 bg-blue-50",
    iconBg: "bg-blue-100 text-blue-700",
  },
]

export default async function PostInstallPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: {
      routes: Route[]
      related: { items: RelatedItem[] }
    } }
  }
  const routes = messages.docs.postInstall.routes
  const relatedItems = messages.docs.postInstall.related.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const autoLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/automated" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const customLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/customizable" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const updatesLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/updates" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const uninstallLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/uninstall" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const xshokAnchor = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/extremeshok/xshok-proxmox"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const communityAnchor = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/community-scripts/ProxmoxVE"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const externalRepoLink = (chunks: React.ReactNode) => (
    <Link href="/docs/external-repositories" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={3}
        scriptPath="menus/menu_post_install.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("openingMenu.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("openingMenu.body", { strong })}
      </p>

      <Image
        src="/post-install/post-install-menu.png"
        alt={t("openingMenu.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("threeWays.heading")}</h2>
      <p className="mb-6 text-gray-800 leading-relaxed">{t("threeWays.body")}</p>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-8 not-prose">
        {ROUTE_CONFIG.map(({ key, href, Icon, accent, iconBg }, idx) => {
          const route = routes[idx]
          return (
            <Link
              key={key}
              href={href}
              className={`rounded-lg border-2 p-5 ${accent} flex flex-col transition-shadow hover:shadow-md`}
            >
              <div className="flex items-center gap-3 mb-3">
                <span className={`inline-flex h-9 w-9 items-center justify-center rounded-full ${iconBg}`}>
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </span>
                <h3 className="text-lg font-semibold text-gray-900 m-0">{route.title}</h3>
              </div>
              <p className="text-sm text-gray-800 mb-3">{route.description}</p>
              <ul className="space-y-1 text-sm text-gray-700 list-disc pl-5 mb-0 marker:text-gray-400">
                {route.bullets.map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
            </Link>
          )
        })}
      </div>

      <Callout variant="tip" title={t("whichTitle")}>
        {t.rich("whichBody", { strong, autoLink, customLink, updatesLink, uninstallLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("mixing.heading")}</h2>

      <Callout variant="warning" title={t("mixing.stackTitle")}>
        {t.rich("mixing.stackBody", { strong })}
      </Callout>

      <Callout variant="info" title={t("mixing.xshokTitle")}>
        {t.rich("mixing.xshokBody", { a: xshokAnchor })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("community.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("community.body", { em, code, a: communityAnchor, link: externalRepoLink })}
      </p>

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
