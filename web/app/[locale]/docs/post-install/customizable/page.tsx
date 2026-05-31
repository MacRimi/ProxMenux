import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import { ArrowRight } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.postInstall.customizable.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/post-install/customizable",
    },
  }
}

type Category = { name: string; description: string }
type RelatedItem = { label: string; href: string; tail?: string; tailRich?: string }

const CATEGORY_SLUGS = [
  "basic-settings",
  "system",
  "virtualization",
  "network",
  "storage",
  "security",
  "customization",
  "monitoring",
  "performance",
  "optional",
]

export default async function CustomizablePage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.customizable" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { customizable: {
      categories: Category[]
      related: { items: RelatedItem[] }
    } } }
  }
  const categories = messages.docs.postInstall.customizable.categories
  const relatedItems = messages.docs.postInstall.customizable.related.items

  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const uninstallLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/uninstall" className="text-blue-700 hover:underline">{chunks}</Link>
  )
  const autoLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/automated" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const storageLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/storage" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const networkLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/network" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const customLink = (chunks: React.ReactNode) => (
    <Link href="/docs/post-install/customization" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={15}
        scriptPath="post_install/customizable_post_install.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { link: uninstallLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("compare.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("compare.body", { link: autoLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("categoriesSection.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("categoriesSection.body")}</p>

      <div className="grid gap-3 md:grid-cols-2 mb-8 not-prose">
        {categories.map((category, idx) => (
          <Link
            key={CATEGORY_SLUGS[idx]}
            href={`/docs/post-install/${CATEGORY_SLUGS[idx]}`}
            className="group flex items-start gap-2 rounded-md border border-gray-200 bg-white p-3 transition-colors hover:border-blue-400 hover:bg-blue-50"
          >
            <ArrowRight
              className="h-4 w-4 mt-0.5 text-gray-400 group-hover:text-blue-600 flex-shrink-0"
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1">
              <div className="font-medium text-sm text-gray-900 group-hover:text-blue-700">{category.name}</div>
              <div className="text-xs text-gray-600 mt-0.5 leading-snug">{category.description}</div>
            </div>
          </Link>
        ))}
      </div>

      <Callout variant="tip" title={t("mixTip.title")}>
        {t.rich("mixTip.body", { strong })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("related.heading")}</h2>
      <ul className="list-disc pl-6 text-gray-800 leading-relaxed space-y-1">
        {relatedItems.map((item, idx) => (
          <li key={item.href}>
            <Link href={item.href} className="text-blue-600 hover:underline">
              {item.label}
            </Link>
            {item.tailRich ? t.rich(`related.items.${idx}.tailRich`, { storageLink, networkLink, customLink }) : item.tail}
          </li>
        ))}
      </ul>
    </div>
  )
}
