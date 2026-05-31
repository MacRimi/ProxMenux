import type { Metadata } from "next"
import Image from "next/image"
import { ExternalLink } from "lucide-react"
import { getTranslations, getMessages, setRequestLocale } from "next-intl/server"
import { DocHeader } from "@/components/ui/doc-header"
import { Callout } from "@/components/ui/callout"

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>
}): Promise<Metadata> {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: "docs.utils.uupDumpIsoCreator.meta" })
  return {
    title: t("title"),
    description: t("description"),
    openGraph: {
      title: t("ogTitle"),
      description: t("ogDescription"),
      type: "article",
      url: "https://macrimi.github.io/ProxMenux/docs/utils/UUp-Dump-ISO-Creator",
      images: [
        {
          url: "/utils/uup-dump-iso-creator.png",
          width: 1200,
          height: 630,
          alt: t("ogImageAlt"),
        },
      ],
    },
  }
}

type DepRow = { pkg: string; roleRich: string }
type FlowStep = string
type Flag = string
type StepItem = {
  title: string
  img: string
  caption: string
  body?: string
  bodyRich?: string
}

export default async function UUPDumpISOCreatorPage({
  params,
}: {
  params: Promise<{ locale: string }>
}) {
  const { locale } = await params
  setRequestLocale(locale)
  const t = await getTranslations({ locale, namespace: "docs.utils.uupDumpIsoCreator" })

  const messages = (await getMessages({ locale })) as unknown as {
    docs: {
      utils: {
        uupDumpIsoCreator: {
          what: { items: string[] }
          dependencies: { rows: DepRow[] }
          flow: { steps: FlowStep[] }
          aria2: { flags: Flag[] }
          step1: { items: StepItem[] }
          step2: { items: StepItem[] }
        }
      }
    }
  }
  const block = messages.docs.utils.uupDumpIsoCreator
  const whatItems = block.what.items
  const depRows = block.dependencies.rows
  const flowSteps = block.flow.steps
  const aria2Flags = block.aria2.flags
  const step1Items = block.step1.items
  const step2Items = block.step2.items

  const code = (chunks: React.ReactNode) => <code>{chunks}</code>
  const strong = (chunks: React.ReactNode) => <strong>{chunks}</strong>
  const em = (chunks: React.ReactNode) => <em>{chunks}</em>
  const extlinkUupdump = (chunks: React.ReactNode) => (
    <a
      href="https://uupdump.net/"
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-600 hover:underline inline-flex items-center gap-1"
    >
      {chunks}
      <ExternalLink className="w-3 h-3" />
    </a>
  )

  const step1Badge = t("step1.stepBadge")
  const step2Badge = t("step2.stepBadge")

  return (
    <div>
      <DocHeader
        title={t("header.title")}
        description={t("header.description")}
        section={t("header.section")}
        estimatedMinutes={15}
        scriptPath="vm/uupdump_creator.sh"
      />

      <Callout variant="info" title={t("intro.title")}>
        {t("intro.body")}
      </Callout>

      <div className="flex flex-col items-center my-6">
        <div className="w-full max-w-[768px] overflow-hidden rounded-md border border-gray-200">
          <Image
            src="/utils/uup-dump-iso-creator.png"
            alt={t("hero.imageAlt")}
            width={768}
            height={0}
            style={{ height: "auto" }}
            className="w-full object-contain"
            sizes="(max-width: 768px) 100vw, 768px"
          />
        </div>
        <span className="mt-2 text-sm text-gray-600">{t("hero.caption")}</span>
      </div>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("what.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("what.intro")}</p>
      <ul className="list-disc pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {whatItems.map((_, idx) => (
          <li key={idx}>{t(`what.items.${idx}`)}</li>
        ))}
      </ul>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("what.learnMore", { extlink: extlinkUupdump })}
      </p>

      <h2 className="text-2xl font-semibold mt-10 mb-4 text-gray-900">{t("automates.heading")}</h2>

      <h3 className="text-xl font-semibold mt-6 mb-3 text-gray-900">{t("dependencies.heading")}</h3>
      <p className="mb-3 text-gray-800 leading-relaxed">{t.rich("dependencies.intro", { code })}</p>
      <div className="overflow-x-auto mb-4 rounded-md border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-gray-700">
            <tr>
              <th className="px-4 py-2 font-semibold">{t("dependencies.headerPackage")}</th>
              <th className="px-4 py-2 font-semibold">{t("dependencies.headerRole")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 text-gray-800">
            {depRows.map((row, idx) => (
              <tr key={row.pkg}>
                <td className="px-4 py-2"><code>{row.pkg}</code></td>
                <td className="px-4 py-2">{t.rich(`dependencies.rows.${idx}.roleRich`, { code })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mb-3 text-sm text-gray-700 leading-relaxed">{t("dependencies.manualIntro")}</p>
      <pre className="bg-gray-100 p-3 rounded-md overflow-x-auto text-sm font-mono mb-4">
        <code>{t("dependencies.manualCode")}</code>
      </pre>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("flow.heading")}</h3>
      <ol className="list-decimal pl-6 mb-4 text-gray-800 leading-relaxed space-y-1">
        {flowSteps.map((_, idx) => (
          <li key={idx}>{t.rich(`flow.steps.${idx}`, { code })}</li>
        ))}
      </ol>

      <h3 className="text-xl font-semibold mt-8 mb-3 text-gray-900">{t("aria2.heading")}</h3>
      <pre className="bg-gray-100 p-3 rounded-md overflow-x-auto text-sm font-mono mb-3">
        <code>{t("aria2.code")}</code>
      </pre>
      <ul className="list-disc pl-6 mb-4 text-sm text-gray-700 leading-relaxed space-y-1">
        {aria2Flags.map((_, idx) => (
          <li key={idx}>{t.rich(`aria2.flags.${idx}`, { code })}</li>
        ))}
      </ul>
      <p className="text-sm text-gray-600 mb-4">{t("aria2.runtime")}</p>

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("step1.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">
        {t.rich("step1.intro", { code, extlink: extlinkUupdump })}
      </p>

      {step1Items.map((item, idx) => (
        <section key={`s1-${idx}`} className="mt-8 border-b border-gray-200 pb-8">
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-800">
              {step1Badge} {idx + 1}
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{item.title}</h3>
          </div>
          <p className="mb-4 text-gray-800 leading-relaxed">
            {item.bodyRich ? t.rich(`step1.items.${idx}.bodyRich`, { code, strong, em }) : item.body}
          </p>
          <div className="flex flex-col items-center">
            <div className="w-full max-w-[768px] overflow-hidden rounded-md border border-gray-200">
              <Image
                src={item.img}
                alt={item.caption}
                width={768}
                height={0}
                style={{ height: "auto" }}
                className="w-full object-contain"
                sizes="(max-width: 768px) 100vw, 768px"
              />
            </div>
            <span className="mt-2 text-sm text-gray-600">{item.caption}</span>
          </div>
        </section>
      ))}

      <h2 className="text-2xl font-semibold mt-12 mb-4 text-gray-900">{t("step2.heading")}</h2>
      <p className="mb-4 text-gray-800 leading-relaxed">{t("step2.intro")}</p>

      {step2Items.map((item, idx) => (
        <section key={`s2-${idx}`} className="mt-8 border-b border-gray-200 pb-8">
          <div className="flex items-center gap-3 mb-3">
            <span className="inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-800">
              {step2Badge} {idx + 1}
            </span>
            <h3 className="text-lg font-semibold text-gray-900 m-0">{item.title}</h3>
          </div>
          <p className="mb-4 text-gray-800 leading-relaxed">
            {item.bodyRich ? t.rich(`step2.items.${idx}.bodyRich`, { code, strong, em }) : item.body}
          </p>
          <div className="flex flex-col items-center">
            <div className="w-full max-w-[768px] overflow-hidden rounded-md border border-gray-200">
              <Image
                src={item.img}
                alt={item.caption}
                width={768}
                height={0}
                style={{ height: "auto" }}
                className="w-full object-contain"
                sizes="(max-width: 768px) 100vw, 768px"
              />
            </div>
            <span className="mt-2 text-sm text-gray-600">{item.caption}</span>
          </div>
        </section>
      ))}

      <Callout variant="info" title={t("tempFiles.title")}>
        {t.rich("tempFiles.body", { code })}
      </Callout>
    </div>
  )
}
