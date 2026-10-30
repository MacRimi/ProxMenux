import type { Metadata } from "next"
import { getTranslations, setRequestLocale } from "next-intl/server"
import { DocPage } from "@/components/docs/DocBlocks"

const NAMESPACE = "docs.ociManager.contributeApp"
const URL = "https://proxmenux.com/docs/oci-manager/contribute-app"

const LINKS = {
  roadmap: "https://github.com/users/MacRimi/projects/1",
  catalog: "https://github.com/MacRimi/ProxMenux/tree/develop/oci/catalog",
  validation: "https://github.com/MacRimi/ProxMenux/blob/develop/oci/VALIDATION.md",
}

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: `${NAMESPACE}.meta` })
  return {
    title: t("title"),
    description: t("description"),
    alternates: { canonical: URL },
    openGraph: { title: t("title"), description: t("description"), type: "article", url: URL },
  }
}

export default async function Page({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params
  setRequestLocale(locale)
  return <DocPage locale={locale} namespace={NAMESPACE} minutes={12} links={LINKS} />
}
