import type { Metadata } from "next"
import { getTranslations, setRequestLocale } from "next-intl/server"
import { DocPage } from "@/components/docs/DocBlocks"

const NAMESPACE = "docs.monitor.auditReport.assessment"
const LINKS = {
  reportsLink: "/docs/monitor/audit-report/reports",
}
const URL = "https://proxmenux.com/docs/monitor/audit-report/assessment"

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
  return <DocPage locale={locale} namespace={NAMESPACE} minutes={6} links={LINKS} />
}
