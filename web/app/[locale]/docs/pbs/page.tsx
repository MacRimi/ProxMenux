import type { Metadata } from "next"
import { getTranslations } from "next-intl/server"
import { DocPage } from "@/components/docs/DocBlocks"

const NAMESPACE = "docs.pbs"
const URL = "https://proxmenux.com/docs/pbs"

const LINKS = {
  installLink: "/docs/installation",
  utilsLink: "/docs/utils/system-utils",
  healthLink: "/docs/monitor/health-monitor",
  postLink: "/docs/post-install#pbs",
  settingsLink: "/docs/settings",
  backupTabLink: "/docs/monitor/dashboard/backup#pbs",
  pbsDestLink: "/docs/backup-restore/destinations/pbs",
  monitorLink: "/docs/pbs/monitor",
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
  return <DocPage locale={locale} namespace={NAMESPACE} minutes={7} links={LINKS} />
}
