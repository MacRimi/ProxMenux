import type { Metadata } from "next"
import { getTranslations } from "next-intl/server"
import { DocPage } from "@/components/docs/DocBlocks"

const NAMESPACE = "docs.monitor.dashboard.backup"
const URL = "https://proxmenux.com/docs/monitor/dashboard/backup"

const LINKS = {
  backupLink: "/docs/backup-restore",
  jobsLink: "/docs/backup-restore/scheduled-jobs",
  restoreLink: "/docs/backup-restore/restoring",
  crossKernelLink: "/docs/backup-restore/cross-kernel",
  pbsLink: "/docs/backup-restore/destinations/pbs",
  vmsLink: "/docs/monitor/dashboard/vms-lxcs",
  accessLink: "/docs/monitor/access-auth#users-profiles",
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
  return <DocPage locale={locale} namespace={NAMESPACE} minutes={12} links={LINKS} />
}
