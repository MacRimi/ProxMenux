import type { Metadata } from "next"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { Link } from "@/i18n/navigation"
import Image from "next/image"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"
import { Steps } from "@/components/ui/steps"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.postInstall.updates.meta" })
  return {
    title: t("title"),
    description: t("description"),
    alternates: { canonical: "https://proxmenux.com/docs/post-install/updates" },
  }
}

type Step = { title: string; body: string }
type DiffRow = { pathLabel: string; pathHref: string | null; scope: string; when: string }

export default async function PostInstallUpdatesPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.postInstall.updates" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: { postInstall: { updates: {
      detection: { steps: Step[] }
      applying: { steps: Step[] }
      differs: { rows: DiffRow[] }
    } } }
  }
  const detectionSteps = messages.docs.postInstall.updates.detection.steps
  const applyingSteps = messages.docs.postInstall.updates.applying.steps
  const diffRows = messages.docs.postInstall.updates.differs.rows

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const optimizationsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/settings#proxmenux-optimizations" className="text-blue-600 hover:underline">{chunks}</Link>
  )
  const settingsLink = (chunks: React.ReactNode) => (
    <Link href="/docs/monitor/dashboard/settings" className="text-blue-600 hover:underline">{chunks}</Link>
  )

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={4}
        scriptPath="scripts/post_install/update_post_install_function.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t.rich("intro.body", { code })}
      </Callout>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("why.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("why.body", { em })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("detection.heading")}</h2>

      <Steps>
        {detectionSteps.map((step, idx) => (
          <Steps.Step key={idx} title={step.title}>
            <p className="mb-2 text-gray-800">
              {t.rich(`detection.steps.${idx}.body`, { code, em })}
            </p>
          </Steps.Step>
        ))}
      </Steps>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("pathA.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pathA.intro", { strong, em })}
      </p>

      <figure className="my-4">
        <Image
          src="/post-install/post-install-updates-menu.png"
          alt={t("pathA.menuAlt")}
          width={1200}
          height={680}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t.rich("pathA.menuCaption", { em })}
        </figcaption>
      </figure>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pathA.checklistBody", { code })}
      </p>

      <figure className="my-4">
        <Image
          src="/post-install/post-install-updates-checklist.png"
          alt={t("pathA.checklistAlt")}
          width={1200}
          height={680}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("pathA.checklistCaption")}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("pathB.heading")}</h2>

      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("pathB.intro", { strong, link: optimizationsLink })}
      </p>

      <figure className="my-4">
        <Image
          src="/monitor/settings/proxmenux-optimizations-update-banner.png"
          alt={t("pathB.imageAlt")}
          width={2000}
          height={1146}
          className="rounded-lg border border-gray-200 shadow-sm w-full h-auto"
        />
        <figcaption className="text-sm text-gray-500 mt-2 text-center italic">
          {t("pathB.imageCaption")}
        </figcaption>
      </figure>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("applying.heading")}</h2>

      <Steps>
        {applyingSteps.map((step, idx) => (
          <Steps.Step key={idx} title={step.title}>
            <p className="mb-2 text-gray-800">
              {t.rich(`applying.steps.${idx}.body`, { code, strong })}
            </p>
          </Steps.Step>
        ))}
      </Steps>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("differs.heading")}</h2>

      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded-md">
          <thead className="bg-gray-50 text-gray-900">
            <tr>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("differs.headerPath")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("differs.headerScope")}</th>
              <th className="text-left px-3 py-2 border-b border-gray-200">{t("differs.headerWhen")}</th>
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {diffRows.map((row, idx) => (
              <tr key={row.pathLabel} className={idx < diffRows.length - 1 ? "border-b border-gray-100" : ""}>
                <td className="px-3 py-2 align-top">
                  {row.pathHref ? (
                    <Link href={row.pathHref} className="text-blue-600 hover:underline">
                      {row.pathLabel}
                    </Link>
                  ) : (
                    <strong>{row.pathLabel}</strong>
                  )}
                </td>
                <td className="px-3 py-2 align-top">{t.rich(`differs.rows.${idx}.scope`, { em })}</td>
                <td className="px-3 py-2 align-top">{row.when}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout variant="info" title={t("notifTitle")}>
        {t.rich("notifBody", { em, link: settingsLink })}
      </Callout>
    </div>
  )
}
