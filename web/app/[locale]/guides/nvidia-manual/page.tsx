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
  const t = await getTranslations({ locale, namespace: "guides.nvidiaManual.meta" })
  return {
    title: t("title"),
    description: t("description"),
    alternates: { canonical: "https://proxmenux.com/docs/guides/nvidia-manual" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/guides/nvidia-manual",
    },
  }
}

export default async function NvidiaManualGuide({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "guides.nvidiaManual" })

  const messages = (await getMessages({ locale })) as unknown as {
    guides: { nvidiaManual: {
      intro: { steps: string[] }
      lxcSetup: { tableRows: { device: string; major: string }[] }
      troubleshoot: { items: string[] }
    } }
  }
  const introSteps = messages.guides.nvidiaManual.intro.steps
  const tableRows = messages.guides.nvidiaManual.lxcSetup.tableRows
  const troubleItems = messages.guides.nvidiaManual.troubleshoot.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const patchLink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/keylase/nvidia-patch"
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
        estimatedMinutes={30}
      />

      <Callout variant="info" title={t("intro.calloutTitle")}>
        {t.rich("intro.calloutBody", { strong, em })}
      </Callout>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("intro.targetNote", { strong })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("intro.stepsTitle")}</h2>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {introSteps.map((_, idx) => (
          <li key={idx}>{t(`intro.steps.${idx}`)}</li>
        ))}
      </ol>

      {/* Section 1 - Prepare host */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("prepareHost.heading")}</h2>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("prepareHost.blacklistHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("prepareHost.blacklistBody", { code })}</p>
      <CopyableCode code={t.raw("prepareHost.blacklistCheckCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("prepareHost.blacklistAdd", { code })}</p>
      <CopyableCode code={t.raw("prepareHost.blacklistAddCode") as string} className="my-4" />
      <Image
        src="/guides/nvidia/nvidia-2.png"
        alt={t("prepareHost.blacklistImageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("prepareHost.reposHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("prepareHost.reposBody")}</p>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("prepareHost.reposOtherwise")}</p>
      <CopyableCode code={t.raw("prepareHost.reposEditCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("prepareHost.reposPveBody")}</p>
      <CopyableCode code={t.raw("prepareHost.reposPveCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("prepareHost.reposDebianBody", { code })}</p>
      <CopyableCode code={t.raw("prepareHost.reposDebianCode") as string} className="my-4" />

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("prepareHost.updateHeading")}</h3>
      <CopyableCode code={t.raw("prepareHost.updateCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("prepareHost.buildToolsBody")}</p>
      <CopyableCode code={t.raw("prepareHost.buildToolsCode") as string} className="my-4" />

      {/* Section 2 - Install driver */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("installDriver.heading")}</h2>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("installDriver.pickHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("installDriver.pickBody")}</p>
      <CopyableCode code={t.raw("installDriver.pickUrlCode") as string} className="my-4" />
      <Callout variant="info" title={t("installDriver.nvencCalloutTitle")}>
        {t.rich("installDriver.nvencCallout", { patchLink })}
      </Callout>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installDriver.pickReplace", { code })}</p>
      <CopyableCode code={t.raw("installDriver.pickListCode") as string} className="my-4" />
      <Image
        src="/guides/nvidia/nvidia-1.png"
        alt={t("installDriver.pickImageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installDriver.pickVersionNote", { code })}</p>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("installDriver.downloadHeading")}</h3>
      <CopyableCode code={t.raw("installDriver.downloadCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installDriver.firstPassBody", { code })}</p>
      <CopyableCode code={t.raw("installDriver.firstPassCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("installDriver.secondPassBody")}</p>
      <CopyableCode code={t.raw("installDriver.secondPassCode") as string} className="my-4" />

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("installDriver.modulesHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("installDriver.modulesBody")}</p>
      <CopyableCode code={t.raw("installDriver.modulesEditCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("installDriver.modulesAddBody")}</p>
      <CopyableCode code={t.raw("installDriver.modulesAddCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installDriver.modulesSaveBody", { code })}</p>
      <CopyableCode code={t.raw("installDriver.modulesSaveCode") as string} className="my-4" />

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("installDriver.udevHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installDriver.udevBody", { code })}</p>
      <CopyableCode code={t.raw("installDriver.udevEditCode") as string} className="my-4" />
      <CopyableCode code={t.raw("installDriver.udevRulesCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("installDriver.udevSaveBody", { code })}</p>

      {/* Section 3 - Persistence */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("persistence.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("persistence.body")}</p>
      <CopyableCode code={t.raw("persistence.installCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("persistence.verifyBody")}</p>
      <CopyableCode code={t.raw("persistence.verifySmiCode") as string} className="my-4" />
      <Image
        src="/guides/nvidia/nvidia-3.png"
        alt={t("persistence.smiImageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <CopyableCode code={t.raw("persistence.verifyServiceCode") as string} className="my-4" />
      <Image
        src="/guides/nvidia/nvidia-4.png"
        alt={t("persistence.serviceImageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />

      {/* Section 4 - NVENC */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("nvenc.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("nvenc.body")}</p>
      <CopyableCode code={t.raw("nvenc.code") as string} className="my-4" />
      <Image
        src="/guides/nvidia/nvidia-5.png"
        alt={t("nvenc.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("nvenc.after", { code })}</p>

      {/* Section 5 - LXC setup */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("lxcSetup.heading")}</h2>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("lxcSetup.identifyHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("lxcSetup.identifyBody")}</p>
      <CopyableCode code={t.raw("lxcSetup.identifyCode") as string} className="my-4" />
      <Image
        src="/guides/nvidia/nvidia-6.png"
        alt={t("lxcSetup.identifyImageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("lxcSetup.identifyNote")}</p>
      <div className="overflow-x-auto my-4">
        <table className="min-w-full border-collapse border border-gray-300">
          <thead className="bg-gray-100">
            <tr>
              <th className="border border-gray-300 px-4 py-2 text-left text-gray-900">{t("lxcSetup.tableHeaders.device")}</th>
              <th className="border border-gray-300 px-4 py-2 text-left text-gray-900">{t("lxcSetup.tableHeaders.major")}</th>
            </tr>
          </thead>
          <tbody>
            {tableRows.map((_, idx) => (
              <tr key={idx}>
                <td className="border border-gray-300 px-4 py-2 text-gray-800">
                  {t.rich(`lxcSetup.tableRows.${idx}.device`, { code })}
                </td>
                <td className="border border-gray-300 px-4 py-2 text-gray-800">
                  {t.rich(`lxcSetup.tableRows.${idx}.major`, { code })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("lxcSetup.editHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("lxcSetup.editBody", { code })}</p>
      <CopyableCode code={t.raw("lxcSetup.editCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("lxcSetup.editConfigBody", { code, strong })}</p>
      <CopyableCode code={t.raw("lxcSetup.editConfigCode") as string} className="my-4" />
      <Image
        src="/guides/nvidia/nvidia-7.png"
        alt={t("lxcSetup.editConfigImageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("lxcSetup.editSave", { code })}</p>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("lxcSetup.installCtHeading")}</h3>
      <Callout variant="warning" title={t("lxcSetup.installCtCalloutTitle")}>
        {t.rich("lxcSetup.installCtCalloutBody", { strong })}
      </Callout>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("lxcSetup.installCtBody")}</p>
      <CopyableCode code={t.raw("lxcSetup.installCtCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("lxcSetup.installCtAfter")}</p>
      <Image
        src="/guides/nvidia/nvidia-8.png"
        alt={t("lxcSetup.installCtImageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("lxcSetup.verifyCtHeading")}</h3>
      <CopyableCode code={t.raw("lxcSetup.verifyCtSmiCode") as string} className="my-4" />
      <Image
        src="/guides/nvidia/nvidia-9.png"
        alt={t("lxcSetup.verifyCtSmiImageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <CopyableCode code={t.raw("lxcSetup.verifyCtLsCode") as string} className="my-4" />
      <Image
        src="/guides/nvidia/nvidia-10.png"
        alt={t("lxcSetup.verifyCtLsImageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("lxcSetup.verifyCtAfter")}</p>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("lxcSetup.workloadHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("lxcSetup.workloadBody")}</p>
      <Image
        src="/guides/nvidia/nvidia-11.png"
        alt={t("lxcSetup.workloadImage1Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <Image
        src="/guides/nvidia/nvidia-12.png"
        alt={t("lxcSetup.workloadImage2Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("lxcSetup.repeatNote", { strong })}</p>

      {/* Section 6 - Docker */}
      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("docker.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("docker.body", { code })}</p>
      <CopyableCode code={t.raw("docker.code") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("docker.after")}</p>

      {/* Troubleshooting */}
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
