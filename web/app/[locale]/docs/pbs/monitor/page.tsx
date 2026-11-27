import type { Metadata } from "next"
import { getTranslations } from "next-intl/server"
import { DocPage } from "@/components/docs/DocBlocks"

const NAMESPACE = "docs.pbs.monitor"
const URL = "https://proxmenux.com/docs/pbs/monitor"

const LINKS = {
  detectionLink: "/docs/pbs#detection",
  updatesLink: "/docs/pbs#updates",
  overviewLink: "/docs/monitor/dashboard/system-overview",
  storageLink: "/docs/monitor/dashboard/storage",
  networkLink: "/docs/monitor/dashboard/network",
  hardwareLink: "/docs/monitor/dashboard/hardware",
  terminalLink: "/docs/monitor/dashboard/terminal",
  settingsLink: "/docs/monitor/dashboard/settings",
  securityLink: "/docs/monitor/dashboard/security",
  accessLink: "/docs/monitor/access-auth",
  proxmoxAccountsLink: "/docs/monitor/access-auth#proxmox-ve-accounts",
  profilesLink: "/docs/monitor/access-auth#users-profiles",
  healthLink: "/docs/monitor/health-monitor",
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
  return <DocPage locale={locale} namespace={NAMESPACE} minutes={6} links={LINKS} />
}
