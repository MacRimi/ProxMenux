import type { Metadata } from "next"
import { getTranslations } from "next-intl/server"
import { DocPage } from "@/components/docs/DocBlocks"

const NAMESPACE = "docs.monitor.dashboard.catalog"
const URL = "https://proxmenux.com/docs/monitor/dashboard/catalog"

const LINKS = {
  accessLink: "/docs/monitor/access-auth#users-profiles",
  ociLink: "/docs/oci-manager",
  ociModesLink: "/docs/oci-manager#where",
  stacksLink: "/docs/oci-manager/stacks",
  ociMonitorLink: "/docs/oci-manager/monitor",
  lxcLink: "/docs/create-vm/lxc",
  createVmLink: "/docs/create-vm",
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
  return <DocPage locale={locale} namespace={NAMESPACE} minutes={8} links={LINKS} />
}
