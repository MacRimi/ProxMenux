import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { ExternalLink } from "lucide-react"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import Image from "next/image"
import CopyableCode from "@/components/CopyableCode"
import Footer from "@/components/footer"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "guides.backupCloud.meta" })
  return {
    title: t("title"),
    description: t("description"),
    alternates: { canonical: "https://proxmenux.com/docs/guides/backup-cloud" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/guides/backup-cloud",
    },
  }
}

export default async function BackupCloudGuide({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "guides.backupCloud" })

  const messages = (await getMessages({ locale })) as unknown as {
    guides: { backupCloud: {
      intro: { steps: string[] }
      createDir: { configItems: string[] }
      mount: { mountItems: string[] }
      retention: { starterItems: string[] }
      troubleshoot: { items: string[] }
    } }
  }
  const introSteps = messages.guides.backupCloud.intro.steps
  const configItems = messages.guides.backupCloud.createDir.configItems
  const mountItems = messages.guides.backupCloud.mount.mountItems
  const starterItems = messages.guides.backupCloud.retention.starterItems
  const troubleItems = messages.guides.backupCloud.troubleshoot.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>

  const pbsLink = (chunks: React.ReactNode) => (
    <a
      href="https://www.proxmox.com/proxmox-backup-server"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const rcloneLink = (chunks: React.ReactNode) => (
    <a
      href="https://rclone.org"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const remoteSetupLink = (chunks: React.ReactNode) => (
    <a
      href="https://rclone.org/remote_setup/"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const providerDocsLink = (chunks: React.ReactNode) => (
    <a
      href="https://rclone.org/docs/"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )

  return (
    <div className="min-h-screen bg-white text-gray-900 pt-16 flex flex-col">
      <div className="container mx-auto px-4 pt-6 pb-16 flex-grow" style={{ maxWidth: "980px" }}>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={15}
      />

      <Callout variant="info" title={t("intro.pbsCalloutTitle")}>
        {t.rich("intro.pbsCalloutBody", { strong, code, pbsLink })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("intro.stepsTitle")}</h2>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {introSteps.map((_, idx) => (
          <li key={idx}>{t(`intro.steps.${idx}`)}</li>
        ))}
      </ol>

      <Callout variant="warning" title={t("intro.vzdumpCalloutTitle")}>
        {t.rich("intro.vzdumpCalloutBody", { strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("createDir.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("createDir.body", { strong, code })}</p>
      <CopyableCode code={t.raw("createDir.mkdirCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("createDir.afterMkdir", { strong, code })}</p>
      <Image
        src="/guides/backup_cloud/imagen1.png"
        alt={t("createDir.image1Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("createDir.configIntro")}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {configItems.map((_, idx) => (
          <li key={idx}>{t.rich(`createDir.configItems.${idx}`, { strong, code })}</li>
        ))}
      </ul>
      <Image
        src="/guides/backup_cloud/imagen2.png"
        alt={t("createDir.image2Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("createDir.afterConfig", { strong })}</p>
      <Image
        src="/guides/backup_cloud/imagen3.png"
        alt={t("createDir.image3Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("createDir.afterAdd")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("installRclone.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installRclone.body", { rcloneLink })}</p>
      <CopyableCode code={t.raw("installRclone.installCode") as string} className="my-4" />

      <Callout variant="info" title={t("installRclone.newerCalloutTitle")}>
        <p className="mb-2">{t("installRclone.newerCalloutBody")}</p>
        <CopyableCode code={t.raw("installRclone.newerCode") as string} className="my-2" />
      </Callout>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("installRclone.tunnelHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installRclone.tunnelBody", { remoteSetupLink })}</p>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installRclone.tunnelFrom", { strong, code })}</p>
      <CopyableCode code={t.raw("installRclone.tunnelCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("installRclone.tunnelAfter")}</p>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("installRclone.runHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("installRclone.runBody")}</p>
      <CopyableCode code={t.raw("installRclone.runCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installRclone.runAfter", { providerDocsLink })}</p>
      <CopyableCode code={t.raw("installRclone.authPrompt") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installRclone.authAfter", { strong })}</p>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installRclone.nameRemote", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("mount.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("mount.body", { code })}</p>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("mount.mountIntro")}</p>
      <CopyableCode code={t.raw("mount.mountCode") as string} className="my-4" />
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {mountItems.map((_, idx) => (
          <li key={idx}>{t.rich(`mount.mountItems.${idx}`, { code })}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("mount.mountFootnote", { strong })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("systemd.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("systemd.body", { code })}</p>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("systemd.createIntro")}</p>
      <CopyableCode code={t.raw("systemd.createCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("systemd.pasteIntro")}</p>
      <CopyableCode code={t.raw("systemd.unitCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("systemd.adjust", { code })}</p>
      <CopyableCode code={t.raw("systemd.enableCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("systemd.verifyIntro")}</p>
      <CopyableCode code={t.raw("systemd.verifyCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("systemd.verifyAfter", { code })}</p>

      <Callout variant="info" title={t("systemd.vfsCalloutTitle")}>
        {t.rich("systemd.vfsCalloutBody", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("configureBackup.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("configureBackup.body", { strong })}</p>
      <Image
        src="/guides/backup_cloud/imagen5.png"
        alt={t("configureBackup.image5Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("configureBackup.after")}</p>
      <Image
        src="/guides/backup_cloud/imagen6.png"
        alt={t("configureBackup.image6Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("retention.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("retention.body", { strong })}</p>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("retention.uiPath", { strong })}</p>
      <Image
        src="/guides/backup_cloud/imagen7.png"
        alt={t("retention.image7Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("retention.starterIntro")}</p>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {starterItems.map((_, idx) => (
          <li key={idx}>{t(`retention.starterItems.${idx}`)}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("retention.adjust")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-2">
        {troubleItems.map((_, idx) => (
          <li key={idx}>{t.rich(`troubleshoot.items.${idx}`, { code, strong })}</li>
        ))}
      </ul>
      </div>
      <Footer />
    </div>
  )
}
