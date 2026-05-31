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
  const t = await getTranslations({ locale, namespace: "guides.kodiLxc.meta" })
  return {
    title: t("title"),
    description: t("description"),
    alternates: { canonical: "https://proxmenux.com/docs/guides/kodi-lxc" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/guides/kodi-lxc",
    },
  }
}

export default async function KodiLxcGuide({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "guides.kodiLxc" })

  const messages = (await getMessages({ locale })) as unknown as {
    guides: { kodiLxc: {
      intro: { steps: string[] }
      troubleshoot: { items: string[] }
    } }
  }
  const introSteps = messages.guides.kodiLxc.intro.steps
  const troubleItems = messages.guides.kodiLxc.troubleshoot.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const gpuLink = (chunks: React.ReactNode) => (
    <a
      href="/docs/hardware/igpu-acceleration-lxc"
      className="text-blue-700 hover:underline"
    >
      {chunks}
    </a>
  )
  const authorLink = (chunks: React.ReactNode) => (
    <a
      href="https://github.com/mrrudy"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-700 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )
  const konpatLink = (chunks: React.ReactNode) => (
    <a
      href="https://blog.konpat.me/dev/2019/03/11/setting-up-lxc-for-intel-gpu-proxmox.html"
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
        estimatedMinutes={10}
      />

      <Callout variant="info" title={t("intro.calloutTitle")}>
        {t.rich("intro.calloutBody", { strong, code, gpuLink })}
      </Callout>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("intro.credit", { authorLink })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("intro.stepsTitle")}</h2>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {introSteps.map((_, idx) => (
          <li key={idx}>{t(`intro.steps.${idx}`)}</li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("createCt.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("createCt.body", { strong, code })}</p>
      <CopyableCode code={t.raw("createCt.code") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("createCt.after", { code })}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("addInput.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("addInput.body", { code })}</p>
      <CopyableCode code={t.raw("addInput.listCode") as string} className="my-4" />
      <Image
        src="/guides/kodi/kodi1.png"
        alt={t("addInput.imageAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("addInput.afterList", { code, strong })}</p>
      <CopyableCode code={t.raw("addInput.editCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("addInput.addLines", { code, strong })}</p>
      <CopyableCode code={t.raw("addInput.configCode") as string} className="my-4" />
      <Image
        src="/guides/kodi/kodi2.png"
        alt={t("addInput.imageConfigAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("addInput.save", { code, strong })}</p>
      <CopyableCode code={t.raw("addInput.restartCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("addInput.plug")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("updateKodi.heading")}</h2>
      <Callout variant="warning" title={t("updateKodi.calloutTitle")}>
        {t.rich("updateKodi.calloutBody", { strong, code })}
      </Callout>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("updateKodi.body", { code })}</p>
      <CopyableCode code={t.raw("updateKodi.code") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("updateKodi.after")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("screenshots.heading")}</h2>
      <Image
        src="/guides/kodi/kodi3.png"
        alt={t("screenshots.image1Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <Image
        src="/guides/kodi/kodi4.jpeg"
        alt={t("screenshots.image2Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("troubleshoot.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-2">
        {troubleItems.map((_, idx) => (
          <li key={idx}>{t.rich(`troubleshoot.items.${idx}`, { code, strong })}</li>
        ))}
      </ul>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("further.heading")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        <li>{t.rich("further.konpatRich", { konpatLink })}</li>
      </ul>
      </div>
      <Footer />
    </div>
  )
}
