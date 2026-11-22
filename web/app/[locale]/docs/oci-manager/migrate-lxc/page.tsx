import type { Metadata } from "next"
import { getTranslations } from "next-intl/server"
import { DocPage } from "@/components/docs/DocBlocks"

const NAMESPACE = "docs.ociManager.migrateLxc"
const URL = "https://proxmenux.com/docs/oci-manager/migrate-lxc"

const LINKS = {
  customLink: "/docs/oci-manager/custom-image",
  contributeLink: "/docs/oci-manager/contribute-app",
  storageLink: "/docs/oci-manager/storage-network",
  hardwareLink: "/docs/oci-manager/hardware",
  stacksLink: "/docs/oci-manager/stacks",
  lifecycleLink: "/docs/oci-manager/lifecycle",
  monitorLink: "/docs/oci-manager/monitor",
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
  return <DocPage locale={locale} namespace={NAMESPACE} minutes={13} links={LINKS} />
}
