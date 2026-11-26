import type { Metadata } from "next"
import { getTranslations } from "next-intl/server"
import { DocPage } from "@/components/docs/DocBlocks"

const NAMESPACE = "docs.createVm.lxc"
const URL = "https://proxmenux.com/docs/create-vm/lxc"

const LINKS = {
  vmsLxcsLink: "/docs/monitor/dashboard/vms-lxcs",
  appsLink: "/docs/monitor/dashboard/apps",
  terminalLink: "/docs/monitor/dashboard/terminal",
  accessLink: "/docs/monitor/access-auth#users-profiles",
  mountPointsLink: "/docs/storage-share/lxc-mount-points",
  igpuLink: "/docs/hardware/igpu-acceleration-lxc",
  nvidiaLink: "/docs/hardware/nvidia-host",
  coralLink: "/docs/hardware/coral-tpu-lxc",
  ociLink: "/docs/oci-manager",
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
  return <DocPage locale={locale} namespace={NAMESPACE} minutes={10} links={LINKS} />
}
