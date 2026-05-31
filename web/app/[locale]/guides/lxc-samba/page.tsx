import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
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
  const t = await getTranslations({ locale, namespace: "guides.lxcSamba.meta" })
  return {
    title: t("title"),
    description: t("description"),
    alternates: { canonical: "https://proxmenux.com/docs/guides/lxc-samba" },
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://proxmenux.com/docs/guides/lxc-samba",
    },
  }
}

export default async function LxcSambaGuide({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "guides.lxcSamba" })

  const messages = (await getMessages({ locale })) as unknown as {
    guides: { lxcSamba: {
      recommended: { items: string[] }
      intro: { steps: string[]; useCases: string[] }
      troubleshoot: { items: string[] }
    } }
  }
  const recommendedItems = messages.guides.lxcSamba.recommended.items
  const introSteps = messages.guides.lxcSamba.intro.steps
  const useCases = messages.guides.lxcSamba.intro.useCases
  const troubleItems = messages.guides.lxcSamba.troubleshoot.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>

  return (
    <div className="min-h-screen bg-white text-gray-900 pt-16 flex flex-col">
      <div className="container mx-auto px-4 pt-6 pb-16 flex-grow" style={{ maxWidth: "980px" }}>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={20}
      />

      <Callout variant="warning" title={t("recommended.calloutTitle")}>
        <p className="mb-2">{t("recommended.calloutIntro")}</p>
        <ul className="list-disc pl-6 mb-3 space-y-1">
          {recommendedItems.map((_, idx) => (
            <li key={idx}>{t.rich(`recommended.items.${idx}`, { strong, code })}</li>
          ))}
        </ul>
        <p>{t("recommended.calloutOutro")}</p>
      </Callout>

      <p className="mb-4 text-gray-800 leading-relaxed">{t("intro.body")}</p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("intro.stepsTitle")}</h2>
      <ol className="list-decimal pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {introSteps.map((_, idx) => (
          <li key={idx}>{t(`intro.steps.${idx}`)}</li>
        ))}
      </ol>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("intro.useCasesTitle")}</h2>
      <ul className="list-disc pl-6 mb-6 text-gray-800 leading-relaxed space-y-1">
        {useCases.map((_, idx) => (
          <li key={idx}>{t(`intro.useCases.${idx}`)}</li>
        ))}
      </ul>

      <Callout variant="warning" title={t("intro.privilegedCalloutTitle")}>
        {t.rich("intro.privilegedCalloutBody", { strong, code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("attach.heading")}</h2>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("attach.identifyHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("attach.identifyBody", { strong })}</p>
      <p className="mb-2 text-gray-800 leading-relaxed">{t("attach.beforeLabel")}</p>
      <Image
        src="/guides/lxc_samba/lxc_3.png"
        alt={t("attach.imageBeforeAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-2 text-gray-800 leading-relaxed">{t("attach.afterLabel")}</p>
      <Image
        src="/guides/lxc_samba/lxc_4.png"
        alt={t("attach.imageAfterAlt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("attach.lsblkBody", { code })}</p>

      <Callout variant="warning" title={t("attach.stableCalloutTitle")}>
        <p className="mb-2">{t.rich("attach.stableCalloutBody", { code })}</p>
        <CopyableCode code={t.raw("attach.stableCalloutCode") as string} className="my-3" />
        <p>{t.rich("attach.stableCalloutAfter", { code })}</p>
      </Callout>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("attach.formatHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("attach.formatBody", { strong })}</p>
      <CopyableCode code={t.raw("attach.formatCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("attach.formatAfter", { code })}</p>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("attach.mkdirHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("attach.mkdirBody")}</p>
      <CopyableCode code={t.raw("attach.mkdirCode") as string} className="my-4" />

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("attach.wireHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("attach.wireBody", { strong, code })}</p>
      <CopyableCode code={t.raw("attach.wireEditCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("attach.wireAddLine")}</p>
      <CopyableCode code={t.raw("attach.wireConfigCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("attach.wireShortForm", { code })}</p>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("attach.wireBackupNote", { code })}</p>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("attach.restartHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("attach.restartBody")}</p>
      <CopyableCode code={t.raw("attach.restartCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("attach.permsBody")}</p>
      <CopyableCode code={t.raw("attach.permsCode") as string} className="my-4" />
      <Callout variant="info" title={t("attach.permsNoteTitle")}>
        {t.rich("attach.permsNote", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("samba.heading")}</h2>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("samba.installHeading")}</h3>
      <CopyableCode code={t.raw("samba.installCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("samba.confirmBody")}</p>
      <CopyableCode code={t.raw("samba.confirmCode") as string} className="my-4" />

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("samba.userHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("samba.userBody", { code })}</p>
      <CopyableCode code={t.raw("samba.userCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("samba.passwordBody")}</p>
      <CopyableCode code={t.raw("samba.passwordCode") as string} className="my-4" />

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("samba.aclHeading")}</h3>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("samba.aclBody", { code })}</p>
      <CopyableCode code={t.raw("samba.aclCode") as string} className="my-4" />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("configure.heading")}</h2>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("configure.editHeading")}</h3>
      <CopyableCode code={t.raw("configure.editCode") as string} className="my-4" />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("configure.appendBody")}</p>
      <CopyableCode code={t.raw("configure.shareCode") as string} className="my-4" />
      <Callout variant="info" title={t("configure.validUsersNoteTitle")}>
        {t.rich("configure.validUsersNote", { code })}
      </Callout>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("configure.reloadHeading")}</h3>
      <CopyableCode code={t.raw("configure.reloadCode") as string} className="my-4" />

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("verify.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t.rich("verify.body", { code })}</p>
      <Image
        src="/guides/lxc_samba/lxc_1.png"
        alt={t("verify.image1Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <Image
        src="/guides/lxc_samba/lxc_2.png"
        alt={t("verify.image2Alt")}
        width={900}
        height={500}
        className="rounded shadow-lg my-6"
        unoptimized
      />
      <p className="mb-4 text-gray-800 leading-relaxed">{t("verify.usageBody")}</p>
      <Image
        src="/guides/lxc_samba/lxc_5.png"
        alt={t("verify.image3Alt")}
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
      </div>
      <Footer />
    </div>
  )
}
